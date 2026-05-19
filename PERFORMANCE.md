# MEGAligner Performance Plan

## Purpose

This is the single working performance plan for MEGAligner. It consolidates the
earlier performance drafts and the evidence from a real 99-pair Multilateral
Fund run that took about nine minutes on an M4 Pro MacBook Pro.

The target workflow is the default Mac path:

```bash
make align
```

That path writes one combined TMX file, uses native `uv`, and can use Apple MPS
acceleration. Docker and Linux CPU support still matter, but Mac-native
translator usage is the primary optimization target.

The goal is faster end-to-end alignment without reducing output quality. In this
document, "accuracy-neutral" means the change preserves the same model, same
extracted text, same segmentation, same scoring objective, and same TMX cleanup
policy. Some changes can still alter floating-point tie behavior or duplicate
provenance, so "accuracy-neutral" must be verified, not assumed.

## Current Workflow

The current combined-output workflow is:

1. Discover file pairs.
2. Load one SentenceTransformer model.
3. For each pair, serially:
   - extract DOCX paragraphs,
   - split paragraphs into sentence segments,
   - build grouped segment windows,
   - encode the pair's unique window texts with LaBSE and scatter duplicate
     windows back to their original positions,
   - run monotonic dynamic programming,
   - append the pair's alignment units.
4. Write one combined TMX.
5. Trim and normalize whitespace, remove exact duplicate EN/RU pairs, and emit QA
   sidecar reports.

Relevant files:

- `docx_bitext_aligner/runner.py`: orchestration and combined batch mode.
- `docx_bitext_aligner/text.py`: DOCX extraction and sentence segmentation.
- `docx_bitext_aligner/alignment.py`: window generation and DP alignment.
- `docx_bitext_aligner/embedding.py`: model loading and `model.encode`.
- `docx_bitext_aligner/tmx.py`: TMX cleanup, deduplication, validation, write.
- `docx_bitext_aligner/qa.py`: QA sidecar reports.

Current limitation: `run_combined_batch` processes pairs strictly serially. The
`WORKERS` setting helps per-file batch mode, but not the default combined-TMX
path.

## Real Corpus Observations

The first real output, `/Users/gallium/sandbox/aligned.tmx`, produced these
useful signals:

| Metric | Value |
|---|---:|
| Document pairs | 99 |
| Wall time | about 9 minutes |
| TMX size | about 20 MB |
| Translation units | 34,978 |
| Exact duplicate EN/RU pairs left | 0 |
| Empty units | 0 |
| Median similarity | 0.909 |
| Units below 0.55 similarity | 319 |
| Numeric/punctuation-like pairs | 13,890 |
| Numeric-looking pairs with different digit sequences | 224 |
| Units with one side <= 8 characters | 12,052 |
| Long extreme length-ratio candidates | 38 |

Takeaways:

- TMX structure and exact-pair deduplication look healthy.
- Output quality issues are concentrated in short/table/header material, not in
  whole-document failure.
- A blunt higher similarity threshold would remove useful short labels along
  with bad fragments.
- QA reporting should guide future filters.
- The corpus has repeated source strings and boilerplate, supporting exact
  window-text deduplication before embedding.
- The largest pairs dominate the output volume, so optimizing embedding and DP
  on large pairs matters more than micro-optimizing TMX writing.

## Baseline Before Optimizing

Before changing the implementation, capture a repeatable profile:

```bash
make align DIR=/Users/gallium/sandbox/mlatfund OUT=/Users/gallium/sandbox/aligned-baseline.tmx PROFILE=1
```

For shorter iteration, add a development-only pair limit or run a copied subset
of representative files.

The baseline should capture:

- total wall time,
- model load time,
- extraction time,
- segmentation time,
- window generation time,
- embedding time,
- DP time,
- TMX write time,
- QA report time,
- source/target segment counts,
- source/target window counts,
- duplicate window rate within and across pairs,
- band fallback count,
- slowest pairs.

Without this, we can reason about likely wins but cannot rank them as measured
outcomes.

## Cost Model

For one document pair:

- `n`: source segment count.
- `m`: target segment count.
- `g`: `--max-group`, default `3`.
- source windows are roughly `n * g`, limited by paragraph boundaries.
- target windows are roughly `m * g`, limited by paragraph boundaries.

Primary costs:

| Phase | Approximate cost | Notes |
|---|---:|---|
| DOCX extraction | O(document size) | Usually not dominant, but tables vary. |
| Segmentation | O(text length) | `pysbd` setup is avoidable overhead. |
| Window build | O((n + m) * g) | Small compared with embedding and DP. |
| Embedding | Transformer forward over all windows | Likely a major cost on MPS. |
| DP similarity | Many vector dot products | Current code performs many tiny `np.dot` calls. |
| DP recurrence | Python nested loops | Can still matter after similarity optimization. |
| TMX/QA write | O(number of units) | Usually not the bottleneck. |

The most promising targets are embedding efficiency and DP similarity lookup.

## Recommended Rollout

### Phase 0: Measurement

Improve profiling enough to identify real bottlenecks:

- Add band fallback counters.
- Add duplicate window counters.
- Add QA write timing to profile output.
- Preserve a baseline TMX for diffing.
- Preserve a baseline QA report for quality review.

### Phase 1: Low-Risk Local Optimizations

1. Precompute pair similarity matrices with a memory guard. Implemented.
2. Reuse sentence segmenters. Implemented.
3. Remove throwaway TUID computation inside DP. Implemented.
4. Verify output stability against the baseline TMX and QA report.

### Phase 2: Embedding Efficiency

1. Deduplicate exact window text within a pair before embedding. Implemented.
2. Report duplicate window text counts.
3. Benchmark batch sizes on Apple Silicon.

Batch-size tuning is most meaningful after embedding calls become large enough
to fill the device well.

### Phase 3: Combined-Mode Architecture

Rework combined mode around one shared model and larger encode batches:

1. Discover pairs.
2. Extract, segment, and build windows for all pairs.
3. Collect per-pair failures across all phases.
4. Deduplicate exact window text globally.
5. Encode unique window texts in large batches.
6. Attach vectors back to each pair.
7. Run DP per pair.
8. Merge results in discovery order.
9. Preserve the existing gate: if any pair failed, do not write the combined TMX.
10. Write the combined TMX and QA sidecars once.

This should be preferred before process-pool parallelism on Apple Silicon,
because it avoids multiple model copies and should feed MPS more efficiently.

### Phase 4: Conditional Deeper Work

Only after measurement:

- Dense or banded DP storage if DP still dominates.
- CPU-only process-pool combined mode if measured workloads benefit.
- Wider initial band if fallback retries are common.
- Persistent embedding cache if repeated reruns of the same corpora are common.

## Recommendations

### 1. Precompute Similarity Matrices

Current code calls `np.dot` inside the inner DP loop. Replace many tiny dot
calls with one matrix multiply:

```python
similarities = src_vectors @ tgt_vectors.T
```

Then DP reads:

```python
similarity = float(similarities[src_window.vector_index, tgt_window.vector_index])
```

Why it should help:

- LaBSE embeddings are already normalized.
- Cosine similarity is therefore a dot product.
- One BLAS matrix multiply is much faster than many Python-level dot calls.

Caveats:

- This is not guaranteed bit-identical. BLAS matrix multiplication may use a
  different floating-point reduction order from repeated `np.dot` calls.
- Tiny score changes can flip exact ties because DP currently uses strict
  `score > best`.
- Add a memory guard. Matrix size is
  `src_window_count * tgt_window_count * 4` bytes for float32.

Verification:

- Diff TMX output before and after.
- If diffs occur, classify whether they are tiny tie flips or real path changes.

### 2. Reuse Sentence Segmenters

`split_sentences` currently constructs a new `pysbd.Segmenter` for every
non-Russian paragraph. Cache one segmenter per language per process.

This should preserve segmentation exactly while removing repeated setup work.
Hoisting imports is fine; be careful with broad process-wide warning changes.

### 3. Remove Throwaway TUID Computation

`run_alignment_dp` builds temporary `AlignmentUnit` values with a TUID generated
using `stem=""`. `align_segments` immediately recomputes the final TUID with the
real stem. Defer TUID generation until the final unit is built.

This is a small cleanup, but it is free and makes ownership of final IDs clearer.

### 4. Deduplicate Exact Window Text Before Encoding

Exact duplicate window strings should be embedded once and scattered back to all
window positions.

This is especially relevant for UN-style corpora with repeated headers, table
labels, boilerplate, agenda text, document codes, and short labels.

Cache keys must include every setting that can affect embeddings: model,
language behavior if added later, prompt if added later, and normalized text.

### 5. Corpus-Level Embedding for Combined Mode

This is the largest Mac-first improvement. Instead of encoding one pair at a
time, build windows for all pairs, deduplicate exact window text globally, and
encode larger batches through one loaded model.

Memory estimate:

```text
model (~1.8 GB)
+ unique vectors: U_unique * 768 * 4 bytes
+ one pair's transient similarity matrix
+ accumulated alignment units
```

At 300,000 unique windows, vectors take about 0.9 GB. At 800,000, they take
about 2.3 GB. Add a threshold and fallback so a MacBook Air does not suffer from
memory pressure.

### 6. Tune Batch Size on Apple Silicon

Benchmark:

- `--batch-size 32`
- `--batch-size 64`
- `--batch-size 128`
- `--batch-size 256`

Do not change the default until measured on representative Mac hardware.

### 7. Pin Torch Threads for CPU Worker Modes

For Docker, Linux CPU, or future CPU process pools, avoid thread
oversubscription:

```python
torch.set_num_threads(1)
```

Environment variables may also be useful:

- `OMP_NUM_THREADS=1`
- `MKL_NUM_THREADS=1`

This matters less for the current default Mac combined mode because it uses one
model in one process.

### 8. Dense or Banded DP Storage

Current DP uses `list[dict]` plus `BackPointer` objects. Dense arrays and compact
backpointer storage could reduce dictionary lookup and allocation overhead.

Do this only if DP still dominates after similarity-matrix precompute.

### 9. Be Careful With Process-Pool Combined Mode

Naively parallelizing combined mode is not output-neutral:

- Multiple processes may each load the 1.8 GB model.
- MPS may not benefit from competing Python processes.
- MacBook Air memory pressure could erase any speedup.
- Collecting results out of order changes combined TMX order.
- Global dedup keys by `(normalized src_text, normalized tgt_text)`.
- The first occurrence controls list position.
- The highest-similarity duplicate controls stored content.
- Tied duplicates keep the first-seen content, including TUID.

If process-pool combined mode is added, merge results in discovery order and
make it opt-in or CPU-only until measured.

### 10. Band Fallback Tuning

The automatic band can cause DP to run twice: first inside the chosen band, then
again as full DP if no path is found. Add a counter for this.

If fallback is common, a wider initial band may improve speed. This is not
strictly output-neutral: a wider band searches a larger objective space and may
produce a different alignment. Treat it as measured tuning, not a silent
accuracy-neutral optimization.

## Quality Guardrails

Do not treat these as accuracy-neutral performance changes:

- Smaller embedding models.
- Quantized models.
- Lowering `--max-group`.
- More aggressive banding.
- Changing gap or group penalties.
- Raising the similarity threshold.
- Dropping short segments before alignment.
- Skipping table text.
- Automatically removing broad QA-flagged categories.

These may be valid product decisions later, but they require QA review and human
judgment.

## QA-Driven Filtering Policy

The new QA sidecars are diagnostic:

```text
aligned.tmx.qa.txt
aligned.tmx.qa.json
```

They should be used before turning any warning into a default filter. Useful
candidate categories include:

- numeric-looking pairs with different digit sequences,
- extreme length-ratio pairs,
- identical source/target text,
- very short one-side alignments,
- low-similarity samples by document stem,
- source strings with many target variants,
- target strings with many source variants.

The intended sequence is:

1. Generate the TMX and QA sidecars.
2. Review the compact QA summary and samples.
3. Decide which categories are clearly harmful.
4. Promote only high-confidence categories into default filters.
5. Keep borderline categories as warnings or opt-in cleanup.

Standalone numeric-only pairs are the first promoted filter. Entries such as
`182.22 -> 182,22` are skipped by default because they are table values, not
useful translation-memory units. This filter is intentionally narrow: text-bearing
entries such as `Table 3`, `III.`, or `US $10,220` are not removed by it.

## Verification Standard

For every proposed performance optimization:

1. Run unit tests.
2. Generate TMX before and after on a representative fixture.
3. Diff the TMX.
4. Compare QA reports.
5. Compare profile output.
6. On real corpora, compare:
   - written TU count,
   - duplicate count,
   - low-similarity filtered count,
   - QA warning counts,
   - sample alignment quality around the slowest/largest pairs.

For floating-point-sensitive changes:

1. Diff before/after TMX.
2. If there are no diffs, the change is output-neutral for that corpus.
3. If there are diffs, classify whether they are tiny tie flips or larger path
   changes.
4. If tie flips are common, consider an explicit deterministic tie-break as a
   separate reviewed baseline change.
