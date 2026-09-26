"""Run Forge on SWE-bench Verified instances and write predictions for the official harness.

Runs ON THE VM (Linux + Docker). For each selected instance:
  1. pull the prebuilt SWE-bench image (the dataset's `image` field, e.g.
     swebench/sweb.eval.x86_64.django_1776_django-11099:latest)
  2. start a container (sleep entrypoint, --network host so Vertex AI + the GCE metadata
     server for credentials are reachable) with Forge's runtime mounted read-only at /opt/forge-rt
  3. run `forge -p <issue + instructions> --yes --json` with cwd /testbed, under `timeout -s INT`
     *inside* the container, with FORGE_SHELL_INIT activating the testbed conda env
  4. extract the patch: git add -A && git diff --cached <base_commit>
  5. append the prediction to predictions.jsonl and stats to stats.jsonl, remove the container

Forge's runtime (uv-managed Python 3.11 + google-genai + rich + Forge itself) is built ONCE on
the host in /opt/forge-rt and bind-mounted read-only into every container. It is completely
separate from the repo's `testbed` conda env, and the agent can't modify it.

Usage (see swebench/README.md):
    python swebench/run_forge.py --prepare-only                 # build /opt/forge-rt, smoke test imports
    python swebench/run_forge.py --n 3 --seed 42 --workers 1    # pilot
    mkdir -p ~/swebench-runs && nohup python swebench/run_forge.py --n 50 --seed 42 --workers 4 --out ~/swebench-runs/main > ~/swebench-runs/main.out 2>&1 &
    python swebench/run_forge.py --ids django__django-11099 sympy__sympy-20590

Resumable: instance ids already in predictions.jsonl are skipped. The chosen instance list is
frozen in <out>/selection.json so evaluation and reporting use the same denominator.
"""
import argparse
import datetime
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(HERE)

DATASET = "SWE-bench/SWE-bench_Verified"   # same 500 ids as princeton-nlp/..., but has the fields swebench 5.x needs
MODEL = "gemini-3.7-flash"
MODEL_NAME = "forge-gemini-3.7-flash"      # model_name_or_path in predictions (also names the harness report)
# From the dataset's own eval_script: "source /opt/miniconda3/bin/activate; conda activate testbed"
SHELL_INIT = "source /opt/miniconda3/bin/activate && conda activate testbed"
RUNTIME = "/opt/forge-rt"                  # host dir, mounted read-only at the same path in containers

PROMPT_TEMPLATE = """<issue>
{problem_statement}
</issue>

The repository with the code for this issue is checked out in the current working directory (/testbed).
Your task: make the minimal changes to non-test source files in /testbed so that the issue above is resolved.

Instructions:
- Do NOT modify or delete existing tests or test files; the fix is evaluated with hidden tests.
- Explore the code first (list_dir, grep, read_file) to find where the problem is.
- You may write small scripts and run code (python, pytest) with run_shell to reproduce the issue and verify your fix.
  The shell already has the project's Python environment activated.
- Keep the change focused; match the existing code style; handle closely related edge cases.
- When done, delete any scratch/reproduction files you created, so that only the fix remains.
- Do not commit; just leave the changes in the working tree.
"""

write_lock = threading.Lock()


# ---------------------------------------------------------------- helpers

def now() -> str:
    return datetime.datetime.now().strftime("%H:%M:%S")


def say(msg: str) -> None:
    print(f"[{now()}] {msg}", flush=True)


class InstanceLog:
    """Per-instance log file: every command, its exit code and (truncated) output."""

    def __init__(self, path: str):
        self.f = open(path, "a", encoding="utf-8", errors="replace")
        self.write(f"===== {datetime.datetime.now().isoformat()} =====")

    def write(self, text: str) -> None:
        self.f.write(text.rstrip("\n") + "\n")
        self.f.flush()

    def close(self) -> None:
        self.f.close()


def run(cmd: list[str], log: InstanceLog | None, timeout: float | None = None, check: bool = True,
        quiet: bool = False, max_log: int = 20_000) -> subprocess.CompletedProcess:
    """Run a host command, log it, return CompletedProcess (text). Raises on failure if check."""
    shown = " ".join(c if len(c) < 200 else c[:200] + "...<truncated>" for c in cmd)
    if log:
        log.write(f"$ {shown}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired as e:
        if log:
            log.write(f"[timed out after {timeout}s]")
        raise RuntimeError(f"command timed out after {timeout}s: {shown}") from e
    if log and not quiet:
        out = (r.stdout or "") + (("\n[stderr]\n" + r.stderr) if r.stderr and r.stderr.strip() else "")
        if len(out) > max_log:
            out = out[:max_log // 2] + f"\n...<{len(out) - max_log} chars truncated>...\n" + out[-max_log // 2:]
        log.write(out)
        log.write(f"[exit {r.returncode}]")
    if check and r.returncode != 0:
        raise RuntimeError(f"command failed (exit {r.returncode}): {shown}\n{(r.stderr or r.stdout)[-2000:]}")
    return r


def find_uv() -> str:
    uv = shutil.which("uv") or os.path.expanduser("~/.local/bin/uv")
    if not os.path.exists(uv):
        sys.exit("uv not found. Run swebench/vm_bootstrap.sh first.")
    return uv


def image_name(row: dict) -> str:
    if row.get("image"):
        return row["image"]
    # Fallback: SWE-bench's Docker Hub naming (dunders are not allowed in Docker Hub names).
    return f"swebench/sweb.eval.x86_64.{row['instance_id']}:latest".lower().replace("__", "_1776_")


def append_jsonl(path: str, obj: dict) -> None:
    with write_lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(obj) + "\n")
            f.flush()
            os.fsync(f.fileno())


def read_jsonl(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    pass   # a line cut off by a crash; that instance will simply be re-run
    return rows


def last_json_line(text: str) -> dict | None:
    for line in reversed(text.strip().splitlines()):
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return None


# ---------------------------------------------------------------- runtime (built once on the host)

def prepare_runtime(forge_src: str, runtime: str) -> None:
    """uv-managed Python 3.11 + venv with Forge and its deps in `runtime`. Idempotent; reinstalls Forge."""
    uv = find_uv()
    if not os.access(runtime, os.W_OK):
        sys.exit(f"{runtime} is not writable. Run: sudo mkdir -p {runtime} && sudo chown $USER {runtime}")
    env = {**os.environ, "UV_PYTHON_INSTALL_DIR": f"{runtime}/python", "UV_PYTHON_PREFERENCE": "only-managed"}
    py = f"{runtime}/venv/bin/python"

    def step(cmd):
        say("  $ " + " ".join(cmd))
        subprocess.run(cmd, env=env, check=True)

    step([uv, "python", "install", "3.11"])
    if not os.path.exists(py):
        step([uv, "venv", "--python", "3.11", f"{runtime}/venv"])
    # Non-editable install: Forge's code is copied into the venv, so the container needs no source checkout.
    step([uv, "pip", "install", "--python", py, "--reinstall-package", "forge-agent", forge_src])
    step([py, "-c", "import forge, google.genai, rich, sys; print('forge runtime OK', sys.version.split()[0])"])
    if not os.path.exists(f"{runtime}/venv/bin/forge"):
        sys.exit(f"{runtime}/venv/bin/forge was not created")
    # Record which Forge version is baked into the runtime.
    commit_file = os.path.join(forge_src, "FORGE_COMMIT")
    commit = open(commit_file).read().strip() if os.path.exists(commit_file) else "unknown"
    with open(f"{runtime}/FORGE_COMMIT", "w") as f:
        f.write(commit + "\n")


# ---------------------------------------------------------------- one instance

def run_instance(row: dict, args, out: str) -> dict:
    iid = row["instance_id"]
    log = InstanceLog(os.path.join(out, "logs", f"{iid}.log"))
    image = image_name(row)
    cname = "forge." + re.sub(r"[^a-z0-9_.-]", "-", iid.lower())
    stats = {"instance_id": iid, "image": image, "model": args.model, "max_turns": args.max_turns,
             "started": datetime.datetime.now().isoformat(timespec="seconds"), "status": "running"}
    t0 = time.time()
    started_container = False
    try:
        # 1. image
        if run(["docker", "image", "inspect", image], log, check=False, quiet=True).returncode != 0:
            t = time.time()
            for attempt in range(3):
                r = run(["docker", "pull", "-q", image], log, timeout=1800, check=False)
                if r.returncode == 0:
                    break
                log.write(f"pull failed (attempt {attempt + 1}/3); retrying")
                time.sleep(30 * (attempt + 1))
            else:
                raise RuntimeError(f"docker pull failed for {image}")
            stats["pull_seconds"] = round(time.time() - t, 1)

        # 2. container
        run(["docker", "rm", "-f", cname], log, check=False, quiet=True)
        run(["docker", "run", "-d", "--name", cname, "--network", "host",
             "-v", f"{args.runtime}:{args.runtime}:ro",
             "--entrypoint", "sleep", image, "infinity"], log, timeout=300)
        started_container = True

        def dexec(cmd: str, timeout: float = 300, check: bool = True, **kw) -> subprocess.CompletedProcess:
            return run(["docker", "exec", cname, "bash", "-c", cmd], log, timeout=timeout, check=check, **kw)

        head = dexec("git -C /testbed rev-parse HEAD").stdout.strip()
        stats["head_matches_base"] = head == row["base_commit"]
        if head != row["base_commit"]:
            log.write(f"WARNING: /testbed HEAD {head} != base_commit {row['base_commit']}")
        dexec("git -C /testbed status --porcelain | head -20")
        # Forge's own state dir must never end up in the patch.
        dexec("mkdir -p /testbed/.git/info && printf '.forge/\\n' >> /testbed/.git/info/exclude")
        # Sanity check that FORGE_SHELL_INIT works in this image (logged; not fatal).
        dexec(f"{SHELL_INIT} && python --version && which python", check=False)

        # 3. Forge
        prompt = PROMPT_TEMPLATE.format(problem_statement=row["problem_statement"].strip())
        env = ["-e", f"FORGE_PROJECT={args.project}", "-e", f"FORGE_SHELL_INIT={SHELL_INIT}",
               "-e", "PYTHONUNBUFFERED=1"]
        if os.environ.get("FORGE_LOCATION"):
            env += ["-e", f"FORGE_LOCATION={os.environ['FORGE_LOCATION']}"]
        # The console script (not `python -m forge`) keeps /testbed off Forge's own sys.path, so a
        # repo module named e.g. `requests` can't shadow the libraries Forge itself imports.
        # SIGINT first: Forge catches KeyboardInterrupt, stops cleanly and still prints its usage JSON.
        forge_cmd = ["timeout", "-s", "INT", "-k", "60", str(args.timeout), f"{args.runtime}/venv/bin/forge",
                     "-p", prompt, "--yes", "--json", "--verbose",
                     "--model", args.model, "--no-fallback", "--max-turns", str(args.max_turns)]
        t = time.time()
        log.write("----- forge run -----")
        timed_out = False
        try:
            r = run(["docker", "exec", "-w", "/testbed", *env, cname, *forge_cmd], log,
                    timeout=args.timeout + 120, check=False, max_log=200_000)
            rc = r.returncode
            stdout = r.stdout or ""
            timed_out = rc in (124, 137)
        except RuntimeError:   # outer safety timeout; kill whatever is left in the container
            run(["docker", "exec", cname, "pkill", "-9", "-f", f"{args.runtime}/venv"], log, check=False)
            rc, stdout, timed_out = -1, "", True
        stats["agent_seconds"] = round(time.time() - t, 1)
        stats["forge_exit"] = rc
        stats["timed_out"] = timed_out
        result = last_json_line(stdout)
        if result:
            for k in ("error", "tool_calls", "input_tokens", "output_tokens", "thinking_tokens",
                      "cost_usd", "model_used", "seconds"):
                stats[k] = result.get(k)
            stats["final_message"] = (result.get("result") or "")[:2000]
            if result.get("result") == "(interrupted)":
                timed_out = stats["timed_out"] = True
        else:
            stats["error"] = stats.get("error") or ("timed out" if timed_out else "no JSON output from forge")

        # 4. patch
        log.write("----- patch -----")
        p = dexec(f"git -C /testbed add -A && git -C /testbed -c core.fileMode=false diff --cached {row['base_commit']}",
                  timeout=300, max_log=100_000)
        patch = p.stdout or ""
        if patch and not patch.endswith("\n"):
            patch += "\n"
        files = re.findall(r"^diff --git a/(\S+) b/", patch, flags=re.M)
        stats["patch_files"] = files
        stats["patch_lines"] = patch.count("\n")
        stats["touched_tests"] = [f for f in files if re.search(r"(^|/)(tests?|testing)(/|_)|test_[^/]*\.py$|_tests?\.py$", f)]

        # 5. record. An agent that crashed before doing anything (e.g. Vertex auth error) is NOT
        # recorded as a prediction, so a resume retries it; if it never succeeds it still counts
        # as unresolved because evaluation uses the frozen selection as the denominator.
        # A timed-out run is never retried (pass@1): it is recorded even with an empty patch.
        no_work = (not patch.strip()) and not (stats.get("tool_calls") or 0) and bool(stats.get("error")) \
            and not timed_out
        if no_work:
            stats["status"] = "agent_error_no_work"
        else:
            append_jsonl(os.path.join(out, "predictions.jsonl"),
                         {"instance_id": iid, "model_name_or_path": MODEL_NAME, "model_patch": patch})
            stats["status"] = "timed_out" if timed_out else ("agent_error" if stats.get("error") else "ok")
    except Exception as e:
        stats["status"] = "infra_error"
        stats["error"] = f"{type(e).__name__}: {e}"[:2000]
        log.write(traceback.format_exc())
    finally:
        if started_container:
            run(["docker", "rm", "-f", cname], log, check=False, quiet=True)
        free_gb = shutil.disk_usage("/").free / 1e9
        stats["disk_free_gb"] = round(free_gb, 1)
        if args.rm_images or free_gb < args.min_free_gb:
            run(["docker", "rmi", image], log, check=False)
        stats["wall_seconds"] = round(time.time() - t0, 1)
        log.write("----- stats -----\n" + json.dumps(stats, indent=2))
        log.close()
        append_jsonl(os.path.join(out, "stats.jsonl"), stats)
    return stats


# ---------------------------------------------------------------- selection + main

def load_dataset_rows(name: str, split: str) -> dict[str, dict]:
    from datasets import load_dataset
    ds = load_dataset(name, split=split)
    return {r["instance_id"]: dict(r) for r in ds}


def choose_ids(all_ids: list[str], args, out: str) -> list[str]:
    sel_path = os.path.join(out, "selection.json")
    existing = json.load(open(sel_path)) if os.path.exists(sel_path) else None
    if args.ids:
        unknown = [i for i in args.ids if i not in all_ids]
        if unknown:
            sys.exit(f"Unknown instance ids: {unknown}")
        ids, how = list(dict.fromkeys(args.ids)), {"method": "explicit ids"}
    elif args.n:
        ids = random.Random(args.seed).sample(sorted(all_ids), args.n)
        how = {"method": "seeded random sample", "seed": args.seed, "n": args.n}
    elif existing:
        return existing["instance_ids"]
    else:
        sys.exit("Pass --n N [--seed S] or --ids ... (or reuse an existing <out>/selection.json).")
    if existing and existing["instance_ids"] != ids:
        sys.exit(f"{sel_path} already holds a different selection. Use a new --out directory "
                 f"(or delete that file if you really mean to change the subset).")
    if not existing:
        with open(sel_path, "w") as f:
            json.dump({**how, "dataset": args.dataset, "split": args.split, "model": args.model,
                       "max_turns": args.max_turns, "timeout": args.timeout,
                       "created": datetime.datetime.now().isoformat(timespec="seconds"),
                       "forge_commit": open(f"{args.runtime}/FORGE_COMMIT").read().strip()
                       if os.path.exists(f"{args.runtime}/FORGE_COMMIT") else "unknown",
                       "instance_ids": ids}, f, indent=2)
    return ids


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ids", nargs="+", help="explicit instance ids")
    p.add_argument("--n", type=int, help="number of instances to sample at random")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--workers", type=int, default=4, help="parallel instances (VM has 8 vCPU)")
    # Outside the repo on purpose: `setup_vm.sh copy` replaces ~/forge and must not delete results.
    p.add_argument("--out", default=os.path.expanduser("~/swebench-runs/main"),
                   help="output dir (predictions, stats, logs)")
    p.add_argument("--model", default=MODEL)
    p.add_argument("--max-turns", type=int, default=50)
    p.add_argument("--timeout", type=int, default=1800, help="seconds per Forge run (enforced in-container)")
    p.add_argument("--dataset", default=DATASET)
    p.add_argument("--split", default="test")
    p.add_argument("--project", default=os.environ.get("FORGE_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT"))
    p.add_argument("--forge-src", default=REPO_ROOT)
    p.add_argument("--runtime", default=RUNTIME)
    p.add_argument("--rm-images", action="store_true", help="delete each instance image after use")
    p.add_argument("--min-free-gb", type=float, default=40, help="delete images when free disk drops below this")
    p.add_argument("--prepare-only", action="store_true", help="build the Forge runtime and exit")
    p.add_argument("--skip-prepare", action="store_true", help="don't rebuild the Forge runtime")
    args = p.parse_args()

    if not args.project:
        sys.exit("Set FORGE_PROJECT (e.g. export FORGE_PROJECT=<your-gcp-project-id>) or pass --project.")
    if not args.skip_prepare:
        say(f"Preparing Forge runtime in {args.runtime} from {args.forge_src}")
        prepare_runtime(args.forge_src, args.runtime)
    if args.prepare_only:
        say("Runtime ready. Smoke test: "
            f"FORGE_PROJECT={args.project} {args.runtime}/venv/bin/forge -p 'Reply with OK' --json "
            f"--model {args.model} --no-fallback")
        return
    if shutil.which("docker") is None:
        sys.exit("docker not found")

    out = os.path.abspath(args.out)
    os.makedirs(os.path.join(out, "logs"), exist_ok=True)
    say(f"Loading {args.dataset} [{args.split}]")
    rows = load_dataset_rows(args.dataset, args.split)
    ids = choose_ids(list(rows), args, out)
    done = {r["instance_id"] for r in read_jsonl(os.path.join(out, "predictions.jsonl"))}
    todo = [i for i in ids if i not in done]
    say(f"{len(ids)} selected, {len(ids) - len(todo)} already have predictions, {len(todo)} to run "
        f"with {args.workers} workers -> {out}")

    counts: dict[str, int] = {}
    cost = 0.0
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {pool.submit(run_instance, rows[i], args, out): i for i in todo}
        for n, fut in enumerate(as_completed(futures), 1):
            iid = futures[fut]
            try:
                s = fut.result()
            except Exception as e:   # run_instance catches everything; this is a last resort
                s = {"status": "crash", "error": repr(e)}
            counts[s["status"]] = counts.get(s["status"], 0) + 1
            cost += s.get("cost_usd") or 0
            say(f"[{n}/{len(todo)}] {iid}: {s['status']} | patch {s.get('patch_lines', 0)} lines | "
                f"{s.get('tool_calls')} tools | ${s.get('cost_usd') or 0:.3f} | {s.get('wall_seconds')}s"
                + (f" | {str(s.get('error'))[:150]}" if s.get("error") else ""))
    say(f"Finished. {counts} | this session's Forge cost ${cost:.2f}")
    missing = [i for i in ids if i not in {r['instance_id'] for r in read_jsonl(os.path.join(out, 'predictions.jsonl'))}]
    if missing:
        say(f"{len(missing)} selected instances have no prediction yet (re-run the same command to retry): "
            + " ".join(missing[:20]) + (" ..." if len(missing) > 20 else ""))


if __name__ == "__main__":
    main()
