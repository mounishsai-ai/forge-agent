"""Eval runner: measures how often Forge actually completes coding tasks.

For each task in evals/tasks/<id>/:
  1. copy repo/ into a fresh temp directory (the agent never sees check.py)
  2. run `forge -p <prompt> --yes --json` headlessly in that directory
  3. run check.py in that directory -> exit 0 means the task passed
Results (pass rate, tokens, cost, time per task) go to evals/results/.

    python evals/run.py                         # all tasks, default eval model
    python evals/run.py --tasks lru_cache slugify --repeat 3 --workers 4
"""
import argparse
import concurrent.futures as cf
import datetime
import json
import os
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


def load_tasks(only: list[str] | None) -> list[dict]:
    tasks = []
    for name in sorted(os.listdir(TASKS_DIR)):
        spec = os.path.join(TASKS_DIR, name, "task.json")
        if os.path.isfile(spec) and (not only or name in only):
            with open(spec, encoding="utf-8") as f:
                tasks.append({**json.load(f), "dir": os.path.join(TASKS_DIR, name)})
    return tasks


def run_one(task: dict, model: str, attempt: int, keep: bool) -> dict:
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
    if keep:
        result["workdir"] = workdir
    else:
        shutil.rmtree(workdir, ignore_errors=True)
    return result


def summarize(results: list[dict], model: str) -> str:
    n = len(results)
    passed = sum(r["passed"] for r in results)
    cost = sum(r.get("cost_usd") or 0 for r in results)
    tokens_in = sum(r.get("input_tokens") or 0 for r in results)
    tokens_out = sum((r.get("output_tokens") or 0) + (r.get("thinking_tokens") or 0) for r in results)
    lines = [
        f"# Forge eval results ({datetime.date.today().isoformat()})",
        "",
        f"- Model: `{model}` (pinned, no fallback)",
        f"- **Pass rate: {passed}/{n} = {100 * passed / n:.0f}%**",
        f"- Total cost: ${cost:.3f} (avg ${cost / n:.4f}/run) | tokens in {tokens_in:,} / out {tokens_out:,}",
        f"- Median time per task: {sorted(r['seconds'] for r in results)[n // 2]:.0f}s",
        "",
        "| task | category | difficulty | pass | tool calls | cost $ | time s |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda r: (r["id"], r["attempt"])):
        lines.append(f"| {r['id']} | {r.get('category')} | {r.get('difficulty')} | {'PASS' if r['passed'] else 'FAIL'} "
                     f"| {r.get('tool_calls', '-')} | {r.get('cost_usd') or 0:.4f} | {r['seconds']:.0f} |")
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tasks", nargs="*", help="task ids (default: all)")
    p.add_argument("--model", default=EVAL_MODEL)
    p.add_argument("--repeat", type=int, default=1, help="runs per task (for pass-rate variance)")
    p.add_argument("--workers", type=int, default=4, help="tasks run in parallel")
    p.add_argument("--keep", action="store_true", help="keep work dirs for debugging")
    args = p.parse_args()

    tasks = load_tasks(args.tasks)
    jobs = [(t, a) for t in tasks for a in range(1, args.repeat + 1)]
    print(f"Running {len(jobs)} runs ({len(tasks)} tasks x {args.repeat}) on {args.model} ...")
    results = []
    with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_one, t, args.model, a, args.keep): (t, a) for t, a in jobs}
        for fut in cf.as_completed(futures):
            r = fut.result()
            results.append(r)
            print(f"  {'PASS' if r['passed'] else 'FAIL'}  {r['id']} #{r['attempt']}  ({r['seconds']:.0f}s)"
                  + (f"  error: {r['error'][:100]}" if r.get("error") else ""), flush=True)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    with open(os.path.join(RESULTS_DIR, f"{stamp}.json"), "w", encoding="utf-8") as f:
        json.dump({"model": args.model, "results": results}, f, indent=1)
    report = summarize(results, args.model)
    with open(os.path.join(RESULTS_DIR, f"{stamp}.md"), "w", encoding="utf-8") as f:
        f.write(report + "\n")
    print("\n" + report)


if __name__ == "__main__":
    main()
