from __future__ import annotations

import datetime
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

from sns_trend.alerts import (  # noqa: E402
    notify_airflow_failure,
    notify_review_required_discord,
)
from review_queue.build_review_queue import (  # noqa: E402
    DEFAULT_CONFIG_DIR,
    build_review_queue,
    discover_candidate_paths,
)

CURATED_ROOT = PROJECT_ROOT / "data" / "curated" / "sns_trend" / "v3"
CANDIDATES_ROOT = CURATED_ROOT / "meme_card_candidates"
QUEUE_ROOT = CURATED_ROOT / "review_queue"
REQUIRED_SOURCES = ("youtube", "gogumafarm", "careet")


def resolve_review_context(**context: Any) -> dict[str, Any]:
    dag_run = context.get("dag_run")
    logical_date = context.get("logical_date") or datetime.datetime.now(datetime.timezone.utc)

    conf = (getattr(dag_run, "conf", None) or {}) if dag_run else {}

    # Calculate ISO week in Asia/Seoul timezone
    if "week" in conf and str(conf["week"]).strip():
        week = str(conf["week"]).strip()
    else:
        # Convert to Asia/Seoul
        kst_tz = datetime.timezone(datetime.timedelta(hours=9))
        kst_dt = logical_date.astimezone(kst_tz)
        year, iso_week, _ = kst_dt.isocalendar()
        week = f"{year}-W{iso_week:02d}"

    if "run_id" in conf and str(conf["run_id"]).strip():
        run_id = str(conf["run_id"]).strip()
    else:
        dag_run_id = getattr(dag_run, "run_id", None) or "manual_run"
        sanitized_run_id = str(dag_run_id).replace(":", "-").replace("+", "_")
        run_id = f"airflow_queue_{sanitized_run_id}"

    return {
        "week": week,
        "run_id": run_id,
        "logical_date_utc": logical_date.isoformat(),
    }


def load_and_validate_source_candidates(**context: Any) -> dict[str, Any]:
    ti = context["task_instance"]
    resolved_ctx = ti.xcom_pull(task_ids="resolve_review_context")
    week = resolved_ctx["week"]

    candidate_paths = discover_candidate_paths(CANDIDATES_ROOT, week)

    # Check required sources
    found_sources = set()
    for path in candidate_paths:
        for src in REQUIRED_SOURCES:
            if f"/{src}/" in str(path):
                found_sources.add(src)

    missing = [src for src in REQUIRED_SOURCES if src not in found_sources]
    if missing:
        raise ValueError(
            f"Missing required source candidate files for week {week}: {missing}. "
            f"Expected under {CANDIDATES_ROOT}"
        )

    return {
        "week": week,
        "found_candidate_count": len(candidate_paths),
        "candidate_paths": [str(p) for p in candidate_paths],
    }


def build_review_queue_artifact_task(**context: Any) -> dict[str, Any]:
    ti = context["task_instance"]
    resolved_ctx = ti.xcom_pull(task_ids="resolve_review_context")
    week = resolved_ctx["week"]
    run_id = resolved_ctx["run_id"]

    candidate_paths = discover_candidate_paths(CANDIDATES_ROOT, week)

    result = build_review_queue(
        week=week,
        run_id=run_id,
        candidate_paths=candidate_paths,
        output_root=QUEUE_ROOT,
        alias_config_path=DEFAULT_CONFIG_DIR / "aliases.json",
        generic_terms_config_path=DEFAULT_CONFIG_DIR / "generic_terms.json",
        scoring_config_path=DEFAULT_CONFIG_DIR / "scoring_v1.json",
        overwrite=True,
    )

    output_dir = result.output_dir

    # Read top candidate for notification
    top_candidate = None
    queue_json = result.queue_json_path
    if queue_json.exists():
        try:
            import json

            with queue_json.open("r", encoding="utf-8") as f:
                data = json.load(f)
                candidates = data.get("candidates", [])
                if candidates:
                    top_candidate = candidates[0]
        except Exception:
            pass

    return {
        "output_dir": str(output_dir),
        "summary": {
            "candidate_count": result.candidate_count,
            "queue_json_sha256": result.queue_json_sha256,
            "queue_csv_sha256": result.queue_csv_sha256,
        },
        "top_candidate": top_candidate,
    }


def notify_review_required_discord_task(**context: Any) -> dict[str, Any]:
    ti = context["task_instance"]
    resolved_ctx = ti.xcom_pull(task_ids="resolve_review_context")
    build_res = ti.xcom_pull(task_ids="build_review_queue_artifact")

    week = resolved_ctx["week"]
    run_id = resolved_ctx["run_id"]
    summary = build_res["summary"]
    top_candidate = build_res.get("top_candidate")

    res = notify_review_required_discord(
        week=week,
        run_id=run_id,
        summary=summary,
        top_candidate=top_candidate,
    )
    return res


default_args = {
    "owner": "brandmate",
    "depends_on_past": False,
    "retries": 1,
    "retry_delay": datetime.timedelta(seconds=30),
    "on_failure_callback": notify_airflow_failure,
}

with DAG(
    dag_id="sns_trend_review_queue_build",
    default_args=default_args,
    description="Build cross-platform review queue artifact from source meme card candidates & notify review required",
    schedule_interval=None,
    start_date=datetime.datetime(2026, 1, 1),
    catchup=False,
    tags=["sns_trend", "curated", "review_queue", "phase5"],
) as dag:

    t1 = PythonOperator(
        task_id="resolve_review_context",
        python_callable=resolve_review_context,
    )

    t2 = PythonOperator(
        task_id="load_and_validate_source_candidates",
        python_callable=load_and_validate_source_candidates,
    )

    t3 = PythonOperator(
        task_id="build_review_queue_artifact",
        python_callable=build_review_queue_artifact_task,
    )

    t4 = PythonOperator(
        task_id="notify_review_required_discord",
        python_callable=notify_review_required_discord_task,
    )

    t1 >> t2 >> t3 >> t4
