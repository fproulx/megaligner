from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docx_bitext_aligner.config import RunConfig
from docx_bitext_aligner.models import AlignmentUnit
from docx_bitext_aligner.utils import digit_signature, is_numericish_text

LOW_SIMILARITY_THRESHOLD = 0.55
SHORT_TEXT_CHARS = 8
LONG_TEXT_CHARS = 50
LENGTH_RATIO_THRESHOLD = 4.0
MAX_SAMPLES = 20
MAX_TEXT_REPORT_SAMPLES = 8

@dataclass(frozen=True)
class QaReportResult:
    json_path: Path
    text_path: Path
    summary: dict[str, int]


def qa_report_paths(out_path: Path) -> tuple[Path, Path]:
    return (
        out_path.with_name(f"{out_path.name}.qa.json"),
        out_path.with_name(f"{out_path.name}.qa.txt"),
    )


def stem_from_tuid(tuid: str) -> str:
    if "-" not in tuid:
        return ""
    return tuid.rsplit("-", 1)[0]


def unit_record(unit: AlignmentUnit, reason: str | None = None) -> dict[str, Any]:
    record: dict[str, Any] = {
        "tuid": unit.tuid,
        "stem": stem_from_tuid(unit.tuid),
        "similarity": round(unit.similarity, 6),
        "score": round(unit.score, 6),
        "grouping": f"{unit.src_len}:{unit.tgt_len}",
        "src_chars": len(unit.src_text),
        "tgt_chars": len(unit.tgt_text),
        "src_text": unit.src_text,
        "tgt_text": unit.tgt_text,
    }
    if reason:
        record["reason"] = reason
    return record


def length_ratio(unit: AlignmentUnit) -> float:
    shorter = max(1, min(len(unit.src_text), len(unit.tgt_text)))
    longer = max(len(unit.src_text), len(unit.tgt_text))
    return longer / shorter


def add_sample(samples: list[dict[str, Any]], unit: AlignmentUnit, reason: str | None = None) -> None:
    if len(samples) < MAX_SAMPLES:
        samples.append(unit_record(unit, reason))


def make_category(description: str, count: int, samples: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "description": description,
        "count": count,
        "samples": samples,
    }


def build_qa_report(out_path: Path, units: list[AlignmentUnit], config: RunConfig) -> dict[str, Any]:
    low_similarity_samples: list[dict[str, Any]] = []
    numeric_mismatch_samples: list[dict[str, Any]] = []
    length_outlier_samples: list[dict[str, Any]] = []
    identical_text_samples: list[dict[str, Any]] = []
    short_side_samples: list[dict[str, Any]] = []

    low_similarity = 0
    numeric_pairs = 0
    numeric_mismatches = 0
    length_outliers = 0
    identical_text = 0
    short_side_units = 0

    source_targets: dict[str, Counter[str]] = defaultdict(Counter)
    target_sources: dict[str, Counter[str]] = defaultdict(Counter)
    low_similarity_by_stem: Counter[str] = Counter()
    length_outliers_by_stem: Counter[str] = Counter()
    short_side_by_stem: Counter[str] = Counter()

    for unit in units:
        stem = stem_from_tuid(unit.tuid)
        source_targets[unit.src_text][unit.tgt_text] += 1
        target_sources[unit.tgt_text][unit.src_text] += 1

        if unit.similarity < LOW_SIMILARITY_THRESHOLD:
            low_similarity += 1
            low_similarity_by_stem[stem] += 1
            add_sample(low_similarity_samples, unit, f"similarity below {LOW_SIMILARITY_THRESHOLD:.2f}")

        if is_numericish_text(unit.src_text) and is_numericish_text(unit.tgt_text):
            numeric_pairs += 1
            if digit_signature(unit.src_text) != digit_signature(unit.tgt_text):
                numeric_mismatches += 1
                add_sample(numeric_mismatch_samples, unit, "numeric-looking texts have different digit sequences")

        ratio = length_ratio(unit)
        if ratio >= LENGTH_RATIO_THRESHOLD and max(len(unit.src_text), len(unit.tgt_text)) >= LONG_TEXT_CHARS:
            length_outliers += 1
            length_outliers_by_stem[stem] += 1
            add_sample(length_outlier_samples, unit, f"length ratio {ratio:.2f}")

        if unit.src_text == unit.tgt_text:
            identical_text += 1
            add_sample(identical_text_samples, unit, "source and target text are identical")

        if len(unit.src_text) <= SHORT_TEXT_CHARS or len(unit.tgt_text) <= SHORT_TEXT_CHARS:
            short_side_units += 1
            short_side_by_stem[stem] += 1
            add_sample(short_side_samples, unit, f"one side has {SHORT_TEXT_CHARS} or fewer characters")

    source_conflicts = make_conflict_groups(source_targets, "source_text", "targets")
    target_conflicts = make_conflict_groups(target_sources, "target_text", "sources")

    summary = {
        "translation_units": len(units),
        "low_similarity_units": low_similarity,
        "numeric_like_units": numeric_pairs,
        "numeric_mismatch_units": numeric_mismatches,
        "length_ratio_outliers": length_outliers,
        "identical_source_target_units": identical_text,
        "short_side_units": short_side_units,
        "source_texts_with_multiple_targets": len(source_conflicts),
        "target_texts_with_multiple_sources": len(target_conflicts),
    }

    return {
        "output_tmx": str(out_path),
        "output_name": out_path.stem,
        "src_lang": config.src_lang,
        "tgt_lang": config.tgt_lang,
        "model": config.model,
        "thresholds": {
            "low_similarity": LOW_SIMILARITY_THRESHOLD,
            "short_text_chars": SHORT_TEXT_CHARS,
            "long_text_chars": LONG_TEXT_CHARS,
            "length_ratio": LENGTH_RATIO_THRESHOLD,
        },
        "summary": summary,
        "categories": {
            "low_similarity": make_category(
                "Units below the QA low-similarity threshold. These are not automatically wrong, but deserve review.",
                low_similarity,
                low_similarity_samples,
            ),
            "numeric_mismatches": make_category(
                "Pairs where both sides look numeric but their digit sequences differ.",
                numeric_mismatches,
                numeric_mismatch_samples,
            ),
            "length_ratio_outliers": make_category(
                "Pairs where one side is much longer than the other.",
                length_outliers,
                length_outlier_samples,
            ),
            "identical_source_target": make_category(
                "Pairs where source and target text are identical.",
                identical_text,
                identical_text_samples,
            ),
            "short_side": make_category(
                "Pairs where at least one side is very short.",
                short_side_units,
                short_side_samples,
            ),
            "source_text_multiple_targets": {
                "description": "Repeated source strings that aligned to more than one target string.",
                "count": len(source_conflicts),
                "groups": source_conflicts[:MAX_SAMPLES],
            },
            "target_text_multiple_sources": {
                "description": "Repeated target strings that aligned to more than one source string.",
                "count": len(target_conflicts),
                "groups": target_conflicts[:MAX_SAMPLES],
            },
        },
        "by_stem": {
            "low_similarity": counter_items(low_similarity_by_stem),
            "length_ratio_outliers": counter_items(length_outliers_by_stem),
            "short_side": counter_items(short_side_by_stem),
        },
    }


def make_conflict_groups(
    mapping: dict[str, Counter[str]],
    text_key: str,
    variants_key: str,
) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for text, variants in mapping.items():
        if len(variants) <= 1:
            continue
        groups.append(
            {
                text_key: text,
                "total_units": sum(variants.values()),
                "unique_variants": len(variants),
                variants_key: [
                    {"text": value, "count": count}
                    for value, count in variants.most_common(MAX_TEXT_REPORT_SAMPLES)
                ],
            }
        )
    groups.sort(key=lambda item: (item["total_units"], item["unique_variants"], item[text_key]), reverse=True)
    return groups


def counter_items(counter: Counter[str]) -> list[dict[str, Any]]:
    return [{"stem": stem, "count": count} for stem, count in counter.most_common()]


def write_qa_report(out_path: Path, units: list[AlignmentUnit], config: RunConfig) -> QaReportResult:
    json_path, text_path = qa_report_paths(out_path)
    report = build_qa_report(out_path, units, config)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    text_path.write_text(format_qa_text_report(report, json_path, text_path), encoding="utf-8")
    return QaReportResult(
        json_path=json_path,
        text_path=text_path,
        summary=dict(report["summary"]),
    )


def format_qa_text_report(report: dict[str, Any], json_path: Path, text_path: Path) -> str:
    summary = report["summary"]
    lines = [
        f"MEGAligner QA report for {report['output_name']}",
        "",
        f"TMX: {report['output_tmx']}",
        f"Text report: {text_path}",
        f"JSON report: {json_path}",
        "",
        "Summary",
        f"  translation units: {summary['translation_units']}",
        f"  low-similarity units (<{report['thresholds']['low_similarity']:.2f}): {summary['low_similarity_units']}",
        f"  numeric-looking mismatches: {summary['numeric_mismatch_units']}",
        f"  long/short length outliers: {summary['length_ratio_outliers']}",
        f"  identical source/target units: {summary['identical_source_target_units']}",
        f"  units with one very short side: {summary['short_side_units']}",
        f"  repeated source texts with multiple targets: {summary['source_texts_with_multiple_targets']}",
        f"  repeated target texts with multiple sources: {summary['target_texts_with_multiple_sources']}",
        "",
        "These are review signals only. MEGAligner did not remove these units from the TMX.",
    ]

    categories = report["categories"]
    add_sample_section(lines, "Low-Similarity Samples", categories["low_similarity"]["samples"])
    add_sample_section(lines, "Numeric Mismatch Samples", categories["numeric_mismatches"]["samples"])
    add_sample_section(lines, "Length Outlier Samples", categories["length_ratio_outliers"]["samples"])
    add_sample_section(lines, "Identical Source/Target Samples", categories["identical_source_target"]["samples"])
    add_conflict_section(lines, "Repeated Source With Multiple Targets", categories["source_text_multiple_targets"]["groups"], "source_text", "targets")
    add_conflict_section(lines, "Repeated Target With Multiple Sources", categories["target_text_multiple_sources"]["groups"], "target_text", "sources")
    return "\n".join(lines) + "\n"


def add_sample_section(lines: list[str], title: str, samples: list[dict[str, Any]]) -> None:
    if not samples:
        return
    lines.extend(["", title])
    for sample in samples[:MAX_TEXT_REPORT_SAMPLES]:
        lines.append(
            f"  {sample['stem']} {sample['grouping']} sim={sample['similarity']:.6f} "
            f"chars={sample['src_chars']}/{sample['tgt_chars']}"
        )
        lines.append(f"    {sample['src_text']}")
        lines.append(f"    => {sample['tgt_text']}")


def add_conflict_section(
    lines: list[str],
    title: str,
    groups: list[dict[str, Any]],
    text_key: str,
    variants_key: str,
) -> None:
    if not groups:
        return
    lines.extend(["", title])
    for group in groups[:MAX_TEXT_REPORT_SAMPLES]:
        lines.append(
            f"  {group['total_units']} uses / {group['unique_variants']} variants: {group[text_key]}"
        )
        for variant in group[variants_key][:4]:
            lines.append(f"    {variant['count']}x => {variant['text']}")


def format_qa_console_summary(result: QaReportResult) -> str:
    summary = result.summary
    return "\n".join(
        [
            "QA highlights",
            f"  report: {result.text_path}",
            f"  units reviewed: {summary['translation_units']}",
            f"  low-similarity units: {summary['low_similarity_units']}",
            f"  numeric-looking mismatches: {summary['numeric_mismatch_units']}",
            f"  long/short length outliers: {summary['length_ratio_outliers']}",
            f"  identical source/target units: {summary['identical_source_target_units']}",
            "  review the QA report before deciding whether any cleanup is needed",
        ]
    )
