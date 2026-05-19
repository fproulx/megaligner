from __future__ import annotations

import re
import time
from typing import Any


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


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
