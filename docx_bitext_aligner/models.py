from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


@dataclass(frozen=True)
class Segment:
    text: str
    paragraph_index: int
    sentence_index: int
    global_index: int


@dataclass(frozen=True)
class SegmentWindow:
    start: int
    length: int
    paragraph_index: int
    text: str
    vector_index: int


@dataclass(frozen=True)
class AlignmentUnit:
    src_start: int
    src_len: int
    tgt_start: int
    tgt_len: int
    similarity: float
    score: float
    src_text: str
    tgt_text: str
    tuid: str


@dataclass
class PairResult:
    stem: str
    status: str
    out_path: Optional[Path] = None
    alignments: int = 0
    raw_alignments: int = 0
    dropped: int = 0
    duplicate_units: int = 0
    empty_units: int = 0
    normalized_units: int = 0
    tmx_units_final: bool = True
    src_segments: int = 0
    tgt_segments: int = 0
    src_windows: int = 0
    tgt_windows: int = 0
    reason: Optional[str] = None
    traceback_text: Optional[str] = None
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def units_before_tmx_cleanup(self) -> int:
        return self.raw_alignments if self.raw_alignments else self.alignments


@dataclass
class PairAlignment:
    units: list[AlignmentUnit]
    dropped: int
    src_segments: list[Segment]
    tgt_segments: list[Segment]
    src_windows: int
    tgt_windows: int
    timings: dict[str, float]


@dataclass(frozen=True)
class BackPointer:
    prev_i: int
    prev_j: int
    src_len: int
    tgt_len: int
    similarity: float
    score: float
