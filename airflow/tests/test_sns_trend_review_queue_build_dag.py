from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any, Callable

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DAG_FILE = REPO_ROOT / "airflow" / "dags" / "sns_trend_review_queue_build.py"


def _load_dag_module_with_fake_airflow(monkeypatch: pytest.MonkeyPatch) -> Any:
    airflow_module = types.ModuleType("airflow")
    decorators_module = types.ModuleType("airflow.decorators")
    exceptions_module = types.ModuleType("airflow.exceptions")
    models_module = types.ModuleType("airflow.models")
    operators_module = types.ModuleType("airflow.operators")
    python_operator_module = types.ModuleType("airflow.operators.python")

    class FakeAirflowException(Exception):
        pass

    active_dag: list[FakeDAG] = []

    class FakeDAG:
        def __init__(self, dag_id: str, **kwargs: Any) -> None:
            self.dag_id = dag_id
            self.kwargs = kwargs
            self.task_dict: dict[str, FakePythonOperator] = {}

        def __enter__(self) -> FakeDAG:
            active_dag.append(self)
            return self

        def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
            if active_dag:
                active_dag.pop()

        def get_task(self, task_id: str) -> FakePythonOperator:
            return self.task_dict[task_id]

    class FakePythonOperator:
        def __init__(
            self,
            *,
            task_id: str,
            python_callable: Callable[..., Any],
            dag: FakeDAG | None = None,
            **kwargs: Any,
        ) -> None:
            self.task_id = task_id
            self.python_callable = python_callable
            self.dag = dag or (active_dag[-1] if active_dag else None)
            self.kwargs = kwargs
            self.upstream_list: list[FakePythonOperator] = []
            self.downstream_list: list[FakePythonOperator] = []

            if self.dag is not None:
                self.dag.task_dict[task_id] = self

        def __rshift__(self, other: FakePythonOperator) -> FakePythonOperator:
            if isinstance(other, FakePythonOperator):
                self.downstream_list.append(other)
                other.upstream_list.append(self)
            return other

    airflow_module.DAG = FakeDAG
    exceptions_module.AirflowException = FakeAirflowException
    python_operator_module.PythonOperator = FakePythonOperator

    monkeypatch.setitem(sys.modules, "airflow", airflow_module)
    monkeypatch.setitem(sys.modules, "airflow.decorators", decorators_module)
    monkeypatch.setitem(sys.modules, "airflow.exceptions", exceptions_module)
    monkeypatch.setitem(sys.modules, "airflow.models", models_module)
    monkeypatch.setitem(sys.modules, "airflow.operators", operators_module)
    monkeypatch.setitem(sys.modules, "airflow.operators.python", python_operator_module)

    gather_data_dir = REPO_ROOT / "gather_data"
    include_dir = REPO_ROOT / "airflow" / "include"
    if str(gather_data_dir) not in sys.path:
        sys.path.insert(0, str(gather_data_dir))
    if str(include_dir) not in sys.path:
        sys.path.insert(0, str(include_dir))

    spec = importlib.util.spec_from_file_location("sns_trend_review_queue_build_dag", DAG_FILE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_review_queue_build_dag_structure(monkeypatch: pytest.MonkeyPatch):
    module = _load_dag_module_with_fake_airflow(monkeypatch)
    dag = module.dag

    assert dag.dag_id == "sns_trend_review_queue_build"
    assert set(dag.task_dict.keys()) == {
        "resolve_review_context",
        "load_and_validate_source_candidates",
        "build_review_queue_artifact",
        "notify_review_required_discord",
    }

    t1 = dag.get_task("resolve_review_context")
    t2 = dag.get_task("load_and_validate_source_candidates")
    t3 = dag.get_task("build_review_queue_artifact")
    t4 = dag.get_task("notify_review_required_discord")

    assert t2 in t1.downstream_list
    assert t3 in t2.downstream_list
    assert t4 in t3.downstream_list


def test_resolve_review_context_task(monkeypatch: pytest.MonkeyPatch):
    module = _load_dag_module_with_fake_airflow(monkeypatch)

    class FakeDagRun:
        conf = {"week": "2026-W31", "run_id": "test_run_123"}

    context = {"dag_run": FakeDagRun()}
    res = module.resolve_review_context(**context)

    assert res["week"] == "2026-W31"
    assert res["run_id"] == "test_run_123"
