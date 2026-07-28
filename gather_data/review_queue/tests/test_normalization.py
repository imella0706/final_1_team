from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from review_queue.normalization import (
    NormalizationConfigError,
    load_alias_index,
    load_generic_term_index,
    normalized_match_key,
    resolve_candidate_key,
)


CONFIG_DIR = Path(__file__).resolve().parents[1] / "config"


class ReviewQueueNormalizationTest(unittest.TestCase):
    def test_normalized_match_key_collapses_spacing_and_case(self) -> None:
        self.assertEqual(normalized_match_key("  Forgot   Airpod  "), "forgot airpod")

    def test_normalized_match_key_strips_edge_symbols_only(self) -> None:
        self.assertEqual(normalized_match_key("💖 니가 좋아💖"), "니가 좋아")
        self.assertEqual(normalized_match_key("좋🤙다👍"), "좋🤙다")

    def test_alias_index_resolves_explicit_alias_only(self) -> None:
        aliases = load_alias_index(CONFIG_DIR / "aliases.json")

        self.assertEqual(resolve_candidate_key("밤티난다", aliases), "밤티")
        self.assertEqual(resolve_candidate_key("밤티 난다", aliases), "밤티")
        self.assertEqual(
            resolve_candidate_key("Forgot Airpods trend", aliases),
            "에어팟 스위치 밈".casefold(),
        )

    def test_alias_index_does_not_fuzzy_merge_unknown_variants(self) -> None:
        aliases = load_alias_index(CONFIG_DIR / "aliases.json")

        self.assertEqual(resolve_candidate_key("밤티스럽다", aliases), "밤티스럽다")

    def test_generic_term_index_marks_generic_words(self) -> None:
        generic_terms = load_generic_term_index(CONFIG_DIR / "generic_terms.json")

        self.assertTrue(generic_terms.contains("카페"))
        self.assertTrue(generic_terms.contains("  리뷰  "))
        self.assertFalse(generic_terms.contains("니가 좋아"))

    def test_alias_conflict_fails_fast(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "aliases.json"
            path.write_text(
                json.dumps(
                    {
                        "aliases": [
                            {"canonical": "A", "aliases": ["same"]},
                            {"canonical": "B", "aliases": ["same"]},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            with self.assertRaises(NormalizationConfigError):
                load_alias_index(path)


if __name__ == "__main__":
    unittest.main()
