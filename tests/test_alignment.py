from __future__ import annotations

import unittest

from docx_bitext_aligner.alignment import band_range, choose_band, make_tuid, make_windows
from docx_bitext_aligner.models import Segment


def segment(text: str, paragraph: int, index: int) -> Segment:
    return Segment(text=text, paragraph_index=paragraph, sentence_index=index, global_index=index)


class AlignmentUtilityTests(unittest.TestCase):
    def test_make_windows_does_not_cross_paragraphs(self) -> None:
        segments = [
            segment("First.", 0, 0),
            segment("Second.", 0, 1),
            segment("Third.", 1, 2),
        ]

        windows, lookup = make_windows(segments, max_group=3)

        self.assertEqual([window.text for window in windows], ["First.", "First. Second.", "Second.", "Third."])
        self.assertIn((0, 2), lookup)
        self.assertNotIn((1, 2), lookup)

    def test_band_range_is_clamped(self) -> None:
        self.assertEqual(band_range(i=5, n=10, m=20, band=3), (7, 13))
        self.assertEqual(band_range(i=0, n=10, m=20, band=3), (0, 3))
        self.assertEqual(band_range(i=10, n=10, m=20, band=3), (17, 20))

    def test_choose_band_uses_full_matrix_for_small_inputs(self) -> None:
        self.assertIsNone(choose_band(100, 100, requested=None))
        self.assertIsNone(choose_band(100, 100, requested=0))
        self.assertEqual(choose_band(100, 100, requested=42), 42)

    def test_tuid_is_stable_and_uses_safe_prefix(self) -> None:
        first = make_tuid("Chapter 1/*", "en", "ru", 0, 1, 0, 1, "Hello", "Привет")
        second = make_tuid("Chapter 1/*", "en", "ru", 0, 1, 0, 1, "Hello", "Привет")

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("Chapter_1-"))


if __name__ == "__main__":
    unittest.main()
