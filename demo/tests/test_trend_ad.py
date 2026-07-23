from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from demo.trend_ad.models import TrendCard
from demo.trend_ad.pipeline import (
    build_storyboard,
    load_trend_cards,
    search_trends,
    write_html_report,
    write_text_artifacts,
)
from demo.trend_ad.render import render_animatic


ROOT = Path(__file__).resolve().parents[2]


class TrendPipelineTests(unittest.TestCase):
    def test_repository_snapshots_load_as_cards(self) -> None:
        cards = load_trend_cards(ROOT)
        sources = {card.source for card in cards}

        self.assertGreater(len(cards), 140)
        self.assertTrue({"careet", "gogumafarm", "youtube", "naver"} <= sources)
        self.assertNotIn("expired", {card.metadata.get("trend_status") for card in cards})

    def test_exact_meme_phrase_beats_unrelated_signal(self) -> None:
        cards = [
            TrendCard(card_id="popular", title="아주 인기 있는 다른 주제", source="youtube", signal=1.0),
            TrendCard(card_id="target", title="니가 좋아💖", source="gogumafarm", signal=0.1),
        ]

        results = search_trends(cards, "니가 좋아 밈으로 카페 광고 제작", limit=2)

        self.assertEqual(results[0].card.card_id, "target")
        self.assertIn("니가", results[0].matched_terms)

    def test_storyboard_and_report_contain_selected_evidence(self) -> None:
        card = TrendCard(
            card_id="gogumafarm:1",
            title="니가 좋아",
            source="gogumafarm",
            source_url="https://example.com/meme",
            context="SNS 밈 바이럴",
        )
        result = search_trends([card], "니가 좋아 카페 광고", limit=1)[0]
        storyboard = build_storyboard(
            brief="카페 신메뉴 광고",
            product="제로 콜드브루",
            audience="20대 직장인",
            cta="오늘 만나보기",
            trend=card,
        )

        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary)
            write_text_artifacts(output, results=[result], storyboard=storyboard)
            report = write_html_report(
                output,
                results=[result],
                storyboard=storyboard,
                has_video=False,
                has_gif=False,
            )

            self.assertIn("제로 콜드브루", (output / "prompt.txt").read_text(encoding="utf-8"))
            self.assertIn("니가 좋아", report.read_text(encoding="utf-8"))
            self.assertTrue((output / "retrieval.json").exists())
            self.assertTrue((output / "storyboard.json").exists())

    def test_animatic_is_readable_mp4(self) -> None:
        try:
            import cv2
        except ImportError:
            self.skipTest("OpenCV is not installed")

        storyboard = build_storyboard(
            brief="카페 광고",
            product="제로 콜드브루",
            audience="20대 직장인",
            cta="오늘 만나보기",
            trend=TrendCard(card_id="trend", title="니가 좋아💖", source="test"),
        )
        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / "animatic.mp4"
            metadata = render_animatic(
                storyboard,
                video,
                width=180,
                height=320,
                fps=2,
            )
            capture = cv2.VideoCapture(str(video))
            try:
                ok, frame = capture.read()
                self.assertTrue(ok)
                self.assertEqual(frame.shape[:2], (320, 180))
                self.assertEqual(int(capture.get(cv2.CAP_PROP_FRAME_COUNT)), 20)
            finally:
                capture.release()
            self.assertEqual(metadata["frames"], 20)
            self.assertGreater(video.stat().st_size, 1_000)


if __name__ == "__main__":
    unittest.main()
