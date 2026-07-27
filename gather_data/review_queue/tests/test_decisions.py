from __future__ import annotations

import json
from pathlib import Path
import pytest

from review_queue.contracts import (
    DecisionValidationError,
    ReviewDecisionError,
    ReviewDecisionRecord,
)
from review_queue.decisions import (
    load_review_decisions,
    save_review_decisions,
    validate_decisions_json_csv_consistency,
    validate_review_decisions,
)


@pytest.fixture
def sample_queue_candidates() -> list[dict]:
    return [
        {
            "candidate_id": "cand_youtube_001",
            "term": "버리지않아",
            "display_term": "난 널 버리지 않아",
            "source_family": "youtube",
            "usage_policy": "candidate",
            "eligible_for_processed": True,
        },
        {
            "candidate_id": "cand_careet_002",
            "term": "난리자베스",
            "display_term": "난리자베스",
            "source_family": "careet",
            "usage_policy": "candidate",
            "eligible_for_processed": True,
        },
        {
            "candidate_id": "cand_naver_003",
            "term": "천연위고비",
            "display_term": "천연 위고비",
            "source_family": "naver",
            "usage_policy": "reference_only",
            "eligible_for_processed": False,
        },
    ]


def test_valid_review_decision_record():
    record = ReviewDecisionRecord(
        candidate_id="cand_youtube_001",
        review_decision="accept",
        reviewer="chaebin",
        reviewed_at="2026-07-28T01:00:00Z",
        review_note="좋은 밈 카드",
    )
    assert record.candidate_id == "cand_youtube_001"
    assert record.review_decision == "accept"

    data = record.to_dict()
    restored = ReviewDecisionRecord.from_dict(data)
    assert restored == record


def test_invalid_decision_enum():
    with pytest.raises(ReviewDecisionError, match="review_decision must be one of"):
        ReviewDecisionRecord(
            candidate_id="cand_001",
            review_decision="approved",
            reviewer="tester",
            reviewed_at="2026-07-28T01:00:00Z",
        )


def test_invalid_reviewer_or_timestamp():
    with pytest.raises(ReviewDecisionError, match="reviewer must be a non-empty string"):
        ReviewDecisionRecord(
            candidate_id="cand_001",
            review_decision="accept",
            reviewer="",
            reviewed_at="2026-07-28T01:00:00Z",
        )


def test_validate_review_decisions_success(sample_queue_candidates):
    decisions = [
        ReviewDecisionRecord(
            candidate_id="cand_youtube_001",
            review_decision="accept",
            reviewer="reviewer_1",
            reviewed_at="2026-07-28T01:00:00Z",
        ),
        ReviewDecisionRecord(
            candidate_id="cand_careet_002",
            review_decision="reject",
            reviewer="reviewer_1",
            reviewed_at="2026-07-28T01:00:00Z",
        ),
        ReviewDecisionRecord(
            candidate_id="cand_naver_003",
            review_decision="hold",
            reviewer="reviewer_1",
            reviewed_at="2026-07-28T01:00:00Z",
        ),
    ]

    summary = validate_review_decisions(decisions, sample_queue_candidates)
    assert summary["total_decisions"] == 3
    assert summary["accepted_count"] == 1
    assert summary["rejected_count"] == 1
    assert summary["held_count"] == 1
    assert summary["accepted_candidate_ids"] == ["cand_youtube_001"]


def test_validate_review_decisions_unknown_candidate(sample_queue_candidates):
    decisions = [
        ReviewDecisionRecord(
            candidate_id="cand_unknown_999",
            review_decision="accept",
            reviewer="reviewer_1",
            reviewed_at="2026-07-28T01:00:00Z",
        )
    ]
    with pytest.raises(DecisionValidationError, match="does not exist in the review queue"):
        validate_review_decisions(decisions, sample_queue_candidates)


def test_validate_review_decisions_duplicate_decision(sample_queue_candidates):
    decisions = [
        ReviewDecisionRecord(
            candidate_id="cand_youtube_001",
            review_decision="accept",
            reviewer="reviewer_1",
            reviewed_at="2026-07-28T01:00:00Z",
        ),
        ReviewDecisionRecord(
            candidate_id="cand_youtube_001",
            review_decision="reject",
            reviewer="reviewer_1",
            reviewed_at="2026-07-28T01:05:00Z",
        ),
    ]
    with pytest.raises(DecisionValidationError, match="duplicate decision for candidate_id"):
        validate_review_decisions(decisions, sample_queue_candidates)


def test_validate_review_decisions_naver_only_accept_rejected(sample_queue_candidates):
    decisions = [
        ReviewDecisionRecord(
            candidate_id="cand_naver_003",
            review_decision="accept",
            reviewer="reviewer_1",
            reviewed_at="2026-07-28T01:00:00Z",
        )
    ]
    with pytest.raises(DecisionValidationError, match="reference-only/ineligible for processed"):
        validate_review_decisions(decisions, sample_queue_candidates)


def test_save_load_and_json_csv_consistency(tmp_path: Path, sample_queue_candidates):
    decisions = [
        ReviewDecisionRecord(
            candidate_id="cand_youtube_001",
            review_decision="accept",
            reviewer="reviewer_1",
            reviewed_at="2026-07-28T01:00:00Z",
            review_note="Good candidate",
        ),
        ReviewDecisionRecord(
            candidate_id="cand_careet_002",
            review_decision="hold",
            reviewer="reviewer_2",
            reviewed_at="2026-07-28T01:02:00Z",
        ),
    ]

    json_path = tmp_path / "review_decisions.json"
    csv_path = tmp_path / "review_decisions.csv"

    save_review_decisions(decisions, json_path, csv_path)

    assert json_path.exists()
    assert csv_path.exists()

    loaded = load_review_decisions(json_path)
    assert len(loaded) == 2
    assert loaded[0].candidate_id == "cand_youtube_001"

    is_consistent = validate_decisions_json_csv_consistency(json_path, csv_path)
    assert is_consistent is True


def test_queue_immutability_and_decision_isolation(tmp_path: Path, sample_queue_candidates):
    queue_path = tmp_path / "sns_trend_review_queue.json"
    with queue_path.open("w", encoding="utf-8") as f:
        json.dump({"candidates": sample_queue_candidates}, f)

    decision_dir = tmp_path / "review_decisions"
    decisions = [
        ReviewDecisionRecord(
            candidate_id="cand_youtube_001",
            review_decision="accept",
            reviewer="reviewer_1",
            reviewed_at="2026-07-28T01:00:00Z",
        )
    ]
    save_review_decisions(decisions, decision_dir / "review_decisions.json", decision_dir / "review_decisions.csv")

    with queue_path.open("w", encoding="utf-8") as f:
        json.dump({"candidates": sample_queue_candidates, "rebuilt_at": "2026-07-28T02:00:00Z"}, f)

    loaded_decisions = load_review_decisions(decision_dir / "review_decisions.json")
    assert len(loaded_decisions) == 1
    assert loaded_decisions[0].candidate_id == "cand_youtube_001"
