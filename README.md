# MEGAligner

Create a TMX translation memory from paired English and Russian DOCX files.

MEGAligner is designed for United Nations (UN) translation and bitext alignment workflows. A typical source is a UN-style document repository such as the Multilateral Fund's [97th Meeting pre-session documents](https://www.multilateralfund.org/meetings/97/pre-session), but it is not limited to that site.

## Quick Start on Mac

Recommended workflow for translators on Apple Silicon Macs:

1. Go to https://github.com/fproulx/megaligner
2. Click **Code** -> **Download ZIP**
3. Unzip the download
4. Download the source DOCX files from the document repository
5. Put all English and Russian `.docx` files together in one folder
6. Open `Align.command`
7. Choose the folder containing the DOCX files
8. Choose where to save the output `.tmx` file
9. Review the detected document pairs
10. Click **Align** when the preview looks right

For example, on the Multilateral Fund [97th Meeting pre-session page](https://www.multilateralfund.org/meetings/97/pre-session), use **Download All Files**, then put the English and Russian DOCX files in one folder. The folder can be inside the unzipped `megaligner` folder, such as `documents/`, or anywhere else on the Mac.

The launcher opens Terminal only to show progress and errors. No commands need to be typed.

The first time only, macOS may show `"Align.command" Not Opened` because the ZIP was downloaded from the internet. Click **Done**, then in Finder hold **Control** and click `Align.command`, choose **Open**, and confirm. After that first approval, normal double-clicking should work.

If macOS still does not show an **Open** button, open **System Settings** -> **Privacy & Security**, scroll to the security message for `Align.command`, click **Open Anyway**, then open `Align.command` again.

## First Run

The first run takes longer because MEGAligner sets itself up and downloads the language model it uses for alignment. Terminal will show status messages and progress while this happens. The first large download can take a short while to appear.

Everything is kept inside the unzipped MEGAligner folder, so later runs are faster and do not need to download the same files again.

MEGAligner does not ask for an administrator password and does not change Mac system settings.

## Pair Preview

Before alignment starts, MEGAligner scans the folder, detects likely English/Russian pairs, and shows a preview like this:

```text
Discovery summary
  scheme: Russian DOCX files prefixed with R; normalized stem matching
  docx files: 204
  en files: 104
  ru files: 100
  bitext pairs: 99
  unpaired files: 6
Sample mappings
  9701.docx -> R9701.docx => aligned.tmx
  9701a1.docx -> R9701a1.docx => aligned.tmx
Unpaired files
  9766.docx: missing ru
  R9790.docx: missing en
```

If there are unpaired files, odd file counts, duplicate candidates, or ignored DOCX files, the preview says so before any model is loaded. This is the checkpoint for confirming that the folder contents make sense.

## Terminal Use

Double-clicking `Align.command` is the simplest Mac workflow. The same flow is also available from Terminal:

```bash
make align
```

On macOS this opens native dialogs for the input DOCX folder and output TMX filename.

You can also pass paths directly:

```bash
make align /absolute/path/to/docx-folder /absolute/path/to/output.tmx
```

For paths containing spaces, use variables:

```bash
make align DIR="/absolute/path/with spaces/docx-folder" OUT="/absolute/path/out file.tmx"
```

Useful options:

```bash
make align DIR=/corpus OUT=/tmx/result.tmx DRY_RUN=1
make align DIR=/corpus OUT=/tmx/result.tmx WORKERS=2
make align DIR=/corpus OUT=/tmx/result.tmx PROFILE=1
make align DIR=/corpus OUT=/tmx/result.tmx ALIGN_ARGS="--min-similarity 0.55"
make align DIR=/corpus OUT=/tmx/result.tmx ALIGN_ARGS="--no-similarity-filter"
make align DIR=/corpus OUT=/tmx/result.tmx ALIGN_ARGS="--keep-trivial-numeric-units"
make align DIR=/corpus OUT=/tmx/result.tmx ALIGN_ARGS="--src-lang en --tgt-lang ru --pattern auto"
```

`make align` writes one combined TMX file containing every successfully aligned pair in the selected directory.

## Output Quality

MEGAligner prepares the TMX as a translation memory, not as a raw dump of every aligned row. Before writing the file, it trims and normalizes whitespace, removes exact duplicate English/Russian segment pairs, skips empty entries, skips standalone numeric-only pairs such as `182.22 -> 182,22`, and filters very low-similarity alignments by default.

The default similarity threshold is `0.45`, which removes obvious mismatches while keeping normal sentence and table alignments. To be stricter, pass for example `ALIGN_ARGS="--min-similarity 0.55"`. To keep low-similarity entries, pass `ALIGN_ARGS="--no-similarity-filter"`. To keep standalone numeric-only entries, pass `ALIGN_ARGS="--keep-trivial-numeric-units"`.

This default was checked against a small Multilateral Fund 97th Meeting EN/RU sample using LaBSE scores and shuffled-target negative controls. In that sample, `0.45` removed about 1 percent of aligned units; the lowest removed examples were document-code/date and front-matter mismatches. Raising the threshold to `0.55` removed more false positives but also started dropping useful short table labels such as `Background`, `Other`, and `Description`.

For combined TMX output, exact duplicates are kept once across the whole corpus. That is usually what translators want from a translation memory, but it means the final TMX is not a document-by-document provenance record.

At the end of a run, the `TMX output` summary is the authoritative final count. It reports how many low-similarity units were filtered, how many duplicates were removed, and how many translation units were written.

For speed, combined TMX output embeds repeated text only once across the selected folder. This is useful for UN-style corpora with repeated headers, table labels, and boilerplate. Very large corpora automatically fall back to a lower-memory path; advanced users can force that comparison with `ALIGN_ARGS="--global-embedding-max-mb 0"`.

MEGAligner also writes QA side reports next to the TMX file. For `aligned.tmx`, the reports are:

```text
aligned.tmx.qa.txt
aligned.tmx.qa.json
```

The text report is meant for quick review. It highlights suspicious-but-not-automatically-wrong units, such as numeric mismatches, very short/long alignments, identical source/target text, and low-similarity samples. The same compact QA summary is printed at the end of the run. MEGAligner does not remove those highlighted units from the TMX.

## Supported Naming Schemes

MEGAligner defaults to automatic pair detection. It scores the officially supported naming schemes below and selects the one that yields the most complete, least ambiguous pairs.

Supported language suffix schemes:

```text
{stem}.{lang}.docx    chapter1.en.docx     chapter1.ru.docx
{stem}_{lang}.docx    chapter1_en.docx     chapter1_ru.docx
{stem}-{lang}.docx    chapter1-en.docx     chapter1-ru.docx
```

Supported language prefix schemes:

```text
{lang}.{stem}.docx    en.chapter1.docx     ru.chapter1.docx
{lang}_{stem}.docx    en_chapter1.docx     ru_chapter1.docx
{lang}-{stem}.docx    en-chapter1.docx     ru-chapter1.docx
```

Supported Russian prefix scheme:

```text
{stem}.docx           9719.docx
R{stem}.docx          R9719.docx
```

Language markers are matched case-insensitively. The detector accepts configured language tags from `--src-lang` and `--tgt-lang`, their base tags such as `en` from `en-US`, and these English/Russian aliases:

```text
English: en, eng, english
Russian: ru, r, rus, russian
```

For the `R{stem}.docx` convention, discovery first tries exact stem matching. If files remain unmatched, it also recovers unique normalized matches such as `_p1` versus `p1`, `_0`, `ri`, `r1`, and `b` suffix differences. These appear under `Normalized pair matches` in the preview.

For an unusual corpus, pass an explicit pattern containing exactly one `{stem}` and one `{lang}`:

```bash
make align DIR=/corpus OUT=/tmx/result.tmx ALIGN_ARGS="--pattern '{stem}.{lang}.docx'"
```

## Docker

The default Mac workflow is native because it can use Apple MPS acceleration. Docker is still available when host isolation matters:

```bash
make align-dockerized DIR=/absolute/path/to/docx-folder OUT=/absolute/path/output.tmx
```

Build the image manually:

```bash
docker build -t docx-bitext-aligner:local .
```

Validate pair discovery without loading the embedding model:

```bash
docker run --rm -it \
  -v "$PWD/documents:/data/input:ro" \
  -v "$PWD/out:/data/out" \
  docx-bitext-aligner:local /data/input /data/out --dry-run
```

Run after validating the mapping:

```bash
docker run --rm -it \
  -v "$PWD/documents:/data/input:ro" \
  -v "$PWD/out:/data/out" \
  -v "$PWD/.hf-cache:/models/huggingface" \
  docx-bitext-aligner:local /data/input /data/out \
    --combined-output /data/out/aligned.tmx \
    --allow-model-download
```

For non-interactive runs, use `--dry-run` first, then add `--yes`.

## Native uv

`make align` runs `uv run align-docx`, creates or reuses `.venv/`, and uses the same `.hf-cache/` model cache. Use `DEVICE=auto` to let the tool choose `cuda`, then `mps`, then `cpu`; use `DEVICE=cpu` for a controlled CPU comparison.

Direct `uv` usage is also supported:

```bash
HF_HOME="$PWD/.hf-cache" uv run align-docx /path/to/docx-folder /path/to/out-dir \
  --combined-output /path/to/aligned.tmx \
  --allow-model-download \
  --device auto
```

## Developer Notes

The code is packaged under `docx_bitext_aligner/`:

```text
discovery.py   filename scheme detection and pair preflight
config.py      runtime configuration and validation
text.py        DOCX extraction and sentence segmentation
embedding.py   SentenceTransformer loading, device selection, encoding
alignment.py   sentence-window generation and dynamic programming
tmx.py         TMX tree construction, validation, and atomic writes
reports.py     JSON report writers
runner.py      pair and batch orchestration
cli.py         command-line parser and entry point
```

Dependencies are defined in `pyproject.toml` and locked in `uv.lock`. Docker installs with `uv sync`; `requirements.txt` is intentionally not used. The Linux Docker build uses PyTorch CPU wheels. Native macOS `uv` installs use the normal macOS wheel so MPS can be selected when available.

The default tests avoid Docker, model downloads, and heavyweight runtime dependencies:

```bash
make test
```

## Alignment Notes

The script extracts paragraph text from the document body and tables with `python-docx`. Sentence splitting is performed independently inside each paragraph, so paragraph boundaries are hard breaks before segmentation. Russian uses `razdel`; other languages use `pysbd`.

Alignment uses multilingual sentence embeddings and monotonic dynamic programming with 1:1 and m:n candidates up to `--max-group`. The writer emits Level 1 plaintext TMX, adds deterministic `tuid` values, adds a `tmx14.dtd` doctype reference, validates the emitted structure against the tool's Level 1 DTD subset, writes UTF-8, and reparses the file after writing.

## License

MEGAligner is released under the MIT License. See [LICENSE](LICENSE).
