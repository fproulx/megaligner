from __future__ import annotations

import hashlib
import math
import time
from collections import Counter
from typing import Any, Optional

from docx_bitext_aligner.config import PairProcessingError, RunConfig
from docx_bitext_aligner.embedding import encode_texts
from docx_bitext_aligner.models import AlignmentUnit, BackPointer, Segment, SegmentWindow
from docx_bitext_aligner.utils import normalize_space, safe_stem_for_tuid, timed_call

FLOAT32_BYTES = 4


def make_windows(segments: list[Segment], max_group: int) -> tuple[list[SegmentWindow], dict[tuple[int, int], SegmentWindow]]:
    windows: list[SegmentWindow] = []
    lookup: dict[tuple[int, int], SegmentWindow] = {}
    for start in range(len(segments)):
        paragraph_index = segments[start].paragraph_index
        parts: list[str] = []
        for length in range(1, max_group + 1):
            end = start + length
            if end > len(segments):
                break
            if any(seg.paragraph_index != paragraph_index for seg in segments[start:end]):
                break
            parts.append(segments[end - 1].text)
            text = normalize_space(" ".join(parts))
            window = SegmentWindow(
                start=start,
                length=length,
                paragraph_index=paragraph_index,
                text=text,
                vector_index=len(windows),
            )
            windows.append(window)
            lookup[(start, length)] = window
    return windows, lookup


def band_range(i: int, n: int, m: int, band: Optional[int]) -> tuple[int, int]:
    if band is None:
        return 0, m
    expected = (i * m / n) if n else 0
    low = max(0, int(math.floor(expected - band)))
    high = min(m, int(math.ceil(expected + band)))
    return low, high


def choose_band(n: int, m: int, requested: Optional[int]) -> Optional[int]:
    if requested is not None:
        return requested if requested > 0 else None
    cells = (n + 1) * (m + 1)
    if cells <= 4_000_000:
        return None
    return max(80, int(max(n, m) * 0.08))


def get_score(dp: list[dict[int, float]], i: int, j: int) -> float:
    if i < 0 or j < 0:
        return -math.inf
    if i >= len(dp):
        return -math.inf
    return dp[i].get(j, -math.inf)


def count_duplicate_window_texts(windows: list[SegmentWindow]) -> int:
    counts = Counter(window.text for window in windows)
    return sum(count - 1 for count in counts.values() if count > 1)


def similarity_matrix_size_bytes(src_count: int, tgt_count: int) -> int:
    return src_count * tgt_count * FLOAT32_BYTES


def precompute_similarity_matrix(src_vectors: Any, tgt_vectors: Any, max_mb: int) -> Any | None:
    import numpy as np

    if max_mb <= 0:
        return None
    size_bytes = similarity_matrix_size_bytes(len(src_vectors), len(tgt_vectors))
    if size_bytes > max_mb * 1024 * 1024:
        return None
    return np.asarray(src_vectors, dtype=np.float32) @ np.asarray(tgt_vectors, dtype=np.float32).T


def cosine_similarity(
    src_vectors: Any,
    tgt_vectors: Any,
    src_index: int,
    tgt_index: int,
    similarities: Any | None = None,
) -> float:
    if similarities is not None:
        return float(similarities[src_index, tgt_index])

    import numpy as np

    return float(np.dot(src_vectors[src_index], tgt_vectors[tgt_index]))


def run_alignment_dp(
    src_segments: list[Segment],
    tgt_segments: list[Segment],
    src_window_lookup: dict[tuple[int, int], SegmentWindow],
    tgt_window_lookup: dict[tuple[int, int], SegmentWindow],
    src_vectors: Any,
    tgt_vectors: Any,
    similarities: Any | None,
    config: RunConfig,
    band: Optional[int],
) -> list[AlignmentUnit]:
    n = len(src_segments)
    m = len(tgt_segments)
    max_group = config.max_group
    dp: list[dict[int, float]] = [dict() for _ in range(n + 1)]
    back: dict[tuple[int, int], BackPointer] = {}
    dp[0][0] = 0.0

    for i in range(n + 1):
        low, high = band_range(i, n, m, band)
        for j in range(low, high + 1):
            if i == 0 and j == 0:
                continue
            best = -math.inf
            best_back: Optional[BackPointer] = None

            from_src_gap = get_score(dp, i - 1, j)
            if from_src_gap > -math.inf:
                score = from_src_gap + config.gap_penalty
                if score > best:
                    best = score
                    best_back = BackPointer(i - 1, j, 1, 0, 0.0, config.gap_penalty)

            from_tgt_gap = get_score(dp, i, j - 1)
            if from_tgt_gap > -math.inf:
                score = from_tgt_gap + config.gap_penalty
                if score > best:
                    best = score
                    best_back = BackPointer(i, j - 1, 0, 1, 0.0, config.gap_penalty)

            for src_len in range(1, max_group + 1):
                src_start = i - src_len
                if src_start < 0:
                    continue
                src_window = src_window_lookup.get((src_start, src_len))
                if src_window is None:
                    continue
                for tgt_len in range(1, max_group + 1):
                    tgt_start = j - tgt_len
                    if tgt_start < 0:
                        continue
                    tgt_window = tgt_window_lookup.get((tgt_start, tgt_len))
                    if tgt_window is None:
                        continue
                    previous = get_score(dp, src_start, tgt_start)
                    if previous == -math.inf:
                        continue
                    similarity = cosine_similarity(
                        src_vectors,
                        tgt_vectors,
                        src_window.vector_index,
                        tgt_window.vector_index,
                        similarities,
                    )
                    transition = similarity - config.group_penalty * (src_len + tgt_len - 2)
                    score = previous + transition
                    if score > best:
                        best = score
                        best_back = BackPointer(src_start, tgt_start, src_len, tgt_len, similarity, transition)

            if best_back is not None:
                dp[i][j] = best
                back[(i, j)] = best_back

    if get_score(dp, n, m) == -math.inf:
        raise PairProcessingError("Alignment path could not be found within the configured band")

    raw_steps: list[BackPointer] = []
    i = n
    j = m
    while i != 0 or j != 0:
        pointer = back.get((i, j))
        if pointer is None:
            raise PairProcessingError("Alignment traceback failed")
        raw_steps.append(pointer)
        i, j = pointer.prev_i, pointer.prev_j
    raw_steps.reverse()

    units: list[AlignmentUnit] = []
    for pointer in raw_steps:
        if pointer.src_len == 0 or pointer.tgt_len == 0:
            continue
        src_text = src_window_lookup[(pointer.prev_i, pointer.src_len)].text
        tgt_text = tgt_window_lookup[(pointer.prev_j, pointer.tgt_len)].text
        units.append(
            AlignmentUnit(
                src_start=pointer.prev_i,
                src_len=pointer.src_len,
                tgt_start=pointer.prev_j,
                tgt_len=pointer.tgt_len,
                similarity=pointer.similarity,
                score=pointer.score,
                src_text=src_text,
                tgt_text=tgt_text,
                tuid="",
            )
        )
    return units


def align_segments(
    src_segments: list[Segment],
    tgt_segments: list[Segment],
    stem: str,
    model: Any,
    config: RunConfig,
) -> tuple[list[AlignmentUnit], int, dict[str, float], int, int, int, int]:
    if not src_segments:
        raise PairProcessingError("Source document produced zero sentence segments")
    if not tgt_segments:
        raise PairProcessingError("Target document produced zero sentence segments")

    timings: dict[str, float] = {}
    src_windows, src_lookup = timed_call(timings, "src_windows", make_windows, src_segments, config.max_group)
    tgt_windows, tgt_lookup = timed_call(timings, "tgt_windows", make_windows, tgt_segments, config.max_group)
    duplicate_window_texts = count_duplicate_window_texts([*src_windows, *tgt_windows])
    src_window_count = len(src_windows)
    vectors = timed_call(
        timings,
        "encode",
        encode_texts,
        model,
        [window.text for window in [*src_windows, *tgt_windows]],
        config.batch_size,
    )
    src_vectors = vectors[:src_window_count]
    tgt_vectors = vectors[src_window_count:]
    similarities = timed_call(
        timings,
        "similarity_matrix",
        precompute_similarity_matrix,
        src_vectors,
        tgt_vectors,
        config.similarity_matrix_max_mb,
    )

    band = choose_band(len(src_segments), len(tgt_segments), config.band)
    dp_full_retries = 0
    try:
        units = timed_call(
            timings,
            "dp",
            run_alignment_dp,
            src_segments,
            tgt_segments,
            src_lookup,
            tgt_lookup,
            src_vectors,
            tgt_vectors,
            similarities,
            config,
            band,
        )
    except PairProcessingError:
        if band is not None and config.band is None:
            dp_full_retries = 1
            units = timed_call(
                timings,
                "dp_full_retry",
                run_alignment_dp,
                src_segments,
                tgt_segments,
                src_lookup,
                tgt_lookup,
                src_vectors,
                tgt_vectors,
                similarities,
                config,
                None,
            )
        else:
            raise

    postprocess_started = time.perf_counter()
    stable_units: list[AlignmentUnit] = []
    for unit in units:
        tuid = make_tuid(
            stem=stem,
            src_lang=config.src_lang,
            tgt_lang=config.tgt_lang,
            src_start=unit.src_start,
            src_len=unit.src_len,
            tgt_start=unit.tgt_start,
            tgt_len=unit.tgt_len,
            src_text=unit.src_text,
            tgt_text=unit.tgt_text,
        )
        stable_units.append(
            AlignmentUnit(
                src_start=unit.src_start,
                src_len=unit.src_len,
                tgt_start=unit.tgt_start,
                tgt_len=unit.tgt_len,
                similarity=unit.similarity,
                score=unit.score,
                src_text=unit.src_text,
                tgt_text=unit.tgt_text,
                tuid=tuid,
            )
        )

    dropped = 0
    if config.min_similarity is not None:
        before = len(stable_units)
        stable_units = [unit for unit in stable_units if unit.similarity >= config.min_similarity]
        dropped = before - len(stable_units)
    timings["postprocess"] = timings.get("postprocess", 0.0) + time.perf_counter() - postprocess_started

    if not stable_units:
        raise PairProcessingError("Alignment produced zero usable translation units")
    return stable_units, dropped, timings, len(src_windows), len(tgt_windows), duplicate_window_texts, dp_full_retries


def make_tuid(
    stem: str,
    src_lang: str,
    tgt_lang: str,
    src_start: int,
    src_len: int,
    tgt_start: int,
    tgt_len: int,
    src_text: str,
    tgt_text: str,
) -> str:
    material = "\x1f".join(
        [
            stem,
            src_lang,
            tgt_lang,
            str(src_start),
            str(src_len),
            str(tgt_start),
            str(tgt_len),
            src_text,
            tgt_text,
        ]
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:20]
    prefix = safe_stem_for_tuid(stem)
    return f"{prefix}-{digest}" if stem else digest
