from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from docx_bitext_aligner.config import RunConfig
from docx_bitext_aligner.discovery import DiscoveryResult
from docx_bitext_aligner.models import AlignmentUnit, PairResult, Segment
from docx_bitext_aligner.tmx import TmxWriteStats


def write_report(
    out_path: Path,
    stem: str,
    src_path: Path,
    tgt_path: Path,
    src_segments: list[Segment],
    tgt_segments: list[Segment],
    units: list[AlignmentUnit],
    config: RunConfig,
) -> None:
    report_path = out_path.with_suffix(".alignment.json")
    payload: dict[str, Any] = {
        "stem": stem,
        "source_docx": str(src_path),
        "target_docx": str(tgt_path),
        "output_tmx": str(out_path),
        "src_lang": config.src_lang,
        "tgt_lang": config.tgt_lang,
        "model": config.model,
        "min_similarity": config.min_similarity,
        "src_segments": len(src_segments),
        "tgt_segments": len(tgt_segments),
        "translation_units": len(units),
        "units": [],
    }
    for unit in units:
        src_slice = src_segments[unit.src_start : unit.src_start + unit.src_len]
        tgt_slice = tgt_segments[unit.tgt_start : unit.tgt_start + unit.tgt_len]
        payload["units"].append(
            {
                "tuid": unit.tuid,
                "similarity": round(unit.similarity, 6),
                "score": round(unit.score, 6),
                "grouping": f"{unit.src_len}:{unit.tgt_len}",
                "src_indices": [seg.global_index for seg in src_slice],
                "tgt_indices": [seg.global_index for seg in tgt_slice],
                "src_paragraphs": sorted({seg.paragraph_index for seg in src_slice}),
                "tgt_paragraphs": sorted({seg.paragraph_index for seg in tgt_slice}),
                "src_text": unit.src_text,
                "tgt_text": unit.tgt_text,
            }
        )
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def write_combined_report(
    out_path: Path,
    results: list[PairResult],
    discovery: DiscoveryResult,
    config: RunConfig,
    tmx_stats: TmxWriteStats | None = None,
) -> None:
    report_path = out_path.with_suffix(".alignment.json")
    payload: dict[str, Any] = {
        "output_tmx": str(out_path),
        "src_lang": config.src_lang,
        "tgt_lang": config.tgt_lang,
        "model": config.model,
        "min_similarity": config.min_similarity,
        "pairs": [
            {
                "stem": result.stem,
                "status": result.status,
                "aligned_units_before_tmx_cleanup": result.units_before_tmx_cleanup,
                "tmx_units_written": result.alignments if result.tmx_units_final else None,
                "tmx_units_final": result.tmx_units_final,
                "dropped": result.dropped,
                "duplicate_units": result.duplicate_units,
                "empty_units": result.empty_units,
                "normalized_units": result.normalized_units,
                "identical_source_target_units": result.identical_source_target_units,
                "trivial_numeric_units": result.trivial_numeric_units,
                "src_segments": result.src_segments,
                "tgt_segments": result.tgt_segments,
                "src_windows": result.src_windows,
                "tgt_windows": result.tgt_windows,
                "duplicate_window_texts": result.duplicate_window_texts,
                "dp_full_retries": result.dp_full_retries,
                "reason": result.reason,
            }
            for result in sorted(results, key=lambda item: item.stem.lower())
        ],
        "discovery": {
            "scheme": discovery.scheme,
            "scheme_description": discovery.scheme_description,
            "total_docx": discovery.total_docx,
            "src_files": discovery.src_files,
            "tgt_files": discovery.tgt_files,
            "bitext_pairs": len(discovery.jobs),
            "unpaired": discovery.unpaired,
            "duplicate_groups": discovery.duplicate_groups,
            "fuzzy_pairs": discovery.fuzzy_pairs,
            "ignored": [path.name for path in discovery.ignored],
        },
    }
    if tmx_stats is not None:
        payload["tmx_output"] = {
            "input_units": tmx_stats.input_units,
            "written_units": tmx_stats.written_units,
            "duplicate_units": tmx_stats.duplicate_units,
            "empty_units": tmx_stats.empty_units,
            "normalized_units": tmx_stats.normalized_units,
            "identical_source_target_units": tmx_stats.identical_source_target_units,
            "trivial_numeric_units": tmx_stats.trivial_numeric_units,
        }
    report_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
