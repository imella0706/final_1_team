"""Airflow DAG for collecting Careet landing and curated candidate artifacts.

[Design Intent] Keep Phase 4 orchestration thin: Airflow runs the existing
Careet crawler CLI and verifies the landing/curated artifact contract. It does
not promote candidate terms to the official processed package.
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


DAG_ID = "sns_trend_careet_landing_collection"
SOURCE_NAME = "careet"
KST = ZoneInfo("Asia/Seoul")

AIRFLOW_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(os.getenv("BRANDMATE_REPO_ROOT", AIRFLOW_ROOT.parent))
CAREET_DIR = REPO_ROOT / "gather_data" / "crawling" / "careet"
LANDING_ROOT = REPO_ROOT / "data" / "landing" / "sns_trend"
CURATED_ROOT = REPO_ROOT / "data" / "curated" / "sns_trend"

CAREET_LANDING_SCHEDULE = os.environ[
    "BRANDMATE_SNS_TREND_CAREET_LANDING_SCHEDULE"
].strip()
CAREET_DELAY_SECONDS = float(os.getenv("BRANDMATE_SNS_TREND_CAREET_DELAY", "1.5"))
CAREET_TIMEOUT_SECONDS = float(os.getenv("BRANDMATE_SNS_TREND_CAREET_TIMEOUT", "15"))
CAREET_RETRIES = int(os.getenv("BRANDMATE_SNS_TREND_CAREET_RETRIES", "3"))
CAREET_CURATED_VERSION = os.getenv(
    "BRANDMATE_SNS_TREND_CAREET_CURATED_VERSION",
    "v3",
).strip()

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


def _resolve_careet_landing_config(
    *,
    conf: dict[str, Any],
    dag_run_id: str,
    logical_date: Any,
    landing_root: Path = LANDING_ROOT,
    curated_root: Path = CURATED_ROOT,
    careet_dir: Path = CAREET_DIR,
) -> dict[str, Any]:
    run_datetime = _date_from_logical_date(logical_date)
    run_date = str(conf.get("run_date") or conf.get("date") or run_datetime.date())
    week = str(conf.get("week") or _iso_week(run_datetime)).strip().upper()
    run_id = _safe_path_fragment(str(conf.get("run_id") or dag_run_id))
    curated_version = str(
        conf.get("curated_version") or CAREET_CURATED_VERSION
    ).strip()
    emit_curated = _bool_conf(
        conf.get("emit_curated_meme_card_candidates"),
        default=True,
    )
    start_page = _int_conf(conf.get("start_page"), default=1, minimum=1)
    end_page = conf.get("end_page")
    end_page_value = (
        _int_conf(end_page, default=start_page, minimum=1)
        if end_page is not None and end_page != ""
        else None
    )
    delay = _float_conf(conf.get("delay"), default=CAREET_DELAY_SECONDS, minimum=1.0)
    timeout = _float_conf(
        conf.get("timeout"),
        default=CAREET_TIMEOUT_SECONDS,
        minimum=0.1,
    )
    retries = _int_conf(conf.get("retries"), default=CAREET_RETRIES, minimum=0)
    summary_mode = str(conf.get("summary_mode") or "rule").strip()
    fail_if_exists = _bool_conf(conf.get("fail_if_exists"), default=False)
    resume = _bool_conf(conf.get("resume"), default=False)
    list_only = _bool_conf(conf.get("list_only"), default=False)
    download_thumbnails = _bool_conf(conf.get("download_thumbnails"), default=False)
    log_level = str(conf.get("log_level") or "INFO").strip().upper()

    if not re.fullmatch(r"\d{4}-W\d{2}", week):
        raise AirflowException("week must use YYYY-Www format")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", run_date):
        raise AirflowException("run_date must use YYYY-MM-DD format")
    if not re.fullmatch(r"v[1-9]\d*", curated_version):
        raise AirflowException("curated_version must use vN format")
    if end_page_value is not None and start_page > end_page_value:
        raise AirflowException("start_page must be less than or equal to end_page")
    if summary_mode not in {"rule", "off"}:
        raise AirflowException("summary_mode must be one of: rule, off")
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
        / f"careet_meme_card_candidates_{week}.json"
    )

    return {
        "source": SOURCE_NAME,
        "week": week,
        "run_id": run_id,
        "run_date": run_date,
        "stamp": stamp,
        "curated_version": curated_version,
        "emit_curated_meme_card_candidates": emit_curated,
        "start_page": start_page,
        "end_page": end_page_value,
        "delay": delay,
        "timeout": timeout,
        "retries": retries,
        "summary_mode": summary_mode,
        "fail_if_exists": fail_if_exists,
        "resume": resume,
        "list_only": list_only,
        "download_thumbnails": download_thumbnails,
        "log_level": log_level,
        "careet_dir": str(careet_dir),
        "run_dir": str(run_dir),
        "curated_root": str(curated_root),
        "article_csv": str(run_dir / f"careet_articles_{stamp}.csv"),
        "meme_csv": str(run_dir / f"careet_memes_{stamp}.csv"),
        "term_json": str(run_dir / f"careet_meme_terms_{stamp}.json"),
        "suspect_csv": str(run_dir / f"careet_meme_term_suspects_{stamp}.csv"),
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
        "careet_crawler.py",
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
        "--start-page",
        str(config["start_page"]),
        "--delay",
        str(config["delay"]),
        "--timeout",
        str(config["timeout"]),
        "--retries",
        str(config["retries"]),
        "--summary-mode",
        str(config["summary_mode"]),
        "--log-level",
        str(config["log_level"]),
    ]
    if config.get("end_page") is not None:
        command.extend(["--end-page", str(config["end_page"])])
    if config.get("fail_if_exists"):
        command.append("--fail-if-exists")
    if config.get("resume"):
        command.append("--resume")
    if config.get("list_only"):
        command.append("--list-only")
    if config.get("download_thumbnails"):
        command.append("--download-thumbnails")
    if config.get("emit_curated_meme_card_candidates"):
        command.append("--emit-curated-meme-card-candidates")
    return command


def _verify_careet_landing_artifacts(config: dict[str, Any]) -> dict[str, Any]:
    article_csv = Path(config["article_csv"])
    meme_csv = Path(config["meme_csv"])
    term_json = Path(config["term_json"])
    suspect_csv = Path(config["suspect_csv"])
    summary_json = Path(config["crawler_run_summary"])
    error_json = Path(config["error_json"])
    curated_candidates = (
        Path(config["curated_meme_card_candidates"])
        if config.get("emit_curated_meme_card_candidates")
        else None
    )

    expected_paths = [article_csv, meme_csv, term_json, suspect_csv, summary_json]
    if curated_candidates is not None:
        expected_paths.append(curated_candidates)
    missing = [str(path) for path in expected_paths if not path.is_file()]
    if missing:
        raise AirflowException(f"missing Careet landing artifacts: {missing}")
    if error_json.exists():
        raise AirflowException(f"Careet landing error artifact exists: {error_json}")

    summary = json.loads(summary_json.read_text(encoding="utf-8"))
    if summary.get("status") != "success":
        raise AirflowException(f"crawler_run_summary status is not success: {summary}")
    if summary.get("source") != SOURCE_NAME:
        raise AirflowException(f"crawler_run_summary source is not {SOURCE_NAME}")
    if summary.get("week") != config["week"] or summary.get("run_id") != config["run_id"]:
        raise AirflowException("crawler_run_summary week/run_id does not match config")

    with article_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        article_rows = sum(1 for _ in csv.DictReader(handle))
    with meme_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        meme_rows = sum(1 for _ in csv.DictReader(handle))
    with suspect_csv.open("r", encoding="utf-8-sig", newline="") as handle:
        suspect_rows = sum(1 for _ in csv.DictReader(handle))

    terms = json.loads(term_json.read_text(encoding="utf-8"))
    if not isinstance(terms, list):
        raise AirflowException(f"term JSON must be a list: {term_json}")
    if int(summary.get("article_count", -1)) != article_rows:
        raise AirflowException("article CSV row count does not match summary")
    if int(summary.get("meme_count", -1)) != meme_rows:
        raise AirflowException("meme CSV row count does not match summary")

    curated_check: dict[str, Any] | None = None
    if curated_candidates is not None:
        curated_payload = json.loads(curated_candidates.read_text(encoding="utf-8"))
        if curated_payload.get("stage") != "curated":
            raise AirflowException("curated candidate stage must be curated")
        if curated_payload.get("artifact_name") != "meme_card_candidates":
            raise AirflowException(
                "curated candidate artifact_name must be meme_card_candidates"
            )
        if curated_payload.get("source_family") != SOURCE_NAME:
            raise AirflowException("curated candidate source_family must be careet")
        if curated_payload.get("source_landing_run_id") != config["run_id"]:
            raise AirflowException(
                "curated candidate source_landing_run_id does not match"
            )
        if int(curated_payload.get("term_count", -1)) != len(
            curated_payload.get("terms", [])
        ):
            raise AirflowException("curated candidate term_count does not match terms")
        curated_check = {
            "path": str(curated_candidates),
            "term_count": curated_payload.get("term_count"),
            "review_status": curated_payload.get("review_status"),
        }

    return {
        **config,
        "artifact_check": {
            "status": "passed",
            "article_csv": str(article_csv),
            "meme_csv": str(meme_csv),
            "term_json": str(term_json),
            "suspect_csv": str(suspect_csv),
            "crawler_run_summary": str(summary_json),
            "article_count": article_rows,
            "meme_count": meme_rows,
            "term_count": len(terms),
            "suspect_row_count": suspect_rows,
            "curated_meme_card_candidates": curated_check,
        },
    }


@dag(
    dag_id=DAG_ID,
    start_date=datetime(2026, 7, 22, 19, 48, tzinfo=timezone.utc),
    schedule=CAREET_LANDING_SCHEDULE,
    catchup=False,
    max_active_runs=1,
    tags=["brandmate", "sns_trend", "landing", "careet"],
    default_args={"owner": "brandmate-data", "retries": 0},
    doc_md="""
    Collect Careet `sns_trend` landing and curated candidate artifacts.

    Manual trigger config:

    ```json
    {
      "week": "2026-W31",
      "run_date": "2026-07-27",
      "run_id": "manual__careet_phase4_smoke",
      "end_page": 1,
      "curated_version": "v3",
      "emit_curated_meme_card_candidates": true
    }
    ```
    """,
)
def sns_trend_careet_landing_collection() -> None:
    @task
    def resolve_careet_landing_context() -> dict[str, Any]:
        context = get_current_context()
        dag_run = context.get("dag_run")
        conf = dict(getattr(dag_run, "conf", None) or {})
        dag_run_id = str(getattr(dag_run, "run_id", "manual"))

        return _resolve_careet_landing_config(
            conf=conf,
            dag_run_id=dag_run_id,
            logical_date=context.get("logical_date"),
        )

    @task
    def collect_careet_landing(config: dict[str, Any]) -> dict[str, Any]:
        result = _run_command(
            _collector_command(config),
            cwd=Path(config["careet_dir"]),
            env=os.environ.copy(),
        )
        return {**config, "collector": result}

    @task
    def verify_careet_landing_contract(config: dict[str, Any]) -> dict[str, Any]:
        return _verify_careet_landing_artifacts(config)

    @task
    def upload_careet_landing_to_gcs(config: dict[str, Any]) -> dict[str, Any]:
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
                f"Failed to upload Careet landing artifacts to GCS: {error}"
            ) from error

    resolved_config = resolve_careet_landing_context()
    collected = collect_careet_landing(resolved_config)
    verified = verify_careet_landing_contract(collected)
    upload_careet_landing_to_gcs(verified)


sns_trend_careet_landing_collection()
