from __future__ import annotations

import unittest

from docx_bitext_aligner.embedding import encode_texts


class FakeEmbeddingModel:
    def __init__(self) -> None:
        self.encoded_texts: list[str] = []

    def encode(self, texts: list[str], **kwargs: object) -> object:
        try:
            import numpy as np
        except Exception as exc:
            raise unittest.SkipTest(f"numpy is not installed: {exc}") from exc

        self.encoded_texts = list(texts)
        return np.asarray([[float(len(text)), float(index)] for index, text in enumerate(texts)])


class EmbeddingTests(unittest.TestCase):
    def test_encode_texts_deduplicates_exact_texts_and_scatters_vectors(self) -> None:
        try:
            import numpy as np
        except Exception as exc:
            self.skipTest(f"numpy is not installed: {exc}")

        model = FakeEmbeddingModel()

        vectors = encode_texts(model, ["same", "other", "same"], batch_size=64)

        self.assertEqual(model.encoded_texts, ["same", "other"])
        np.testing.assert_array_equal(vectors[0], vectors[2])
        self.assertEqual(vectors.shape, (3, 2))


if __name__ == "__main__":
    unittest.main()
