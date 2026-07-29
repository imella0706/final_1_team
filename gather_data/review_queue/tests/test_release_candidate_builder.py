from __future__ import annotations

import json
from pathlib import Path
import pytest

from sns_trend.validation import validate_processed_package

from review_queue.release_candidate_builder import (
    ProcessedReleaseBuildError,
    build_processed_release_candidate,
    main,
)


@pytest.fixture
def sample_drafts_payload() -> dict:
    return {
        "artifact_name": "trendcard_drafts",
        "week": "2026-W31",
        "run_id": "test_run_001",
        "draft_count": 1,
        "drafts": [
            {
                "meme_id": "cand_youtube_001",
                "name": "난 널 버리지 않아",
                "search_keywords": ["난 널 버리지 않아", "버리지않아"],
                "meaning": "주간 1위 밈",
                "text_patterns": ["{대표상품} 난 널 버리지 않아"],
                "copy_markers": ["난 널 버리지 않아"],
                "rights_risk": {
                    "has_risk": False,
                    "risk_type": "none",
                    "description": "사람 검수 완료",
                },
                "trend_meta": {
                    "collected_week": "2026-W31",
                    "status": "active",
                    "sources": ["youtube", "gogumafarm"],
                    "curation_meta": {
                        "status": "reviewed",
                        "reviewer": "chaebin",
                        "reviewed_at": "2026-07-28T01:10:00Z",
                    },
                },
            }
        ],
    }


@pytest.fixture
def sample_queue_payload() -> dict:
    return {
        "artifact_name": "review_queue",
        "week": "2026-W31",
        "run_id": "test_run_001",
        "candidates": [
            {
                "candidate_id": "cand_youtube_001",
                "term": "버리지않아",
                "display_term": "난 널 버리지 않아",
                "source_families": ["youtube", "gogumafarm"],
                "usage_policy": "candidate",
                "eligible_for_processed": True,
            }
        ],
    }


def test_build_processed_release_candidate_success(
    tmp_path: Path, sample_drafts_payload: dict, sample_queue_payload: dict
):
    drafts_path = tmp_path / "sns_trend_trendcard_drafts.json"
    queue_path = tmp_path / "sns_trend_review_queue.json"
    output_dir = tmp_path / "processed_v3_out"

    drafts_path.write_text(json.dumps(sample_drafts_payload, ensure_ascii=False), encoding="utf-8")
    queue_path.write_text(json.dumps(sample_queue_payload, ensure_ascii=False), encoding="utf-8")

    result = build_processed_release_candidate(
        week="2026-W31",
        run_id="test_run_001",
        drafts_path=drafts_path,
        queue_path=queue_path,
        output_dir=output_dir,
        version="v3",
    )

    assert result.card_count == 1
    assert result.processed_json_path.exists()
    assert result.processed_csv_path.exists()
    assert result.summary_path.exists()

    # Validate against sns_trend.validation package
    val_summary = validate_processed_package(
        processed_dir=output_dir,
        expected_card_count=1,
        expected_schema_version="2.0",
    )

    assert val_summary["status"] == "passed"
    assert val_summary["card_count"] == 1


def test_missing_drafts_fails(tmp_path: Path):
    with pytest.raises(ProcessedReleaseBuildError, match="Drafts payload not found"):
        build_processed_release_candidate(
            week="2026-W31",
            run_id="test_run_001",
            drafts_path=tmp_path / "non_existent_drafts.json",
            queue_path=tmp_path / "non_existent_queue.json",
            output_dir=tmp_path / "out",
        )


def test_cli_main_execution(
    tmp_path: Path, sample_drafts_payload: dict, sample_queue_payload: dict
):
    drafts_path = tmp_path / "sns_trend_trendcard_drafts.json"
    queue_path = tmp_path / "sns_trend_review_queue.json"
    output_dir = tmp_path / "processed_cli_out"

    drafts_path.write_text(json.dumps(sample_drafts_payload, ensure_ascii=False), encoding="utf-8")
    queue_path.write_text(json.dumps(sample_queue_payload, ensure_ascii=False), encoding="utf-8")

    main(
        [
            "--week",
            "2026-W31",
            "--run-id",
            "test_run_001",
            "--drafts-path",
            str(drafts_path),
            "--queue-path",
            str(queue_path),
            "--output-dir",
            str(output_dir),
            "--version",
            "v3",
        ]
    )

    assert (output_dir / "cross_platform_signal_top_candidates.json").exists()
    assert (output_dir / "cross_platform_signal_top_candidates.csv").exists()
