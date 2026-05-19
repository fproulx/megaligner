from __future__ import annotations

import unittest

from docx_bitext_aligner.cli import make_config, parse_args
from docx_bitext_aligner.config import DEFAULT_GLOBAL_EMBEDDING_MAX_MB, DEFAULT_MIN_SIMILARITY


class CliTests(unittest.TestCase):
    def test_parse_batch_args(self) -> None:
        args = parse_args(
            [
                "documents",
                "out",
                "--combined-output",
                "out/aligned.tmx",
                "--device",
                "mps",
                "--profile",
                "--sample-size",
                "5",
            ]
        )
        config = make_config(args)

        self.assertEqual(args.input_dir, "documents")
        self.assertEqual(args.output_dir, "out")
        self.assertEqual(args.combined_output, "out/aligned.tmx")
        self.assertEqual(config.device, "mps")
        self.assertTrue(config.profile)
        self.assertEqual(config.sample_size, 5)
        self.assertEqual(config.min_similarity, DEFAULT_MIN_SIMILARITY)

    def test_parse_pair_args(self) -> None:
        args = parse_args(["--pair", "a.docx", "b.docx", "out.tmx", "--force"])
        config = make_config(args)

        self.assertEqual(args.pair, ["a.docx", "b.docx", "out.tmx"])
        self.assertTrue(config.force)

    def test_parse_internal_suppress_discovery_report_flag(self) -> None:
        args = parse_args(["documents", "out", "--suppress-discovery-report"])

        self.assertTrue(args.suppress_discovery_report)

    def test_no_similarity_filter_disables_default_threshold(self) -> None:
        args = parse_args(["documents", "out", "--no-similarity-filter"])
        config = make_config(args)

        self.assertIsNone(config.min_similarity)

    def test_keep_trivial_numeric_units_flag(self) -> None:
        args = parse_args(["documents", "out", "--keep-trivial-numeric-units"])
        config = make_config(args)

        self.assertTrue(config.keep_trivial_numeric_units)

    def test_similarity_matrix_memory_guard_flag(self) -> None:
        args = parse_args(["documents", "out", "--similarity-matrix-max-mb", "0"])
        config = make_config(args)

        self.assertEqual(config.similarity_matrix_max_mb, 0)

    def test_global_embedding_memory_guard_flag(self) -> None:
        args = parse_args(["documents", "out", "--global-embedding-max-mb", "0"])
        config = make_config(args)

        self.assertEqual(config.global_embedding_max_mb, 0)
        self.assertNotEqual(config.global_embedding_max_mb, DEFAULT_GLOBAL_EMBEDDING_MAX_MB)


if __name__ == "__main__":
    unittest.main()
