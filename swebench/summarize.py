"""Summarize a Forge SWE-bench run: resolved rate (from the official harness report) + tokens/cost/time.

    python swebench/summarize.py --out ~/swebench-runs/main --run-id forge-20260927
    python swebench/summarize.py --out ~/swebench-runs/main      # stats only (before evaluation)

The denominator is ALWAYS the frozen selection in <out>/selection.json: instances that crashed,
timed out or never produced a prediction count as unresolved.
"""
import argparse
import glob
import json
import os

IN_PRICE, OUT_PRICE = 0.75, 3.75   # USD per 1M tokens, gemini-3.7-flash (thinking billed as output)


def read_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    for line in open(path, encoding="utf-8"):
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", default=os.path.expanduser("~/swebench-runs/main"))
    p.add_argument("--run-id", help="the --run_id given to the swebench harness")
    p.add_argument("--json", action="store_true", help="also write <out>/summary.json")
    a = p.parse_args()

    sel = json.load(open(os.path.join(a.out, "selection.json")))
    ids = sel["instance_ids"]
    n = len(ids)
    preds = {r["instance_id"]: r for r in read_jsonl(os.path.join(a.out, "predictions.jsonl"))}
    stats = {}
    for r in read_jsonl(os.path.join(a.out, "stats.jsonl")):
        if r["instance_id"] in ids:
            stats.setdefault(r["instance_id"], []).append(r)

    # Cost counts EVERY attempt (retries after errors cost money too); time/status use the latest attempt.
    all_attempts = [s for lst in stats.values() for s in lst]
    latest = {i: lst[-1] for i, lst in stats.items()}
    tok_in = sum(s.get("input_tokens") or 0 for s in all_attempts)
    tok_out = sum(s.get("output_tokens") or 0 for s in all_attempts)
    tok_think = sum(s.get("thinking_tokens") or 0 for s in all_attempts)
    cost_logged = sum(s.get("cost_usd") or 0 for s in all_attempts)
    cost_formula = (tok_in * IN_PRICE + (tok_out + tok_think) * OUT_PRICE) / 1e6
    statuses = {}
    for s in latest.values():
        statuses[s["status"]] = statuses.get(s["status"], 0) + 1
    with_pred = [i for i in ids if i in preds]
    empty = [i for i in with_pred if not preds[i]["model_patch"].strip()]
    agent_secs = [s.get("agent_seconds") or 0 for s in latest.values() if s.get("agent_seconds")]
    ran = max(len([s for s in latest.values() if s.get("input_tokens")]), 1)
    # Attempts that ran the agent but have no usage record (killed hard before Forge printed its JSON):
    # their Gemini cost is real but unknown, so it is reported instead of silently counted as $0.
    no_usage = [s["instance_id"] for s in all_attempts
                if s.get("agent_seconds") and s.get("input_tokens") is None]
    commit_raw = str(sel.get("forge_commit") or "unknown")
    commit = commit_raw.split()[0][:12] + (" (DIRTY: uncommitted changes)" if "dirty" in commit_raw else "")

    summary = {
        "dataset": sel.get("dataset"), "selection": {k: sel.get(k) for k in ("method", "seed", "n")},
        "model": sel.get("model"), "max_turns": sel.get("max_turns"), "forge_commit": sel.get("forge_commit"),
        "selected": n, "with_prediction": len(with_pred), "empty_patches": len(empty),
        "never_ran": n - len(latest), "status_latest_attempt": statuses,
        "attempts": len(all_attempts),
        "attempts_with_unrecorded_cost": no_usage,
        "tokens": {"input": tok_in, "output": tok_out, "thinking": tok_think},
        "cost_usd_logged": round(cost_logged, 4), "cost_usd_formula": round(cost_formula, 4),
        "cost_per_instance_usd": round(cost_logged / ran, 4),
        "tokens_per_instance": {"input": tok_in // ran, "output_plus_thinking": (tok_out + tok_think) // ran},
        "agent_minutes_mean": round(sum(agent_secs) / len(agent_secs) / 60, 1) if agent_secs else None,
    }

    if a.run_id:
        reports = glob.glob(os.path.join(a.out, f"*.{a.run_id}.json"))
        if not reports:
            raise SystemExit(f"No harness report *.{a.run_id}.json in {a.out} (did evaluate.sh finish?)")
        rep = json.load(open(reports[0]))
        resolved = [i for i in rep.get("resolved_ids", []) if i in ids]
        if rep.get("total_instances") != n:
            print(f"WARNING: harness total_instances={rep.get('total_instances')} != selected {n}; "
                  f"using the selection ({n}) as denominator.")
        summary.update({
            "harness_report": os.path.basename(reports[0]),
            "resolved": len(resolved), "resolved_rate": round(len(resolved) / n, 4),
            "harness_errors": rep.get("error_instances"), "harness_infra_failures": rep.get("infra_failure_instances"),
            "resolved_ids": resolved,
        })

    print(json.dumps(summary, indent=2))
    if a.run_id:
        how = (f"seeded random subset (seed {sel.get('seed')})" if sel.get("method") == "seeded random sample"
               else "hand-picked subset")
        print(f"\nResult: Forge resolved {summary['resolved']}/{n} ({100 * summary['resolved_rate']:.1f}%) "
              f"on a {how} of {n} instances of SWE-bench Verified, model {sel.get('model')} "
              f"(pass@1, no hints, max {sel.get('max_turns')} turns, Forge {commit}); "
              f"total Gemini cost ${cost_logged:.2f}"
              + (f" + {len(no_usage)} runs with unrecorded cost" if no_usage else "") + ".")
    if a.json:
        with open(os.path.join(a.out, "summary.json"), "w") as f:
            json.dump(summary, f, indent=2)


if __name__ == "__main__":
    main()
