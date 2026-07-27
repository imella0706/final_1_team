"""Airflow DAG for building and validating official Processed v3 release package.

[Design Intent] Event-driven release pipeline triggered from Streamlit Review Dashboard.
Extracts accepted decisions, builds TrendCard drafts, converts them to official processed v3 release
package, and runs automated validation gate before notifying via Discord.
"""

from __future__ import annotations

import datetime
import json
import os
from pathlib import Path
import sys
from typing import Any

from airflow import DAG
from airflow.operators.python import PythonOperator


def _resolve_repo_root() -> Path:
    env_value = os.getenv("BRANDMATE_REPO_ROOT")
    if env_value and Path(env_value).exists():
        return Path(env_value)
    current = Path(__file__).resolve()
    for parent in current.parents:
        if (parent / "gather_data").exists():
            return parent
    return current.parents[2]


PROJECT_ROOT = _resolve_repo_root()
AIRFLOW_DIR = PROJECT_ROOT / "airflow"
GATHER_DATA_DIR = PROJECT_ROOT / "gather_data"
INCLUDE_DIR = Path(os.getenv("BRANDMATE_AIRFLOW_INCLUDE_DIR", AIRFLOW_DIR / "include"))

for p in (PROJECT_ROOT, GATHER_DATA_DIR, INCLUDE_DIR):
    if str(p) not in sys.path and p.exists():
        sys.path.insert(0, str(p))

from sns_trend.alerts import notify_airflow_failure  # noqa: E402
from sns_trend.validation import validate_processed_package  # noqa: E402
from review_queue.draft_builder import build_trendcard_drafts  # noqa: E402
from review_queue.release_candidate_builder import (  # noqa: E402
    DEFAULT_PROCESSED_V3_DIR,
    build_processed_release_candidate,
)

CURATED_ROOT = PROJECT_ROOT / "data" / "curated" / "sns_trend" / "v3"


def resolve_release_context(**context: Any) -> dict[str, Any]:
    dag_run = context.get("dag_run")
    logical_date = context.get("logical_date") or datetime.datetime.now(datetime.timezone.utc)

    conf = (getattr(dag_run, "conf", None) or {}) if dag_run else {}

    if "week" in conf and str(conf["week"]).strip():
        week = str(conf["week"]).strip()
    else:
        kst_tz = datetime.timezone(datetime.timedelta(hours=9))
        kst_dt = logical_date.astimezone(kst_tz)
        year, iso_week, _ = kst_dt.isocalendar()
        week = f"{year}-W{iso_week:02d}"

    if "run_id" in conf and str(conf["run_id"]).strip():
        run_id = str(conf["run_id"]).strip()
    else:
        dag_run_id = getattr(dag_run, "run_id", None) or "manual_release"
        sanitized_run_id = str(dag_run_id).replace(":", "-").replace("+", "_")
        run_id = f"airflow_release_{sanitized_run_id}"

    return {
        "week": week,
        "run_id": run_id,
        "logical_date_utc": logical_date.isoformat(),
    }


def build_drafts_if_needed_task(**context: Any) -> dict[str, Any]:
    ti = context["task_instance"]
    resolved_ctx = ti.xcom_pull(task_ids="resolve_release_context")
    week = resolved_ctx["week"]
    run_id = resolved_ctx["run_id"]

    drafts_dir = CURATED_ROOT / "trendcard_drafts" / f"week={week}" / f"run_id={run_id}"
    drafts_json = drafts_dir / "sns_trend_trendcard_drafts.json"

    decisions_json = CURATED_ROOT / "review_decisions" / f"week={week}" / "sns_trend_review_decisions.json"
    queue_json = CURATED_ROOT / "review_queue" / f"week={week}" / f"run_id={run_id}" / "sns_trend_review_queue.json"

    # Fallback to auto-discover latest available queue run_id for week if specified queue_json does not exist
    if not queue_json.exists():
        queue_week_dir = CURATED_ROOT / "review_queue" / f"week={week}"
        if queue_week_dir.exists():
            for run_dir in sorted(queue_week_dir.glob("run_id=*"), reverse=True):
                cand_queue = run_dir / "sns_trend_review_queue.json"
                if cand_queue.exists():
                    queue_json = cand_queue
                    run_id = run_dir.name.split("run_id=", 1)[-1]
                    drafts_dir = CURATED_ROOT / "trendcard_drafts" / f"week={week}" / f"run_id={run_id}"
                    drafts_json = drafts_dir / "sns_trend_trendcard_drafts.json"
                    break

    if not decisions_json.exists():
        raise ValueError(f"Review decisions not found: {decisions_json}")
    if not queue_json.exists():
        raise ValueError(f"Review queue not found: {queue_json}")

    # Rebuild trendcard drafts from latest decisions_json
    draft_result = build_trendcard_drafts(
        week=week,
        run_id=run_id,
        decisions_path=decisions_json,
        queue_path=queue_json,
        output_dir=drafts_dir,
        overwrite=True,
    )
    draft_count = draft_result.draft_count

    return {
        "week": week,
        "run_id": run_id,
        "draft_count": draft_count,
        "drafts_json_path": str(drafts_json),
        "queue_json_path": str(queue_json),
    }


def build_processed_release_candidate_task(**context: Any) -> dict[str, Any]:
    ti = context["task_instance"]
    resolved_ctx = ti.xcom_pull(task_ids="resolve_release_context")
    draft_ctx = ti.xcom_pull(task_ids="build_drafts_if_needed")

    week = resolved_ctx["week"]
    run_id = resolved_ctx["run_id"]

    drafts_path = Path(draft_ctx["drafts_json_path"])
    queue_path = Path(draft_ctx["queue_json_path"])

    result = build_processed_release_candidate(
        week=week,
        run_id=run_id,
        drafts_path=drafts_path,
        queue_path=queue_path,
        output_dir=DEFAULT_PROCESSED_V3_DIR,
        version="v3",
        overwrite=True,
    )

    return {
        "week": week,
        "run_id": run_id,
        "card_count": result.card_count,
        "processed_json_path": str(result.processed_json_path),
        "processed_csv_path": str(result.processed_csv_path),
        "summary_path": str(result.summary_path),
        "json_sha256": result.json_sha256,
        "csv_sha256": result.csv_sha256,
    }


def validate_processed_release_task(**context: Any) -> dict[str, Any]:
    ti = context["task_instance"]
    rel_ctx = ti.xcom_pull(task_ids="build_processed_release_candidate")

    card_count = rel_ctx["card_count"]
    processed_dir = DEFAULT_PROCESSED_V3_DIR

    val_summary = validate_processed_package(
        processed_dir=processed_dir,
        expected_card_count=card_count,
        expected_schema_version="2.0",
    )

    if val_summary.get("status") != "passed":
        raise ValueError(f"Processed release validation failed: {val_summary}")

    return {
        "status": "passed",
        "card_count": card_count,
        "validation_summary": val_summary,
    }


default_args = {
    "owner": "brandmate",
    "depends_on_past": False,
    "email_on_failure": False,
    "on_failure_callback": notify_airflow_failure,
}

with DAG(
    dag_id="sns_trend_processed_release",
    default_args=default_args,
    description="Event-driven release DAG for sns_trend processed v3 package",
    schedule=None,
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    tags=["sns_trend", "processed", "release", "v3"],
) as dag:
    t_context = PythonOperator(
        task_id="resolve_release_context",
        python_callable=resolve_release_context,
    )

    t_drafts = PythonOperator(
        task_id="build_drafts_if_needed",
        python_callable=build_drafts_if_needed_task,
    )

    t_release = PythonOperator(
        task_id="build_processed_release_candidate",
        python_callable=build_processed_release_candidate_task,
    )

    t_validate = PythonOperator(
        task_id="validate_processed_release",
        python_callable=validate_processed_release_task,
    )

    t_context >> t_drafts >> t_release >> t_validate
