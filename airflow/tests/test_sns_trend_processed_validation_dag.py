from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DAG_FILE = REPO_ROOT / "airflow" / "dags" / "sns_trend_processed_validation.py"


def test_sns_trend_processed_validation_dag_compiles() -> None:
    source = DAG_FILE.read_text(encoding="utf-8")

    compile(source, str(DAG_FILE), "exec")


def test_sns_trend_processed_validation_dagbag_imports_when_airflow_is_installed() -> None:
    pytest.importorskip(
        "airflow.models.dagbag",
        reason="apache-airflow is only installed in the Airflow Docker image",
    )
    from airflow.models.dagbag import DagBag

    dagbag = DagBag(dag_folder=str(DAG_FILE.parent), include_examples=False)

    assert not dagbag.import_errors
    dag = dagbag.get_dag("sns_trend_processed_validation")
    assert dag is not None
    assert dag.catchup is False
    assert {task.task_id for task in dag.tasks} == {
        "resolve_processed_package",
        "validate_package",
        "write_validation_summary",
    }
