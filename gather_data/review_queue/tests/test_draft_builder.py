from __future__ import annotations

import json
from pathlib import Path
import pytest

from review_queue.contracts import ReviewDecisionRecord
from review_queue.decisions import save_review_decisions
from review_queue.draft_builder import (
    TrendCardDraftBuildError,
    build_trendcard_drafts,
    main,
)


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
                "requires_risk_review": False,
                "risk_review_notes": "",
            },
            {
                "candidate_id": "cand_careet_002",
                "term": "난리자베스",
                "display_term": "난리자베스",
                "source_families": ["careet"],
                "usage_policy": "candidate",
                "eligible_for_processed": True,
                "requires_risk_review": True,
                "risk_review_notes": "인물 패러디 확인 필요",
            },
            {
                "candidate_id": "cand_naver_003",
                "term": "천연위고비",
                "display_term": "천연 위고비",
                "source_families": ["naver"],
                "usage_policy": "reference_only",
                "eligible_for_processed": False,
                "requires_risk_review": False,
            },
        ],
    }


def test_build_trendcard_drafts_success(tmp_path: Path, sample_queue_payload: dict):
    queue_path = tmp_path / "sns_trend_review_queue.json"
    queue_path.write_text(json.dumps(sample_queue_payload, ensure_ascii=False), encoding="utf-8")

    decisions = [
        ReviewDecisionRecord(
            candidate_id="cand_youtube_001",
            review_decision="accept",
            reviewer="chaebin",
            reviewed_at="2026-07-28T01:10:00Z",
            review_note="주간 1위 밈",
        ),
        ReviewDecisionRecord(
            candidate_id="cand_careet_002",
            review_decision="reject",
            reviewer="chaebin",
            reviewed_at="2026-07-28T01:10:00Z",
        ),
    ]

    decisions_path = tmp_path / "sns_trend_review_decisions.json"
    save_review_decisions(decisions, decisions_path)

    output_dir = tmp_path / "drafts_out"
    result = build_trendcard_drafts(
        week="2026-W31",
        run_id="test_run_001",
        decisions_path=decisions_path,
        queue_path=queue_path,
        output_dir=output_dir,
    )

    assert result.draft_count == 1
    assert result.drafts_json_path.exists()
    assert result.drafts_csv_path.exists()

    with result.drafts_json_path.open("r", encoding="utf-8") as f:
        draft_payload = json.load(f)

    assert len(draft_payload["drafts"]) == 1
    draft_item = draft_payload["drafts"][0]
    assert draft_item["meme_id"] == "cand_youtube_001"
    assert draft_item["name"] == "난 널 버리지 않아"
    assert draft_item["meaning"] == "주간 1위 밈"
    assert draft_item["trend_meta"]["curation_meta"]["reviewer"] == "chaebin"


def test_naver_only_accept_filtered_out(tmp_path: Path, sample_queue_payload: dict):
    queue_path = tmp_path / "sns_trend_review_queue.json"
    queue_path.write_text(json.dumps(sample_queue_payload, ensure_ascii=False), encoding="utf-8")

    decisions = [
        ReviewDecisionRecord(
            candidate_id="cand_youtube_001",
            review_decision="accept",
            reviewer="chaebin",
            reviewed_at="2026-07-28T01:10:00Z",
        ),
        ReviewDecisionRecord(
            candidate_id="cand_naver_003",
            review_decision="accept",  # Naver-only candidate forced accept
            reviewer="chaebin",
            reviewed_at="2026-07-28T01:10:00Z",
        ),
    ]

    decisions_path = tmp_path / "sns_trend_review_decisions.json"
    save_review_decisions(decisions, decisions_path)

    output_dir = tmp_path / "drafts_out"
    result = build_trendcard_drafts(
        week="2026-W31",
        run_id="test_run_001",
        decisions_path=decisions_path,
        queue_path=queue_path,
        output_dir=output_dir,
    )

    # Naver-only accept must be skipped and filtered out
    assert result.draft_count == 1
    with result.summary_path.open("r", encoding="utf-8") as f:
        summary = json.load(f)
    assert summary["skipped_ineligible_count"] == 1


def test_zero_accepted_fails_draft_build(tmp_path: Path, sample_queue_payload: dict):
    queue_path = tmp_path / "sns_trend_review_queue.json"
    queue_path.write_text(json.dumps(sample_queue_payload, ensure_ascii=False), encoding="utf-8")

    decisions = [
        ReviewDecisionRecord(
            candidate_id="cand_youtube_001",
            review_decision="reject",
            reviewer="chaebin",
            reviewed_at="2026-07-28T01:10:00Z",
        )
    ]

    decisions_path = tmp_path / "sns_trend_review_decisions.json"
    save_review_decisions(decisions, decisions_path)

    output_dir = tmp_path / "drafts_out"
    with pytest.raises(TrendCardDraftBuildError, match="no 'accept' decisions found"):
        build_trendcard_drafts(
            week="2026-W31",
            run_id="test_run_001",
            decisions_path=decisions_path,
            queue_path=queue_path,
            output_dir=output_dir,
        )


def test_draft_builder_cli_main(tmp_path: Path, sample_queue_payload: dict):
    queue_dir = tmp_path / "review_queue" / "week=2026-W31" / "run_id=test_run_cli"
    queue_dir.mkdir(parents=True)
    queue_path = queue_dir / "sns_trend_review_queue.json"
    queue_path.write_text(json.dumps(sample_queue_payload, ensure_ascii=False), encoding="utf-8")

    decisions_dir = tmp_path / "review_decisions" / "week=2026-W31"
    decisions_dir.mkdir(parents=True)
    decisions_path = decisions_dir / "sns_trend_review_decisions.json"

    decisions = [
        ReviewDecisionRecord(
            candidate_id="cand_youtube_001",
            review_decision="accept",
            reviewer="chaebin",
            reviewed_at="2026-07-28T01:10:00Z",
        )
    ]
    save_review_decisions(decisions, decisions_path)

    output_dir = tmp_path / "drafts_cli_out"

    main(
        [
            "--week",
            "2026-W31",
            "--run-id",
            "test_run_cli",
            "--decisions-path",
            str(decisions_path),
            "--queue-path",
            str(queue_path),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert (output_dir / "sns_trend_trendcard_drafts.json").exists()
    assert (output_dir / "sns_trend_trendcard_drafts.csv").exists()
