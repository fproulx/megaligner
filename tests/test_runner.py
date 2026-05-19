from __future__ import annotations

import unittest
from pathlib import Path

from docx_bitext_aligner.discovery import PairJob
from docx_bitext_aligner.models import PairResult, PairWindows, SegmentWindow
from docx_bitext_aligner.runner import (
    PreparedCombinedPair,
    embedding_vector_cache_mb,
    format_pair_result,
    should_use_global_embedding,
    unique_window_texts,
)


class RunnerFormattingTests(unittest.TestCase):
    def test_combined_pair_result_labels_units_as_before_cleanup(self) -> None:
        result = PairResult(
            stem="9701",
            status="succeeded",
            alignments=42,
            raw_alignments=42,
            tmx_units_final=False,
            src_segments=50,
            tgt_segments=51,
            dropped=2,
        )

        self.assertEqual(result.units_before_tmx_cleanup, 42)
        self.assertIn("42 aligned units before TMX cleanup", format_pair_result(result))
        self.assertNotIn("42 TUs", format_pair_result(result))

    def test_unique_window_texts_preserves_first_seen_order(self) -> None:
        job = PairJob(stem="a", src_path=Path("a.en.docx"), tgt_path=Path("a.ru.docx"), out_path=Path("a.tmx"))
        pair_windows = PairWindows(
            src_segments=[],
            tgt_segments=[],
            src_windows=[
                SegmentWindow(0, 1, 0, "first", 0),
                SegmentWindow(1, 1, 0, "shared", 1),
            ],
            tgt_windows=[
                SegmentWindow(0, 1, 0, "shared", 0),
                SegmentWindow(1, 1, 0, "target", 1),
            ],
            src_lookup={},
            tgt_lookup={},
            duplicate_window_texts=1,
        )

        texts, indexes, total = unique_window_texts(
            [PreparedCombinedPair(index=0, job=job, pair_windows=pair_windows, timings={})]
        )

        self.assertEqual(texts, ["first", "shared", "target"])
        self.assertEqual(indexes, {"first": 0, "shared": 1, "target": 2})
        self.assertEqual(total, 4)

    def test_global_embedding_memory_guard(self) -> None:
        self.assertAlmostEqual(embedding_vector_cache_mb(1024, 256), 1.0)
        self.assertTrue(should_use_global_embedding(1024, 256, max_mb=1))
        self.assertTrue(should_use_global_embedding(1024, 256, max_mb=2))
        self.assertFalse(should_use_global_embedding(1024, 256, max_mb=0))
        self.assertFalse(should_use_global_embedding(2048, 256, max_mb=1))


if __name__ == "__main__":
    unittest.main()
