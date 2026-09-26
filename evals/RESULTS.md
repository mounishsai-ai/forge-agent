# Forge eval results across models

_Generated 2026-09-26 by `evals/aggregate.py` from 3 file(s) in `evals/results/`. Only runs of tasks currently present under `evals/tasks/` are counted; a model with fewer than 20 valid runs is marked **insufficient data** below (its numbers may not be reliable)._

_Note: 0 of 105 runs classified as a genuine agent/checker failure -- every non-pass run ended on an infra_error (API/network error, timeout, or no JSON output). The 100% valid pass rates below reflect that, not a classifier swallowing real failures._

"Valid" excludes `infra_error` runs (Vertex/Gemini 5xx/429s, DNS/oauth failures, timeouts, or no JSON output at all -- see `classify_outcome` in `evals/run.py`); "all runs" counts those as failures. `avg cost/run` and `avg tokens/run` are averaged over valid runs only -- an infra_error run that died on the first API call costs ~$0 and takes ~0s, so folding it into the average makes a model that had a bad afternoon of 504s/429s look artificially cheap and fast. `total spend` is the real bill across every attempt, including quota burned by discarded infra-error retries.

> Prices for gemini-3.1-pro-preview come from third-party trackers, not yet confirmed on Google's own pricing page (see `forge/pricing.py`) -- treat their cost columns as estimates.

## Comparison

| model | valid pass rate | all-runs pass rate | runs | valid runs | infra errors | avg cost/run (valid) | avg tokens/run (valid) | total spend (all attempts) | median time (valid) | note |
|---|---|---|---|---|---|---|---|---|---|---|
| `gemini-3.1-pro-preview` | 100% | 15% | 26 | 4 | 22 | $0.0404 | 14,538 | $0.226 | 171s | insufficient data |
| `gemini-3.7-flash` | 100% | 53% | 79 | 42 | 37 | $0.0970 | 107,321 | $4.241 | 88s |  |

## Per-task pass fraction (valid runs, `pass % (n valid)`)

| task | `gemini-3.1-pro-preview` | `gemini-3.7-flash` |
|---|---|---|
| bugfix-average-score-crash | - | 100% (4) |
| bugfix-inventory-key-mismatch | - | 100% (4) |
| bugfix-pagination-off-by-one | 100% (1) | 100% (4) |
| expr_calculator | - | 100% (1) |
| extract_helper | 100% (1) | 100% (3) |
| feature-lru-cache | 100% (1) | 100% (2) |
| feature-shop-discount-codes | - | 100% (3) |
| feature-slugify | - | 100% (3) |
| feature-wordfreq-flags | - | 100% (1) |
| find_jwt_leeway | - | 100% (3) |
| hard-async-crawler | - | - |
| hard-bug-hunt-from-logs | - | - |
| hard-concurrency-bank | - | - |
| hard-dependency-resolver | - | - |
| hard-fix-flaky-tests | - | 100% (3) |
| hard-js-event-emitter | - | - |
| hard-multi-file-feature-cli-todo | - | 100% (3) |
| hard-parser-ini-roundtrip | - | - |
| hard-perf-dedupe | - | 100% (1) |
| hard-rate-limiter | - | 100% (1) |
| hard-refactor-god-class | - | 100% (2) |
| hard-sqlite-migration | - | 100% (1) |
| js_deep_merge | - | - |
| log_report | - | - |
| rename_symbol | 100% (1) | 100% (1) |
| write_tests | - | 100% (2) |
