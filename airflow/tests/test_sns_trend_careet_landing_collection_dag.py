from __future__ import annotations

import csv
import importlib.util
import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
DAG_FILE = REPO_ROOT / "airflow" / "dags" / "sns_trend_careet_landing_collection.py"


def _load_dag_module_with_fake_airflow(monkeypatch: pytest.MonkeyPatch) -> Any:
    airflow_module = types.ModuleType("airflow")
    decorators_module = types.ModuleType("airflow.decorators")
    exceptions_module = types.ModuleType("airflow.exceptions")
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

    decorators_module.dag = fake_dag
    decorators_module.task = lambda func: func
    exceptions_module.AirflowException = FakeAirflowException
    python_operator_module.get_current_context = lambda: {}

    monkeypatch.setitem(sys.modules, "airflow", airflow_module)
    monkeypatch.setitem(sys.modules, "airflow.decorators", decorators_module)
    monkeypatch.setitem(sys.modules, "airflow.exceptions", exceptions_module)
    monkeypatch.setitem(sys.modules, "airflow.operators", operators_module)
    monkeypatch.setitem(sys.modules, "airflow.operators.python", python_operator_module)

    module_name = "sns_trend_careet_landing_collection_under_test"
    spec = importlib.util.spec_from_file_location(module_name, DAG_FILE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def _write_careet_artifacts(
    *,
    run_dir: Path,
    week: str = "2026-W31",
    run_id: str = "manual__careet_smoke",
    stamp: str = "20260727",
) -> dict[str, str]:
    run_dir.mkdir(parents=True, exist_ok=True)

    article_csv = run_dir / f"careet_articles_{stamp}.csv"
    meme_csv = run_dir / f"careet_memes_{stamp}.csv"
    term_json = run_dir / f"careet_meme_terms_{stamp}.json"
    suspect_csv = run_dir / f"careet_meme_term_suspects_{stamp}.csv"
    summary_json = run_dir / "crawler_run_summary.json"

    with article_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["article_id", "title"])
        writer.writeheader()
        writer.writerow({"article_id": "123", "title": "샘플 밈"})
    with meme_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["meme_id", "term"])
        writer.writeheader()
        writer.writerow({"meme_id": "123_1", "term": "샘플 밈"})
    term_json.write_text(json.dumps(["샘플 밈"], ensure_ascii=False), encoding="utf-8")
    with suspect_csv.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["meme_id", "term", "reason"])
        writer.writeheader()

    summary_json.write_text(
        json.dumps(
            {
                "schema_version": "1.0",
                "source": "careet",
                "status": "success",
                "week": week,
                "run_id": run_id,
                "article_count": 1,
                "meme_count": 1,
                "outputs": {
                    "articles_csv": str(article_csv),
                    "memes_csv": str(meme_csv),
                    "meme_terms_json": str(term_json),
                    "meme_term_suspects_csv": str(suspect_csv),
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    return {
        "article_csv": str(article_csv),
        "meme_csv": str(meme_csv),
        "term_json": str(term_json),
        "suspect_csv": str(suspect_csv),
        "crawler_run_summary": str(summary_json),
        "error_json": str(run_dir / "error.json"),
    }


def test_sns_trend_careet_landing_collection_dag_compiles() -> None:
    source = DAG_FILE.read_text(encoding="utf-8")

    compile(source, str(DAG_FILE), "exec")


def test_dag_defaults_to_manual_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)

    assert module.sns_trend_careet_landing_collection.dag_kwargs["schedule"] is None
    assert module.sns_trend_careet_landing_collection.dag_kwargs["catchup"] is False
    assert module.sns_trend_careet_landing_collection.dag_kwargs["max_active_runs"] == 1


def test_resolve_careet_landing_config_uses_manual_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)

    config = module._resolve_careet_landing_config(
        conf={
            "week": "2026-W31",
            "run_date": "2026-07-27",
            "run_id": "manual__careet_smoke",
            "start_page": 1,
            "end_page": 2,
            "delay": 1.2,
            "timeout": 20,
            "retries": 2,
            "summary_mode": "off",
        },
        dag_run_id="manual__unused",
        logical_date=datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc),
        landing_root=tmp_path / "landing" / "sns_trend",
        careet_dir=tmp_path / "gather_data" / "crawling" / "careet",
    )

    assert config["week"] == "2026-W31"
    assert config["run_date"] == "2026-07-27"
    assert config["stamp"] == "20260727"
    assert config["run_id"] == "manual__careet_smoke"
    assert config["end_page"] == 2
    assert config["summary_mode"] == "off"
    assert config["article_csv"].endswith(
        "week=2026-W31/raw/careet/run_id=manual__careet_smoke/"
        "careet_articles_20260727.csv"
    )


def test_resolve_careet_landing_config_defaults_to_kst_iso_week(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)

    config = module._resolve_careet_landing_config(
        conf={},
        dag_run_id="manual__careet_latest",
        logical_date=datetime(2026, 7, 26, 15, 10, tzinfo=timezone.utc),
        landing_root=tmp_path,
        careet_dir=tmp_path / "careet",
    )

    assert config["week"] == "2026-W31"
    assert config["run_date"] == "2026-07-27"


def test_collector_command_emits_landing_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)
    config = {
        "week": "2026-W31",
        "run_id": "manual__careet_smoke",
        "run_date": "2026-07-27",
        "run_dir": str(tmp_path / "landing"),
        "start_page": 1,
        "end_page": 1,
        "delay": 1.0,
        "timeout": 15.0,
        "retries": 3,
        "summary_mode": "rule",
        "log_level": "INFO",
        "fail_if_exists": False,
        "resume": False,
        "list_only": False,
        "download_thumbnails": False,
    }

    command = module._collector_command(config)

    assert "careet_crawler.py" in command
    assert command[command.index("--output-dir") + 1] == str(tmp_path / "landing")
    assert command[command.index("--end-page") + 1] == "1"
    assert "--fail-if-exists" not in command
    assert "--resume" not in command


def test_verify_careet_landing_artifacts_accepts_expected_contract(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)
    paths = _write_careet_artifacts(run_dir=tmp_path / "landing-run")

    result = module._verify_careet_landing_artifacts(
        {
            "week": "2026-W31",
            "run_id": "manual__careet_smoke",
            **paths,
        }
    )

    assert result["artifact_check"]["status"] == "passed"
    assert result["artifact_check"]["article_count"] == 1
    assert result["artifact_check"]["meme_count"] == 1
    assert result["artifact_check"]["term_count"] == 1
    assert result["artifact_check"]["suspect_row_count"] == 0


def test_verify_careet_landing_artifacts_rejects_error_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)
    paths = _write_careet_artifacts(run_dir=tmp_path / "landing-run")
    Path(paths["error_json"]).write_text('{"status":"failed"}', encoding="utf-8")

    with pytest.raises(module.AirflowException, match="error artifact"):
        module._verify_careet_landing_artifacts(
            {
                "week": "2026-W31",
                "run_id": "manual__careet_smoke",
                **paths,
            }
        )


def test_sns_trend_careet_landing_collection_dagbag_imports_when_airflow_is_installed() -> None:
    pytest.importorskip(
        "airflow.models.dagbag",
        reason="apache-airflow is only installed in the Airflow Docker image",
    )
    from airflow.models.dagbag import DagBag

    dagbag = DagBag(dag_folder=str(DAG_FILE.parent), include_examples=False)

    assert not dagbag.import_errors
    dag = dagbag.get_dag("sns_trend_careet_landing_collection")
    assert dag is not None
    assert dag.catchup is False
    assert {task.task_id for task in dag.tasks} == {
        "resolve_careet_landing_context",
        "collect_careet_landing",
        "verify_careet_landing_contract",
    }
