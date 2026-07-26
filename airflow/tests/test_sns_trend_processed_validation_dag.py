from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DAG_FILE = REPO_ROOT / "airflow" / "dags" / "sns_trend_processed_validation.py"


def _load_dag_module_with_fake_airflow(monkeypatch: pytest.MonkeyPatch) -> Any:
    airflow_module = types.ModuleType("airflow")
    decorators_module = types.ModuleType("airflow.decorators")
    exceptions_module = types.ModuleType("airflow.exceptions")
    models_module = types.ModuleType("airflow.models")
    operators_module = types.ModuleType("airflow.operators")
    python_operator_module = types.ModuleType("airflow.operators.python")

    def fake_dag(**dag_kwargs: Any) -> Any:
        def decorator(func: Any) -> Any:
            def wrapper(*args: Any, **kwargs: Any) -> None:
                return None

            wrapper.__wrapped__ = func
            wrapper.dag_kwargs = dag_kwargs
            return wrapper

        return decorator

    class FakeAirflowException(Exception):
        pass

    class FakeVariable:
        values: dict[str, str] = {}

        @classmethod
        def set(cls, key: str, value: str) -> None:
            cls.values[key] = value

    decorators_module.dag = fake_dag
    decorators_module.task = lambda func: func
    exceptions_module.AirflowException = FakeAirflowException
    models_module.Variable = FakeVariable
    python_operator_module.get_current_context = lambda: {}

    monkeypatch.setitem(sys.modules, "airflow", airflow_module)
    monkeypatch.setitem(sys.modules, "airflow.decorators", decorators_module)
    monkeypatch.setitem(sys.modules, "airflow.exceptions", exceptions_module)
    monkeypatch.setitem(sys.modules, "airflow.models", models_module)
    monkeypatch.setitem(sys.modules, "airflow.operators", operators_module)
    monkeypatch.setitem(sys.modules, "airflow.operators.python", python_operator_module)

    module_name = "sns_trend_processed_validation_under_test"
    spec = importlib.util.spec_from_file_location(module_name, DAG_FILE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def test_sns_trend_processed_validation_dag_compiles() -> None:
    source = DAG_FILE.read_text(encoding="utf-8")

    compile(source, str(DAG_FILE), "exec")


def test_resolve_processed_config_prefers_manual_source_gcs_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)

    def fail_discovery(**_: Any) -> dict[str, Any]:
        raise AssertionError("manual source_gcs_prefix must not discover latest version")

    monkeypatch.setattr(module, "discover_latest_gcs_processed_version", fail_discovery)

    config = module._resolve_processed_config(
        conf={
            "source_gcs_prefix": (
                "gs://ssakda/projects/brandmate/data/processed/sns_trend/"
                "v7/cross_platform_signal_top_candidates/"
            )
        },
        run_id="manual__test",
        processed_gcs_root="gs://ssakda/projects/brandmate/data/processed/sns_trend/",
    )

    assert config["source_type"] == "gcs"
    assert config["version"] == "v7"
    assert config["source_gcs_prefix"].endswith(
        "/v7/cross_platform_signal_top_candidates/"
    )
    assert "version=v7" in config["processed_dir"]


def test_resolve_processed_config_builds_gcs_prefix_from_manual_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)

    config = module._resolve_processed_config(
        conf={"version": "v4"},
        run_id="manual__test",
        processed_gcs_root="gs://ssakda/projects/brandmate/data/processed/sns_trend/",
    )

    assert config["source_type"] == "gcs"
    assert config["version"] == "v4"
    assert config["source_gcs_prefix"] == (
        "gs://ssakda/projects/brandmate/data/processed/sns_trend/"
        "v4/cross_platform_signal_top_candidates/"
    )


def test_resolve_processed_config_discovers_latest_gcs_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)

    def fake_discovery(**_: Any) -> dict[str, Any]:
        return {
            "status": "discovered",
            "version": "v10",
            "source_gcs_prefix": (
                "gs://ssakda/projects/brandmate/data/processed/sns_trend/"
                "v10/cross_platform_signal_top_candidates/"
            ),
        }

    monkeypatch.setattr(module, "discover_latest_gcs_processed_version", fake_discovery)

    config = module._resolve_processed_config(
        conf={},
        run_id="scheduled__test",
        processed_gcs_root="gs://ssakda/projects/brandmate/data/processed/sns_trend/",
    )

    assert config["source_type"] == "gcs"
    assert config["version"] == "v10"
    assert config["gcs_version_discovery"]["status"] == "discovered"
    assert "version=v10" in config["processed_dir"]


def test_resolve_processed_config_falls_back_to_local_v2(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)

    config = module._resolve_processed_config(
        conf={},
        run_id="manual__test",
        processed_gcs_root="",
    )

    assert config["source_type"] == "local"
    assert config["version"] == "v2"
    assert config["source_gcs_prefix"] is None
    assert config["processed_dir"].endswith(
        "data/processed/sns_trend/v2/cross_platform_signal_top_candidates"
    )


def test_build_validated_version_state_keeps_only_release_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)

    state = module._build_validated_version_state(
        summary={
            "dataset_name": "sns_trend",
            "artifact_name": "cross_platform_signal_top_candidates",
            "status": "passed",
            "card_count": 20,
            "csv": {"row_count": 20},
            "checksums": {"json": "json-sha", "csv": "csv-sha"},
            "cards": [{"meme_id": "must-not-store"}],
        },
        config={
            "version": "v3",
            "source_gcs_prefix": (
                "gs://ssakda/projects/brandmate/data/processed/sns_trend/"
                "v3/cross_platform_signal_top_candidates/"
            ),
        },
        write_result={
            "validation_summary_path": "/opt/airflow/mock_gcs/summary.json",
            "gcs_validation_summary_path": "gs://ssakda/projects/brandmate/logs/summary.json",
        },
        run_id="manual__test",
        validated_at_utc="2026-07-26T19:30:00Z",
    )

    assert state == {
        "dataset_name": "sns_trend",
        "artifact_name": "cross_platform_signal_top_candidates",
        "version": "v3",
        "source_gcs_prefix": (
            "gs://ssakda/projects/brandmate/data/processed/sns_trend/"
            "v3/cross_platform_signal_top_candidates/"
        ),
        "run_id": "manual__test",
        "validated_at_utc": "2026-07-26T19:30:00Z",
        "status": "passed",
        "card_count": 20,
        "csv_row_count": 20,
        "checksums": {"json": "json-sha", "csv": "csv-sha"},
        "validation_summary_path": "/opt/airflow/mock_gcs/summary.json",
        "gcs_validation_summary_path": "gs://ssakda/projects/brandmate/logs/summary.json",
    }
    assert "cards" not in state


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
        "sync_processed_package_from_gcs",
        "validate_package",
        "write_validation_summary",
        "record_validated_version",
    }
