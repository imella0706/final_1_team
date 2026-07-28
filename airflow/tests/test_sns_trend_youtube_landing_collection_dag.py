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
DAG_FILE = REPO_ROOT / "airflow" / "dags" / "sns_trend_youtube_landing_collection.py"


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

    module_name = "sns_trend_youtube_landing_collection_under_test"
    spec = importlib.util.spec_from_file_location(module_name, DAG_FILE)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, module_name, module)
    spec.loader.exec_module(module)
    return module


def test_sns_trend_youtube_landing_collection_dag_compiles() -> None:
    source = DAG_FILE.read_text(encoding="utf-8")

    compile(source, str(DAG_FILE), "exec")


def test_dag_defaults_to_weekly_schedule(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)

    assert module.sns_trend_youtube_landing_collection.dag_kwargs["schedule"] == "0 4 * * 3"
    assert module.sns_trend_youtube_landing_collection.dag_kwargs["catchup"] is False
    assert module.sns_trend_youtube_landing_collection.dag_kwargs["max_active_runs"] == 1


def test_resolve_youtube_landing_config_uses_manual_values(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)

    config = module._resolve_youtube_landing_config(
        conf={
            "week": "2026-W31",
            "run_date": "2026-07-27",
            "run_id": "manual__youtube_smoke",
            "limit": 5,
        },
        dag_run_id="manual__unused",
        logical_date=datetime(2026, 7, 27, 0, 0, tzinfo=timezone.utc),
        landing_root=tmp_path / "landing" / "sns_trend",
        youtube_dir=tmp_path / "gather_data" / "youtube",
        curated_root=tmp_path / "curated" / "sns_trend",
    )

    assert config["week"] == "2026-W31"
    assert config["run_date"] == "2026-07-27"
    assert config["run_id"] == "manual__youtube_smoke"
    assert config["limit"] == 5
    assert config["raw_csv"].endswith(
        "week=2026-W31/raw/youtube/run_id=manual__youtube_smoke/"
        "youtube_trending_KR_2026-W31.csv"
    )
    assert config["keyword_csv"].endswith(
        "week=2026-W31/raw/youtube/run_id=manual__youtube_smoke/"
        "youtube_keywords_2026-07-27.csv"
    )
    assert config["emit_curated_meme_card_candidates"] is True
    assert config["curated_version"] == "v3"
    assert config["curated_candidates_json"].endswith(
        "curated/sns_trend/v3/meme_card_candidates/youtube/"
        "youtube_meme_card_candidates_2026-W31.json"
    )


def test_resolve_youtube_landing_config_defaults_to_kst_iso_week(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)

    config = module._resolve_youtube_landing_config(
        conf={},
        dag_run_id="manual__latest",
        logical_date=datetime(2026, 7, 26, 15, 10, tzinfo=timezone.utc),
        landing_root=tmp_path,
        youtube_dir=tmp_path / "youtube",
        curated_root=tmp_path / "curated",
    )

    assert config["week"] == "2026-W31"
    assert config["run_date"] == "2026-07-27"


def test_collector_command_keeps_landing_run_directory(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)
    config = {
        "week": "2026-W31",
        "run_id": "manual__youtube_smoke",
        "run_date": "2026-07-27",
        "region": "KR",
        "limit": 5,
        "run_dir": str(tmp_path),
        "fail_if_exists": False,
    }

    command = module._collector_command(config)

    assert "youtube_trending_collector.py" in command
    assert command[command.index("--output-dir") + 1] == str(tmp_path)
    assert "--fail-if-exists" not in command


def test_keyword_command_emits_curated_candidates_by_default(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)
    config = {
        "week": "2026-W31",
        "run_id": "manual__youtube_smoke",
        "run_date": "2026-07-27",
        "raw_csv": str(tmp_path / "youtube_trending_KR_2026-W31.csv"),
        "keyword_csv": str(tmp_path / "youtube_keywords_2026-07-27.csv"),
        "tokenizer": "regex",
        "fail_if_exists": False,
        "emit_curated_meme_card_candidates": True,
        "curated_version": "v3",
        "curated_root": str(tmp_path / "curated" / "sns_trend"),
    }

    command = module._keyword_command(config)

    assert "daily_keyword_tracker.py" in command
    assert "--emit-curated-meme-card-candidates" in command
    assert command[command.index("--week") + 1] == "2026-W31"
    assert command[command.index("--run-id") + 1] == "manual__youtube_smoke"
    assert command[command.index("--curated-version") + 1] == "v3"


def test_verify_youtube_landing_artifacts_accepts_keyword_count(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)
    raw_csv = tmp_path / "youtube_trending_KR_2026-W31.csv"
    keyword_csv = tmp_path / "youtube_keywords_2026-07-27.csv"
    summary_json = tmp_path / "crawler_run_summary.json"
    curated_json = tmp_path / "youtube_meme_card_candidates_2026-W31.json"
    raw_csv.write_text("video_id,title\nvideo-1,test\n", encoding="utf-8")
    with keyword_csv.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["keyword", "count"])
        writer.writeheader()
        writer.writerow({"keyword": "T1", "count": 3})
    summary_json.write_text(
        json.dumps({"status": "success", "collected_count": 1}),
        encoding="utf-8",
    )
    curated_json.write_text(
        json.dumps(
            {
                "stage": "curated",
                "artifact_name": "meme_card_candidates",
                "source_family": "youtube",
                "review_status": "pending",
                "collected_week": "2026-W31",
                "source_landing_run_id": "manual__youtube_smoke",
                "term_count": 1,
            }
        ),
        encoding="utf-8",
    )

    result = module._verify_youtube_landing_artifacts(
        {
            "week": "2026-W31",
            "run_id": "manual__youtube_smoke",
            "run_dir": str(tmp_path),
            "raw_csv": str(raw_csv),
            "keyword_csv": str(keyword_csv),
            "crawler_run_summary": str(summary_json),
            "emit_curated_meme_card_candidates": True,
            "curated_candidates_json": str(curated_json),
        }
    )

    assert result["artifact_check"] == {
        "status": "passed",
        "raw_csv": str(raw_csv),
        "keyword_csv": str(keyword_csv),
        "crawler_run_summary": str(summary_json),
        "collected_count": 1,
        "keyword_row_count": 1,
        "curated_candidates_json": str(curated_json),
        "curated_term_count": 1,
    }


def test_verify_youtube_landing_artifacts_rejects_wrong_keyword_schema(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    module = _load_dag_module_with_fake_airflow(monkeypatch)
    raw_csv = tmp_path / "youtube_trending_KR_2026-W31.csv"
    keyword_csv = tmp_path / "youtube_keywords_2026-07-27.csv"
    summary_json = tmp_path / "crawler_run_summary.json"
    raw_csv.write_text("video_id,title\nvideo-1,test\n", encoding="utf-8")
    keyword_csv.write_text("keyword,occurrence_count\nT1,3\n", encoding="utf-8")
    summary_json.write_text(
        json.dumps({"status": "success", "collected_count": 1}),
        encoding="utf-8",
    )

    with pytest.raises(module.AirflowException, match="keyword,count"):
        module._verify_youtube_landing_artifacts(
            {
                "run_dir": str(tmp_path),
                "raw_csv": str(raw_csv),
                "keyword_csv": str(keyword_csv),
                "crawler_run_summary": str(summary_json),
                "emit_curated_meme_card_candidates": False,
            }
        )


def test_sns_trend_youtube_landing_collection_dagbag_imports_when_airflow_is_installed() -> None:
    pytest.importorskip(
        "airflow.models.dagbag",
        reason="apache-airflow is only installed in the Airflow Docker image",
    )
    from airflow.models.dagbag import DagBag

    dagbag = DagBag(dag_folder=str(DAG_FILE.parent), include_examples=False)

    assert not dagbag.import_errors
    dag = dagbag.get_dag("sns_trend_youtube_landing_collection")
    assert dag is not None
    assert dag.catchup is False
    assert {task.task_id for task in dag.tasks} == {
        "resolve_youtube_landing_context",
        "collect_youtube_trending_raw",
        "build_youtube_keyword_snapshot",
        "verify_youtube_landing_contract",
    }
