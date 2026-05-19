from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from docx_bitext_aligner.config import RunConfig
from docx_bitext_aligner.models import AlignmentUnit
from docx_bitext_aligner.qa import build_qa_report, qa_report_paths, write_qa_report


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


class QaReportTests(unittest.TestCase):
    def test_qa_report_paths_append_to_tmx_filename(self) -> None:
        out_path = Path("/tmp/mlatfund2026-aligned.tmx")

        json_path, text_path = qa_report_paths(out_path)

        self.assertEqual(json_path.name, "mlatfund2026-aligned.tmx.qa.json")
        self.assertEqual(text_path.name, "mlatfund2026-aligned.tmx.qa.txt")

    def test_build_qa_report_counts_review_signals(self) -> None:
        units = [
            unit("Hello world", "Privet mir", 0.90, "doc-1"),
            unit("42", "100", 0.50, "doc-2"),
            unit("EP", "EP", 1.00, "doc-3"),
            unit(
                "III.",
                "III. This target side is much longer than the source side and should be flagged.",
                0.60,
                "doc-4",
            ),
            unit("Operating costs", "Variant one translation", 0.88, "doc-5"),
            unit("Operating costs", "Variant two translation", 0.89, "doc-6"),
        ]

        report = build_qa_report(Path("aligned.tmx"), units, RunConfig())
        summary = report["summary"]

        self.assertEqual(report["output_name"], "aligned")
        self.assertEqual(summary["translation_units"], 6)
        self.assertEqual(summary["low_similarity_units"], 1)
        self.assertEqual(summary["numeric_like_units"], 1)
        self.assertEqual(summary["numeric_mismatch_units"], 1)
        self.assertEqual(summary["length_ratio_outliers"], 1)
        self.assertEqual(summary["identical_source_target_units"], 1)
        self.assertEqual(summary["short_side_units"], 3)
        self.assertEqual(summary["source_texts_with_multiple_targets"], 1)
        self.assertEqual(summary["target_texts_with_multiple_sources"], 0)

    def test_write_qa_report_writes_json_and_text_sidecars(self) -> None:
        with TemporaryDirectory() as tmp:
            out_path = Path(tmp) / "aligned.tmx"
            result = write_qa_report(
                out_path,
                [unit("42", "100", 0.50, "doc-1")],
                RunConfig(),
            )

            self.assertTrue(result.json_path.exists())
            self.assertTrue(result.text_path.exists())
            payload = json.loads(result.json_path.read_text(encoding="utf-8"))
            text = result.text_path.read_text(encoding="utf-8")

            self.assertEqual(payload["summary"]["numeric_mismatch_units"], 1)
            self.assertIn("MEGAligner QA report for aligned", text)
            self.assertIn("numeric-looking mismatches: 1", text)


if __name__ == "__main__":
    unittest.main()
