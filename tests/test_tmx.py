from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from xml.etree import ElementTree

from docx_bitext_aligner.config import RunConfig
from docx_bitext_aligner.models import AlignmentUnit
from docx_bitext_aligner.tmx import prepare_tmx_units, write_tmx


def unit(src: str, tgt: str, similarity: float, tuid: str) -> AlignmentUnit:
    return AlignmentUnit(
        src_start=0,
        src_len=1,
        tgt_start=0,
        tgt_len=1,
        similarity=similarity,
        score=similarity,
        src_text=src,
        tgt_text=tgt,
        tuid=tuid,
    )


class TmxPreparationTests(unittest.TestCase):
    def test_prepare_tmx_units_normalizes_and_deduplicates_pairs(self) -> None:
        prepared, stats = prepare_tmx_units(
            [
                unit("  Hello\u00a0 world  ", " Привет   мир ", 0.70, "first"),
                unit("Hello world", "Привет мир", 0.91, "better"),
                unit("Hello world", "Привет мир", 0.60, "worse"),
                unit("   ", "ignored", 0.99, "empty-source"),
            ]
        )

        self.assertEqual(stats.input_units, 4)
        self.assertEqual(stats.written_units, 1)
        self.assertEqual(stats.duplicate_units, 2)
        self.assertEqual(stats.empty_units, 1)
        self.assertEqual(stats.normalized_units, 2)
        self.assertEqual(stats.trivial_numeric_units, 0)
        self.assertEqual(prepared[0].src_text, "Hello world")
        self.assertEqual(prepared[0].tgt_text, "Привет мир")
        self.assertEqual(prepared[0].similarity, 0.91)
        self.assertEqual(prepared[0].tuid, "better")

    def test_prepare_tmx_units_skips_standalone_numeric_pairs_by_default(self) -> None:
        prepared, stats = prepare_tmx_units(
            [
                unit("182.22", "182,22", 0.95, "decimal"),
                unit("$10,220", "10 220", 0.90, "money"),
                unit("Table 3", "Таблица 3", 0.80, "text-bearing"),
                unit("III.", "III. Раздел", 0.80, "roman"),
            ]
        )

        self.assertEqual(stats.input_units, 4)
        self.assertEqual(stats.written_units, 2)
        self.assertEqual(stats.trivial_numeric_units, 2)
        self.assertEqual([item.tuid for item in prepared], ["text-bearing", "roman"])

    def test_prepare_tmx_units_can_keep_standalone_numeric_pairs(self) -> None:
        prepared, stats = prepare_tmx_units(
            [unit("182.22", "182,22", 0.95, "decimal")],
            keep_trivial_numeric_units=True,
        )

        self.assertEqual(stats.written_units, 1)
        self.assertEqual(stats.trivial_numeric_units, 0)
        self.assertEqual(prepared[0].tuid, "decimal")

    def test_write_tmx_returns_written_units_and_stats(self) -> None:
        try:
            import lxml.etree  # noqa: F401
        except Exception as exc:
            self.skipTest(f"lxml is not installed: {exc}")

        with TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "out.tmx"
            result = write_tmx(
                [
                    unit(" Hello  world ", " Привет   мир ", 0.70, "first"),
                    unit("Hello world", "Привет мир", 0.91, "better"),
                ],
                out_path,
                RunConfig(),
            )

            self.assertEqual(result.stats.input_units, 2)
            self.assertEqual(result.stats.written_units, 1)
            self.assertEqual(result.units[0].tuid, "better")

            body = ElementTree.parse(out_path).getroot().find("body")
            self.assertIsNotNone(body)
            tus = body.findall("tu") if body is not None else []
            self.assertEqual(len(tus), 1)


if __name__ == "__main__":
    unittest.main()
