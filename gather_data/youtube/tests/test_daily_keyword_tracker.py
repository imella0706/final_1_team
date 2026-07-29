from __future__ import annotations

import csv
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from daily_keyword_tracker import main
from youtube_trends.collector import VideoRecord, write_video_csv


def _read_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), [dict(row) for row in reader]


def _write_raw_video_csv(path: Path) -> None:
    videos = [
        VideoRecord(
            video_id="video-1",
            title="T1 T1 메이플",
            channel_title="channel-a",
            category_id="20",
            published_at="2026-07-27T00:00:00Z",
            view_count=100,
            like_count=10,
            comment_count=1,
            tags=("T1", "호프"),
            url="https://www.youtube.com/watch?v=video-1",
        ),
        VideoRecord(
            video_id="video-2",
            title="호프 테스트",
            channel_title="channel-b",
            category_id="20",
            published_at="2026-07-27T01:00:00Z",
            view_count=200,
            like_count=20,
            comment_count=2,
            tags=("호프",),
            url="https://www.youtube.com/watch?v=video-2",
        ),
    ]
    write_video_csv(path, videos, region_code="KR", collected_at="2026-07-27T00:00:00Z")


class DailyKeywordTrackerOutputTest(unittest.TestCase):
    def test_writes_keyword_count_columns(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_csv = root / "youtube_trending_KR_20260727.csv"
            output_csv = root / "youtube_keywords_2026-07-27.csv"
            _write_raw_video_csv(input_csv)

            exit_code = main(
                [
                    "--input-csv",
                    str(input_csv),
                    "--date",
                    "2026-07-27",
                    "--output-file",
                    str(output_csv),
                    "--tokenizer",
                    "regex",
                ]
            )

            self.assertEqual(exit_code, 0)
            fields, rows = _read_rows(output_csv)
            self.assertEqual(fields, ["keyword", "count"])
            self.assertIn({"keyword": "T1", "count": "3"}, rows)
            self.assertIn({"keyword": "호프", "count": "3"}, rows)

    def test_writes_curated_meme_card_candidates_when_enabled(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_csv = root / "youtube_trending_KR_20260727.csv"
            output_csv = root / "youtube_keywords_2026-07-27.csv"
            curated_root = root / "curated" / "sns_trend"
            curated_json = (
                curated_root
                / "v3"
                / "meme_card_candidates"
                / "youtube"
                / "youtube_meme_card_candidates_2026-W31.json"
            )
            _write_raw_video_csv(input_csv)

            exit_code = main(
                [
                    "--input-csv",
                    str(input_csv),
                    "--date",
                    "2026-07-27",
                    "--output-file",
                    str(output_csv),
                    "--tokenizer",
                    "regex",
                    "--week",
                    "2026-W31",
                    "--run-id",
                    "manual__youtube_smoke",
                    "--emit-curated-meme-card-candidates",
                    "--curated-root",
                    str(curated_root),
                ]
            )

            self.assertEqual(exit_code, 0)
            payload = json.loads(curated_json.read_text(encoding="utf-8"))
            self.assertEqual(payload["dataset_name"], "sns_trend")
            self.assertEqual(payload["version"], "v3")
            self.assertEqual(payload["stage"], "curated")
            self.assertEqual(payload["artifact_name"], "meme_card_candidates")
            self.assertEqual(payload["source_family"], "youtube")
            self.assertEqual(payload["review_status"], "pending")
            self.assertFalse(payload["auto_promote_to_processed"])
            self.assertEqual(payload["collected_week"], "2026-W31")
            self.assertEqual(payload["source_landing_run_id"], "manual__youtube_smoke")
            self.assertEqual(payload["region"], "KR")
            self.assertEqual(payload["source_keyword_csv"], str(output_csv))
            self.assertEqual(payload["source_video_count"], 2)
            self.assertGreaterEqual(payload["term_count"], 2)
            self.assertIn("T1", payload["terms"])
            self.assertIn("호프", payload["terms"])
            self.assertIn({"keyword": "T1", "count": 3}, payload["term_scores"])

    def test_curated_meme_card_candidates_requires_week_and_run_id(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            input_csv = root / "youtube_trending_KR_20260727.csv"
            output_csv = root / "youtube_keywords_2026-07-27.csv"
            _write_raw_video_csv(input_csv)

            exit_code = main(
                [
                    "--input-csv",
                    str(input_csv),
                    "--date",
                    "2026-07-27",
                    "--output-file",
                    str(output_csv),
                    "--emit-curated-meme-card-candidates",
                ]
            )

            self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
