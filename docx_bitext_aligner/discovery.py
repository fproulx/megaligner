from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

AUTO_PATTERN = "auto"
DEFAULT_PATTERN = AUTO_PATTERN


@dataclass(frozen=True)
class PairJob:
    stem: str
    src_path: Path
    tgt_path: Path
    out_path: Path


@dataclass(frozen=True)
class FileMatch:
    stem: str
    lang: str
    path: Path


@dataclass(frozen=True)
class DiscoveryResult:
    jobs: list[PairJob]
    unpaired: list[str] = field(default_factory=list)
    ignored: list[Path] = field(default_factory=list)
    duplicate_groups: list[str] = field(default_factory=list)
    fuzzy_pairs: list[str] = field(default_factory=list)
    scheme: str = "unknown"
    scheme_description: str = "unknown"
    total_docx: int = 0
    src_files: int = 0
    tgt_files: int = 0


def build_pattern_regex(pattern: str) -> re.Pattern[str]:
    if pattern.count("{stem}") != 1 or pattern.count("{lang}") != 1:
        raise ValueError("Pattern must contain exactly one {stem} and one {lang} placeholder")
    escaped = re.escape(pattern)
    escaped = escaped.replace(re.escape("{stem}"), r"(?P<stem>.+?)")
    escaped = escaped.replace(re.escape("{lang}"), r"(?P<lang>[A-Za-z0-9_-]+)")
    return re.compile(rf"^{escaped}$")


def lang_base(lang: str) -> str:
    return lang.lower().split("-")[0].split("_")[0]


def language_markers(lang: str) -> set[str]:
    base = lang_base(lang)
    markers = {lang.lower(), base}
    if base == "en":
        markers.update({"eng", "english"})
    if base == "ru":
        markers.update({"r", "rus", "russian"})
    return markers


def resolve_lang_marker(marker: str, config: object) -> Optional[str]:
    normalized = marker.lower()
    marker_base = lang_base(marker)
    src_lang = getattr(config, "src_lang")
    tgt_lang = getattr(config, "tgt_lang")
    src_key = src_lang.lower()
    tgt_key = tgt_lang.lower()
    src_markers = language_markers(src_lang)
    tgt_markers = language_markers(tgt_lang)
    if normalized in src_markers or marker_base in src_markers:
        return src_key
    if normalized in tgt_markers or marker_base in tgt_markers:
        return tgt_key
    return None


def iter_docx_files(input_dir: Path) -> list[Path]:
    return [
        path
        for path in sorted(input_dir.iterdir(), key=lambda p: p.name.lower())
        if path.is_file() and path.suffix.lower() == ".docx" and not path.name.startswith("~$")
    ]


def parse_pattern_match(path: Path, regex: re.Pattern[str], config: object) -> Optional[FileMatch]:
    match = regex.match(path.name)
    if not match:
        return None
    lang = resolve_lang_marker(match.group("lang"), config)
    if lang is None:
        return None
    return FileMatch(stem=match.group("stem"), lang=lang, path=path)


def parse_suffix_match(path: Path, delimiter: str, config: object) -> Optional[FileMatch]:
    stem, separator, marker = path.stem.rpartition(delimiter)
    if not separator or not stem:
        return None
    lang = resolve_lang_marker(marker, config)
    if lang is None:
        return None
    return FileMatch(stem=stem, lang=lang, path=path)


def parse_language_prefix_match(path: Path, delimiter: str, config: object) -> Optional[FileMatch]:
    marker, separator, stem = path.stem.partition(delimiter)
    if not separator or not stem:
        return None
    lang = resolve_lang_marker(marker, config)
    if lang is None:
        return None
    return FileMatch(stem=stem, lang=lang, path=path)


def parse_russian_prefix_match(path: Path, config: object) -> Optional[FileMatch]:
    src_lang = getattr(config, "src_lang")
    tgt_lang = getattr(config, "tgt_lang")
    src_key = src_lang.lower()
    tgt_key = tgt_lang.lower()
    if lang_base(src_lang) == "ru":
        russian_key = src_key
        unmarked_key = tgt_key
    elif lang_base(tgt_lang) == "ru":
        russian_key = tgt_key
        unmarked_key = src_key
    else:
        return None

    stem = path.stem
    if stem.lower().startswith("r") and len(stem) > 1:
        return FileMatch(stem=stem[1:], lang=russian_key, path=path)
    return FileMatch(stem=stem, lang=unmarked_key, path=path)


def clean_pair_stem(stem: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", stem.lower())


def normalized_stem_variants(stem: str) -> set[str]:
    variants: set[str] = set()
    seen: set[str] = set()
    stack = [stem.lower()]
    plain_suffixes = ("ri1", "ri", "r1", "b")
    separated_suffixes = ("_p1", "-p1", ".p1", "_0", "-0", ".0")

    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        cleaned = clean_pair_stem(current)
        if cleaned:
            variants.add(cleaned)
        for suffix in plain_suffixes:
            if current.endswith(suffix) and len(current) > len(suffix):
                stack.append(current[: -len(suffix)])
        for suffix in separated_suffixes:
            if current.endswith(suffix) and len(current) > len(suffix):
                stack.append(current[: -len(suffix)])
    return variants


def build_discovery_result(
    docx_files: list[Path],
    matches: list[FileMatch],
    ignored: list[Path],
    output_dir: Path,
    config: object,
    scheme: str,
    scheme_description: str,
) -> DiscoveryResult:
    by_stem: dict[str, dict[str, list[Path]]] = defaultdict(lambda: defaultdict(list))
    src_key = getattr(config, "src_lang").lower()
    tgt_key = getattr(config, "tgt_lang").lower()
    src_files = 0
    tgt_files = 0
    for match in matches:
        by_stem[match.stem][match.lang].append(match.path)
        if match.lang == src_key:
            src_files += 1
        elif match.lang == tgt_key:
            tgt_files += 1

    jobs: list[PairJob] = []
    unpaired: list[str] = []
    duplicate_groups: list[str] = []

    for stem, langs in sorted(by_stem.items(), key=lambda item: item[0].lower()):
        src_paths = sorted(langs.get(src_key, []), key=lambda p: p.name.lower())
        tgt_paths = sorted(langs.get(tgt_key, []), key=lambda p: p.name.lower())
        if len(src_paths) == 1 and len(tgt_paths) == 1:
            out_path = output_dir / f"{stem}.tmx"
            jobs.append(PairJob(stem=stem, src_path=src_paths[0], tgt_path=tgt_paths[0], out_path=out_path))
            continue

        if len(src_paths) > 1:
            names = ", ".join(path.name for path in src_paths)
            duplicate_groups.append(f"{stem}: multiple {getattr(config, 'src_lang')} candidates ({names})")
        if len(tgt_paths) > 1:
            names = ", ".join(path.name for path in tgt_paths)
            duplicate_groups.append(f"{stem}: multiple {getattr(config, 'tgt_lang')} candidates ({names})")
        if not src_paths:
            for path in tgt_paths:
                unpaired.append(f"{path.name}: missing {getattr(config, 'src_lang')}")
        if not tgt_paths:
            for path in src_paths:
                unpaired.append(f"{path.name}: missing {getattr(config, 'tgt_lang')}")

    return DiscoveryResult(
        jobs=jobs,
        unpaired=unpaired,
        ignored=ignored,
        duplicate_groups=duplicate_groups,
        scheme=scheme,
        scheme_description=scheme_description,
        total_docx=len(docx_files),
        src_files=src_files,
        tgt_files=tgt_files,
    )


def build_normalized_russian_prefix_result(
    docx_files: list[Path],
    matches: list[FileMatch],
    ignored: list[Path],
    output_dir: Path,
    config: object,
) -> DiscoveryResult:
    exact = build_discovery_result(
        docx_files=docx_files,
        matches=matches,
        ignored=ignored,
        output_dir=output_dir,
        config=config,
        scheme="russian-prefix-normalized",
        scheme_description="Russian DOCX files prefixed with R; normalized stem matching",
    )
    src_key = getattr(config, "src_lang").lower()
    tgt_key = getattr(config, "tgt_lang").lower()
    paired_src = {job.src_path for job in exact.jobs}
    paired_tgt = {job.tgt_path for job in exact.jobs}
    unmatched_src = [match for match in matches if match.lang == src_key and match.path not in paired_src]
    unmatched_tgt = [match for match in matches if match.lang == tgt_key and match.path not in paired_tgt]

    src_candidates: dict[Path, list[FileMatch]] = {match.path: [] for match in unmatched_src}
    tgt_candidates: dict[Path, list[FileMatch]] = {match.path: [] for match in unmatched_tgt}
    for src_match in unmatched_src:
        src_variants = normalized_stem_variants(src_match.stem)
        for tgt_match in unmatched_tgt:
            if src_variants & normalized_stem_variants(tgt_match.stem):
                src_candidates[src_match.path].append(tgt_match)
                tgt_candidates[tgt_match.path].append(src_match)

    fuzzy_jobs: list[PairJob] = []
    fuzzy_pairs: list[str] = []
    fuzzy_src_paths: set[Path] = set()
    fuzzy_tgt_paths: set[Path] = set()
    for src_match in sorted(unmatched_src, key=lambda item: item.path.name.lower()):
        candidates = src_candidates[src_match.path]
        if len(candidates) != 1:
            continue
        tgt_match = candidates[0]
        if len(tgt_candidates[tgt_match.path]) != 1:
            continue
        fuzzy_src_paths.add(src_match.path)
        fuzzy_tgt_paths.add(tgt_match.path)
        fuzzy_jobs.append(
            PairJob(
                stem=src_match.stem,
                src_path=src_match.path,
                tgt_path=tgt_match.path,
                out_path=output_dir / f"{src_match.stem}.tmx",
            )
        )
        fuzzy_pairs.append(f"{src_match.path.name} -> {tgt_match.path.name} (normalized stem)")

    unpaired: list[str] = []
    duplicate_groups: list[str] = list(exact.duplicate_groups)
    for match in sorted(unmatched_src, key=lambda item: item.path.name.lower()):
        if match.path not in fuzzy_src_paths:
            unpaired.append(f"{match.path.name}: missing {getattr(config, 'tgt_lang')}")
    for match in sorted(unmatched_tgt, key=lambda item: item.path.name.lower()):
        if match.path not in fuzzy_tgt_paths:
            unpaired.append(f"{match.path.name}: missing {getattr(config, 'src_lang')}")

    return replace(
        exact,
        jobs=sorted([*exact.jobs, *fuzzy_jobs], key=lambda job: job.stem.lower()),
        unpaired=unpaired,
        duplicate_groups=duplicate_groups,
        fuzzy_pairs=fuzzy_pairs,
    )


def score_discovery(result: DiscoveryResult) -> tuple[int, int, int, int]:
    problem_count = len(result.unpaired) + len(result.duplicate_groups) * 2
    return (len(result.jobs), result.src_files + result.tgt_files, -problem_count, -len(result.ignored))


def discover_pairs(input_dir: Path, output_dir: Path, config: object) -> DiscoveryResult:
    docx_files = iter_docx_files(input_dir)
    pattern = getattr(config, "pattern", DEFAULT_PATTERN)

    if pattern != AUTO_PATTERN:
        regex = build_pattern_regex(pattern)
        matches = []
        ignored = []
        for path in docx_files:
            match = parse_pattern_match(path, regex, config)
            if match is None:
                ignored.append(path)
            else:
                matches.append(match)
        return build_discovery_result(
            docx_files=docx_files,
            matches=matches,
            ignored=ignored,
            output_dir=output_dir,
            config=config,
            scheme="explicit-pattern",
            scheme_description=pattern,
        )

    candidates: list[DiscoveryResult] = []
    suffix_schemes = [
        ("suffix-dot", ".", "{stem}.{lang}.docx"),
        ("suffix-underscore", "_", "{stem}_{lang}.docx"),
        ("suffix-hyphen", "-", "{stem}-{lang}.docx"),
    ]
    for scheme, delimiter, description in suffix_schemes:
        matches = []
        ignored = []
        for path in docx_files:
            match = parse_suffix_match(path, delimiter, config)
            if match is None:
                ignored.append(path)
            else:
                matches.append(match)
        candidates.append(build_discovery_result(docx_files, matches, ignored, output_dir, config, scheme, description))

    prefix_schemes = [
        ("prefix-dot", ".", "{lang}.{stem}.docx"),
        ("prefix-underscore", "_", "{lang}_{stem}.docx"),
        ("prefix-hyphen", "-", "{lang}-{stem}.docx"),
    ]
    for scheme, delimiter, description in prefix_schemes:
        matches = []
        ignored = []
        for path in docx_files:
            match = parse_language_prefix_match(path, delimiter, config)
            if match is None:
                ignored.append(path)
            else:
                matches.append(match)
        candidates.append(build_discovery_result(docx_files, matches, ignored, output_dir, config, scheme, description))

    prefix_matches = []
    prefix_ignored = []
    for path in docx_files:
        match = parse_russian_prefix_match(path, config)
        if match is None:
            prefix_ignored.append(path)
        else:
            prefix_matches.append(match)
    if prefix_matches:
        candidates.append(
            build_discovery_result(
                docx_files=docx_files,
                matches=prefix_matches,
                ignored=prefix_ignored,
                output_dir=output_dir,
                config=config,
                scheme="russian-prefix",
                scheme_description="Russian DOCX files prefixed with R; other language unprefixed",
            )
        )
        candidates.append(
            build_normalized_russian_prefix_result(
                docx_files=docx_files,
                matches=prefix_matches,
                ignored=prefix_ignored,
                output_dir=output_dir,
                config=config,
            )
        )

    if not candidates:
        return DiscoveryResult(
            jobs=[],
            ignored=docx_files,
            scheme=AUTO_PATTERN,
            scheme_description="No supported naming scheme detected",
            total_docx=len(docx_files),
        )
    return max(candidates, key=score_discovery)
