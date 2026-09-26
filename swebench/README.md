# SWE-bench Verified with Forge

Runs Forge on a subset of [SWE-bench Verified](https://www.swebench.com/) (500 human-validated
real GitHub issues from 12 Python repos) and scores the patches with the official harness.

```
your PC ──setup_vm.sh──> GCE VM (n2-standard-8, Docker)
                           │
  run_forge.py  ── for each instance ──────────────────────────────────────────┐
  │  docker pull swebench/sweb.eval.x86_64.<id>:latest  (repo at base commit,   │
  │  docker run  (sleep, --network host, /opt/forge-rt mounted read-only)       │
  │  docker exec -w /testbed  timeout 1800 forge -p "<issue + rules>" --yes --json
  │       Forge -> Gemini on Vertex AI (VM service account, no keys)             │
  │       run_shell -> bash with `conda activate testbed` (FORGE_SHELL_INIT)     │
  │  git add -A && git diff --cached <base_commit>  -> predictions.jsonl         │
  │  per-instance tokens/cost/time                    -> stats.jsonl, logs/<id>.log
  └──────────────────────────────────────────────────────────────────────────────┘
  evaluate.sh -> python -m swebench.harness.run_evaluation (applies each patch in a
                 fresh container, runs the hidden FAIL_TO_PASS / PASS_TO_PASS tests)
             -> summarize.py: resolved X/N + tokens + cost
```

| File | Where it runs | What it does |
|---|---|---|
| `setup_vm.sh` | your PC | create VM, IAM binding, copy code, ssh, fetch results, stop/delete |
| `vm_bootstrap.sh` | VM, once | Docker, git, python3, uv, `swebench==5.0.2` + `datasets` in `~/sb-venv` |
| `run_forge.py` | VM | runs Forge on each instance, writes `predictions.jsonl`, `stats.jsonl`, `selection.json`, `logs/<id>.log` into `~/swebench-runs/<name>/` |
| `evaluate.sh` | VM | official harness on exactly the selected ids, then `summarize.py` |
| `summarize.py` | anywhere | resolved rate + tokens + cost from a run directory |

## Decisions worth knowing (and defending)

- **Dataset name: `SWE-bench/SWE-bench_Verified`, not `princeton-nlp/SWE-bench_Verified`.**
  Same 500 instances, but the harness we pin (`swebench==5.0.2`, latest on PyPI on 2026-09-26)
  builds each test spec from the dataset fields `image`, `eval_script`, `log_parser`, `eval_type`
  (`swebench/harness/utils.py: make_test_spec`). Only the `SWE-bench/` copy has those columns;
  the `princeton-nlp/` copy would crash the harness with a `KeyError`. Checked with the Hugging
  Face datasets-server column listing for both names.
- **Images**: the `image` field of each row is the prebuilt Docker Hub image, e.g.
  `swebench/sweb.eval.x86_64.astropy_1776_astropy-12907:latest` (`__` becomes `_1776_`; the
  script derives that name itself if the field is ever missing). The harness pulls the same image.
- **Shell env**: `FORGE_SHELL_INIT="source /opt/miniconda3/bin/activate && conda activate testbed"`,
  taken from the dataset's own `eval_script` (it runs exactly `source /opt/miniconda3/bin/activate;
  conda activate testbed`). `run_forge.py` also runs it once per container and logs `python --version`,
  so you can check it in `~/swebench-runs/<name>/logs/<id>.log`. Verify on the first pilot instance.
- **Forge's own Python is isolated**: `run_forge.py --prepare-only` builds `/opt/forge-rt` on the VM
  (uv-managed Python 3.11 + venv with google-genai, rich and Forge installed non-editably, i.e. a copy
  of the source). It is bind-mounted **read-only** into every container, so the testbed conda env is
  untouched and the agent can't modify its own harness. (This replaces "copy the source into each
  container + install": same isolation, installed once instead of 50 times.) Forge is launched through
  its console script, so `/testbed` isn't on Forge's `sys.path` (e.g. the `requests` repo can't shadow
  the `requests` library Forge's auth uses).
- **Credentials**: none are copied anywhere. The VM's service account has `roles/aiplatform.user`;
  `--network host` lets Forge inside the container reach the GCE metadata server for tokens.
- **Timeout**: enforced *inside* the container (`timeout -s INT -k 60 1800 forge ...`), because killing
  `docker exec` doesn't kill the process inside. SIGINT lets Forge stop cleanly (it catches
  KeyboardInterrupt) and still print its token/cost JSON; if it has to be killed, `summarize.py` lists
  that run under `attempts_with_unrecorded_cost`. A timed-out run still submits whatever patch it made
  and is never retried.
- **No cheating**: the prompt is only the issue text (no hints, no test names). Forge is told not to
  touch tests; `stats.jsonl` records `touched_tests` so you can check. Hidden tests are only run by
  the harness, in a fresh container.
- **Outputs live outside the repo** (`~/swebench-runs/<name>/`), because `setup_vm.sh copy` replaces
  `~/forge` and must not delete a paid-for run.
- **Denominator**: `selection.json` freezes the chosen ids (seed, N). `evaluate.sh` passes them
  with `--instance_ids`, so the harness reports `total_instances = N`, and anything that crashed or
  has no prediction counts as **unresolved**.

## Machine size (read-only quota check, 2026-09-26)

`gcloud compute regions describe us-central1` / `project-info describe` on `divyastra-agent-37057`:

| Quota | Limit | Consequence |
|---|---|---|
| CPUS_ALL_REGIONS | **12** | the binding limit: max 12 vCPUs in total |
| N2_CPUS (us-central1) | 32 | n2 is allowed |
| SSD_TOTAL_GB (us-central1) | **250** | pd-balanced counts as SSD: a 250 GB disk uses **all** of it |
| PREEMPTIBLE_CPUS | **0** | no Spot VMs on the free trial |

=> **n2-standard-8** (8 vCPU, 32 GB) + 250 GB pd-balanced, us-central1-a, Ubuntu 22.04.
SWE-bench asks for >= 8 cores, >= 16 GB RAM, >= 120 GB free disk. n2-standard-16 would exceed 12 vCPUs.
Instance images are 1-4 GB each (layers shared within a repo); `run_forge.py` deletes images when free
disk drops below 40 GB (`--min-free-gb`), which just means the evaluator pulls them again.

## Step by step

All commands from the repo root. On Windows use Git Bash. Nothing here runs automatically.

**1. Create the VM + allow it to call Gemini** (your PC)
```bash
bash swebench/setup_vm.sh create
bash swebench/setup_vm.sh iam        # roles/aiplatform.user for the VM's default service account; ~1-2 min to apply
```

**2. Copy Forge to the VM** (your PC). **Commit everything first** (including `forge/config.py` /
`forge/tools/run_shell.py`, where `FORGE_SHELL_INIT` lives): the copy records `git rev-parse HEAD`
(+ "dirty" if there are uncommitted changes) in `~/forge/FORGE_COMMIT`, and the result line names that
commit, flagged DIRTY if the code that ran isn't in it. Re-run `copy` + `run_forge.py --prepare-only`
after any change to Forge.
```bash
bash swebench/setup_vm.sh copy
bash swebench/setup_vm.sh ssh
```

**3. Bootstrap** (on the VM)
```bash
bash ~/forge/swebench/vm_bootstrap.sh
exit                                  # log out + back in so the docker group applies
```
```bash
bash swebench/setup_vm.sh ssh         # (your PC) back in
docker run --rm hello-world           # docker works without sudo
docker login                          # optional but recommended: free Docker Hub account, avoids anonymous pull limits
```

**4. Build Forge's runtime and smoke-test Gemini** (VM; `~/.bashrc` already exports FORGE_PROJECT and activates `~/sb-venv`)
```bash
cd ~/forge
python swebench/run_forge.py --prepare-only
/opt/forge-rt/venv/bin/forge -p "Reply with OK" --json --model gemini-3.7-flash --no-fallback
```
Expect one JSON line with `"result": "OK"` and non-zero tokens. A 403 means the IAM binding hasn't applied yet.

**5. Pilot: 3 instances** (VM) - measures tokens/instance and checks every step
```bash
python swebench/run_forge.py --n 3 --seed 1 --workers 1 --out ~/swebench-runs/pilot --skip-prepare
cat ~/swebench-runs/pilot/stats.jsonl | jq '{instance_id,status,tool_calls,input_tokens,output_tokens,cost_usd,patch_lines,touched_tests}'
less ~/swebench-runs/pilot/logs/*.log    # check: HEAD matches base, "python --version" ran in testbed, a sane diff
bash swebench/evaluate.sh ~/swebench-runs/pilot forge-pilot 3
```

**6. The real run** (VM) - e.g. 50 instances, in the background so it survives ssh disconnects
```bash
mkdir -p ~/swebench-runs && nohup python swebench/run_forge.py --n 50 --seed 42 --workers 4 --skip-prepare --out ~/swebench-runs/main \
  > ~/swebench-runs/main.out 2>&1 &
tail -f ~/swebench-runs/main.out      # one line per finished instance
python swebench/summarize.py --out ~/swebench-runs/main    # running totals (tokens/cost) at any time
```
If it stops (crash, VM restart), run the **same command** again: ids already in `predictions.jsonl`
are skipped. Instances where Forge failed before doing anything (e.g. an API error) have no
prediction, so they are retried too.

**7. Evaluate** (VM)
```bash
bash swebench/evaluate.sh ~/swebench-runs/main forge-v1 6
```
Prints the harness summary, then `summarize.py` output and a one-line result.

**8. Get results, then tear down** (your PC)
```bash
bash swebench/setup_vm.sh fetch       # VM ~/swebench-runs -> swebench/out/vm-<date>/ (gitignored)
bash swebench/setup_vm.sh delete      # deletes VM + disk; billing stops. Free credits expire soon!
```
Use `setup_vm.sh stop` between sessions if you're not done (disk still costs ~$0.8/day).

## Cost and time estimates

Tokens per instance are **unknown until the pilot**. Formula (gemini-3.7-flash intro price,
same as `forge/pricing.py`; thinking tokens are billed as output):

```
cost per instance = (input_tokens * $0.75 + (output_tokens + thinking_tokens) * $3.75) / 1,000,000
total Gemini cost = N * average cost per instance        (take the average from the pilot)
```

Order of magnitude: an agent loop re-sends the growing conversation every turn, so input dominates.
E.g. 30 turns with ~40k tokens of context on average = 1.2M input tokens (~$0.90) + ~40k
output/thinking (~$0.15), so roughly **$0.5-2 per instance**, i.e. **$25-100 for 50 instances**.
Replace this with `summarize.py`'s `cost_per_instance_usd` from the pilot before scaling up.

VM: n2-standard-8 ~ $0.39/h + disk ~ $0.035/h (us-central1 on-demand list prices; check the
pricing page). Time: ~5-20 min per instance for Forge (+ image pull the first time),
4 in parallel -> 50 instances in ~2-4 h; evaluation ~1-2 min per instance with 6 workers.
50 instances => roughly 4-6 VM hours ~ $2-3, much less than the Gemini cost.

## Reporting results honestly

Use `summarize.py`'s result line, which contains everything needed:

> Forge resolved **X/N** (Y%) on a seeded random subset (seed 42) of N instances of **SWE-bench
> Verified**, model **gemini-3.7-flash** (pass@1, no hints, max 50 turns, Forge commit abc123);
> total Gemini cost $Z.

Rules:
- Say **subset of N**, with the seed. Never write "Y% on SWE-bench Verified" without that; a small
  subset has a wide margin of error (with N = 50, +/- ~13 percentage points at 95%).
- One attempt per instance (pass@1). If you re-run an instance to "get a better result", that's
  no longer pass@1; retries are only for infrastructure failures (no prediction produced).
- The denominator is N: timeouts, crashes and empty patches count as unresolved.
- Name the model and the scaffold (Forge); scores are not comparable with leaderboard entries that
  use other models or the full 500.
- Keep the run directory (predictions, logs, harness report) so the number can be reproduced/audited.

## Troubleshooting

- `403 PERMISSION_DENIED` from Vertex: wait for the IAM binding, check `setup_vm.sh iam` ran; the VM
  needs `--scopes=cloud-platform` (set at create time; changing it requires stopping the VM).
- `429` / `RESOURCE_EXHAUSTED`: lower `--workers`. Forge retries with backoff but `--no-fallback`
  (reproducibility) means it won't switch models.
- `toomanyrequests` on `docker pull`: `docker login`.
- Disk full: `docker image prune -a`, or run with `--rm-images`.
- The testbed env path: every log shows the output of the `FORGE_SHELL_INIT` check
  (`python --version && which python` should print `/opt/miniconda3/envs/testbed/bin/python`).
