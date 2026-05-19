from __future__ import annotations

import re
import time
from typing import Any

_DIGIT_RE = re.compile(r"\d")
_NON_DIGIT_RE = re.compile(r"\D+")
_NUMERICISH_RE = re.compile(r"^[\s\d.,;:%$\u20ac\u00a3\u00a5()+\-\u2013\u2014/\\*]+$")


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


def is_numericish_text(text: str) -> bool:
    return bool(text) and bool(_NUMERICISH_RE.fullmatch(text)) and bool(_DIGIT_RE.search(text))


def digit_signature(text: str) -> str:
    return _NON_DIGIT_RE.sub("", text)


def safe_stem_for_tuid(stem: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", stem).strip("_")
    return safe or "segment"


def timed_call(timings: dict[str, float], key: str, func: Any, *args: Any, **kwargs: Any) -> Any:
    started = time.perf_counter()
    try:
        return func(*args, **kwargs)
    finally:
        timings[key] = timings.get(key, 0.0) + time.perf_counter() - started


def format_duration(seconds: float) -> str:
    if seconds < 1:
        return f"{seconds * 1000:.0f}ms"
    return f"{seconds:.2f}s"
