from __future__ import annotations

import os
import sys
from datetime import timedelta

from airflow.decorators import dag, task
from airflow.operators.python import get_current_context
from pendulum import datetime


sys.path.append("/opt/airflow/include")

from brandmate_meme_validation import run_validation  # noqa: E402


MOCK_GCS_BASE_DIR = os.getenv("BRANDMATE_MOCK_GCS_BASE_DIR", "/opt/airflow/mock_gcs")


@dag(
    dag_id="brandmate_weekly_meme_csv_validation",
    start_date=datetime(2026, 7, 15, tz="Asia/Seoul"),
    schedule="0 7 * * 1",
    catchup=False,
    max_active_runs=1,
    default_args={
        "retries": 1,
        "retry_delay": timedelta(minutes=3),
        "execution_timeout": timedelta(minutes=10),
    },
    tags=["brandmate", "trend", "meme", "validation"],
)
def brandmate_weekly_meme_csv_validation():
    # [Design Intent] 초기 DAG는 GCS를 로컬 mock 경로로 대체해 Airflow 실행/검증 흐름부터 증명한다.
    @task
    def validate_mock_weekly_csv(week: str | None = None):
        context = get_current_context()
        dag_run = context.get("dag_run")
        conf_week = dag_run.conf.get("week") if dag_run and dag_run.conf else None
        return run_validation(base_dir=MOCK_GCS_BASE_DIR, week=week or conf_week)

    validate_mock_weekly_csv()


brandmate_weekly_meme_csv_validation()
