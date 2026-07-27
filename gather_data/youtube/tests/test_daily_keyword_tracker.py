from __future__ import annotations

import csv
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


if __name__ == "__main__":
    unittest.main()
