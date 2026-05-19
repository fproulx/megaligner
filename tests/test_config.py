from __future__ import annotations

import unittest

from docx_bitext_aligner.config import RunConfig, validate_config


class ConfigTests(unittest.TestCase):
    def test_valid_default_config(self) -> None:
        validate_config(RunConfig())

    def test_rejects_invalid_workers(self) -> None:
        with self.assertRaisesRegex(ValueError, "--workers"):
            validate_config(RunConfig(workers=0))

    def test_rejects_invalid_device(self) -> None:
        with self.assertRaisesRegex(ValueError, "--device"):
            validate_config(RunConfig(device="metal"))

    def test_rejects_bad_explicit_pattern(self) -> None:
        with self.assertRaisesRegex(ValueError, "Pattern"):
            validate_config(RunConfig(pattern="{stem}.docx"))


if __name__ == "__main__":
    unittest.main()
