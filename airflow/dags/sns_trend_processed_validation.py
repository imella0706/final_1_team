"""Airflow DAG for validating the official sns_trend processed package.

[Design Intent] Keep Airflow as a read-only validation gate: the data owner
publishes processed files, and the DAG rejects payloads that the API/DVC path
cannot safely consume.
"""

from __future__ import annotations

import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


DAG_ID = "sns_trend_processed_validation"
DEFAULT_VERSION = "v2"
DEFAULT_ARTIFACT_NAME = "cross_platform_signal_top_candidates"

AIRFLOW_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(os.getenv("BRANDMATE_REPO_ROOT", AIRFLOW_ROOT.parent))
INCLUDE_DIR = Path(os.getenv("BRANDMATE_AIRFLOW_INCLUDE_DIR", AIRFLOW_ROOT / "include"))
MOCK_GCS_BASE_DIR = Path(
    os.getenv("BRANDMATE_MOCK_GCS_BASE_DIR", AIRFLOW_ROOT / "mock_gcs")
)
GCS_CACHE_BASE_DIR = Path(
    os.getenv("BRANDMATE_AIRFLOW_GCS_CACHE_DIR", AIRFLOW_ROOT / "gcs_data_cache")
)
GCS_LOGS_PREFIX = os.getenv(
    "BRANDMATE_AIRFLOW_GCS_LOGS_PREFIX",
    "gs://ssakda/projects/brandmate/logs/data_pipeline/airflow",
).rstrip("/")
SNS_TREND_PROCESSED_GCS_ROOT = os.getenv(
    "BRANDMATE_SNS_TREND_PROCESSED_GCS_ROOT", ""
).strip()
SNS_TREND_VALIDATION_SCHEDULE = (
    os.getenv("BRANDMATE_SNS_TREND_VALIDATION_SCHEDULE", "").strip() or None
)

for import_path in (INCLUDE_DIR,):
    import_path_value = str(import_path)
    if import_path_value not in sys.path:
        sys.path.insert(0, import_path_value)

from airflow.decorators import dag, task  # noqa: E402
from airflow.exceptions import AirflowException  # noqa: E402
from airflow.operators.python import get_current_context  # noqa: E402

from sns_trend.storage import (  # noqa: E402
    StorageError,
    discover_latest_gcs_processed_version,
    sync_gcs_prefix_to_local,
    upload_json_to_gcs,
)
from sns_trend.validation import (  # noqa: E402
    ProcessedValidationError,
    validate_processed_package,
    write_json,
)


def _bool_conf(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _int_conf(value: Any, *, default: int | None) -> int | None:
    if value is None:
        return default
    if value == "":
        return None
    return int(value)


def _repo_path(value: str) -> Path:
    if value.startswith("gs://"):
        raise AirflowException("GCS URI는 source_gcs_prefix로 전달하세요.")
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _cache_processed_dir(*, version: str, run_id: str) -> Path:
    return (
        GCS_CACHE_BASE_DIR
        / f"dag_id={DAG_ID}"
        / f"version={_safe_path_fragment(version)}"
        / f"run_id={_safe_path_fragment(run_id)}"
        / DEFAULT_ARTIFACT_NAME
    )


def _safe_path_fragment(value: str) -> str:
    safe_value = re.sub(r"[^A-Za-z0-9_.=-]+", "_", value).strip("_")
    return safe_value or "unknown"


def _optional_conf_str(conf: dict[str, Any], key: str) -> str | None:
    value = conf.get(key)
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def _version_from_path(value: str) -> str | None:
    match = re.search(r"(?:^|/)v([1-9]\d*)(?:/|$)", value.strip("/"))
    if not match:
        return None
    return f"v{match.group(1)}"


def _gcs_processed_prefix(*, gcs_root: str, version: str) -> str:
    return f"{gcs_root.rstrip('/')}/{version}/{DEFAULT_ARTIFACT_NAME}/"


def _resolve_processed_config(
    *,
    conf: dict[str, Any],
    run_id: str,
    processed_gcs_root: str = SNS_TREND_PROCESSED_GCS_ROOT,
) -> dict[str, Any]:
    requested_version = _optional_conf_str(conf, "version")
    processed_prefix = _optional_conf_str(conf, "processed_prefix")
    source_gcs_prefix = _optional_conf_str(conf, "source_gcs_prefix") or _optional_conf_str(
        conf, "processed_gcs_prefix"
    )
    discovery_summary = None

    if processed_prefix and processed_prefix.startswith("gs://") and not source_gcs_prefix:
        source_gcs_prefix = processed_prefix
        processed_prefix = None

    if source_gcs_prefix:
        version = requested_version or _version_from_path(source_gcs_prefix) or DEFAULT_VERSION
        source_gcs_prefix = source_gcs_prefix.rstrip("/") + "/"
        processed_dir = _cache_processed_dir(version=version, run_id=run_id)
        source_type = "gcs"
    elif requested_version and processed_gcs_root:
        version = requested_version
        source_gcs_prefix = _gcs_processed_prefix(
            gcs_root=processed_gcs_root,
            version=version,
        )
        processed_dir = _cache_processed_dir(version=version, run_id=run_id)
        source_type = "gcs"
    elif processed_gcs_root:
        try:
            discovery_summary = discover_latest_gcs_processed_version(
                gcs_root=processed_gcs_root,
                artifact_name=DEFAULT_ARTIFACT_NAME,
            )
        except StorageError as error:
            raise AirflowException(str(error)) from error
        version = str(discovery_summary["version"])
        source_gcs_prefix = str(discovery_summary["source_gcs_prefix"])
        processed_dir = _cache_processed_dir(version=version, run_id=run_id)
        source_type = "gcs"
    else:
        version = requested_version or _version_from_path(processed_prefix or "") or DEFAULT_VERSION
        processed_prefix = processed_prefix or (
            "data/processed/sns_trend/"
            f"{version}/{DEFAULT_ARTIFACT_NAME}/"
        )
        processed_dir = _repo_path(processed_prefix)
        source_type = "local"

    return {
        "version": version,
        "source_type": source_type,
        "source_gcs_prefix": source_gcs_prefix,
        "gcs_version_discovery": discovery_summary,
        "processed_dir": str(processed_dir),
        "json_path": str(processed_dir / f"{DEFAULT_ARTIFACT_NAME}.json"),
        "csv_path": str(processed_dir / f"{DEFAULT_ARTIFACT_NAME}.csv"),
        "expected_card_count": _int_conf(conf.get("expected_card_count"), default=20),
        "expected_schema_version": conf.get("expected_schema_version", "2.0"),
        "api_loader_smoke": _bool_conf(conf.get("api_loader_smoke"), default=True),
        "dvc_check": _bool_conf(conf.get("dvc_check"), default=True),
        "require_dvc": _bool_conf(conf.get("require_dvc"), default=False),
        "write_gcs_summary": _bool_conf(
            conf.get("write_gcs_summary"),
            default=bool(source_gcs_prefix),
        ),
        "gcs_logs_prefix": str(conf.get("gcs_logs_prefix") or GCS_LOGS_PREFIX),
    }


@dag(
    dag_id=DAG_ID,
    start_date=datetime(2026, 7, 26),
    schedule=SNS_TREND_VALIDATION_SCHEDULE,
    catchup=False,
    max_active_runs=1,
    tags=["brandmate", "sns_trend", "processed", "validation"],
    default_args={"owner": "brandmate-data", "retries": 0},
    doc_md="""
    Validate the official `sns_trend` processed package.

    Manual trigger config:

    ```json
    {
      "version": "v2",
      "processed_prefix": "data/processed/sns_trend/v2/cross_platform_signal_top_candidates/",
      "source_gcs_prefix": "gs://ssakda/projects/brandmate/data/processed/sns_trend/v2/cross_platform_signal_top_candidates/"
    }
    ```
    """,
)
def sns_trend_processed_validation() -> None:
    @task
    def resolve_processed_package() -> dict[str, Any]:
        context = get_current_context()
        dag_run = context.get("dag_run")
        run_id = str(getattr(dag_run, "run_id", "manual"))
        conf = dict(getattr(dag_run, "conf", None) or {})

        return _resolve_processed_config(conf=conf, run_id=run_id)

    @task
    def sync_processed_package_from_gcs(config: dict[str, Any]) -> dict[str, Any]:
        if config.get("source_type") != "gcs":
            return {
                **config,
                "gcs_sync": {
                    "status": "skipped",
                    "reason": "local processed_prefix was provided",
                },
            }

        try:
            sync_summary = sync_gcs_prefix_to_local(
                gcs_prefix=str(config["source_gcs_prefix"]),
                local_dir=Path(config["processed_dir"]),
                required_file_names={
                    f"{DEFAULT_ARTIFACT_NAME}.json",
                    f"{DEFAULT_ARTIFACT_NAME}.csv",
                },
            )
        except StorageError as error:
            raise AirflowException(str(error)) from error

        return {**config, "gcs_sync": sync_summary}

    @task
    def validate_package(config: dict[str, Any]) -> dict[str, Any]:
        try:
            return validate_processed_package(
                repo_root=REPO_ROOT,
                processed_dir=Path(config["processed_dir"]),
                json_path=Path(config["json_path"]),
                csv_path=Path(config["csv_path"]),
                expected_card_count=config["expected_card_count"],
                expected_schema_version=config["expected_schema_version"],
                api_loader_smoke=config["api_loader_smoke"],
                dvc_check=config["dvc_check"],
                require_dvc=config["require_dvc"],
            )
        except ProcessedValidationError as error:
            raise AirflowException(str(error)) from error

    @task
    def write_validation_summary(
        summary: dict[str, Any],
        config: dict[str, Any],
    ) -> dict[str, Any]:
        context = get_current_context()
        dag_run = context.get("dag_run")
        run_id = str(getattr(dag_run, "run_id", "manual"))

        summary_path = (
            MOCK_GCS_BASE_DIR
            / "logs"
            / "data_pipeline"
            / "airflow"
            / f"dag_id={DAG_ID}"
            / f"version={_safe_path_fragment(config['version'])}"
            / f"run_id={_safe_path_fragment(run_id)}"
            / "validation_summary.json"
        )
        persisted_summary = {
            **summary,
            "dag_id": DAG_ID,
            "run_id": run_id,
            "source_type": config.get("source_type"),
            "source_gcs_prefix": config.get("source_gcs_prefix"),
            "gcs_sync": config.get("gcs_sync"),
            "validation_summary_path": str(summary_path),
        }
        write_json(summary_path, persisted_summary)
        gcs_summary_uri = None
        if config.get("write_gcs_summary"):
            gcs_summary_uri = (
                str(config["gcs_logs_prefix"]).rstrip("/")
                + f"/dag_id={DAG_ID}"
                + f"/version={_safe_path_fragment(config['version'])}"
                + f"/run_id={_safe_path_fragment(run_id)}"
                + "/validation_summary.json"
            )
            try:
                upload_result = upload_json_to_gcs(
                    gcs_uri=gcs_summary_uri,
                    payload={**persisted_summary, "gcs_validation_summary_path": gcs_summary_uri},
                )
            except StorageError as error:
                raise AirflowException(str(error)) from error
            persisted_summary["gcs_validation_summary_path"] = gcs_summary_uri
            persisted_summary["gcs_summary_upload"] = upload_result
            write_json(summary_path, persisted_summary)

        return {
            "status": persisted_summary["status"],
            "card_count": persisted_summary["card_count"],
            "validation_summary_path": str(summary_path),
            "gcs_validation_summary_path": gcs_summary_uri,
        }

    resolved_config = resolve_processed_package()
    synced_config = sync_processed_package_from_gcs(resolved_config)
    validation_summary = validate_package(synced_config)
    write_validation_summary(validation_summary, synced_config)


sns_trend_processed_validation()
