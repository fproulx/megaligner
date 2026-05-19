from __future__ import annotations

import unittest

from docx_bitext_aligner.models import PairResult
from docx_bitext_aligner.runner import format_pair_result


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


if __name__ == "__main__":
    unittest.main()
