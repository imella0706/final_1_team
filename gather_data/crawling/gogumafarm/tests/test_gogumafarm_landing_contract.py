from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from gogumafarm_crawler import (
    CRAWLER_ERROR_FILENAME,
    CRAWLER_RUN_SUMMARY_FILENAME,
    build_keyword_artifacts,
    curated_meme_card_candidates_path,
    landing_run_directory,
    main,
)


def _sample_document() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "source": "gogumafarm",
        "source_url": "https://gogumafarm.kr/category/trends/",
        "category": {"id": 1, "name": "최신 밈과 트렌드", "slug": "trends"},
        "tag": {"id": 110, "name": "밈", "slug": "meme"},
        "collected_at": "2026-07-27T00:00:00+09:00",
        "api_reported_total": 1,
        "article_count": 1,
        "meme_item_count": 1,
        "articles": [
            {
                "post_id": 123,
                "slug": "sample-meme",
                "url": "https://gogumafarm.kr/sample-meme/",
                "title": "샘플 밈",
                "status": "publish",
                "published_local": "2026-07-27T09:00:00+09:00",
                "modified_at": "2026-07-27T00:00:00Z",
                "tags": [{"id": 110, "name": "밈", "slug": "meme"}],
                "featured_image": {"url": "https://gogumafarm.kr/image.jpg"},
                "heading_structure": [{"level": 2, "text": "샘플 밈💖", "order": 1}],
                "external_sources": [],
                "summary": "샘플",
                "meme_items": [{"name": "샘플 밈"}],
                "fetch_status": "success",
                "meme_extraction_status": "success",
                "collected_at": "2026-07-27T00:00:00+09:00",
            }
        ],
    }


class GogumafarmLandingContractTest(unittest.TestCase):
    def test_keyword_artifacts_reuse_term_rows_for_final_terms(self) -> None:
        artifacts = build_keyword_artifacts(_sample_document())

        self.assertEqual(len(artifacts.term_rows), 1)
        self.assertEqual(artifacts.term_rows[0]["term"], "샘플 밈💖")
        self.assertEqual(artifacts.final_terms, ["샘플 밈"])
        self.assertEqual(artifacts.display_terms, ["샘플 밈💖"])

    def test_landing_directory_is_partitioned_by_week_and_run(self) -> None:
        with TemporaryDirectory() as temporary:
            path = landing_run_directory(
                week="2026-W31",
                run_id="manual__gogumafarm_smoke",
                root=Path(temporary),
            )

            self.assertEqual(
                path,
                Path(temporary)
                / "week=2026-W31"
                / "raw"
                / "gogumafarm"
                / "run_id=manual__gogumafarm_smoke",
            )

    def test_emit_from_json_landing_mode_writes_flat_artifacts(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_json = root / "gogumafarm_memes_20260727.json"
            source_json.write_text(
                json.dumps(_sample_document(), ensure_ascii=False),
                encoding="utf-8",
            )
            output_dir = root / "landing-run"

            exit_code = main(
                [
                    "--emit-from-json",
                    str(source_json),
                    "--week",
                    "2026-W31",
                    "--run-id",
                    "manual__gogumafarm_smoke",
                    "--output-dir",
                    str(output_dir),
                    "--date",
                    "2026-07-27",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_dir / "gogumafarm_articles_20260727.csv").is_file())
            self.assertTrue((output_dir / "gogumafarm_meme_terms_20260727.csv").is_file())
            self.assertTrue((output_dir / "gogumafarm_meme_terms_20260727.json").is_file())
            self.assertTrue((output_dir / CRAWLER_RUN_SUMMARY_FILENAME).is_file())
            self.assertFalse((output_dir / "processed").exists())
            self.assertFalse((output_dir / "final_processed").exists())

            terms = json.loads(
                (output_dir / "gogumafarm_meme_terms_20260727.json").read_text(encoding="utf-8")
            )
            self.assertEqual(terms, ["샘플 밈"])

            summary = json.loads(
                (output_dir / CRAWLER_RUN_SUMMARY_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(summary["status"], "success")
            self.assertEqual(summary["source"], "gogumafarm")
            self.assertEqual(summary["week"], "2026-W31")
            self.assertEqual(summary["run_id"], "manual__gogumafarm_smoke")
            self.assertEqual(summary["mode"], "emit_from_json")
            self.assertIn("term_json", summary["outputs"])

    def test_emit_from_json_landing_success_removes_stale_error_artifact(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_json = root / "gogumafarm_memes_20260727.json"
            source_json.write_text(
                json.dumps(_sample_document(), ensure_ascii=False),
                encoding="utf-8",
            )
            output_dir = root / "landing-run"
            output_dir.mkdir()
            stale_error = output_dir / CRAWLER_ERROR_FILENAME
            stale_error.write_text('{"status":"failed"}', encoding="utf-8")

            exit_code = main(
                [
                    "--emit-from-json",
                    str(source_json),
                    "--week",
                    "2026-W31",
                    "--run-id",
                    "manual__gogumafarm_smoke",
                    "--output-dir",
                    str(output_dir),
                    "--date",
                    "2026-07-27",
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertFalse(stale_error.exists())
            summary = json.loads(
                (output_dir / CRAWLER_RUN_SUMMARY_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(summary["status"], "success")

    def test_emit_from_json_can_write_curated_meme_card_candidates(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_json = root / "gogumafarm_memes_20260727.json"
            source_json.write_text(
                json.dumps(_sample_document(), ensure_ascii=False),
                encoding="utf-8",
            )
            output_dir = root / "landing-run"
            curated_root = root / "curated"

            exit_code = main(
                [
                    "--emit-from-json",
                    str(source_json),
                    "--week",
                    "2026-W31",
                    "--run-id",
                    "manual__gogumafarm_smoke",
                    "--output-dir",
                    str(output_dir),
                    "--date",
                    "2026-07-27",
                    "--emit-curated-meme-card-candidates",
                    "--curated-root",
                    str(curated_root),
                ]
            )

            self.assertEqual(exit_code, 0)
            curated_path = curated_meme_card_candidates_path(
                version="v3",
                week="2026-W31",
                root=curated_root,
            )
            self.assertTrue(curated_path.is_file())
            payload = json.loads(curated_path.read_text(encoding="utf-8"))
            self.assertEqual(payload["stage"], "curated")
            self.assertEqual(payload["artifact_name"], "meme_card_candidates")
            self.assertEqual(payload["source_family"], "gogumafarm")
            self.assertEqual(payload["curation_status"], "rule_filtered")
            self.assertEqual(payload["review_status"], "pending")
            self.assertEqual(payload["collected_week"], "2026-W31")
            self.assertEqual(payload["source_landing_run_id"], "manual__gogumafarm_smoke")
            self.assertEqual(payload["terms"], ["샘플 밈"])
            self.assertEqual(payload["display_terms"], ["샘플 밈💖"])

            summary = json.loads(
                (output_dir / CRAWLER_RUN_SUMMARY_FILENAME).read_text(encoding="utf-8")
            )
            self.assertEqual(summary["outputs"]["curated_meme_card_candidates"], str(curated_path))

    def test_emit_from_json_legacy_mode_keeps_team_style_subdirectories(self) -> None:
        with TemporaryDirectory() as temporary:
            root = Path(temporary)
            source_json = root / "gogumafarm_memes_20260727.json"
            source_json.write_text(
                json.dumps(_sample_document(), ensure_ascii=False),
                encoding="utf-8",
            )
            output_dir = root / "legacy"

            exit_code = main(
                [
                    "--emit-from-json",
                    str(source_json),
                    "--output-dir",
                    str(output_dir),
                ]
            )

            self.assertEqual(exit_code, 0)
            self.assertTrue((output_dir / "raw" / "gogumafarm_articles_20260727.csv").is_file())
            self.assertTrue((output_dir / "processed" / "gogumafarm_meme_terms_20260727.csv").is_file())
            self.assertTrue((output_dir / "final_processed" / "gogumafarm_meme_terms_20260727.json").is_file())


if __name__ == "__main__":
    unittest.main()
