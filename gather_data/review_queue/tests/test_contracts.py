from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from review_queue.contracts import (
    CandidateContractError,
    load_candidate_records,
    make_candidate_id,
    records_from_candidate_payload,
)


def base_payload(source_family: str) -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "dataset_name": "sns_trend",
        "version": "v3",
        "stage": "curated",
        "artifact_name": "meme_card_candidates",
        "source_family": source_family,
        "review_status": "pending",
        "collected_week": "2026-W31",
        "source_landing_run_id": f"manual__{source_family}_landing",
        "terms": ["니가 좋아", "동결건조"],
        "display_terms": ["니가 좋아💖", "🧊 동결건조"],
    }


class ReviewQueueContractTest(unittest.TestCase):
    def test_youtube_term_scores_become_occurrence_count(self) -> None:
        payload = base_payload("youtube")
        payload["term_scores"] = [
            {"keyword": "니가 좋아", "count": 7},
            {"keyword": "동결건조", "count": 3},
        ]

        records = records_from_candidate_payload(payload)

        self.assertEqual(len(records), 2)
        self.assertEqual(records[0].source_family, "youtube")
        self.assertEqual(records[0].term, "니가 좋아")
        self.assertEqual(records[0].display_term, "니가 좋아💖")
        self.assertEqual(records[0].occurrence_count, 7)
        self.assertEqual(records[0].usage_policy, "candidate")
        self.assertTrue(records[0].eligible_for_processed)
        self.assertTrue(records[0].requires_evidence)

    def test_gogumafarm_keeps_display_term_without_frequency(self) -> None:
        payload = base_payload("gogumafarm")

        records = records_from_candidate_payload(payload)

        self.assertEqual(records[0].display_term, "니가 좋아💖")
        self.assertIsNone(records[0].occurrence_count)
        self.assertTrue(records[0].eligible_for_processed)

    def test_careet_records_share_candidate_id_for_same_normalized_term(self) -> None:
        youtube = base_payload("youtube")
        careet = base_payload("careet")
        youtube["terms"] = ["  니가   좋아  "]
        youtube["display_terms"] = ["니가 좋아"]
        careet["terms"] = ["니가 좋아"]
        careet["display_terms"] = ["니가 좋아"]

        youtube_record = records_from_candidate_payload(youtube)[0]
        careet_record = records_from_candidate_payload(careet)[0]

        self.assertEqual(youtube_record.candidate_id, careet_record.candidate_id)
        self.assertEqual(youtube_record.candidate_id, make_candidate_id("니가 좋아"))

    def test_naver_is_always_reference_only_and_not_processed_eligible(self) -> None:
        payload = base_payload("naver")
        payload["usage_policy"] = "candidate"
        payload["term_scores"] = [{"keyword": "카페", "count": 6}]
        payload["terms"] = ["카페"]
        payload["display_terms"] = ["카페"]

        record = records_from_candidate_payload(payload)[0]

        self.assertEqual(record.usage_policy, "reference_only")
        self.assertFalse(record.eligible_for_processed)
        self.assertEqual(record.occurrence_count, 6)

    def test_load_candidate_records_keeps_source_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "youtube_candidates.json"
            path.write_text(
                json.dumps(base_payload("youtube"), ensure_ascii=False),
                encoding="utf-8",
            )

            records = load_candidate_records([path])

            self.assertEqual(records[0].source_path, str(path))

    def test_missing_terms_fail_contract(self) -> None:
        payload = base_payload("youtube")
        payload.pop("terms")

        with self.assertRaises(CandidateContractError):
            records_from_candidate_payload(payload)

    def test_invalid_source_family_fails_contract(self) -> None:
        payload = base_payload("instagram")

        with self.assertRaises(CandidateContractError):
            records_from_candidate_payload(payload)


if __name__ == "__main__":
    unittest.main()
