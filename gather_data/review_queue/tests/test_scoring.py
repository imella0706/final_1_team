from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from review_queue.contracts import CandidateRecord, records_from_candidate_payload
from review_queue.normalization import load_alias_index, load_generic_term_index
from review_queue.scoring import (
    ScoringConfigError,
    load_scoring_config,
    score_candidates,
)


CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


def candidate_payload(
    source_family: str,
    terms: list[str],
    *,
    display_terms: list[str] | None = None,
    collected_week: str = "2026-W31",
    term_scores: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "schema_version": "1.0",
        "dataset_name": "sns_trend",
        "version": "v3",
        "stage": "curated",
        "artifact_name": "meme_card_candidates",
        "source_family": source_family,
        "review_status": "pending",
        "collected_week": collected_week,
        "source_landing_run_id": f"manual__{source_family}_landing",
        "terms": terms,
        "display_terms": display_terms or terms,
    }
    if term_scores is not None:
        payload["term_scores"] = term_scores
    return payload


def records(*payloads: dict[str, object]) -> list[CandidateRecord]:
    candidate_records: list[CandidateRecord] = []
    for payload in payloads:
        candidate_records.extend(records_from_candidate_payload(payload))
    return candidate_records


class ReviewQueueScoringTest(unittest.TestCase):
    def setUp(self) -> None:
        self.aliases = load_alias_index(CONFIG_DIR / "aliases.json")
        self.generic_terms = load_generic_term_index(CONFIG_DIR / "generic_terms.json")
        self.config = load_scoring_config(CONFIG_DIR / "scoring_v1.json")

    def test_load_scoring_config_snapshot_is_stable(self) -> None:
        snapshot = self.config.to_dict()

        self.assertEqual(snapshot["scoring_config_version"], "scoring_v1")
        self.assertEqual(snapshot["frequency_score"], {"max_score": 20})
        self.assertEqual(snapshot["source_reliability_score"]["gogumafarm"], 5)

    def test_count_is_normalized_inside_source_not_summed_across_sources(self) -> None:
        scored = score_candidates(
            records(
                candidate_payload(
                    "youtube",
                    ["마인크래프트", "둠스데이"],
                    term_scores=[
                        {"keyword": "마인크래프트", "count": 100},
                        {"keyword": "둠스데이", "count": 10},
                    ],
                ),
                candidate_payload("careet", ["둠스데이"]),
            ),
            current_week="2026-W31",
            aliases=self.aliases,
            generic_terms=self.generic_terms,
            scoring_config=self.config,
        )
        by_term = {candidate.term: candidate for candidate in scored}

        self.assertEqual(
            by_term["마인크래프트"].score_breakdown["frequency_score"],
            20.0,
        )
        self.assertEqual(by_term["둠스데이"].score_breakdown["frequency_score"], 0.0)
        self.assertEqual(
            by_term["둠스데이"].score_breakdown["cross_platform_score"],
            15,
        )
        self.assertEqual(
            by_term["둠스데이"].total_score,
            by_term["마인크래프트"].total_score,
        )

    def test_aliases_merge_sources_before_cross_platform_score(self) -> None:
        scored = score_candidates(
            records(
                candidate_payload("youtube", ["Forgot Airpods trend"]),
                candidate_payload("careet", ["Forgot Airpod"]),
            ),
            current_week="2026-W31",
            aliases=self.aliases,
            generic_terms=self.generic_terms,
            scoring_config=self.config,
        )

        self.assertEqual(len(scored), 1)
        self.assertEqual(scored[0].term, "에어팟 스위치 밈".casefold())
        self.assertEqual(scored[0].source_families, ("careet", "youtube"))
        self.assertEqual(scored[0].score_breakdown["cross_platform_score"], 15)

    def test_naver_only_keeps_reference_policy_even_with_high_count(self) -> None:
        scored = score_candidates(
            records(
                candidate_payload(
                    "naver",
                    ["카페"],
                    term_scores=[{"keyword": "카페", "count": 1000}],
                )
            ),
            current_week="2026-W31",
            aliases=self.aliases,
            generic_terms=self.generic_terms,
            scoring_config=self.config,
        )

        self.assertEqual(scored[0].usage_policy, "reference_only")
        self.assertFalse(scored[0].eligible_for_processed)
        self.assertEqual(scored[0].score_breakdown["frequency_score"], 0.0)
        self.assertEqual(scored[0].score_breakdown["generic_term_penalty"], 10)

    def test_naver_can_attach_as_auxiliary_source_without_making_decision(self) -> None:
        scored = score_candidates(
            records(
                candidate_payload("gogumafarm", ["동결건조"]),
                candidate_payload(
                    "naver",
                    ["동결건조"],
                    term_scores=[{"keyword": "동결건조", "count": 30}],
                ),
            ),
            current_week="2026-W31",
            aliases=self.aliases,
            generic_terms=self.generic_terms,
            scoring_config=self.config,
        )

        self.assertTrue(scored[0].eligible_for_processed)
        self.assertEqual(scored[0].source_families, ("gogumafarm", "naver"))
        self.assertEqual(scored[0].score_breakdown["cross_platform_score"], 15)
        self.assertEqual(scored[0].score_breakdown["frequency_score"], 0.0)

    def test_recency_and_risk_penalty_are_visible_in_breakdown(self) -> None:
        scored = score_candidates(
            records(
                candidate_payload(
                    "youtube",
                    ["메이플"],
                    collected_week="2026-W30",
                    term_scores=[{"keyword": "메이플", "count": 1}],
                )
            ),
            current_week="2026-W31",
            aliases=self.aliases,
            generic_terms=self.generic_terms,
            scoring_config=self.config,
        )

        self.assertEqual(scored[0].score_breakdown["recency_score"], 5)
        self.assertEqual(scored[0].score_breakdown["risk_penalty"], 5)
        self.assertTrue(scored[0].requires_risk_review)

    def test_invalid_scoring_config_fails_fast(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "bad_scoring.json"
            path.write_text(
                json.dumps({"scoring_config_version": "bad"}, ensure_ascii=False),
                encoding="utf-8",
            )

            with self.assertRaises(ScoringConfigError):
                load_scoring_config(path)


if __name__ == "__main__":
    unittest.main()
