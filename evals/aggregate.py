"""Aggregate every evals/results/*.json into one cross-model comparison: evals/RESULTS.md.

    python evals/aggregate.py

Each results file is one eval batch (one model, run via run.py). This script pools
all of them, groups runs by the batch's pinned model, and reports:
  - a comparison table (valid pass rate, all-runs pass rate, run counts, infra
    errors, avg cost/run, avg tokens/run, median time)
  - a per-task x per-model matrix of pass fraction

Runs for tasks that no longer exist under evals/tasks/ (renamed/removed since
that batch ran) are dropped so the tables don't get skewed by stale rows. A
model with fewer than MIN_VALID_RUNS valid (non-infra_error) runs is flagged
"insufficient data" rather than trusted at face value.

"Valid" excludes infra_error runs (transient API/network failures -- see
run.py's classify_outcome); "all runs" counts them as failures. Cost/token/time
are averaged over ALL runs (including infra errors), since quota was spent
either way and that's what a real eval batch costs.
"""
import glob
import json
import os
import sys
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)   # for `import run` (evals/run.py)
sys.path.insert(0, ROOT)   # for `import forge.pricing`

from run import classify_outcome, TASKS_DIR  # noqa: E402  (reuse the same outcome logic as run.py)

try:
    from forge.pricing import PRICES  # noqa: E402
except Exception:
    PRICES = {}

RESULTS_DIR = os.path.join(HERE, "results")
OUT_PATH = os.path.join(HERE, "RESULTS.md")
MIN_VALID_RUNS = 20
THIRD_PARTY_PRICED_MODELS = {"gemini-3.5-flash", "gemini-3.1-pro-preview", "gemini-2.5-flash"}


def existing_task_ids() -> set[str]:
    if not os.path.isdir(TASKS_DIR):
        return set()
    return {name for name in os.listdir(TASKS_DIR)
            if os.path.isfile(os.path.join(TASKS_DIR, name, "task.json"))}


def load_all_runs() -> list[dict]:
    """Every run from every evals/results/*.json, tagged with its batch model and
    source file, limited to tasks that still exist in evals/tasks/."""
    task_ids = existing_task_ids()
    paths = sorted(glob.glob(os.path.join(RESULTS_DIR, "*.json")))
    data_by_path = {}
    for path in paths:
        try:
            with open(path, encoding="utf-8") as f:
                data_by_path[path] = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

    # A file written by `run.py --resume <X>` repeats every row of X (with the infra_error
    # ones replaced) and records resumed_from=<basename of X>. Skip any file that some other
    # file's resumed_from names, so a resumed batch's rows are counted once, not twice
    # (this also collapses resume-of-resume chains, since only the newest link in the chain
    # is never itself referenced as somebody's resumed_from).
    skip_names = {data.get("resumed_from") for data in data_by_path.values() if data.get("resumed_from")}

    runs = []
    for path, data in data_by_path.items():
        if os.path.basename(path) in skip_names:
            continue
        model = data.get("model", "unknown")
        if data.get("label"):   # ablation runs, e.g. "gemini-3.7-flash [bash-only]"
            model = f"{model} [{data['label']}]"
        for r in data.get("results", []):
            if r.get("id") not in task_ids:
                continue
            r = dict(r)
            r.setdefault("outcome", classify_outcome(r))
            r["_model"] = model
            r["_source"] = os.path.basename(path)
            runs.append(r)
    return runs


def _tokens(r: dict) -> int:
    return (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0) + (r.get("thinking_tokens") or 0)


def median(xs: list[float]):
    xs = sorted(xs)
    return xs[len(xs) // 2] if xs else None


def per_model_stats(runs: list[dict]) -> dict:
    by_model: dict[str, list[dict]] = {}
    for r in runs:
        by_model.setdefault(r["_model"], []).append(r)

    stats = {}
    for model, rs in by_model.items():
        n = len(rs)
        valid = [r for r in rs if r["outcome"] != "infra_error"]
        nv = len(valid)
        passed_all = sum(1 for r in rs if r["outcome"] == "pass")
        passed_valid = sum(1 for r in valid if r["outcome"] == "pass")

        # avg cost/tokens/time over VALID runs only: an infra_error run that died on the
        # first API call costs ~$0 and takes ~0s, so averaging it in makes a model that had
        # a bad afternoon of 504s/429s look artificially cheap and fast. Discarded retry
        # attempts still burned real quota (run.py rolls that into infra_retry_cost_usd /
        # infra_retry_tokens), so that's reported separately as total spend across ALL runs.
        cost_valid = sum(r.get("cost_usd") or 0 for r in valid)
        tokens_valid = sum(_tokens(r) for r in valid)
        total_spend = sum((r.get("cost_usd") or 0) + (r.get("infra_retry_cost_usd") or 0) for r in rs)
        secs = [r["seconds"] for r in valid if r.get("seconds") is not None]
        stats[model] = {
            "runs": n,
            "valid_runs": nv,
            "infra_errors": n - nv,
            "valid_pass_rate": (passed_valid / nv) if nv else None,
            "all_pass_rate": (passed_all / n) if n else None,
            "avg_cost": (cost_valid / nv) if nv else 0.0,
            "avg_tokens": (tokens_valid / nv) if nv else 0,
            "total_spend": total_spend,
            "median_seconds": median(secs),
            "insufficient": nv < MIN_VALID_RUNS,
        }
    return stats


def per_task_matrix(runs: list[dict], models: list[str]) -> tuple[list[str], dict[str, dict[str, str]]]:
    by_task_model: dict[str, dict[str, list[dict]]] = {}
    for r in runs:
        by_task_model.setdefault(r["id"], {}).setdefault(r["_model"], []).append(r)

    tasks = sorted(by_task_model)
    rows = {}
    for tid in tasks:
        row = {}
        for model in models:
            rs = by_task_model.get(tid, {}).get(model, [])
            valid = [r for r in rs if r["outcome"] != "infra_error"]
            if valid:
                frac = sum(1 for r in valid if r["outcome"] == "pass") / len(valid)
                row[model] = f"{frac * 100:.0f}% ({len(valid)})"
            else:
                row[model] = "-"
        rows[tid] = row
    return tasks, rows


def render(stats: dict, tasks: list[str], matrix: dict[str, dict[str, str]], n_files: int,
           runs: list[dict] | None = None) -> str:
    models = sorted(stats)
    lines = [
        "# Forge eval results across models",
        "",
        f"_Generated {datetime.date.today().isoformat()} by `evals/aggregate.py` from {n_files} file(s) in "
        f"`evals/results/`. Only runs of tasks currently present under `evals/tasks/` are counted; a model with "
        f"fewer than {MIN_VALID_RUNS} valid runs is marked **insufficient data** below (its numbers may not be "
        f"reliable)._",
        "",
    ]
    if runs:
        fails = sum(1 for r in runs if r["outcome"] == "fail")
        if fails == 0:
            lines.append(
                f"_Note: 0 of {len(runs)} runs classified as a genuine agent/checker failure -- every non-pass "
                f"run ended on an infra_error (API/network error, timeout, or no JSON output). The 100% valid "
                f"pass rates below reflect that, not a classifier swallowing real failures._"
            )
        else:
            lines.append(f"_Note: {fails} of {len(runs)} runs were genuine failures (agent ran, checker disagreed) "
                          f"-- see the per-task matrix and each batch's own `.md` file for detail._")
        lines.append("")
    lines += [
        "\"Valid\" excludes `infra_error` runs (Vertex/Gemini 5xx/429s, DNS/oauth failures, timeouts, or no JSON "
        "output at all -- see `classify_outcome` in `evals/run.py`); \"all runs\" counts those as failures. "
        "`avg cost/run` and `avg tokens/run` are averaged over valid runs only -- an infra_error run that died on "
        "the first API call costs ~$0 and takes ~0s, so folding it into the average makes a model that had a bad "
        "afternoon of 504s/429s look artificially cheap and fast. `total spend` is the real bill across every "
        "attempt, including quota burned by discarded infra-error retries.",
        "",
    ]
    if any(m in THIRD_PARTY_PRICED_MODELS for m in models):
        lines += [
            "> Prices for " + ", ".join(sorted(m for m in THIRD_PARTY_PRICED_MODELS if m in models)) +
            " come from third-party trackers, not yet confirmed on Google's own pricing page "
            "(see `forge/pricing.py`) -- treat their cost columns as estimates.",
            "",
        ]

    lines += [
        "## Comparison",
        "",
        "| model | valid pass rate | all-runs pass rate | runs | valid runs | infra errors | "
        "avg cost/run (valid) | avg tokens/run (valid) | total spend (all attempts) | median time (valid) | note |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for model in models:
        s = stats[model]
        vpr = f"{s['valid_pass_rate'] * 100:.0f}%" if s["valid_pass_rate"] is not None else "n/a"
        apr = f"{s['all_pass_rate'] * 100:.0f}%" if s["all_pass_rate"] is not None else "n/a"
        med = f"{s['median_seconds']:.0f}s" if s["median_seconds"] is not None else "n/a"
        note = "insufficient data" if s["insufficient"] else ""
        priced = model in PRICES
        cost_str = f"${s['avg_cost']:.4f}" if priced or s["avg_cost"] else f"${s['avg_cost']:.4f} (unpriced)"
        lines.append(
            f"| `{model}` | {vpr} | {apr} | {s['runs']} | {s['valid_runs']} | {s['infra_errors']} | "
            f"{cost_str} | {s['avg_tokens']:,.0f} | ${s['total_spend']:.3f} | {med} | {note} |"
        )

    lines += ["", "## Per-task pass fraction (valid runs, `pass % (n valid)`)", ""]
    header = "| task | " + " | ".join(f"`{m}`" for m in models) + " |"
    sep = "|---|" + "---|" * len(models)
    lines += [header, sep]
    for tid in tasks:
        row = matrix[tid]
        lines.append(f"| {tid} | " + " | ".join(row[m] for m in models) + " |")

    return "\n".join(lines) + "\n"


def main():
    runs = load_all_runs()
    if not runs:
        print("No runs found under evals/results/ (or none match a task in evals/tasks/) -- nothing to aggregate.")
        return
    stats = per_model_stats(runs)
    models = sorted(stats)
    tasks, matrix = per_task_matrix(runs, models)
    n_files = len(glob.glob(os.path.join(RESULTS_DIR, "*.json")))
    report = render(stats, tasks, matrix, n_files, runs=runs)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"Wrote {OUT_PATH} ({len(runs)} runs, {len(models)} model(s), {len(tasks)} task(s)).")
    print("\n" + report)


if __name__ == "__main__":
    main()
