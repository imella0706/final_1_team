import csv
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import requests

import careet_crawler as cc


FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class ParserTests(unittest.TestCase):
    def test_list_card_fields_and_status(self):
        rows, pages = cc.parse_list_page(fixture("list_page.html"), 1)
        self.assertEqual(12, pages)
        self.assertEqual(2, len(rows))
        self.assertEqual("1929", rows[0]["article_id"])
        self.assertEqual("첫 번째 콘텐츠", rows[0]["title"])
        self.assertEqual("2026-06-17", rows[0]["published_date"])
        self.assertEqual("current", rows[0]["trend_status"])
        self.assertEqual("https://www.careet.net/images/1929.jpg", rows[0]["thumbnail_url"])

    def test_missing_status_is_unknown(self):
        rows, _ = cc.parse_list_page(fixture("list_page.html"), 1)
        self.assertEqual("", rows[1]["trend_status_raw"])
        self.assertEqual("unknown", rows[1]["trend_status"])

    def test_date_conversion(self):
        self.assertEqual("2026-07-08", cc.parse_date("2026.07.08"))
        with self.assertRaises(ValueError):
            cc.parse_date("08/07/2026")

    def test_detail_metadata_and_paywall(self):
        detail = cc.parse_detail_page(fixture("detail_page.html"))
        self.assertEqual("김에디터", detail.values["author"])
        self.assertEqual("77", detail.values["author_id"])
        self.assertEqual("emerging", detail.values["trend_status"])
        self.assertEqual("https://cdn.example/1929.webp", detail.values["thumbnail_url"])
        self.assertTrue(detail.values["is_paywalled"])

    def test_simple_and_nested_toc(self):
        toc = cc.parse_detail_page(fixture("detail_page.html")).toc
        self.assertEqual(6, len(toc))
        self.assertEqual("백룸코어", toc[0]["name"])
        self.assertIsNone(toc[2]["parent_section"])
        self.assertEqual("해외 숏폼 밈 2", toc[3]["parent_section"])
        self.assertEqual("Forgot Airpods trend", toc[4]["name"])
        self.assertEqual(list(range(1, 7)), [item["position"] for item in toc])

    def test_toc_with_marker_in_separate_cells(self):
        html = "<article><table><tr><th>목차</th></tr><tr><td>1.</td><td>첫 항목</td></tr><tr><td>①</td><td>하위 항목</td></tr></table></article>"
        toc = cc.extract_toc(cc._soup(html).article)
        self.assertEqual("첫 항목", toc[0]["name"])
        self.assertEqual("첫 항목", toc[1]["parent_section"])

    def test_no_toc_is_normal(self):
        detail = cc.parse_detail_page(fixture("detail_no_toc.html"))
        self.assertEqual([], detail.toc)
        self.assertEqual("", detail.preview_text)

    def test_rule_summary_only_when_evidence_is_sufficient(self):
        generator = cc.RuleBasedSummaryGenerator()
        result = generator.generate("백룸코어", "공개된 설명이 충분히 길고 의미 및 사용 맥락을 확인할 수 있도록 작성된 테스트 근거 문장입니다.")
        self.assertEqual("generated", result.status)
        self.assertEqual("public_preview", result.source)
        self.assertLessEqual(len(result.summary), 200)
        self.assertNotIn("테스트 근거 문장", result.summary)
        self.assertEqual("insufficient_source", generator.generate("백룸코어", "짧음").status)

    def test_make_meme_rows_limits_evidence_to_first_item(self):
        article = {"article_id": "1", "published_date": "2026-01-01", "trend_status": "current", "url": "https://www.careet.net/1", "collected_at": "now"}
        toc = [{"position": 1, "name": "A", "parent_section": None}, {"position": 2, "name": "B", "parent_section": None}]
        generator = Mock()
        generator.generate.side_effect = [cc.SummaryResult(status="generated"), cc.SummaryResult()]
        cc.make_meme_rows(article, toc, generator, "ephemeral source")
        self.assertEqual("ephemeral source", generator.generate.call_args_list[0].args[1])
        self.assertEqual("", generator.generate.call_args_list[1].args[1])

    def test_duplicate_article_id_merge_policy(self):
        first = {"article_id": "1", "title": "old", "list_page": 1}
        mapping = {first["article_id"]: first}
        second = {"article_id": "1", "title": "new", "list_page": 2}
        mapping[second["article_id"]].update(title=second["title"])
        self.assertEqual(1, len(mapping))
        self.assertEqual(1, mapping["1"]["list_page"])
        self.assertEqual("new", mapping["1"]["title"])


class IOTests(unittest.TestCase):
    def test_csv_has_bom_and_korean_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "out.csv"
            cc.atomic_write_csv(path, ["title", "flag"], [{"title": "한글 제목", "flag": True}])
            self.assertTrue(path.read_bytes().startswith(b"\xef\xbb\xbf"))
            with path.open(encoding="utf-8-sig", newline="") as handle:
                row = next(csv.DictReader(handle))
                self.assertEqual("한글 제목", row["title"])
                self.assertEqual("true", row["flag"])

    def test_image_signature_detection(self):
        self.assertEqual(("image/png", "png"), cc._actual_image_type(b"\x89PNG\r\n\x1a\nmore"))
        self.assertEqual(("image/webp", "webp"), cc._actual_image_type(b"RIFF1234WEBPmore"))
        self.assertIsNone(cc._actual_image_type(b"<html>not image"))

    def test_thumbnail_download_records_safe_path_size_and_hash(self):
        payload = b"\x89PNG\r\n\x1a\n" + b"payload"
        response = ImageResponse(payload, "image/png")
        client = Mock()
        client.get.return_value = response
        article = {"article_id": "123", "thumbnail_url": "https://cdn.example/untrusted-name.exe"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cc.download_thumbnail(client, article, root, 1024)
            self.assertEqual("success", article["thumbnail_download_status"])
            self.assertEqual("raw/thumbnails/123.png", article["thumbnail_local_path"])
            self.assertEqual(len(payload), article["thumbnail_bytes"])
            self.assertEqual(64, len(article["thumbnail_sha256"]))
            self.assertTrue((root / "raw" / "thumbnails" / "123.png").exists())
            self.assertFalse((root / "raw" / "thumbnails" / "123.part").exists())
        self.assertTrue(response.closed)

    def test_thumbnail_rejects_mime_mismatch_and_size_limit(self):
        client = Mock()
        client.get.return_value = ImageResponse(b"<html>not image</html>", "image/png")
        article = {"article_id": "1", "thumbnail_url": "https://cdn.example/a.png"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cc.download_thumbnail(client, article, root, 1024)
            self.assertEqual("failed", article["thumbnail_download_status"])
            self.assertFalse(any((root / "raw" / "thumbnails").glob("*.part")))

        client.get.return_value = ImageResponse(b"\x89PNG\r\n\x1a\nlarge", "image/png")
        article = {"article_id": "2", "thumbnail_url": "https://cdn.example/a.png"}
        with tempfile.TemporaryDirectory() as directory:
            cc.download_thumbnail(client, article, Path(directory), 4)
            self.assertEqual("failed", article["thumbnail_download_status"])

    def test_thumbnail_skips_non_https_url(self):
        client = Mock()
        article = {"article_id": "1", "thumbnail_url": "http://cdn.example/a.png"}
        with tempfile.TemporaryDirectory() as directory:
            cc.download_thumbnail(client, article, Path(directory), 1024)
        self.assertEqual("skipped", article["thumbnail_download_status"])
        client.get.assert_not_called()

    def test_cli_rejects_too_short_delay(self):
        parser = cc.build_parser()
        args = parser.parse_args(["--delay", "0.1"])
        with self.assertRaises(SystemExit):
            cc.validate_args(parser, args)


class Response:
    def __init__(self, status: int, body: bytes = b"ok", headers=None):
        self.status_code = status
        self.content = body
        self.headers = headers or {}
        self.ok = 200 <= status < 400
        self.closed = False

    def close(self):
        self.closed = True


class ImageResponse(Response):
    def __init__(self, body: bytes, content_type: str):
        super().__init__(200, body, {"Content-Type": content_type, "Content-Length": str(len(body))})

    def iter_content(self, chunk_size: int):
        yield self.content


class RetryTests(unittest.TestCase):
    @patch("careet_crawler.time.sleep")
    def test_retries_429_and_5xx(self, sleep):
        polite = cc.PoliteSession(delay=1.0, retries=3)
        polite._wait = Mock()
        polite.session.get = Mock(side_effect=[Response(429), Response(503), Response(200)])
        self.assertEqual(200, polite.get("https://example.test").status_code)
        self.assertEqual(3, polite.session.get.call_count)
        self.assertEqual(2, sleep.call_count)

    @patch("careet_crawler.time.sleep")
    def test_does_not_retry_404(self, sleep):
        polite = cc.PoliteSession(delay=1.0, retries=3)
        polite._wait = Mock()
        polite.session.get = Mock(return_value=Response(404))
        with self.assertRaises(cc.HTTPStatusError):
            polite.get("https://example.test/missing")
        self.assertEqual(1, polite.session.get.call_count)
        sleep.assert_not_called()


if __name__ == "__main__":
    unittest.main()
