from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from docx_bitext_aligner.discovery import AUTO_PATTERN, discover_pairs, normalized_stem_variants


def config(pattern: str = AUTO_PATTERN) -> SimpleNamespace:
    return SimpleNamespace(src_lang="en", tgt_lang="ru", pattern=pattern)


def touch_all(root: Path, names: list[str]) -> None:
    for name in names:
        (root / name).touch()


def mapping(result) -> dict[str, tuple[str, str]]:
    return {job.stem: (job.src_path.name, job.tgt_path.name) for job in result.jobs}


class DiscoveryTests(unittest.TestCase):
    def discover(self, names: list[str], pattern: str = AUTO_PATTERN):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            touch_all(root, names)
            result = discover_pairs(root, root / "out", config(pattern))
            return result

    def test_suffix_schemes_are_auto_detected(self) -> None:
        cases = [
            ("{stem}.{lang}.docx", ["chapter.en.docx", "chapter.ru.docx"]),
            ("{stem}_{lang}.docx", ["chapter_en.docx", "chapter_ru.docx"]),
            ("{stem}-{lang}.docx", ["chapter-en.docx", "chapter-ru.docx"]),
        ]
        for expected_scheme, names in cases:
            with self.subTest(expected_scheme=expected_scheme):
                result = self.discover(names)
                self.assertEqual(result.scheme_description, expected_scheme)
                self.assertEqual(mapping(result), {"chapter": (names[0], names[1])})

    def test_prefix_schemes_are_auto_detected(self) -> None:
        cases = [
            ("{lang}.{stem}.docx", ["en.chapter.docx", "ru.chapter.docx"]),
            ("{lang}_{stem}.docx", ["en_chapter.docx", "ru_chapter.docx"]),
            ("{lang}-{stem}.docx", ["en-chapter.docx", "ru-chapter.docx"]),
        ]
        for expected_scheme, names in cases:
            with self.subTest(expected_scheme=expected_scheme):
                result = self.discover(names)
                self.assertEqual(result.scheme_description, expected_scheme)
                self.assertEqual(mapping(result), {"chapter": (names[0], names[1])})

    def test_region_tags_match_base_languages(self) -> None:
        result = self.discover(["chapter.en-US.docx", "chapter.ru-RU.docx"])
        self.assertEqual(result.scheme_description, "{stem}.{lang}.docx")
        self.assertEqual(mapping(result), {"chapter": ("chapter.en-US.docx", "chapter.ru-RU.docx")})

    def test_russian_prefix_recovers_unique_normalized_stems(self) -> None:
        names = [
            "9701.docx",
            "R9701.docx",
            "9702.docx",
            "R9702r1.docx",
            "9704.docx",
            "R9704ri.docx",
            "9705_p1_0.docx",
            "R9705.docx",
            "9730_p1.docx",
            "R9730p1.docx",
            "9731_p1.docx",
            "R9731p1.docx",
            "9732_p1.docx",
            "R9732.docx",
            "9733_p1.docx",
            "R9733.docx",
            "9736c1b.docx",
            "R9736c1.docx",
            "9777.docx",
            "R9777ri.docx",
            "9783_p1.docx",
            "R9783.docx",
            "9784_0.docx",
            "R9784.docx",
            "9766.docx",
            "R9790.docx",
        ]
        result = self.discover(names)

        self.assertEqual(result.scheme, "russian-prefix-normalized")
        self.assertEqual(len(result.jobs), 12)
        self.assertEqual(len(result.fuzzy_pairs), 11)
        self.assertEqual(result.unpaired, ["9766.docx: missing ru", "R9790.docx: missing en"])

        pairs = mapping(result)
        self.assertEqual(pairs["9701"], ("9701.docx", "R9701.docx"))
        self.assertEqual(pairs["9702"], ("9702.docx", "R9702r1.docx"))
        self.assertEqual(pairs["9705_p1_0"], ("9705_p1_0.docx", "R9705.docx"))
        self.assertEqual(pairs["9730_p1"], ("9730_p1.docx", "R9730p1.docx"))
        self.assertEqual(pairs["9736c1b"], ("9736c1b.docx", "R9736c1.docx"))
        self.assertEqual(pairs["9784_0"], ("9784_0.docx", "R9784.docx"))

    def test_ambiguous_normalized_stems_are_not_guessed(self) -> None:
        result = self.discover(["123_p1.docx", "123_0.docx", "R123.docx"])
        self.assertEqual(result.jobs, [])
        self.assertEqual(result.fuzzy_pairs, [])
        self.assertCountEqual(
            result.unpaired,
            ["123_0.docx: missing ru", "123_p1.docx: missing ru", "R123.docx: missing en"],
        )

    def test_explicit_pattern_reports_ignored_docx(self) -> None:
        result = self.discover(
            ["chapter.en.docx", "chapter.ru.docx", "unmatched.docx"],
            pattern="{stem}.{lang}.docx",
        )
        self.assertEqual(result.scheme, "explicit-pattern")
        self.assertEqual(len(result.jobs), 1)
        self.assertEqual([path.name for path in result.ignored], ["unmatched.docx"])

    def test_normalized_variant_generation_is_conservative(self) -> None:
        self.assertIn("9705", normalized_stem_variants("9705_p1_0"))
        self.assertIn("9730p1", normalized_stem_variants("9730_p1"))
        self.assertIn("9730", normalized_stem_variants("9730_p1"))
        self.assertIn("9704", normalized_stem_variants("9704ri"))


if __name__ == "__main__":
    unittest.main()
