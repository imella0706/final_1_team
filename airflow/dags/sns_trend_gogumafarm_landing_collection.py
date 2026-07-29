"""Airflow DAG for collecting Gogumafarm landing and curated candidate artifacts.

[Design Intent] Keep Phase 4 orchestration thin: Airflow runs the existing
Gogumafarm crawler CLI and verifies the landing/curated artifact contract. It
does not promote candidates to the official processed package.
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


DAG_ID = "sns_trend_gogumafarm_landing_collection"
SOURCE_NAME = "gogumafarm"
DEFAULT_CURATED_VERSION = "v3"
KST = ZoneInfo("Asia/Seoul")

AIRFLOW_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(os.getenv("BRANDMATE_REPO_ROOT", AIRFLOW_ROOT.parent))
GOGUMAFARM_DIR = REPO_ROOT / "gather_data" / "crawling" / "gogumafarm"
LANDING_ROOT = REPO_ROOT / "data" / "landing" / "sns_trend"
CURATED_ROOT = REPO_ROOT / "data" / "curated" / "sns_trend"

GOGUMAFARM_LANDING_SCHEDULE = (
    os.getenv("BRANDMATE_SNS_TREND_GOGUMAFARM_LANDING_SCHEDULE", "40 18 * * 3").strip()
    or "40 18 * * 3"
)
GOGUMAFARM_CURATED_VERSION = (
    os.getenv(
        "BRANDMATE_SNS_TREND_GOGUMAFARM_CURATED_VERSION",
        DEFAULT_CURATED_VERSION,
    ).strip()
    or DEFAULT_CURATED_VERSION
)
GOGUMAFARM_DELAY_SECONDS = float(
    os.getenv("BRANDMATE_SNS_TREND_GOGUMAFARM_DELAY", "1.0")
)
GOGUMAFARM_TIMEOUT_SECONDS = float(
    os.getenv("BRANDMATE_SNS_TREND_GOGUMAFARM_TIMEOUT", "15")
)
GOGUMAFARM_RETRIES = int(
    os.getenv("BRANDMATE_SNS_TREND_GOGUMAFARM_RETRIES", "3")
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


def _float_conf(value: Any, *, default: float, minimum: float) -> float:
    if value is None or value == "":
        result = default
    else:
        result = float(value)
    if result < minimum:
        raise AirflowException(f"value must be at least {minimum}")
    return result


def _int_conf(value: Any, *, default: int, minimum: int) -> int:
    if value is None or value == "":
        result = default
    else:
        result = int(value)
    if result < minimum:
        raise AirflowException(f"value must be at least {minimum}")
    return result


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


def _stamp_from_run_date(run_date: str) -> str:
    return run_date.replace("-", "")


def _resolve_gogumafarm_landing_config(
    *,
    conf: dict[str, Any],
    dag_run_id: str,
    logical_date: Any,
    landing_root: Path = LANDING_ROOT,
    curated_root: Path = CURATED_ROOT,
    gogumafarm_dir: Path = GOGUMAFARM_DIR,
) -> dict[str, Any]:
    run_datetime = _date_from_logical_date(logical_date)
    run_date = str(conf.get("run_date") or conf.get("date") or run_datetime.date())
    week = str(conf.get("week") or _iso_week(run_datetime)).strip().upper()
    run_id = _safe_path_fragment(str(conf.get("run_id") or dag_run_id))
    curated_version = str(
        conf.get("curated_version") or GOGUMAFARM_CURATED_VERSION
    ).strip()
    emit_curated = _bool_conf(
        conf.get("emit_curated_meme_card_candidates"),
        default=True,
    )
    fail_if_exists = _bool_conf(conf.get("fail_if_exists"), default=False)
    resume = _bool_conf(conf.get("resume"), default=False)
    delay = _float_conf(
        conf.get("delay"),
        default=GOGUMAFARM_DELAY_SECONDS,
        minimum=1.0,
    )
    timeout = _float_conf(
        conf.get("timeout"),
        default=GOGUMAFARM_TIMEOUT_SECONDS,
        minimum=0.1,
    )
    retries = _int_conf(
        conf.get("retries"),
        default=GOGUMAFARM_RETRIES,
        minimum=0,
    )
    log_level = str(conf.get("log_level") or "INFO").strip().upper()

    if not re.fullmatch(r"\d{4}-W\d{2}", week):
        raise AirflowException("week must use YYYY-Www format")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", run_date):
        raise AirflowException("run_date must use YYYY-MM-DD format")
    if not re.fullmatch(r"v[1-9]\d*", curated_version):
        raise AirflowException("curated_version must use vN format")
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR"}:
        raise AirflowException("log_level must be one of: DEBUG, INFO, WARNING, ERROR")

    stamp = _stamp_from_run_date(run_date)
    run_dir = (
        landing_root
        / f"week={week}"
        / "raw"
        / SOURCE_NAME
        / f"run_id={run_id}"
    )
    curated_candidates = (
        curated_root
        / curated_version
        / "meme_card_candidates"
        / SOURCE_NAME
        / f"gogumafarm_meme_card_candidates_{week}.json"
    )

    return {
        "source": SOURCE_NAME,
        "week": week,
        "run_id": run_id,
        "run_date": run_date,
        "stamp": stamp,
        "curated_version": curated_version,
        "emit_curated_meme_card_candidates": emit_curated,
        "fail_if_exists": fail_if_exists,
        "resume": resume,
        "delay": delay,
        "timeout": timeout,
        "retries": retries,
        "log_level": log_level,
        "gogumafarm_dir": str(gogumafarm_dir),
        "run_dir": str(run_dir),
        "curated_root": str(curated_root),
        "raw_json": str(run_dir / f"gogumafarm_memes_{stamp}.json"),
        "article_csv": str(run_dir / f"gogumafarm_articles_{stamp}.csv"),
        "term_csv": str(run_dir / f"gogumafarm_meme_terms_{stamp}.csv"),
        "term_json": str(run_dir / f"gogumafarm_meme_terms_{stamp}.json"),
        "crawler_run_summary": str(run_dir / "crawler_run_summary.json"),
        "error_json": str(run_dir / "error.json"),
        "curated_meme_card_candidates": str(curated_candidates),
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
        "gogumafarm_crawler.py",
        "--week",
        str(config["week"]),
        "--run-id",
        str(config["run_id"]),
        "--date",
        str(config["run_date"]),
        "--output-dir",
        str(config["run_dir"]),
        "--curated-version",
        str(config["curated_version"]),
        "--curated-root",
        str(config["curated_root"]),
        "--delay",
        str(config["delay"]),
        "--timeout",
        str(config["timeout"]),
        "--retries",
        str(config["retries"]),
        "--log-level",
        str(config["log_level"]),
    ]
    if config.get("emit_curated_meme_card_candidates"):
        command.append("--emit-curated-meme-card-candidates")
    if config.get("fail_if_exists"):
        command.append("--fail-if-exists")
    if config.get("resume"):
        command.append("--resume")
    return command


def _verify_gogumafarm_landing_artifacts(config: dict[str, Any]) -> dict[str, Any]:
    raw_json = Path(config["raw_json"])
    article_csv = Path(config["article_csv"])
    term_csv = Path(config["term_csv"])
    term_json = Path(config["term_json"])
    summary_json = Path(config["crawler_run_summary"])
    error_json = Path(config["error_json"])
    curated_candidates = Path(config["curated_meme_card_candidates"])

    expected_paths = [raw_json, article_csv, term_csv, term_json, summary_json]
    if config.get("emit_curated_meme_card_candidates"):
        expected_paths.append(curated_candidates)
    missing = [str(path) for path in expected_paths if not path.is_file()]
    if missing:
        raise AirflowException(f"missing Gogumafarm landing artifacts: {missing}")
    if error_json.exists():
        raise AirflowException(
            f"Gogumafarm landing error artifact exists: {error_json}"
        )

    raw_document = json.loads(raw_json.read_text(encoding="utf-8"))
    if raw_document.get("source") != SOURCE_NAME:
        raise AirflowException(f"raw JSON source is not {SOURCE_NAME}: {raw_json}")

    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    if summary.get("status") != "success":
        raise AirflowException(f"crawler_run_summary status is not success: {summary}")
    if summary.get("source") != SOURCE_NAME:
        raise AirflowException(f"crawler_run_summary source is not {SOURCE_NAME}")
    if summary.get("week") != config["week"] or summary.get("run_id") != config["run_id"]:
        raise AirflowException("crawler_run_summary week/run_id does not match config")

    with article_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        article_rows = sum(1 for _ in csv.DictReader(handle))
    with term_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        term_rows = sum(1 for _ in csv.DictReader(handle))
    terms = json.loads(term_json.read_text(encoding="utf-8"))
    if not isinstance(terms, list):
        raise AirflowException(f"term JSON must be a list: {term_json}")
    if int(summary.get("article_count", -1)) != article_rows:
        raise AirflowException("article CSV row count does not match summary")

    curated_check: dict[str, Any] | None = None
    if config.get("emit_curated_meme_card_candidates"):
        curated_payload = json.loads(curated_candidates.read_text(encoding="utf-8"))
        if curated_payload.get("stage") != "curated":
            raise AirflowException("curated candidate stage must be curated")
        if curated_payload.get("artifact_name") != "meme_card_candidates":
            raise AirflowException(
                "curated candidate artifact_name must be meme_card_candidates"
            )
        if curated_payload.get("source_landing_run_id") != config["run_id"]:
            raise AirflowException(
                "curated candidate source_landing_run_id does not match"
            )
        curated_check = {
            "path": str(curated_candidates),
            "term_count": curated_payload.get("term_count"),
            "review_status": curated_payload.get("review_status"),
        }

    return {
        **config,
        "artifact_check": {
            "status": "passed",
            "raw_json": str(raw_json),
            "article_csv": str(article_csv),
            "term_csv": str(term_csv),
            "term_json": str(term_json),
            "crawler_run_summary": str(summary_json),
            "article_count": article_rows,
            "term_csv_row_count": term_rows,
            "term_json_count": len(terms),
            "curated_meme_card_candidates": curated_check,
        },
    }


@dag(
    dag_id=DAG_ID,
    start_date=datetime(2026, 7, 27),
    schedule=GOGUMAFARM_LANDING_SCHEDULE,
    catchup=False,
    max_active_runs=1,
    tags=["brandmate", "sns_trend", "landing", "gogumafarm"],
    default_args={"owner": "brandmate-data", "retries": 0},
    doc_md="""
    Collect Gogumafarm `sns_trend` landing and curated candidate artifacts.

    Manual trigger config:

    ```json
    {
      "week": "2026-W31",
      "run_date": "2026-07-27",
      "run_id": "manual__gogumafarm_phase4_smoke",
      "emit_curated_meme_card_candidates": true
    }
    ```
    """,
)
def sns_trend_gogumafarm_landing_collection() -> None:
    @task
    def resolve_gogumafarm_landing_context() -> dict[str, Any]:
        context = get_current_context()
        dag_run = context.get("dag_run")
        conf = dict(getattr(dag_run, "conf", None) or {})
        dag_run_id = str(getattr(dag_run, "run_id", "manual"))

        return _resolve_gogumafarm_landing_config(
            conf=conf,
            dag_run_id=dag_run_id,
            logical_date=context.get("logical_date"),
        )

    @task
    def collect_gogumafarm_landing(config: dict[str, Any]) -> dict[str, Any]:
        result = _run_command(
            _collector_command(config),
            cwd=Path(config["gogumafarm_dir"]),
            env=os.environ.copy(),
        )
        return {**config, "collector": result}

    @task
    def verify_gogumafarm_landing_contract(config: dict[str, Any]) -> dict[str, Any]:
        return _verify_gogumafarm_landing_artifacts(config)

    @task
    def upload_gogumafarm_landing_to_gcs(config: dict[str, Any]) -> dict[str, Any]:
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
                f"Failed to upload Gogumafarm landing artifacts to GCS: {error}"
            ) from error

    resolved_config = resolve_gogumafarm_landing_context()
    collected = collect_gogumafarm_landing(resolved_config)
    verified = verify_gogumafarm_landing_contract(collected)
    upload_gogumafarm_landing_to_gcs(verified)


sns_trend_gogumafarm_landing_collection()

