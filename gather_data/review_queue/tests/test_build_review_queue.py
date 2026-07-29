from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path

from review_queue.build_review_queue import (
    ReviewQueueBuildError,
    build_review_queue,
    discover_candidate_paths,
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


def write_candidate(
    root: Path,
    source_family: str,
    payload: dict[str, object],
    *,
    week: str = "2026-W31",
) -> Path:
    path = root / source_family / f"{source_family}_meme_card_candidates_{week}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


class BuildReviewQueueTest(unittest.TestCase):
    def test_discover_candidate_paths_is_sorted_by_source_path(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "meme_card_candidates"
            careet = write_candidate(
                root,
                "careet",
                candidate_payload("careet", ["둠스데이"]),
            )
            youtube = write_candidate(
                root,
                "youtube",
                candidate_payload("youtube", ["둠스데이"]),
            )

            self.assertEqual(discover_candidate_paths(root, "2026-W31"), [careet, youtube])

    def test_build_review_queue_writes_json_csv_summary_and_config_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            input_root = base / "meme_card_candidates"
            output_root = base / "review_queue"
            paths = [
                write_candidate(
                    input_root,
                    "youtube",
                    candidate_payload(
                        "youtube",
                        ["마인크래프트", "Forgot Airpods trend"],
                        term_scores=[
                            {"keyword": "마인크래프트", "count": 50},
                            {"keyword": "Forgot Airpods trend", "count": 100},
                        ],
                    ),
                ),
                write_candidate(
                    input_root,
                    "careet",
                    candidate_payload("careet", ["Forgot Airpod"]),
                ),
                write_candidate(
                    input_root,
                    "naver",
                    candidate_payload(
                        "naver",
                        ["카페"],
                        term_scores=[{"keyword": "카페", "count": 1000}],
                    ),
                ),
            ]

            result = build_review_queue(
                week="2026-W31",
                run_id="manual__review_queue_test",
                candidate_paths=paths,
                output_root=output_root,
                alias_config_path=CONFIG_DIR / "aliases.json",
                generic_terms_config_path=CONFIG_DIR / "generic_terms.json",
                scoring_config_path=CONFIG_DIR / "scoring_v1.json",
            )

            self.assertTrue(result.queue_json_path.exists())
            self.assertTrue(result.queue_csv_path.exists())
            self.assertTrue(result.scoring_config_snapshot_path.exists())
            self.assertTrue(result.summary_path.exists())

            queue = json.loads(result.queue_json_path.read_text(encoding="utf-8"))
            self.assertEqual(queue["artifact_name"], "review_queue")
            self.assertEqual(queue["decision_artifact_policy"], "review_decisions are stored separately")
            self.assertEqual(queue["candidate_count"], 3)
            self.assertNotIn("review_decision", queue["candidates"][0])

            with result.queue_csv_path.open("r", encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(len(rows), queue["candidate_count"])
            self.assertEqual(rows[0]["rank"], "1")
            self.assertEqual(rows[0]["source_families"], "careet|youtube")
            self.assertEqual(rows[-1]["usage_policy"], "reference_only")
            self.assertEqual(rows[-1]["eligible_for_processed"], "false")

            summary = json.loads(result.summary_path.read_text(encoding="utf-8"))
            self.assertEqual(summary["candidate_count"], 3)
            self.assertEqual(summary["candidate_count_by_usage_policy"]["candidate"], 2)
            self.assertEqual(summary["candidate_count_by_usage_policy"]["reference_only"], 1)
            self.assertEqual(summary["artifacts"]["queue_json_sha256"], result.queue_json_sha256)

    def test_same_input_and_config_rebuilds_same_checksums_with_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            input_root = base / "meme_card_candidates"
            output_root = base / "review_queue"
            paths = [
                write_candidate(
                    input_root,
                    "youtube",
                    candidate_payload(
                        "youtube",
                        ["둠스데이", "마인크래프트"],
                        term_scores=[
                            {"keyword": "둠스데이", "count": 10},
                            {"keyword": "마인크래프트", "count": 100},
                        ],
                    ),
                ),
                write_candidate(
                    input_root,
                    "gogumafarm",
                    candidate_payload("gogumafarm", ["둠스데이"]),
                ),
            ]

            first = build_review_queue(
                week="2026-W31",
                run_id="manual__stable_review_queue_test",
                candidate_paths=paths,
                output_root=output_root,
                alias_config_path=CONFIG_DIR / "aliases.json",
                generic_terms_config_path=CONFIG_DIR / "generic_terms.json",
                scoring_config_path=CONFIG_DIR / "scoring_v1.json",
            )
            second = build_review_queue(
                week="2026-W31",
                run_id="manual__stable_review_queue_test",
                candidate_paths=paths,
                output_root=output_root,
                alias_config_path=CONFIG_DIR / "aliases.json",
                generic_terms_config_path=CONFIG_DIR / "generic_terms.json",
                scoring_config_path=CONFIG_DIR / "scoring_v1.json",
                overwrite=True,
            )

            self.assertEqual(first.queue_json_sha256, second.queue_json_sha256)
            self.assertEqual(first.queue_csv_sha256, second.queue_csv_sha256)

    def test_existing_output_dir_fails_without_overwrite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            input_root = base / "meme_card_candidates"
            output_root = base / "review_queue"
            paths = [
                write_candidate(
                    input_root,
                    "youtube",
                    candidate_payload("youtube", ["둠스데이"]),
                )
            ]
            kwargs = {
                "week": "2026-W31",
                "run_id": "manual__no_overwrite_test",
                "candidate_paths": paths,
                "output_root": output_root,
                "alias_config_path": CONFIG_DIR / "aliases.json",
                "generic_terms_config_path": CONFIG_DIR / "generic_terms.json",
                "scoring_config_path": CONFIG_DIR / "scoring_v1.json",
            }

            build_review_queue(**kwargs)

            with self.assertRaises(ReviewQueueBuildError):
                build_review_queue(**kwargs)


if __name__ == "__main__":
    unittest.main()
