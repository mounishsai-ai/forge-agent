#!/usr/bin/env bash
# Score Forge's predictions with the official SWE-bench harness (swebench==5.0.2), on the VM.
#
#   bash ~/forge/swebench/evaluate.sh [OUT_DIR] [RUN_ID] [MAX_WORKERS]
#   e.g. bash ~/forge/swebench/evaluate.sh ~/swebench-runs/pilot forge-pilot 3
#
# Only the instances in OUT_DIR/selection.json are evaluated (--instance_ids), so the harness'
# total_instances equals the subset size; selected instances with no prediction count as unresolved.
# Harness logs go to OUT_DIR/logs/run_evaluation/<RUN_ID>/, the report to
# OUT_DIR/forge-gemini-3.7-flash.<RUN_ID>.json.
# Flags verified against swebench 5.0.2 swebench/harness/run_evaluation.py (argparse block).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
OUT="$(cd "${1:-$HOME/swebench-runs/main}" && pwd)"
RUN_ID="${2:-forge-$(date +%Y%m%d-%H%M)}"
WORKERS="${3:-4}"          # harness guidance: <= 75% of CPU cores (6 on n2-standard-8)
PY="${PYTHON:-$HOME/sb-venv/bin/python}"
[ -x "$PY" ] || PY=python3

test -f "$OUT/predictions.jsonl" || { echo "no $OUT/predictions.jsonl"; exit 1; }
test -f "$OUT/selection.json"    || { echo "no $OUT/selection.json"; exit 1; }
IDS=$("$PY" -c 'import json,sys; print(" ".join(json.load(open(sys.argv[1]))["instance_ids"]))' "$OUT/selection.json")
echo "Evaluating $(echo "$IDS" | wc -w) selected instances, run_id=$RUN_ID, workers=$WORKERS"

cd "$OUT"   # the harness writes logs/run_evaluation/... relative to the current directory
# shellcheck disable=SC2086
"$PY" -m swebench.harness.run_evaluation \
  --dataset_name SWE-bench/SWE-bench_Verified \
  --split test \
  --predictions_path predictions.jsonl \
  --instance_ids $IDS \
  --max_workers "$WORKERS" \
  --timeout 1800 \
  --run_id "$RUN_ID" \
  --report_dir "$OUT"

echo
"$PY" "$HERE/summarize.py" --out "$OUT" --run-id "$RUN_ID" --json
