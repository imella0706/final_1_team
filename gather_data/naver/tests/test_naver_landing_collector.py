from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

import naver_landing_collector


class NaverLandingCollectorTest(unittest.TestCase):
    def test_landing_run_directory_uses_standard_partition(self) -> None:
        result = naver_landing_collector.landing_run_directory(
            week="2026-W31",
            run_id="manual__naver_landing_2026W31",
            root=Path("/repo/data/landing/sns_trend"),
        )

        self.assertEqual(
            result,
            Path(
                "/repo/data/landing/sns_trend/week=2026-W31/raw/naver/"
                "run_id=manual__naver_landing_2026W31"
            ),
        )

    def test_curated_candidate_path_uses_standard_dataset_location(self) -> None:
        result = naver_landing_collector.curated_meme_card_candidates_path(
            version="v3",
            week="2026-W31",
            root=Path("/repo/data/curated/sns_trend"),
        )

        self.assertEqual(
            result,
            Path(
                "/repo/data/curated/sns_trend/v3/meme_card_candidates/naver/"
                "naver_meme_card_candidates_2026-W31.json"
            ),
        )

    def test_build_word_frequency_rows_uses_keyword_count_columns(self) -> None:
        rows = naver_landing_collector.build_word_frequency_rows(
            {
                "blog": pd.DataFrame(
                    [
                        {"title": "둠스데이 챌린지", "description": "둠스데이 밈"},
                        {"title": "니가 좋아", "description": "좋아 밈"},
                    ]
                )
            },
            top_n=3,
        )

        self.assertLessEqual(len(rows), 3)
        self.assertEqual(set(rows[0]), {"keyword", "count"})

    @patch("naver_landing_collector.collect_search_dataframes")
    @patch("naver_landing_collector.collect_datalab_search_trend")
    def test_main_writes_landing_and_curated_artifacts(
        self,
        mock_datalab: object,
        mock_search: object,
    ) -> None:
        mock_search.return_value = {
            "blog": pd.DataFrame(
                [
                    {
                        "title": "둠스데이 챌린지",
                        "description": "요즘 뜨는 밈",
                        "link": "https://blog.example/1",
                    }
                ]
            ),
            "news": pd.DataFrame(
                [
                    {
                        "title": "니가 좋아",
                        "description": "콘텐츠 트렌드",
                        "link": "https://news.example/1",
                    }
                ]
            ),
        }
        mock_datalab.return_value = [{"period": "2026-07-20", "ratio": 100.0}]

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            run_dir = (
                root
                / "landing"
                / "sns_trend"
                / "week=2026-W31"
                / "raw"
                / "naver"
                / "run_id=manual__naver_smoke"
            )
            exit_code = naver_landing_collector.main(
                [
                    "--keyword",
                    "카페",
                    "--week",
                    "2026-W31",
                    "--run-id",
                    "manual__naver_smoke",
                    "--date",
                    "2026-07-27",
                    "--limit",
                    "5",
                    "--output-dir",
                    str(run_dir),
                    "--include-datalab",
                    "--emit-curated-meme-card-candidates",
                    "--curated-root",
                    str(root / "curated" / "sns_trend"),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((run_dir / "naver_blog_카페_20260727.csv").is_file())
            self.assertTrue((run_dir / "naver_news_카페_20260727.csv").is_file())
            self.assertTrue((run_dir / "datalab_카페_20260727.csv").is_file())
            word_freq_csv = run_dir / "naver_word_freq_20260727.csv"
            self.assertTrue(word_freq_csv.is_file())
            with word_freq_csv.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                self.assertEqual(reader.fieldnames, ["keyword", "count"])

            summary = json.loads(
                (run_dir / "crawler_run_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["source"], "naver")
            self.assertEqual(summary["week"], "2026-W31")
            self.assertEqual(summary["run_id"], "manual__naver_smoke")
            self.assertEqual(summary["article_count"], 2)
            self.assertIn("curated_meme_card_candidates", summary["outputs"])

            curated_path = (
                root
                / "curated"
                / "sns_trend"
                / "v3"
                / "meme_card_candidates"
                / "naver"
                / "naver_meme_card_candidates_2026-W31.json"
            )
            curated = json.loads(curated_path.read_text(encoding="utf-8"))
            self.assertEqual(curated["stage"], "curated")
            self.assertEqual(curated["artifact_name"], "meme_card_candidates")
            self.assertEqual(curated["source_family"], "naver")
            self.assertEqual(curated["review_status"], "pending")
            self.assertEqual(curated["usage_policy"], "reference_only")
            self.assertFalse(curated["auto_promote_to_processed"])
            self.assertEqual(
                curated["promotion_requirement"],
                "human_review_and_cross_platform_evidence",
            )
            self.assertEqual(curated["source_landing_run_id"], "manual__naver_smoke")

    def test_curated_candidates_require_landing_context(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            exit_code = naver_landing_collector.main(
                [
                    "--output-dir",
                    temporary,
                    "--emit-curated-meme-card-candidates",
                ]
            )

            self.assertEqual(exit_code, 1)
            self.assertTrue((Path(temporary) / "error.json").is_file())


if __name__ == "__main__":
    unittest.main()
