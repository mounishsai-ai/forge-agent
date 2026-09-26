"""Eval runner: measures how often Forge actually completes coding tasks.

For each task in evals/tasks/<id>/:
  1. copy repo/ into a fresh temp directory (the agent never sees check.py)
  2. run `forge -p <prompt> --yes --json` headlessly in that directory
  3. run check.py in that directory -> exit 0 means the task passed
Results (pass rate, tokens, cost, time per task) go to evals/results/.

    python evals/run.py                         # all tasks, default eval model
    python evals/run.py --tasks lru_cache slugify --repeat 3 --workers 4

Real runs are noisy with infrastructure errors (Vertex 504/429s, DNS/oauth blips,
disconnects) that have nothing to do with whether the agent can code. Each run is
classified as "pass", "fail" (agent ran, checker disagreed), or "infra_error"
(transient API/network failure or no JSON output at all). infra_errors are
retried automatically (see --infra-retries); summaries report pass rate both
including and excluding them so a bad afternoon of 504s doesn't read as a
regression.
"""
import argparse
import concurrent.futures as cf
import datetime
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
TASKS_DIR = os.path.join(HERE, "tasks")
RESULTS_DIR = os.path.join(HERE, "results")
EVAL_MODEL = "gemini-3.7-flash"
TASK_TIMEOUT = 900   # seconds per agent run

# Extra attempts for an infra_error, in seconds, indexed by retry number
# (0-based); the last value repeats if --infra-retries asks for more.
INFRA_BACKOFF_SECONDS = [30, 90]

# Matched against result["error"] (case-insensitive). These are the patterns
# observed in real eval runs: Vertex/Gemini server & quota errors, transport
# and DNS/oauth failures, and our own "agent produced no JSON" / timeout markers.
# None of them say anything about whether the agent's code was correct.
INFRA_ERROR_PATTERNS = [
    r"ServerError:\s*5\d\d",
    r"ClientError:\s*429",
    r"RESOURCE_EXHAUSTED",
    r"DEADLINE_EXCEEDED",
    r"TransportError",
    r"RemoteProtocolError",
    r"ConnectError",
    r"ReadTimeout",
    r"getaddrinfo failed",
    r"oauth2\.googleapis\.com",
    r"NameResolutionError",
    r"ConnectionResetError",
    r"Server disconnected without sending a response",
    r"agent timed out after",
    r"no JSON output",
]
_INFRA_ERROR_RE = re.compile("|".join(INFRA_ERROR_PATTERNS), re.IGNORECASE)


def classify_outcome(result: dict) -> str:
    """"pass" / "fail" / "infra_error" for one run, from its passed/error fields.

    A checker pass always wins (even if the agent's own JSON also carried an
    error, e.g. a warning after a retry). Otherwise an error message matching
    a known infra pattern is "infra_error"; any other failure (including a
    finished agent whose checker just disagreed) is "fail".
    """
    if result.get("passed"):
        return "pass"
    err = result.get("error") or ""
    if err and _INFRA_ERROR_RE.search(err):
        return "infra_error"
    return "fail"


def load_tasks(only: list[str] | None) -> list[dict]:
    tasks = []
    for name in sorted(os.listdir(TASKS_DIR)):
        spec = os.path.join(TASKS_DIR, name, "task.json")
        if os.path.isfile(spec) and (not only or name in only):
            with open(spec, encoding="utf-8") as f:
                tasks.append({**json.load(f), "dir": os.path.join(TASKS_DIR, name)})
    return tasks


def run_one(task: dict, model: str, attempt: int, keep: bool) -> dict:
    """Run the agent + checker once. Sets result["outcome"]; never raises."""
    workdir = tempfile.mkdtemp(prefix=f"forge-eval-{task['id']}-")
    shutil.copytree(os.path.join(task["dir"], "repo"), workdir, dirs_exist_ok=True)
    result = {"id": task["id"], "category": task.get("category"), "difficulty": task.get("difficulty"),
              "attempt": attempt, "passed": False}
    start = time.time()
    try:
        agent = subprocess.run(
            [sys.executable, "-m", "forge", "-p", task["prompt"], "--yes", "--json",
             "--model", model, "--no-fallback", "--max-turns", "40"],
            cwd=workdir, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=TASK_TIMEOUT)
        last_line = (agent.stdout.strip().splitlines() or ["{}"])[-1]
        try:
            result.update(json.loads(last_line))
        except json.JSONDecodeError:
            result["error"] = f"no JSON output: {agent.stderr[-500:]}"
    except subprocess.TimeoutExpired:
        result["error"] = f"agent timed out after {TASK_TIMEOUT}s"
    result["seconds"] = round(time.time() - start, 1)

    try:
        check = subprocess.run([sys.executable, os.path.join(task["dir"], "check.py")], cwd=workdir,
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)
        result["passed"] = check.returncode == 0
        result["check_output"] = (check.stdout + check.stderr).strip()[-800:]
    except subprocess.TimeoutExpired:
        result["check_output"] = "checker timed out"
    result.pop("result", None)   # the agent's final message; long and not needed in the summary
    result["outcome"] = classify_outcome(result)
    if keep:
        result["workdir"] = workdir
    else:
        shutil.rmtree(workdir, ignore_errors=True)
    return result


def _tokens(r: dict) -> int:
    return (r.get("input_tokens") or 0) + (r.get("output_tokens") or 0) + (r.get("thinking_tokens") or 0)


def run_one_with_retries(task: dict, model: str, attempt: int, keep: bool, infra_retries: int) -> dict:
    """run_one, automatically retried (with backoff) while the outcome is infra_error.

    A discarded infra_error attempt can still have burned real quota (e.g. a 429 after
    partial usage). That cost/token spend is rolled into infra_retry_cost_usd /
    infra_retry_tokens on the final result so totals reflect what was actually spent,
    not just what the last (kept) attempt cost.
    """
    result = run_one(task, model, attempt, keep)
    retries_used = 0
    retry_errors = []
    retry_cost = 0.0
    retry_tokens = 0
    while result["outcome"] == "infra_error" and retries_used < infra_retries:
        if result.get("error"):
            retry_errors.append(result["error"])
        retry_cost += result.get("cost_usd") or 0
        retry_tokens += _tokens(result)
        delay = INFRA_BACKOFF_SECONDS[min(retries_used, len(INFRA_BACKOFF_SECONDS) - 1)]
        time.sleep(delay)
        retries_used += 1
        result = run_one(task, model, attempt, keep)
    result["infra_retries_used"] = retries_used
    if retry_errors:
        result["infra_retry_errors"] = retry_errors
    if retry_cost:
        result["infra_retry_cost_usd"] = round(retry_cost, 6)
    if retry_tokens:
        result["infra_retry_tokens"] = retry_tokens
    return result


def _task_pass_fractions(results: list[dict]) -> list[tuple[str, float, int]]:
    """Per-task (id, pass_fraction, valid_run_count), over valid (non-infra_error) runs only."""
    by_task: dict[str, list[dict]] = {}
    for r in results:
        by_task.setdefault(r["id"], []).append(r)
    out = []
    for tid, rs in by_task.items():
        valid = [r for r in rs if r.get("outcome") != "infra_error"]
        if valid:
            frac = sum(1 for r in valid if r.get("outcome") == "pass") / len(valid)
            out.append((tid, frac, len(valid)))
    return out


def _difficulty_breakdown(valid: list[dict]) -> list[str]:
    by_diff: dict[str, list[dict]] = {}
    for r in valid:
        by_diff.setdefault(r.get("difficulty") or "unknown", []).append(r)
    lines = []
    for d in sorted(by_diff):
        rs = by_diff[d]
        p = sum(1 for r in rs if r.get("outcome") == "pass")
        lines.append(f"  - {d}: {p}/{len(rs)} = {100 * p / len(rs):.0f}%")
    return lines


def summarize(results: list[dict], model: str) -> str:
    n = len(results)
    valid = [r for r in results if r.get("outcome") != "infra_error"]
    nv = len(valid)
    infra = n - nv
    passed_all = sum(1 for r in results if r.get("outcome") == "pass")
    passed_valid = sum(1 for r in valid if r.get("outcome") == "pass")

    # avg cost/tokens/time are computed over VALID runs: an infra_error run that died on
    # the first API call costs ~$0 and takes ~0s, and averaging that in makes a model with
    # a bad afternoon of 504s look artificially cheap and fast. Retried/discarded attempts
    # still burned real quota though, so that's reported separately as total spend.
    cost_valid = sum(r.get("cost_usd") or 0 for r in valid)
    tokens_valid = sum(_tokens(r) for r in valid)
    total_spend = sum((r.get("cost_usd") or 0) + (r.get("infra_retry_cost_usd") or 0) for r in results)
    total_tokens_spent = sum(_tokens(r) + (r.get("infra_retry_tokens") or 0) for r in results)

    task_fractions = _task_pass_fractions(results)
    pass_at_1 = sum(f for _, f, _ in task_fractions) / len(task_fractions) if task_fractions else None

    lines = [
        f"# Forge eval results ({datetime.date.today().isoformat()})",
        "",
        f"- Model: `{model}` (pinned, no fallback)",
        f"- **Valid pass rate (excl. infra errors): {passed_valid}/{nv} = "
        f"{100 * passed_valid / nv:.0f}%**" if nv else "- Valid pass rate: n/a (no valid runs)",
        f"- All-runs pass rate (infra errors counted as failing): {passed_all}/{n} = {100 * passed_all / n:.0f}%",
        f"- Infra errors: {infra}/{n} ({100 * infra / n:.0f}%)" if n else "- Infra errors: 0/0",
        (f"- pass@1 (mean of each task's pass fraction across its repeats, valid runs only, "
         f"{len(task_fractions)} tasks): {pass_at_1 * 100:.0f}%") if task_fractions else "- pass@1: n/a",
        "- Per-difficulty breakdown (valid runs):",
        *(_difficulty_breakdown(valid) or ["  - n/a"]),
        (f"- Avg cost/run (valid runs only): ${cost_valid / nv:.4f} | avg tokens/run: {tokens_valid / nv:,.0f}"
         if nv else "- Avg cost/run: n/a (no valid runs)"),
        f"- Total spend (all attempts incl. discarded infra-error retries): ${total_spend:.3f} "
        f"| {total_tokens_spent:,} tokens",
        (f"- Median time per task (valid runs only): "
         f"{sorted(r['seconds'] for r in valid)[nv // 2]:.0f}s" if nv else "- Median time: n/a"),
        "",
        "| task | category | difficulty | outcome | pass | tool calls | cost $ | time s | infra retries |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda r: (r["id"], r["attempt"])):
        lines.append(
            f"| {r['id']} | {r.get('category')} | {r.get('difficulty')} | {r.get('outcome', '-')} "
            f"| {'PASS' if r.get('passed') else 'FAIL'} | {r.get('tool_calls', '-')} "
            f"| {r.get('cost_usd') or 0:.4f} | {r['seconds']:.0f} | {r.get('infra_retries_used', 0)} |"
        )

    lines += ["", "| task | pass fraction (valid runs) |", "|---|---|"]
    for tid, frac, cnt in sorted(task_fractions):
        lines.append(f"| {tid} | {frac * 100:.0f}% ({cnt} valid) |")
    return "\n".join(lines)


def _write_results(results: list[dict], model: str, resumed_from: str | None = None) -> str:
    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    json_path = os.path.join(RESULTS_DIR, f"{stamp}.json")
    payload = {"model": model, "results": results}
    if resumed_from:
        # lets aggregate.py skip the file(s) this one supersedes, so rows aren't double
        # counted (the merged file repeats every non-infra_error row from the original).
        payload["resumed_from"] = resumed_from
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    report = summarize(results, model)
    with open(os.path.join(RESULTS_DIR, f"{stamp}.md"), "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print("\n" + report)
    return json_path


def _print_progress(r: dict) -> None:
    extra = ""
    if r.get("error"):
        extra += f"  error: {r['error'][:100]}"
    if r.get("infra_retries_used"):
        extra += f"  [infra retries used: {r['infra_retries_used']}]"
    print(f"  {r.get('outcome', '?').upper()}  {r['id']} #{r['attempt']}  ({r['seconds']:.0f}s){extra}", flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tasks", nargs="*", help="task ids (default: all)")
    p.add_argument("--model", default=EVAL_MODEL)
    p.add_argument("--repeat", type=int, default=1, help="runs per task (for pass-rate variance)")
    p.add_argument("--workers", type=int, default=4, help="tasks run in parallel")
    p.add_argument("--keep", action="store_true", help="keep work dirs for debugging")
    p.add_argument("--infra-retries", type=int, default=2,
                    help="extra attempts for a run classified as infra_error (backoff: %s)"
                         % ", ".join(f"{s}s" for s in INFRA_BACKOFF_SECONDS))
    p.add_argument("--resume", metavar="RESULTS_JSON",
                    help="re-run only the infra_error rows of a previous results file and write a merged file")
    args = p.parse_args()

    if args.resume:
        with open(args.resume, encoding="utf-8") as f:
            prev = json.load(f)
        model = prev["model"]
        prev_results = prev["results"]
        for r in prev_results:
            r.setdefault("outcome", classify_outcome(r))

        to_rerun = [r for r in prev_results if r["outcome"] == "infra_error"]
        if not to_rerun:
            print(f"No infra_error runs in {args.resume} — nothing to resume.")
            return
        task_by_id = {t["id"]: t for t in load_tasks(sorted({r["id"] for r in to_rerun}))}
        jobs = [r for r in to_rerun if r["id"] in task_by_id]
        skipped = [r for r in to_rerun if r["id"] not in task_by_id]
        if skipped:
            print(f"Skipping {len(skipped)} infra_error rows whose task dir no longer exists: "
                  f"{sorted({r['id'] for r in skipped})}")
        print(f"Resuming {len(jobs)} infra_error run(s) from {args.resume} on {model} ...")

        new_by_key = {}
        with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(run_one_with_retries, task_by_id[r["id"]], model, r["attempt"], args.keep,
                                    args.infra_retries): r for r in jobs}
            for fut in cf.as_completed(futures):
                old = futures[fut]
                new = fut.result()
                new["infra_retries_used"] = new.get("infra_retries_used", 0) + old.get("infra_retries_used", 0)
                # the discarded old attempt (and any retries it already burned through) spent
                # real quota too; fold that into the new result so cost/token totals don't lose it.
                old_cost = (old.get("cost_usd") or 0) + (old.get("infra_retry_cost_usd") or 0)
                old_tokens = _tokens(old) + (old.get("infra_retry_tokens") or 0)
                if old_cost:
                    new["infra_retry_cost_usd"] = round((new.get("infra_retry_cost_usd") or 0) + old_cost, 6)
                if old_tokens:
                    new["infra_retry_tokens"] = (new.get("infra_retry_tokens") or 0) + old_tokens
                new_by_key[(new["id"], new["attempt"])] = new
                _print_progress(new)

        results = [new_by_key.get((r["id"], r["attempt"]), r) for r in prev_results]
        print(f"\nResumed {len(new_by_key)}/{len(to_rerun)} infra_error run(s); "
              f"{len(to_rerun) - len(new_by_key)} still skipped/unresolved.")
        resumed_from = os.path.basename(args.resume)
    else:
        tasks = load_tasks(args.tasks)
        jobs = [(t, a) for t in tasks for a in range(1, args.repeat + 1)]
        print(f"Running {len(jobs)} runs ({len(tasks)} tasks x {args.repeat}) on {args.model} "
              f"(infra-retries={args.infra_retries}) ...")
        results = []
        with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(run_one_with_retries, t, args.model, a, args.keep, args.infra_retries): (t, a)
                       for t, a in jobs}
            for fut in cf.as_completed(futures):
                r = fut.result()
                results.append(r)
                _print_progress(r)
        model = args.model
        resumed_from = None

    if not results:
        print("No runs to summarize (no matching tasks?).")
        return
    _write_results(results, model, resumed_from=resumed_from)


if __name__ == "__main__":
    main()
