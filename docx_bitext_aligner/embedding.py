from __future__ import annotations

import sys
from typing import Any

from docx_bitext_aligner.config import ModelLoadError, RunConfig


def _status(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def select_embedding_device(requested: str) -> str:
    device = requested.lower()
    if device != "auto":
        return device

    try:
        import torch
    except Exception:
        return "cpu"

    if torch.cuda.is_available():
        return "cuda"
    mps = getattr(getattr(torch, "backends", None), "mps", None)
    if mps is not None and mps.is_available():
        return "mps"
    return "cpu"


def validate_embedding_device(device: str) -> None:
    if device == "cpu":
        return

    try:
        import torch
    except Exception as exc:
        raise ModelLoadError(f"Could not validate requested device {device!r}; torch is unavailable") from exc

    if device == "cuda" and not torch.cuda.is_available():
        raise ModelLoadError("Requested --device cuda, but CUDA is not available")
    mps = getattr(getattr(torch, "backends", None), "mps", None)
    if device == "mps" and (mps is None or not mps.is_available()):
        raise ModelLoadError("Requested --device mps, but PyTorch MPS is not available")


def load_embedding_model(config: RunConfig) -> Any:
    _status(f"Preparing language model: {config.model}")
    try:
        from sentence_transformers import SentenceTransformer
    except Exception as exc:
        raise ModelLoadError("Could not import sentence-transformers. Install dependencies with uv sync") from exc

    device = select_embedding_device(config.device)
    validate_embedding_device(device)
    _status(f"Using embedding device: {device}")
    if config.allow_model_download:
        _status("Checking local model cache; downloading model files if needed.")
    else:
        _status("Checking local model cache.")
    try:
        model = SentenceTransformer(
            config.model,
            local_files_only=not config.allow_model_download,
            trust_remote_code=False,
            device=device,
        )
        _status("Language model ready.")
        return model
    except Exception as exc:
        mode = "cached locally" if not config.allow_model_download else "available for download"
        raise ModelLoadError(f"Could not load embedding model {config.model!r}; expected {mode}") from exc


def encode_texts(model: Any, texts: list[str], batch_size: int) -> Any:
    import numpy as np

    if not texts:
        return np.empty((0, 0), dtype=np.float32)
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        convert_to_numpy=True,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return np.asarray(vectors, dtype=np.float32)
