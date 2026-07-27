from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from youtube_trending_collector import main
from youtube_trends.collector import CollectionError, VideoRecord
from youtube_trends.config import (
    ConfigurationError,
    landing_run_directory,
)


def _video() -> VideoRecord:
    return VideoRecord(
        video_id="video-1",
        title="test video",
        channel_title="test channel",
        category_id="22",
        published_at="2026-07-27T00:00:00Z",
        view_count=100,
        like_count=10,
        comment_count=1,
        tags=("trend",),
        url="https://www.youtube.com/watch?v=video-1",
    )


class YouTubeLandingContractTest(unittest.TestCase):
    def test_canonical_landing_directory_is_partitioned_by_week_and_run(self) -> None:
        with TemporaryDirectory() as temporary:
            path = landing_run_directory(
                week="2026-W31",
                run_id="manual__youtube_smoke",
                root=Path(temporary),
            )

            self.assertEqual(
                path,
                Path(temporary)
                / "week=2026-W31"
                / "raw"
                / "youtube"
                / "run_id=manual__youtube_smoke",
            )

    @patch(
        "youtube_trending_collector.fetch_trending_videos",
        return_value=[_video()],
    )
    @patch("youtube_trending_collector.build_youtube_service", return_value=object())
    @patch("youtube_trending_collector.require_api_key", return_value="secret-api-key")
    def test_legacy_mode_keeps_date_based_output(
        self,
        _require_api_key: object,
        _build_service: object,
        _fetch_videos: object,
    ) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            exit_code = main(
                [
                    "--output-dir",
                    str(output_dir),
                    "--date",
                    "2026-07-27",
                    "--limit",
                    "1",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(
                (output_dir / "youtube_trending_KR_20260727.csv").is_file()
            )
            self.assertFalse((output_dir / "run_summary.json").exists())

    @patch(
        "youtube_trending_collector.fetch_trending_videos",
        return_value=[_video()],
    )
    @patch("youtube_trending_collector.build_youtube_service", return_value=object())
    @patch("youtube_trending_collector.require_api_key", return_value="secret-api-key")
    def test_landing_success_writes_csv_and_summary(
        self,
        _require_api_key: object,
        _build_service: object,
        _fetch_videos: object,
    ) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            exit_code = main(
                [
                    "--week",
                    "2026-W31",
                    "--run-id",
                    "manual__youtube_smoke",
                    "--output-dir",
                    str(output_dir),
                    "--date",
                    "2026-07-27",
                    "--limit",
                    "1",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue(
                (output_dir / "youtube_trending_KR_2026-W31.csv").is_file()
            )
            summary = json.loads(
                (output_dir / "run_summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["week"], "2026-W31")
            self.assertEqual(summary["run_id"], "manual__youtube_smoke")
            self.assertEqual(summary["collected_count"], 1)
            self.assertNotIn("secret-api-key", json.dumps(summary))

    @patch(
        "youtube_trending_collector.fetch_trending_videos",
        return_value=[_video()],
    )
    @patch("youtube_trending_collector.build_youtube_service", return_value=object())
    @patch("youtube_trending_collector.require_api_key", return_value="secret-api-key")
    @patch("youtube_trending_collector.landing_run_directory")
    def test_landing_default_writes_csv_inside_canonical_run_directory(
        self,
        _landing_run_directory: object,
        _require_api_key: object,
        _build_service: object,
        _fetch_videos: object,
    ) -> None:
        with TemporaryDirectory() as temporary:
            run_directory = Path(temporary)
            _landing_run_directory.return_value = run_directory
            exit_code = main(
                [
                    "--week",
                    "2026-W31",
                    "--run-id",
                    "manual__youtube_smoke",
                    "--date",
                    "2026-07-27",
                    "--limit",
                    "1",
                ]
            )

            self.assertEqual(exit_code, 0)
            _landing_run_directory.assert_called_once_with(
                week="2026-W31",
                run_id="manual__youtube_smoke",
            )
            self.assertTrue(
                (run_directory / "youtube_trending_KR_2026-W31.csv").is_file()
            )
            self.assertTrue((run_directory / "run_summary.json").is_file())

    @patch(
        "youtube_trending_collector.fetch_trending_videos",
        side_effect=CollectionError("YouTube API request failed with HTTP 403"),
    )
    @patch("youtube_trending_collector.build_youtube_service", return_value=object())
    @patch("youtube_trending_collector.require_api_key", return_value="secret-api-key")
    def test_landing_failure_writes_error_artifact(
        self,
        _require_api_key: object,
        _build_service: object,
        _fetch_videos: object,
    ) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            exit_code = main(
                [
                    "--week",
                    "2026-W31",
                    "--run-id",
                    "manual__youtube_failure",
                    "--output-dir",
                    str(output_dir),
                    "--date",
                    "2026-07-27",
                ]
            )

            self.assertEqual(exit_code, 1)
            error = json.loads(
                (output_dir / "error.json").read_text(encoding="utf-8")
            )
            self.assertEqual(error["status"], "failed")
            self.assertEqual(error["exit_code"], 1)
            self.assertEqual(error["error_type"], "CollectionError")
            self.assertNotIn("secret-api-key", json.dumps(error))

    @patch(
        "youtube_trending_collector.require_api_key",
        side_effect=ConfigurationError("YOUTUBE_API_KEY is missing"),
    )
    def test_landing_configuration_failure_writes_error_artifact(
        self,
        _require_api_key: object,
    ) -> None:
        with TemporaryDirectory() as temporary:
            output_dir = Path(temporary)
            exit_code = main(
                [
                    "--week",
                    "2026-W31",
                    "--run-id",
                    "manual__missing_key",
                    "--output-dir",
                    str(output_dir),
                    "--date",
                    "2026-07-27",
                ]
            )

            self.assertEqual(exit_code, 2)
            error = json.loads(
                (output_dir / "error.json").read_text(encoding="utf-8")
            )
            self.assertEqual(error["status"], "failed")
            self.assertEqual(error["exit_code"], 2)
            self.assertEqual(error["error_type"], "ConfigurationError")

    def test_week_and_run_id_are_required_together(self) -> None:
        exit_code = main(["--week", "2026-W31"])

        self.assertEqual(exit_code, 2)

    def test_invalid_iso_week_is_rejected(self) -> None:
        with TemporaryDirectory() as temporary:
            exit_code = main(
                [
                    "--week",
                    "2026-W54",
                    "--run-id",
                    "manual__invalid_week",
                    "--output-dir",
                    temporary,
                ]
            )

            self.assertEqual(exit_code, 2)
