"""Rebuild a (partial) results file from a run.py console log, for a batch that was stopped early.

run.py only writes evals/results/<stamp>.json when the whole batch finishes. If a batch has to be
stopped (deadline, machine going to sleep), its log still has one line per finished run:
    "  PASS  <task-id> #<attempt>  (<seconds>s) ..."
This turns those lines into a results file marked "partial": true, so aggregate.py can include
the runs that did finish. Cost/token fields are not in the log, so they are left out (aggregate
treats them as unknown, and the pass rates are unaffected).

    python evals/partial_from_logs.py LOG --model gemini-3.7-flash [--label bash-only]
"""
import argparse
import datetime
import json
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
LINE = re.compile(r"^\s+(PASS|FAIL|INFRA_ERROR)\s+(\S+)\s+#(\d+)\s+\((\d+)s\)")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("log")
    p.add_argument("--model", required=True)
    p.add_argument("--label")
    args = p.parse_args()

    raw = open(args.log, "rb").read()
    text = raw.decode("utf-16") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "replace")
    results = []
    for line in text.splitlines():
        m = LINE.match(line)
        if not m:
            continue
        outcome, tid, attempt, secs = m.group(1).lower(), m.group(2), int(m.group(3)), int(m.group(4))
        spec = os.path.join(HERE, "tasks", tid, "task.json")
        meta = json.load(open(spec, encoding="utf-8")) if os.path.isfile(spec) else {}
        results.append({"id": tid, "category": meta.get("category"), "difficulty": meta.get("difficulty"),
                        "attempt": attempt, "outcome": outcome, "passed": outcome == "pass",
                        "seconds": float(secs)})
    payload = {"model": args.model, "partial": True, "source_log": os.path.basename(args.log), "results": results}
    if args.label:
        payload["label"] = args.label
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(HERE, "results", f"{stamp}-partial{'-' + args.label if args.label else ''}.json")
    json.dump(payload, open(out, "w", encoding="utf-8"), indent=1)
    print(f"{len(results)} runs -> {out}")


if __name__ == "__main__":
    main()
