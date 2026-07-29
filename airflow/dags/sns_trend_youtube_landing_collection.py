"""Airflow DAG for collecting YouTube landing artifacts.

[Design Intent] Keep Phase 4 focused on the landing contract only: collect the
raw YouTube video snapshot, derive the keyword,count CSV, and verify artifacts.
GCS upload and processed promotion stay in later phases.
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo


DAG_ID = "sns_trend_youtube_landing_collection"
SOURCE_NAME = "youtube"
DEFAULT_REGION = "KR"
DEFAULT_LIMIT = 100
DEFAULT_CURATED_VERSION = "v3"
KST = ZoneInfo("Asia/Seoul")

AIRFLOW_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(os.getenv("BRANDMATE_REPO_ROOT", AIRFLOW_ROOT.parent))
YOUTUBE_DIR = REPO_ROOT / "gather_data" / "youtube"
LANDING_ROOT = REPO_ROOT / "data" / "landing" / "sns_trend"
CURATED_ROOT = REPO_ROOT / "data" / "curated" / "sns_trend"
YOUTUBE_LANDING_SCHEDULE = (
    os.getenv("BRANDMATE_SNS_TREND_YOUTUBE_LANDING_SCHEDULE", "40 18 * * 3").strip()
    or "40 18 * * 3"
)
YOUTUBE_LANDING_LIMIT = int(
    os.getenv("BRANDMATE_SNS_TREND_YOUTUBE_LANDING_LIMIT", str(DEFAULT_LIMIT))
)

from airflow.decorators import dag, task  # noqa: E402
from airflow.exceptions import AirflowException  # noqa: E402
from airflow.operators.python import get_current_context  # noqa: E402


def _safe_path_fragment(value: str) -> str:
    safe_value = re.sub(r"[^A-Za-z0-9_.:+@=-]+", "_", value).strip("_")
    return safe_value or "unknown"


def _bool_conf(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().casefold() in {"1", "true", "yes", "y", "on"}
    return bool(value)


def _int_conf(value: Any, *, default: int) -> int:
    if value is None or value == "":
        return default
    result = int(value)
    if not 1 <= result <= 500:
        raise AirflowException("limit must be between 1 and 500")
    return result


def _dataset_version_conf(value: Any, *, default: str) -> str:
    version = str(value or default).strip().lower()
    if not re.fullmatch(r"v[1-9]\d*", version):
        raise AirflowException("curated_version must use vN format")
    return version


def _date_from_logical_date(value: Any) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).astimezone(KST)
    if hasattr(value, "in_timezone"):
        return value.in_timezone("Asia/Seoul")
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(KST)
    return datetime.now(timezone.utc).astimezone(KST)


def _iso_week(value: datetime) -> str:
    iso = value.date().isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _resolve_youtube_landing_config(
    *,
    conf: dict[str, Any],
    dag_run_id: str,
    logical_date: Any,
    landing_root: Path = LANDING_ROOT,
    youtube_dir: Path = YOUTUBE_DIR,
    curated_root: Path = CURATED_ROOT,
) -> dict[str, Any]:
    run_datetime = _date_from_logical_date(logical_date)
    run_date = str(conf.get("run_date") or conf.get("date") or run_datetime.date())
    week = str(conf.get("week") or _iso_week(run_datetime)).strip().upper()
    region = str(conf.get("region") or DEFAULT_REGION).strip().upper()
    run_id = _safe_path_fragment(str(conf.get("run_id") or dag_run_id))
    limit = _int_conf(conf.get("limit"), default=YOUTUBE_LANDING_LIMIT)
    fail_if_exists = _bool_conf(conf.get("fail_if_exists"), default=False)
    emit_curated = _bool_conf(
        conf.get("emit_curated_meme_card_candidates"),
        default=True,
    )
    curated_version = _dataset_version_conf(
        conf.get("curated_version"),
        default=DEFAULT_CURATED_VERSION,
    )
    upload_gcs = _bool_conf(
        conf.get("upload_gcs"),
        default=True,
    )
    tokenizer = str(conf.get("tokenizer") or "regex").strip()

    if not re.fullmatch(r"\d{4}-W\d{2}", week):
        raise AirflowException("week must use YYYY-Www format")
    if not re.fullmatch(r"[A-Z]{2}", region):
        raise AirflowException("region must be two ASCII letters")
    if tokenizer not in {"regex", "okt"}:
        raise AirflowException("tokenizer must be one of: regex, okt")

    run_dir = (
        landing_root
        / f"week={week}"
        / "raw"
        / SOURCE_NAME
        / f"run_id={run_id}"
    )
    raw_csv = run_dir / f"youtube_trending_{region}_{week}.csv"
    keyword_csv = run_dir / f"youtube_keywords_{run_date}.csv"
    summary_json = run_dir / "crawler_run_summary.json"
    curated_candidates_json = (
        curated_root
        / curated_version
        / "meme_card_candidates"
        / SOURCE_NAME
        / f"youtube_meme_card_candidates_{week}.json"
    )

    return {
        "source": SOURCE_NAME,
        "week": week,
        "run_id": run_id,
        "run_date": run_date,
        "region": region,
        "limit": limit,
        "tokenizer": tokenizer,
        "upload_gcs": upload_gcs,
        "fail_if_exists": fail_if_exists,
        "emit_curated_meme_card_candidates": emit_curated,
        "curated_version": curated_version,
        "youtube_dir": str(youtube_dir),
        "run_dir": str(run_dir),
        "raw_csv": str(raw_csv),
        "keyword_csv": str(keyword_csv),
        "crawler_run_summary": str(summary_json),
        "curated_root": str(curated_root),
        "curated_candidates_json": str(curated_candidates_json),
    }


def _run_command(command: list[str], *, cwd: Path, env: dict[str, str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        message = completed.stderr.strip() or completed.stdout.strip()
        raise AirflowException(
            f"command failed with exit code {completed.returncode}: {message}"
        )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
    }


def _collector_command(config: dict[str, Any]) -> list[str]:
    command = [
        sys.executable,
        "youtube_trending_collector.py",
        "--week",
        str(config["week"]),
        "--run-id",
        str(config["run_id"]),
        "--date",
        str(config["run_date"]),
        "--region",
        str(config["region"]),
        "--limit",
        str(config["limit"]),
        "--output-dir",
        str(config["run_dir"]),
    ]
    if config.get("fail_if_exists"):
        command.append("--fail-if-exists")
    return command


def _keyword_command(config: dict[str, Any]) -> list[str]:
    command = [
        sys.executable,
        "daily_keyword_tracker.py",
        "--input-csv",
        str(config["raw_csv"]),
        "--date",
        str(config["run_date"]),
        "--output-file",
        str(config["keyword_csv"]),
        "--tokenizer",
        str(config["tokenizer"]),
    ]
    if config.get("emit_curated_meme_card_candidates"):
        command.extend(
            [
                "--week",
                str(config["week"]),
                "--run-id",
                str(config["run_id"]),
                "--emit-curated-meme-card-candidates",
                "--curated-version",
                str(config["curated_version"]),
                "--curated-root",
                str(config["curated_root"]),
            ]
        )
    if config.get("fail_if_exists"):
        command.append("--fail-if-exists")
    return command


def _verify_youtube_landing_artifacts(config: dict[str, Any]) -> dict[str, Any]:
    run_dir = Path(config["run_dir"])
    raw_csv = Path(config["raw_csv"])
    keyword_csv = Path(config["keyword_csv"])
    summary_json = Path(config["crawler_run_summary"])
    error_json = run_dir / "error.json"

    required_paths = [raw_csv, keyword_csv, summary_json]
    if config.get("emit_curated_meme_card_candidates"):
        curated_candidates_json = Path(config["curated_candidates_json"])
        required_paths.append(curated_candidates_json)
    missing = [
        str(path)
        for path in required_paths
        if not path.is_file()
    ]
    if missing:
        raise AirflowException(f"missing YouTube landing artifacts: {missing}")
    if error_json.exists():
        raise AirflowException(f"YouTube landing error artifact exists: {error_json}")

    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    if summary.get("status") != "success":
        raise AirflowException(f"crawler_run_summary status is not success: {summary}")

    with keyword_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = list(reader.fieldnames or [])
        keyword_rows = sum(1 for _ in reader)

    if fields != ["keyword", "count"]:
        raise AirflowException(
            f"YouTube keyword CSV must use keyword,count columns. Got: {fields}"
        )

    artifact_check = {
        "status": "passed",
        "raw_csv": str(raw_csv),
        "keyword_csv": str(keyword_csv),
        "crawler_run_summary": str(summary_json),
        "collected_count": summary.get("collected_count"),
        "keyword_row_count": keyword_rows,
    }
    if config.get("emit_curated_meme_card_candidates"):
        curated_candidates_json = Path(config["curated_candidates_json"])
        curated_payload = json.loads(
            curated_candidates_json.read_text(encoding="utf-8")
        )
        expected = {
            "stage": "curated",
            "artifact_name": "meme_card_candidates",
            "source_family": SOURCE_NAME,
            "review_status": "pending",
            "collected_week": config["week"],
            "source_landing_run_id": config["run_id"],
        }
        mismatches = {
            key: {"expected": value, "actual": curated_payload.get(key)}
            for key, value in expected.items()
            if curated_payload.get(key) != value
        }
        if mismatches:
            raise AirflowException(
                f"YouTube curated candidate metadata mismatch: {mismatches}"
            )
        if int(curated_payload.get("term_count") or 0) <= 0:
            raise AirflowException("YouTube curated candidates must contain terms")
        artifact_check["curated_candidates_json"] = str(curated_candidates_json)
        artifact_check["curated_term_count"] = curated_payload.get("term_count")

    return {
        **config,
        "artifact_check": artifact_check,
    }


@dag(
    dag_id=DAG_ID,
    start_date=datetime(2026, 7, 27),
    schedule=YOUTUBE_LANDING_SCHEDULE,
    catchup=False,
    max_active_runs=1,
    tags=["brandmate", "sns_trend", "landing", "youtube"],
    default_args={"owner": "brandmate-data", "retries": 0},
    doc_md="""
    Collect YouTube `sns_trend` landing artifacts.

    Manual trigger config:

    ```json
    {
      "week": "2026-W31",
      "run_date": "2026-07-27",
      "run_id": "manual__youtube_phase4_smoke",
      "limit": 5,
      "upload_gcs": true,
      "emit_curated_meme_card_candidates": true
    }
    ```
    """,
)
def sns_trend_youtube_landing_collection() -> None:
    @task
    def resolve_youtube_landing_context() -> dict[str, Any]:
        context = get_current_context()
        dag_run = context.get("dag_run")
        conf = dict(getattr(dag_run, "conf", None) or {})
        dag_run_id = str(getattr(dag_run, "run_id", "manual"))

        return _resolve_youtube_landing_config(
            conf=conf,
            dag_run_id=dag_run_id,
            logical_date=context.get("logical_date"),
        )

    @task
    def collect_youtube_trending_raw(config: dict[str, Any]) -> dict[str, Any]:
        if not os.getenv("YOUTUBE_API_KEY", "").strip():
            raise AirflowException("YOUTUBE_API_KEY is missing in Airflow environment")

        result = _run_command(
            _collector_command(config),
            cwd=Path(config["youtube_dir"]),
            env=os.environ.copy(),
        )
        return {**config, "collector": result}

    @task
    def build_youtube_keyword_snapshot(config: dict[str, Any]) -> dict[str, Any]:
        result = _run_command(
            _keyword_command(config),
            cwd=Path(config["youtube_dir"]),
            env=os.environ.copy(),
        )
        return {**config, "keyword_tracker": result}

    @task
    def verify_youtube_landing_contract(config: dict[str, Any]) -> dict[str, Any]:
        return _verify_youtube_landing_artifacts(config)

    @task
    def upload_youtube_landing_to_gcs(config: dict[str, Any]) -> dict[str, Any]:
        if not config.get("upload_gcs", True):
            return {**config, "gcs_landing_upload": {"status": "skipped", "reason": "upload_gcs is False"}}

        from sns_trend.storage import StorageError, upload_dir_to_gcs

        run_dir = Path(config["run_dir"])
        week = config["week"]
        source = config["source"]
        run_id = config["run_id"]
        gcs_landing_prefix = str(
            config.get("gcs_landing_prefix")
            or f"gs://ssakda/projects/brandmate/data/landing/sns_trend/week={week}/raw/{source}/run_id={run_id}/"
        )

        try:
            upload_result = upload_dir_to_gcs(
                local_dir=run_dir,
                gcs_prefix=gcs_landing_prefix,
            )
            return {**config, "gcs_landing_upload": upload_result}
        except StorageError as error:
            raise AirflowException(
                f"Failed to upload YouTube landing artifacts to GCS: {error}"
            ) from error

    resolved_config = resolve_youtube_landing_context()
    raw_collected = collect_youtube_trending_raw(resolved_config)
    keywords_built = build_youtube_keyword_snapshot(raw_collected)
    verified = verify_youtube_landing_contract(keywords_built)
    upload_youtube_landing_to_gcs(verified)


sns_trend_youtube_landing_collection()

