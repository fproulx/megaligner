from __future__ import annotations

import argparse
import concurrent.futures
import sys
import time
import traceback
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Optional

from docx_bitext_aligner.alignment import align_prepared_windows, prepare_alignment_windows
from docx_bitext_aligner.config import PairProcessingError, RunConfig
from docx_bitext_aligner.discovery import DiscoveryResult, PairJob, discover_pairs
from docx_bitext_aligner.embedding import encode_texts, load_embedding_model
from docx_bitext_aligner.models import AlignmentUnit, PairAlignment, PairResult, PairWindows, SegmentWindow
from docx_bitext_aligner.qa import QaReportResult, format_qa_console_summary, write_qa_report
from docx_bitext_aligner.reports import write_combined_report, write_report
from docx_bitext_aligner.text import extract_docx_paragraphs, segment_paragraphs
from docx_bitext_aligner.tmx import TmxWriteStats, write_tmx
from docx_bitext_aligner.utils import format_duration, timed_call

_MODEL: Any | None = None
_WORKER_CONFIG: RunConfig | None = None


@dataclass
class PreparedCombinedPair:
    index: int
    job: PairJob
    pair_windows: PairWindows
    timings: dict[str, float]


def align_pair(
    src_path: Path,
    tgt_path: Path,
    stem: str,
    config: RunConfig,
    model: Any,
) -> PairAlignment:
    if not src_path.exists():
        raise PairProcessingError(f"Missing source file: {src_path}")
    if not tgt_path.exists():
        raise PairProcessingError(f"Missing target file: {tgt_path}")

    total_started = time.perf_counter()
    pair_windows, timings = prepare_pair_windows(src_path, tgt_path, config)
    src_window_count = len(pair_windows.src_windows)
    vectors = timed_call(
        timings,
        "encode",
        encode_texts,
        model,
        [window.text for window in [*pair_windows.src_windows, *pair_windows.tgt_windows]],
        config.batch_size,
    )
    src_vectors = vectors[:src_window_count]
    tgt_vectors = vectors[src_window_count:]
    units, dropped, alignment_timings, dp_full_retries = align_prepared_windows(
        pair_windows,
        stem,
        src_vectors,
        tgt_vectors,
        config,
    )
    timings.update(alignment_timings)
    timings["total"] = time.perf_counter() - total_started
    return PairAlignment(
        units=units,
        dropped=dropped,
        src_segments=pair_windows.src_segments,
        tgt_segments=pair_windows.tgt_segments,
        src_windows=len(pair_windows.src_windows),
        tgt_windows=len(pair_windows.tgt_windows),
        duplicate_window_texts=pair_windows.duplicate_window_texts,
        dp_full_retries=dp_full_retries,
        timings=timings,
    )


def prepare_pair_windows(src_path: Path, tgt_path: Path, config: RunConfig) -> tuple[PairWindows, dict[str, float]]:
    if not src_path.exists():
        raise PairProcessingError(f"Missing source file: {src_path}")
    if not tgt_path.exists():
        raise PairProcessingError(f"Missing target file: {tgt_path}")

    timings: dict[str, float] = {}
    src_paragraphs = timed_call(timings, "src_extract", extract_docx_paragraphs, src_path)
    tgt_paragraphs = timed_call(timings, "tgt_extract", extract_docx_paragraphs, tgt_path)
    if not src_paragraphs:
        raise PairProcessingError(f"Empty extracted text: {src_path}")
    if not tgt_paragraphs:
        raise PairProcessingError(f"Empty extracted text: {tgt_path}")

    src_segments = timed_call(timings, "src_segment", segment_paragraphs, src_paragraphs, config.src_lang)
    tgt_segments = timed_call(timings, "tgt_segment", segment_paragraphs, tgt_paragraphs, config.tgt_lang)
    pair_windows, window_timings = prepare_alignment_windows(src_segments, tgt_segments, config)
    timings.update(window_timings)
    return pair_windows, timings


def align_one_pair(
    src_path: Path,
    tgt_path: Path,
    out_path: Path,
    stem: str,
    config: RunConfig,
    model: Any,
) -> PairResult:
    if not src_path.exists():
        raise PairProcessingError(f"Missing source file: {src_path}")
    if not tgt_path.exists():
        raise PairProcessingError(f"Missing target file: {tgt_path}")
    if out_path.exists() and not config.force:
        return PairResult(stem=stem, status="skipped", out_path=out_path, reason="output exists")

    alignment = align_pair(src_path, tgt_path, stem, config, model)
    timings = dict(alignment.timings)
    write_result = timed_call(timings, "write_tmx", write_tmx, alignment.units, out_path, config)
    write_stats = write_result.stats
    qa_result = timed_call(timings, "write_qa_report", write_qa_report, out_path, write_result.units, config)
    if config.report:
        timed_call(
            timings,
            "write_report",
            write_report,
            out_path,
            stem,
            src_path,
            tgt_path,
            alignment.src_segments,
            alignment.tgt_segments,
            write_result.units,
            config,
        )

    return PairResult(
        stem=stem,
        status="succeeded",
        out_path=out_path,
        alignments=write_stats.written_units,
        raw_alignments=write_stats.input_units,
        dropped=alignment.dropped,
        duplicate_units=write_stats.duplicate_units,
        empty_units=write_stats.empty_units,
        normalized_units=write_stats.normalized_units,
        trivial_numeric_units=write_stats.trivial_numeric_units,
        src_segments=len(alignment.src_segments),
        tgt_segments=len(alignment.tgt_segments),
        src_windows=alignment.src_windows,
        tgt_windows=alignment.tgt_windows,
        duplicate_window_texts=alignment.duplicate_window_texts,
        dp_full_retries=alignment.dp_full_retries,
        qa_json_path=qa_result.json_path,
        qa_text_path=qa_result.text_path,
        qa_summary=qa_result.summary,
        timings=timings,
    )


def init_worker(config: RunConfig) -> None:
    global _MODEL, _WORKER_CONFIG
    _WORKER_CONFIG = config
    _MODEL = load_embedding_model(config)


def process_job(job: PairJob) -> PairResult:
    if _MODEL is None or _WORKER_CONFIG is None:
        raise RuntimeError("Worker was not initialized")
    try:
        return align_one_pair(job.src_path, job.tgt_path, job.out_path, job.stem, _WORKER_CONFIG, _MODEL)
    except Exception as exc:
        return PairResult(
            stem=job.stem,
            status="failed",
            out_path=job.out_path,
            reason=str(exc),
            traceback_text=traceback.format_exc(),
        )


def run_single_pair(args: argparse.Namespace, config: RunConfig) -> int:
    src_path = Path(args.pair[0])
    tgt_path = Path(args.pair[1])
    out_path = Path(args.pair[2])
    stem = out_path.stem
    if out_path.exists() and not config.force:
        result = PairResult(stem=stem, status="skipped", out_path=out_path, reason="output exists")
        print(format_pair_result(result))
        return 0
    try:
        model = load_embedding_model(config)
        result = align_one_pair(src_path, tgt_path, out_path, stem, config, model)
    except Exception as exc:
        print(f"FAILED {stem}: {exc}", file=sys.stderr)
        if config.verbosity >= 2:
            print(traceback.format_exc(), file=sys.stderr)
        return 1
    print(format_pair_result(result))
    qa_summary = format_pair_qa_summary(result)
    if qa_summary:
        print(qa_summary)
    if config.profile:
        print_profile([result])
    return 0


def should_skip_before_pool(job: PairJob, force: bool) -> Optional[PairResult]:
    if job.out_path.exists() and not force:
        return PairResult(stem=job.stem, status="skipped", out_path=job.out_path, reason="output exists")
    return None


def print_limited_section(title: str, lines: list[str], limit: int) -> None:
    if not lines:
        return
    print(title)
    shown = lines[:limit]
    for line in shown:
        print(f"  {line}")
    remaining = len(lines) - len(shown)
    if remaining > 0:
        print(f"  ... {remaining} more")


def format_pair_sample(job: PairJob) -> str:
    return f"{job.src_path.name} -> {job.tgt_path.name} => {job.out_path.name}"


def print_discovery_report(discovery: DiscoveryResult, config: RunConfig) -> None:
    print("Discovery summary")
    print(f"  scheme: {discovery.scheme_description}")
    print(f"  docx files: {discovery.total_docx}")
    print(f"  {config.src_lang} files: {discovery.src_files}")
    print(f"  {config.tgt_lang} files: {discovery.tgt_files}")
    print(f"  bitext pairs: {len(discovery.jobs)}")
    print(f"  unpaired files: {len(discovery.unpaired)}")
    print(f"  duplicate groups: {len(discovery.duplicate_groups)}")
    print(f"  normalized pairs: {len(discovery.fuzzy_pairs)}")
    print(f"  ignored docx files: {len(discovery.ignored)}")
    if discovery.total_docx % 2:
        print("  warning: odd number of DOCX files")
    if discovery.src_files != discovery.tgt_files:
        print(f"  warning: {config.src_lang}/{config.tgt_lang} file counts differ")

    sample_limit = max(0, config.sample_size)
    if sample_limit:
        samples = [format_pair_sample(job) for job in discovery.jobs[:sample_limit]]
        print_limited_section("Sample mappings", samples, sample_limit)
    print_limited_section("Unpaired files", discovery.unpaired, sample_limit)
    print_limited_section("Normalized pair matches", discovery.fuzzy_pairs, sample_limit)
    print_limited_section("Duplicate language groups", discovery.duplicate_groups, sample_limit)
    ignored_lines = [path.name for path in discovery.ignored]
    print_limited_section("Ignored DOCX files", ignored_lines, sample_limit)


def discovery_has_warnings(discovery: DiscoveryResult) -> bool:
    return (
        discovery.total_docx % 2 == 1
        or discovery.src_files != discovery.tgt_files
        or bool(discovery.unpaired)
        or bool(discovery.duplicate_groups)
        or bool(discovery.fuzzy_pairs)
        or bool(discovery.ignored)
    )


def confirm_discovery(discovery: DiscoveryResult, config: RunConfig) -> bool:
    if config.yes:
        return True
    if not discovery.jobs:
        return False
    if not sys.stdin.isatty():
        print("Discovery requires confirmation. Re-run with --yes after validating the mapping.", file=sys.stderr)
        return False
    suffix = " despite the warnings" if discovery_has_warnings(discovery) else ""
    answer = input(f"Proceed with {len(discovery.jobs)} bitext pair(s){suffix}? [y/N] ")
    return answer.strip().lower() in {"y", "yes"}


def discovery_with_output(discovery: DiscoveryResult, output_path: Path) -> DiscoveryResult:
    return replace(
        discovery,
        jobs=[
            PairJob(
                stem=job.stem,
                src_path=job.src_path,
                tgt_path=job.tgt_path,
                out_path=output_path,
            )
            for job in discovery.jobs
        ],
    )


def unique_window_texts(prepared_pairs: list[PreparedCombinedPair]) -> tuple[list[str], dict[str, int], int]:
    unique_texts: list[str] = []
    indexes: dict[str, int] = {}
    total = 0
    for prepared in prepared_pairs:
        for window in [*prepared.pair_windows.src_windows, *prepared.pair_windows.tgt_windows]:
            total += 1
            if window.text not in indexes:
                indexes[window.text] = len(unique_texts)
                unique_texts.append(window.text)
    return unique_texts, indexes, total


def vectors_for_windows(vectors: Any, indexes: dict[str, int], windows: list[SegmentWindow]) -> Any:
    import numpy as np

    vector_indexes = np.asarray([indexes[window.text] for window in windows], dtype=np.int64)
    return vectors[vector_indexes]


def model_embedding_dimension(model: Any) -> int:
    for method_name in ("get_embedding_dimension", "get_sentence_embedding_dimension"):
        getter = getattr(model, method_name, None)
        if callable(getter):
            dimension = getter()
            if dimension:
                return int(dimension)
    return 768


def embedding_vector_cache_mb(unique_text_count: int, embedding_dimension: int) -> float:
    return unique_text_count * embedding_dimension * 4 / (1024 * 1024)


def should_use_global_embedding(unique_text_count: int, embedding_dimension: int, max_mb: int) -> bool:
    return max_mb > 0 and embedding_vector_cache_mb(unique_text_count, embedding_dimension) <= max_mb


def timing_subtotal(timings: dict[str, float]) -> float:
    return sum(seconds for key, seconds in timings.items() if key != "total")


def align_prepared_pair(
    prepared: PreparedCombinedPair,
    config: RunConfig,
    model: Any,
    output_path: Path,
    global_vectors: Any | None = None,
    text_indexes: dict[str, int] | None = None,
) -> tuple[PairResult, list[AlignmentUnit]]:
    job = prepared.job
    timings = dict(prepared.timings)
    if global_vectors is None:
        src_window_count = len(prepared.pair_windows.src_windows)
        vectors = timed_call(
            timings,
            "encode",
            encode_texts,
            model,
            [window.text for window in [*prepared.pair_windows.src_windows, *prepared.pair_windows.tgt_windows]],
            config.batch_size,
        )
        src_vectors = vectors[:src_window_count]
        tgt_vectors = vectors[src_window_count:]
    else:
        if text_indexes is None:
            raise PairProcessingError("Global vectors were supplied without text indexes")
        src_vectors = vectors_for_windows(global_vectors, text_indexes, prepared.pair_windows.src_windows)
        tgt_vectors = vectors_for_windows(global_vectors, text_indexes, prepared.pair_windows.tgt_windows)

    units, dropped, alignment_timings, dp_full_retries = align_prepared_windows(
        prepared.pair_windows,
        job.stem,
        src_vectors,
        tgt_vectors,
        config,
    )
    timings.update(alignment_timings)
    timings["total"] = timing_subtotal(timings)
    return (
        PairResult(
            stem=job.stem,
            status="succeeded",
            out_path=output_path,
            alignments=len(units),
            raw_alignments=len(units),
            dropped=dropped,
            tmx_units_final=False,
            src_segments=len(prepared.pair_windows.src_segments),
            tgt_segments=len(prepared.pair_windows.tgt_segments),
            src_windows=len(prepared.pair_windows.src_windows),
            tgt_windows=len(prepared.pair_windows.tgt_windows),
            duplicate_window_texts=prepared.pair_windows.duplicate_window_texts,
            dp_full_retries=dp_full_retries,
            timings=timings,
        ),
        units,
    )


def run_combined_batch(discovery: DiscoveryResult, config: RunConfig, output_path: Path) -> int:
    if output_path.exists() and not config.force:
        print(f"Combined output exists: {output_path}", file=sys.stderr)
        print("Use --force to overwrite it.", file=sys.stderr)
        return 2

    from tqdm import tqdm

    model = load_embedding_model(config)
    combined_timings: dict[str, float] = {}
    all_units: list[AlignmentUnit] = []
    results_by_index: list[PairResult | None] = [None] * len(discovery.jobs)
    prepared_pairs: list[PreparedCombinedPair] = []

    with tqdm(total=len(discovery.jobs), unit="pair", desc="Preparing", disable=not sys.stderr.isatty()) as progress:
        for index, job in enumerate(discovery.jobs):
            try:
                pair_windows, timings = prepare_pair_windows(job.src_path, job.tgt_path, config)
                prepared_pairs.append(
                    PreparedCombinedPair(
                        index=index,
                        job=job,
                        pair_windows=pair_windows,
                        timings=timings,
                    )
                )
            except Exception as exc:
                results_by_index[index] = PairResult(
                    stem=job.stem,
                    status="failed",
                    out_path=output_path,
                    reason=str(exc),
                    traceback_text=traceback.format_exc(),
                )
            status = "failed" if results_by_index[index] is not None else "prepared"
            progress.set_postfix_str(f"{status} {job.stem}")
            progress.update(1)
            if config.verbosity >= 1 and results_by_index[index] is not None:
                tqdm.write(format_pair_result(results_by_index[index]), file=sys.stderr)

    unique_texts, text_indexes, total_window_texts = unique_window_texts(prepared_pairs)
    embedding_dimension = model_embedding_dimension(model)
    global_vector_cache_mb = embedding_vector_cache_mb(len(unique_texts), embedding_dimension)
    use_global_embedding = should_use_global_embedding(
        len(unique_texts),
        embedding_dimension,
        config.global_embedding_max_mb,
    )
    global_vectors = None
    if use_global_embedding:
        global_vectors = timed_call(
            combined_timings,
            "encode",
            encode_texts,
            model,
            unique_texts,
            config.batch_size,
        )
    global_duplicate_window_texts = total_window_texts - len(unique_texts)

    with tqdm(total=len(prepared_pairs), unit="pair", desc="Aligning", disable=not sys.stderr.isatty()) as progress:
        for prepared in prepared_pairs:
            try:
                result, units = align_prepared_pair(
                    prepared,
                    config,
                    model,
                    output_path,
                    global_vectors,
                    text_indexes if use_global_embedding else None,
                )
                all_units.extend(units)
            except Exception as exc:
                result = PairResult(
                    stem=prepared.job.stem,
                    status="failed",
                    out_path=output_path,
                    reason=str(exc),
                    traceback_text=traceback.format_exc(),
                )
            results_by_index[prepared.index] = result
            progress.set_postfix_str(f"{result.status} {result.stem}")
            progress.update(1)
            if config.verbosity >= 1:
                tqdm.write(format_pair_result(result), file=sys.stderr)

    results = [result for result in results_by_index if result is not None]
    failed = [result for result in results if result.status == "failed"]
    if failed:
        print_summary(results, discovery)
        print("Combined TMX was not written because at least one pair failed.", file=sys.stderr)
        return 1
    if not all_units:
        print_summary(results, discovery)
        print("Combined TMX was not written because no translation units were produced.", file=sys.stderr)
        return 1

    write_result = timed_call(combined_timings, "write_combined_tmx", write_tmx, all_units, output_path, config)
    write_stats = write_result.stats
    qa_result = timed_call(combined_timings, "write_qa_report", write_qa_report, output_path, write_result.units, config)
    if config.report:
        timed_call(
            combined_timings,
            "write_combined_report",
            write_combined_report,
            output_path,
            results,
            discovery,
            config,
            write_stats,
        )
    print_summary(results, discovery)
    print_tmx_write_stats(write_stats)
    print(format_qa_console_summary(qa_result))
    if config.profile:
        print_global_embedding_profile(
            total_window_texts,
            len(unique_texts),
            global_duplicate_window_texts,
            embedding_dimension,
            global_vector_cache_mb,
            use_global_embedding,
            config.global_embedding_max_mb,
        )
        print_profile(results, combined_timings)
    print(f"Combined TMX: {output_path}")
    return 0


def run_batch(args: argparse.Namespace, config: RunConfig) -> int:
    input_dir = Path(args.input_dir)
    output_dir = Path(args.output_dir)
    if not input_dir.is_dir():
        print(f"Input directory not found: {input_dir}", file=sys.stderr)
        return 2

    discovery = discover_pairs(input_dir, output_dir, config)
    single_output = Path(args.single_output) if args.single_output else None
    combined_output = Path(args.combined_output) if args.combined_output else None
    if single_output is not None and combined_output is not None:
        print("Use only one of --single-output or --combined-output.", file=sys.stderr)
        return 2
    if single_output is not None and len(discovery.jobs) == 1:
        only_job = discovery.jobs[0]
        discovery = replace(
            discovery,
            jobs=[
                PairJob(
                    stem=single_output.stem,
                    src_path=only_job.src_path,
                    tgt_path=only_job.tgt_path,
                    out_path=single_output,
                )
            ],
        )
    if combined_output is not None:
        discovery = discovery_with_output(discovery, combined_output)
    if config.dry_run or not getattr(args, "suppress_discovery_report", False):
        print_discovery_report(discovery, config)
    if single_output is not None and len(discovery.jobs) != 1:
        print(
            f"--single-output requires exactly one complete bitext pair; detected {len(discovery.jobs)}.",
            file=sys.stderr,
        )
        print("Use batch mode with an output directory for multi-pair corpora.", file=sys.stderr)
        return 2
    if not discovery.jobs:
        print("No complete bitext pairs were detected.", file=sys.stderr)
        return 2
    if config.dry_run:
        return 0
    if not confirm_discovery(discovery, config):
        print("Aborted before loading the embedding model.", file=sys.stderr)
        return 2
    if combined_output is not None:
        combined_output.parent.mkdir(parents=True, exist_ok=True)
        return run_combined_batch(discovery, config, combined_output)
    output_dir.mkdir(parents=True, exist_ok=True)

    skipped: list[PairResult] = []
    jobs: list[PairJob] = []
    for job in discovery.jobs:
        skip = should_skip_before_pool(job, config.force)
        if skip:
            skipped.append(skip)
        else:
            jobs.append(job)

    results: list[PairResult] = list(skipped)
    if jobs:
        from tqdm import tqdm

        if config.workers == 1:
            model = load_embedding_model(config)
            with tqdm(total=len(jobs), unit="pair", desc="Aligning", disable=not sys.stderr.isatty()) as progress:
                for job in jobs:
                    try:
                        result = align_one_pair(job.src_path, job.tgt_path, job.out_path, job.stem, config, model)
                    except Exception as exc:
                        result = PairResult(
                            stem=job.stem,
                            status="failed",
                            out_path=job.out_path,
                            reason=str(exc),
                            traceback_text=traceback.format_exc(),
                        )
                    results.append(result)
                    progress.set_postfix_str(f"{result.status} {result.stem}")
                    progress.update(1)
                    if config.verbosity >= 1:
                        tqdm.write(format_pair_result(result), file=sys.stderr)
        else:
            with concurrent.futures.ProcessPoolExecutor(
                max_workers=config.workers,
                initializer=init_worker,
                initargs=(config,),
            ) as executor:
                future_to_job = {executor.submit(process_job, job): job for job in jobs}
                with tqdm(total=len(jobs), unit="pair", desc="Aligning", disable=not sys.stderr.isatty()) as progress:
                    for future in concurrent.futures.as_completed(future_to_job):
                        job = future_to_job[future]
                        try:
                            result = future.result()
                        except Exception as exc:
                            result = PairResult(
                                stem=job.stem,
                                status="failed",
                                out_path=job.out_path,
                                reason=str(exc),
                                traceback_text=traceback.format_exc(),
                            )
                        results.append(result)
                        progress.set_postfix_str(f"{result.status} {result.stem}")
                        progress.update(1)
                        if config.verbosity >= 1:
                            tqdm.write(format_pair_result(result), file=sys.stderr)

    print_summary(results, discovery)
    if config.profile:
        print_profile(results)
    if any(result.status == "failed" for result in results):
        return 1
    return 0


def format_pair_result(result: PairResult) -> str:
    if result.status == "succeeded":
        if not result.tmx_units_final:
            return (
                f"OK {result.stem}: {result.units_before_tmx_cleanup} aligned units before TMX cleanup, "
                f"src={result.src_segments}, tgt={result.tgt_segments}, dropped={result.dropped}"
            )
        message = (
            f"OK {result.stem}: {result.alignments} TUs, "
            f"src={result.src_segments}, tgt={result.tgt_segments}, dropped={result.dropped}"
        )
        if result.duplicate_units:
            message += f", duplicates removed={result.duplicate_units}"
        if result.empty_units:
            message += f", empty skipped={result.empty_units}"
        if result.trivial_numeric_units:
            message += f", trivial numeric skipped={result.trivial_numeric_units}"
        return message
    if result.status == "skipped":
        return f"SKIPPED {result.stem}: {result.reason or 'not processed'}"
    return f"FAILED {result.stem}: {result.reason or 'unknown error'}"


def format_pair_qa_summary(result: PairResult) -> str | None:
    if result.status != "succeeded" or not result.qa_json_path or not result.qa_text_path or not result.qa_summary:
        return None
    return format_qa_console_summary(
        QaReportResult(
            json_path=result.qa_json_path,
            text_path=result.qa_text_path,
            summary=result.qa_summary,
        )
    )


def print_summary(results: list[PairResult], discovery: DiscoveryResult) -> None:
    succeeded = [result for result in results if result.status == "succeeded"]
    skipped = [result for result in results if result.status == "skipped"]
    failed = [result for result in results if result.status == "failed"]
    print("Batch summary")
    print(f"  total pairs: {len(discovery.jobs)}")
    print(f"  succeeded: {len(succeeded)}")
    print(f"  skipped: {len(skipped)}")
    print(f"  failed: {len(failed)}")
    print(f"  unpaired files: {len(discovery.unpaired)}")
    raw_units = sum(result.units_before_tmx_cleanup for result in succeeded)
    if raw_units:
        print(f"  aligned units before TMX cleanup: {raw_units}")
    dropped = sum(result.dropped for result in succeeded)
    if dropped:
        print(f"  low-similarity units filtered: {dropped}")
    duplicate_units = sum(result.duplicate_units for result in succeeded)
    if duplicate_units:
        print(f"  duplicate units removed: {duplicate_units}")
    empty_units = sum(result.empty_units for result in succeeded)
    if empty_units:
        print(f"  empty units skipped: {empty_units}")
    trivial_numeric_units = sum(result.trivial_numeric_units for result in succeeded)
    if trivial_numeric_units:
        print(f"  trivial numeric units skipped: {trivial_numeric_units}")
    if failed:
        print("Failures")
        for result in failed:
            print(f"  {result.stem}: {result.reason or 'unknown error'}")
    if discovery.unpaired:
        print("Unpaired files")
        for item in discovery.unpaired:
            print(f"  {item}")


def print_tmx_write_stats(stats: TmxWriteStats) -> None:
    print("TMX output")
    print(f"  input units: {stats.input_units}")
    print(f"  written units: {stats.written_units}")
    if stats.duplicate_units:
        print(f"  duplicate units removed: {stats.duplicate_units}")
    if stats.empty_units:
        print(f"  empty units skipped: {stats.empty_units}")
    if stats.normalized_units:
        print(f"  whitespace-normalized units: {stats.normalized_units}")
    if stats.trivial_numeric_units:
        print(f"  trivial numeric units skipped: {stats.trivial_numeric_units}")


def print_global_embedding_profile(
    total_window_texts: int,
    unique_window_texts_count: int,
    duplicate_window_texts: int,
    embedding_dimension: int,
    vector_cache_mb: float,
    used_global_embedding: bool,
    max_mb: int,
) -> None:
    print("Global embedding")
    print(f"  window texts: {total_window_texts}")
    print(f"  unique window texts: {unique_window_texts_count}")
    print(f"  duplicate window texts: {duplicate_window_texts}")
    print(f"  embedding dimension: {embedding_dimension}")
    print(f"  estimated vector cache: {vector_cache_mb:.1f} MB")
    if used_global_embedding:
        print("  mode: global corpus dedupe")
    elif max_mb == 0:
        print("  mode: pair-local fallback (--global-embedding-max-mb=0)")
    else:
        print(f"  mode: pair-local fallback (global cache would exceed {max_mb} MB)")


def print_profile(results: list[PairResult], extra_timings: Optional[dict[str, float]] = None) -> None:
    succeeded = [result for result in results if result.status == "succeeded"]
    if not succeeded:
        return

    profile_keys = [
        "src_extract",
        "tgt_extract",
        "src_segment",
        "tgt_segment",
        "src_windows",
        "tgt_windows",
        "encode",
        "similarity_matrix",
        "dp",
        "dp_full_retry",
        "postprocess",
        "write_tmx",
        "write_qa_report",
    ]
    totals = {key: sum(result.timings.get(key, 0.0) for result in succeeded) for key in profile_keys}
    pair_total = sum(result.timings.get("total", 0.0) for result in succeeded)
    print("Profile summary")
    print(f"  pair time total: {format_duration(pair_total)}")
    print(f"  pair time average: {format_duration(pair_total / len(succeeded))}")
    print(f"  src/tgt segments: {sum(result.src_segments for result in succeeded)} / {sum(result.tgt_segments for result in succeeded)}")
    print(f"  src/tgt windows: {sum(result.src_windows for result in succeeded)} / {sum(result.tgt_windows for result in succeeded)}")
    duplicate_window_texts = sum(result.duplicate_window_texts for result in succeeded)
    if duplicate_window_texts:
        print(f"  duplicate window texts: {duplicate_window_texts}")
    dp_full_retries = sum(result.dp_full_retries for result in succeeded)
    if dp_full_retries:
        print(f"  full DP retries after band miss: {dp_full_retries}")
    for key in profile_keys:
        if totals[key] > 0:
            print(f"  {key}: {format_duration(totals[key])}")
    if extra_timings:
        for key, seconds in extra_timings.items():
            print(f"  {key}: {format_duration(seconds)}")

    slowest = sorted(succeeded, key=lambda result: result.timings.get("total", 0.0), reverse=True)[:5]
    if slowest:
        print("Slowest pairs")
        for result in slowest:
            print(
                f"  {result.stem}: {format_duration(result.timings.get('total', 0.0))}, "
                f"segments={result.src_segments}/{result.tgt_segments}, "
                f"windows={result.src_windows}/{result.tgt_windows}"
            )
