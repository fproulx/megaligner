from __future__ import annotations

import argparse
import sys
from typing import Optional

from docx_bitext_aligner.config import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_MAX_GROUP,
    DEFAULT_MIN_SIMILARITY,
    DEFAULT_MODEL,
    DEFAULT_SAMPLE_SIZE,
    DEFAULT_SIMILARITY_MATRIX_MAX_MB,
    DEFAULT_SRC_LANG,
    DEFAULT_TGT_LANG,
    TOOL_NAME,
    RunConfig,
    default_workers,
    validate_config,
)
from docx_bitext_aligner.discovery import AUTO_PATTERN, DEFAULT_PATTERN
from docx_bitext_aligner.runner import run_batch, run_single_pair


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog=TOOL_NAME,
        description="Align paired English and Russian DOCX files into TMX 1.4 translation memories.",
    )
    parser.add_argument("input_dir", nargs="?", help="Directory containing paired DOCX files")
    parser.add_argument("output_dir", nargs="?", help="Directory where TMX files will be written")
    parser.add_argument("--pair", nargs=3, metavar=("SRC_DOCX", "TGT_DOCX", "OUT_TMX"), help="Process one pair")
    parser.add_argument(
        "--pattern",
        default=DEFAULT_PATTERN,
        help=f"Naming scheme. Use {AUTO_PATTERN!r} to detect supported schemes, default {DEFAULT_PATTERN!r}",
    )
    parser.add_argument("--src-lang", default=DEFAULT_SRC_LANG, help=f"Source language, default {DEFAULT_SRC_LANG!r}")
    parser.add_argument("--tgt-lang", default=DEFAULT_TGT_LANG, help=f"Target language, default {DEFAULT_TGT_LANG!r}")
    parser.add_argument("--workers", type=int, default=default_workers(), help="Parallel workers. Each worker loads one embedding model")
    parser.add_argument("--force", action="store_true", help="Reprocess pairs even when the output TMX exists")
    parser.add_argument(
        "--min-similarity",
        type=float,
        default=DEFAULT_MIN_SIMILARITY,
        help=f"Drop translation units below this embedding similarity, default {DEFAULT_MIN_SIMILARITY}",
    )
    parser.add_argument("--no-similarity-filter", action="store_true", help="Keep low-similarity units in the TMX output")
    parser.add_argument("--report", action="store_true", help="Write a sidecar JSON report for each processed pair")
    parser.add_argument("--yes", action="store_true", help="Accept the detected pair mapping without an interactive prompt")
    parser.add_argument("--dry-run", action="store_true", help="Only print the detected pair mapping and exit")
    parser.add_argument("--suppress-discovery-report", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--profile", action="store_true", help="Print per-stage timing totals after alignment")
    parser.add_argument("--sample-size", type=int, default=DEFAULT_SAMPLE_SIZE, help="Number of sample mappings and warnings to show")
    parser.add_argument(
        "--single-output",
        metavar="OUT_TMX",
        help="Batch mode only: require exactly one detected pair and write it to this TMX file",
    )
    parser.add_argument(
        "--combined-output",
        metavar="OUT_TMX",
        help="Batch mode only: align every detected pair and write one combined TMX file",
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="SentenceTransformer model id or local model path")
    parser.add_argument("--allow-model-download", action="store_true", help="Allow model file downloads when the model is not cached")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE, help="Embedding batch size")
    parser.add_argument("--max-group", type=int, default=DEFAULT_MAX_GROUP, help="Maximum m or n size for grouped alignments")
    parser.add_argument("--band", type=int, default=None, help="Alignment band width. Use 0 for full matrix")
    parser.add_argument(
        "--similarity-matrix-max-mb",
        type=int,
        default=DEFAULT_SIMILARITY_MATRIX_MAX_MB,
        help=f"Maximum per-pair similarity matrix size in MB; 0 disables precompute, default {DEFAULT_SIMILARITY_MATRIX_MAX_MB}",
    )
    parser.add_argument("--device", choices=["auto", "cpu", "cuda", "mps"], default="auto", help="Embedding device")
    parser.add_argument(
        "--keep-trivial-numeric-units",
        action="store_true",
        help="Keep standalone numeric-only translation units such as 182.22 -> 182,22",
    )
    parser.add_argument("-v", "--verbose", action="count", default=0, help="Increase verbosity")
    return parser.parse_args(argv)


def make_config(args: argparse.Namespace) -> RunConfig:
    config = RunConfig(
        src_lang=args.src_lang,
        tgt_lang=args.tgt_lang,
        pattern=args.pattern,
        workers=args.workers,
        force=args.force,
        min_similarity=None if args.no_similarity_filter else args.min_similarity,
        report=args.report,
        verbosity=args.verbose,
        yes=args.yes,
        dry_run=args.dry_run,
        profile=args.profile,
        device=args.device,
        sample_size=args.sample_size,
        model=args.model,
        allow_model_download=args.allow_model_download,
        batch_size=args.batch_size,
        max_group=args.max_group,
        band=args.band,
        keep_trivial_numeric_units=args.keep_trivial_numeric_units,
        similarity_matrix_max_mb=args.similarity_matrix_max_mb,
    )
    validate_config(config)
    return config


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    try:
        config = make_config(args)
    except Exception as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2

    if args.pair:
        return run_single_pair(args, config)

    if not args.input_dir or not args.output_dir:
        print("Batch mode requires input_dir and output_dir", file=sys.stderr)
        return 2
    return run_batch(args, config)


if __name__ == "__main__":
    raise SystemExit(main())
