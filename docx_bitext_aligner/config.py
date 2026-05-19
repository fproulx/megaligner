from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from docx_bitext_aligner.discovery import AUTO_PATTERN, DEFAULT_PATTERN, build_pattern_regex

TOOL_NAME = "align-docx"
DEFAULT_SRC_LANG = "en"
DEFAULT_TGT_LANG = "ru"
DEFAULT_MODEL = "sentence-transformers/LaBSE"
DEFAULT_BATCH_SIZE = 64
DEFAULT_MAX_GROUP = 3
DEFAULT_GAP_PENALTY = -0.40
DEFAULT_GROUP_PENALTY = 0.06
DEFAULT_CREATION_DATE = "19700101T000000Z"
DEFAULT_SAMPLE_SIZE = 12
DEFAULT_MIN_SIMILARITY = 0.45


class PairProcessingError(RuntimeError):
    pass


class ModelLoadError(RuntimeError):
    pass


@dataclass
class RunConfig:
    src_lang: str = DEFAULT_SRC_LANG
    tgt_lang: str = DEFAULT_TGT_LANG
    pattern: str = DEFAULT_PATTERN
    workers: int = 1
    force: bool = False
    min_similarity: Optional[float] = DEFAULT_MIN_SIMILARITY
    report: bool = False
    verbosity: int = 0
    yes: bool = False
    dry_run: bool = False
    profile: bool = False
    device: str = "auto"
    sample_size: int = DEFAULT_SAMPLE_SIZE
    model: str = DEFAULT_MODEL
    allow_model_download: bool = False
    batch_size: int = DEFAULT_BATCH_SIZE
    max_group: int = DEFAULT_MAX_GROUP
    gap_penalty: float = DEFAULT_GAP_PENALTY
    group_penalty: float = DEFAULT_GROUP_PENALTY
    creationdate: str = DEFAULT_CREATION_DATE
    band: Optional[int] = None


def default_workers() -> int:
    cpu = os.cpu_count() or 1
    return max(1, min(4, cpu - 1 if cpu > 1 else 1))


def validate_config(config: RunConfig) -> None:
    if config.workers < 1:
        raise ValueError("--workers must be at least 1")
    if config.max_group < 1:
        raise ValueError("--max-group must be at least 1")
    if config.batch_size < 1:
        raise ValueError("--batch-size must be at least 1")
    if config.sample_size < 0:
        raise ValueError("--sample-size must be at least 0")
    if config.min_similarity is not None and not (-1.0 <= config.min_similarity <= 1.0):
        raise ValueError("--min-similarity must be between -1.0 and 1.0")
    if config.device not in {"auto", "cpu", "cuda", "mps"}:
        raise ValueError("--device must be one of: auto, cpu, cuda, mps")
    if config.pattern != AUTO_PATTERN:
        build_pattern_regex(config.pattern)
