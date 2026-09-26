# Forge eval results across models

_Generated 2026-09-26 by `evals/aggregate.py` from 12 file(s) in `evals/results/`. Only runs of tasks currently present under `evals/tasks/` are counted; a model with fewer than 20 valid runs is marked **insufficient data** below (its numbers may not be reliable)._

_Note: 51 of 572 runs were genuine failures (agent ran, checker disagreed) -- see the per-task matrix and each batch's own `.md` file for detail._

"Valid" excludes `infra_error` runs (Vertex/Gemini 5xx/429s, DNS/oauth failures, timeouts, or no JSON output at all -- see `classify_outcome` in `evals/run.py`); "all runs" counts those as failures. `avg cost/run` and `avg tokens/run` are averaged over valid runs only -- an infra_error run that died on the first API call costs ~$0 and takes ~0s, so folding it into the average makes a model that had a bad afternoon of 504s/429s look artificially cheap and fast. `total spend` is the real bill across every attempt, including quota burned by discarded infra-error retries.

> Prices for gemini-2.5-flash, gemini-3.1-pro-preview, gemini-3.5-flash come from third-party trackers, not yet confirmed on Google's own pricing page (see `forge/pricing.py`) -- treat their cost columns as estimates.

## Comparison

| model | valid pass rate | all-runs pass rate | runs | valid runs | infra errors | avg cost/run (valid) | avg tokens/run (valid) | total spend (all attempts) | median time (valid) | note |
|---|---|---|---|---|---|---|---|---|---|---|
| `gemini-2.5-flash` | 38% | 33% | 51 | 45 | 6 | $0.0024 | 4,322 | $0.322 | 26s |  |
| `gemini-3.1-pro-preview` | 92% | 55% | 104 | 62 | 42 | $0.2126 | 80,060 | $14.983 | 234s |  |
| `gemini-3.5-flash` | 96% | 88% | 78 | 72 | 6 | $0.3625 | 192,790 | $26.234 | 73s |  |
| `gemini-3.6-flash` | 94% | 85% | 78 | 70 | 8 | $0.1811 | 197,440 | $12.877 | 82s |  |
| `gemini-3.7-flash` | 97% | 69% | 140 | 99 | 41 | $0.0412 | 45,530 | $4.241 | 92s |  |
| `gemini-3.7-flash [bash-only]` | 90% | 85% | 53 | 50 | 3 | $0.0000 (unpriced) | 0 | $0.000 | 140s |  |
| `gemini-3.7-flash [no-subagents-no-todo]` | 95% | 87% | 68 | 62 | 6 | $0.0000 (unpriced) | 0 | $0.000 | 114s |  |

## Per-task pass fraction (valid runs, `pass % (n valid)`)

| task | `gemini-2.5-flash` | `gemini-3.1-pro-preview` | `gemini-3.5-flash` | `gemini-3.6-flash` | `gemini-3.7-flash` | `gemini-3.7-flash [bash-only]` | `gemini-3.7-flash [no-subagents-no-todo]` |
|---|---|---|---|---|---|---|---|
| bugfix-average-score-crash | 33% (3) | 100% (3) | 100% (3) | 100% (3) | 100% (7) | 100% (3) | 100% (3) |
| bugfix-inventory-key-mismatch | 0% (3) | - | 100% (3) | 100% (3) | 100% (6) | 100% (3) | 100% (3) |
| bugfix-pagination-off-by-one | 50% (2) | 100% (4) | 100% (3) | 100% (3) | 100% (7) | 100% (3) | 100% (3) |
| expr_calculator | 0% (2) | 100% (3) | 100% (3) | 100% (3) | 100% (4) | 100% (3) | 100% (3) |
| extract_helper | 0% (2) | 100% (4) | 100% (3) | 100% (3) | 100% (6) | 33% (3) | 100% (3) |
| feature-lru-cache | 33% (3) | 100% (4) | 100% (3) | 100% (3) | 100% (5) | 100% (3) | 100% (3) |
| feature-shop-discount-codes | 100% (3) | 100% (3) | 100% (3) | 100% (3) | 100% (6) | 100% (3) | 100% (3) |
| feature-slugify | 33% (3) | 100% (3) | 100% (3) | 100% (3) | 100% (6) | 100% (3) | 100% (3) |
| feature-wordfreq-flags | 67% (3) | 100% (3) | 100% (3) | 100% (3) | 100% (4) | 100% (3) | 100% (3) |
| find_jwt_leeway | 100% (3) | 100% (3) | 100% (3) | 100% (3) | 100% (6) | 100% (3) | 100% (3) |
| hard-async-crawler | 33% (3) | 100% (3) | 100% (3) | 100% (3) | 100% (3) | 100% (3) | 100% (3) |
| hard-bug-hunt-from-logs | 0% (2) | 67% (3) | 100% (3) | 100% (3) | 100% (3) | 100% (3) | 100% (3) |
| hard-concurrency-bank | 0% (2) | 0% (3) | 0% (2) | 0% (3) | 0% (3) | 0% (3) | 0% (3) |
| hard-dependency-resolver | - | 67% (3) | 100% (2) | 100% (1) | 100% (1) | - | - |
| hard-fix-flaky-tests | 0% (1) | 100% (3) | 100% (3) | 100% (3) | 100% (6) | 100% (3) | 100% (3) |
| hard-js-event-emitter | 100% (1) | 100% (3) | 100% (3) | 100% (2) | 100% (3) | 100% (3) | 100% (3) |
| hard-multi-file-feature-cli-todo | - | 100% (3) | 100% (3) | 100% (3) | 100% (6) | 100% (3) | 100% (3) |
| hard-parser-ini-roundtrip | 0% (1) | 100% (3) | 100% (1) | 100% (1) | - | - | - |
| hard-perf-dedupe | 0% (1) | 100% (2) | 0% (1) | - | 100% (4) | 100% (2) | 100% (3) |
| hard-rate-limiter | 100% (1) | 100% (3) | 100% (3) | 100% (3) | 100% (4) | - | 100% (3) |
| hard-refactor-god-class | 0% (1) | 100% (2) | 100% (3) | 67% (3) | 100% (5) | - | 100% (3) |
| hard-sqlite-migration | 0% (1) | - | 100% (3) | 100% (3) | 100% (1) | - | 100% (3) |
| js_deep_merge | 100% (1) | - | 100% (3) | 100% (3) | - | - | 100% (2) |
| log_report | 100% (1) | - | 100% (3) | 100% (3) | - | - | - |
| rename_symbol | 0% (1) | 100% (1) | 100% (3) | 100% (3) | 100% (1) | - | - |
| write_tests | 0% (1) | - | 100% (3) | 100% (3) | 100% (2) | - | - |
