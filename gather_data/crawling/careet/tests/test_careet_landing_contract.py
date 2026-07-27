from __future__ import annotations

import csv
import tempfile
import unittest
from argparse import Namespace
from pathlib import Path

import careet_crawler


class CareetLandingContractTest(unittest.TestCase):
    def test_landing_run_directory_uses_standard_partition(self) -> None:
        result = careet_crawler.landing_run_directory(
            week="2026-W31",
            run_id="manual__careet_landing_2026W31",
            root=Path("/repo/data/landing/sns_trend"),
        )

        self.assertEqual(
            result,
            Path("/repo/data/landing/sns_trend/week=2026-W31/raw/careet/run_id=manual__careet_landing_2026W31"),
        )

    def test_landing_context_requires_week_and_run_id_together(self) -> None:
        with self.assertRaises(careet_crawler.CrawlerError):
            careet_crawler._landing_context(Namespace(week="2026-W31", run_id=None))

        with self.assertRaises(careet_crawler.CrawlerError):
            careet_crawler._landing_context(Namespace(week=None, run_id="manual__careet"))

    def test_emit_final_from_csv_writes_flat_landing_json(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            meme_csv = temporary_path / "careet_memes_20260727.csv"
            with meme_csv.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=careet_crawler.MEME_FIELDS)
                writer.writeheader()
                writer.writerow(
                    {
                        "meme_id": "careet_1",
                        "article_id": "1",
                        "meme_name": "좋좋소",
                        "parent_section": "요즘 뜨는 밈",
                        "position": "1",
                    }
                )

            exit_code = careet_crawler.main(
                [
                    "--emit-final-from-csv",
                    str(meme_csv),
                    "--output-dir",
                    str(temporary_path / "landing_run"),
                    "--week",
                    "2026-W31",
                    "--run-id",
                    "manual__careet_landing_2026W31",
                    "--date",
                    "2026-07-27",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((temporary_path / "landing_run" / "careet_meme_terms_20260727.json").exists())
            self.assertFalse((temporary_path / "landing_run" / "final_processed").exists())

    def test_fail_if_exists_rejects_existing_landing_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_path = Path(temporary)
            output_dir = temporary_path / "landing_run"
            output_dir.mkdir()
            (output_dir / "careet_articles_20260727.csv").write_text("already exists\n", encoding="utf-8")

            args = Namespace(
                delay=1.0,
                timeout=15.0,
                retries=3,
                output_dir=output_dir,
                run_date="2026-07-27",
                week="2026-W31",
                run_id="manual__careet_landing_2026W31",
                fail_if_exists=True,
                resume=False,
                summary_mode="off",
            )

            with self.assertRaises(careet_crawler.CrawlerError):
                careet_crawler.crawl(args, client=object())  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
