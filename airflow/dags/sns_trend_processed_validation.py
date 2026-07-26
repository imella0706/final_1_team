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

for import_path in (INCLUDE_DIR,):
    import_path_value = str(import_path)
    if import_path_value not in sys.path:
        sys.path.insert(0, import_path_value)

from airflow.decorators import dag, task  # noqa: E402
from airflow.exceptions import AirflowException  # noqa: E402
from airflow.operators.python import get_current_context  # noqa: E402

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
        raise AirflowException(
            "GCS 직접 읽기는 아직 이 DAG의 MVP 범위가 아닙니다. "
            "processed package를 /opt/airflow/data 아래로 sync/mount한 뒤 실행하세요."
        )
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def _safe_path_fragment(value: str) -> str:
    safe_value = re.sub(r"[^A-Za-z0-9_.=-]+", "_", value).strip("_")
    return safe_value or "unknown"


@dag(
    dag_id=DAG_ID,
    start_date=datetime(2026, 7, 26),
    schedule=None,
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
      "processed_prefix": "data/processed/sns_trend/v2/cross_platform_signal_top_candidates/"
    }
    ```
    """,
)
def sns_trend_processed_validation() -> None:
    @task
    def resolve_processed_package() -> dict[str, Any]:
        context = get_current_context()
        dag_run = context.get("dag_run")
        conf = dict(getattr(dag_run, "conf", None) or {})

        version = str(conf.get("version") or DEFAULT_VERSION)
        processed_prefix = str(
            conf.get("processed_prefix")
            or (
                "data/processed/sns_trend/"
                f"{version}/{DEFAULT_ARTIFACT_NAME}/"
            )
        )
        processed_dir = _repo_path(processed_prefix)

        return {
            "version": version,
            "processed_dir": str(processed_dir),
            "json_path": str(processed_dir / f"{DEFAULT_ARTIFACT_NAME}.json"),
            "csv_path": str(processed_dir / f"{DEFAULT_ARTIFACT_NAME}.csv"),
            "expected_card_count": _int_conf(conf.get("expected_card_count"), default=20),
            "expected_schema_version": conf.get("expected_schema_version", "2.0"),
            "api_loader_smoke": _bool_conf(conf.get("api_loader_smoke"), default=True),
            "dvc_check": _bool_conf(conf.get("dvc_check"), default=True),
            "require_dvc": _bool_conf(conf.get("require_dvc"), default=False),
        }

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
            "validation_summary_path": str(summary_path),
        }
        write_json(summary_path, persisted_summary)
        return {
            "status": persisted_summary["status"],
            "card_count": persisted_summary["card_count"],
            "validation_summary_path": str(summary_path),
        }

    resolved_config = resolve_processed_package()
    validation_summary = validate_package(resolved_config)
    write_validation_summary(validation_summary, resolved_config)


sns_trend_processed_validation()
