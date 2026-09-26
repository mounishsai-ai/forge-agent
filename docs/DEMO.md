# Recording a 3-minute Forge demo

A scripted terminal walkthrough for a screen recording. It hits every feature on the checklist:
streaming, tool calls, a permission prompt, `/todo`, a sub-agent `task`, `/cost`, `/undo`, MCP, skills,
headless `--json`, and running the eval suite on 2 tasks.

**Read this first, honestly:** each real agent turn in this repo's own eval logs (`evals/results/*.md`)
takes **60-100+ seconds** on `gemini-3.7-flash` — that's measured, not a guess. There is no way to
narrate 10+ live model turns inside 3 minutes of *real time*. Two ways to actually hit 3 minutes:

1. **Record everything at normal speed (~10-15 minutes raw), then cut/speed-ramp the boring parts** —
   the "thinking..." spinner and multi-turn tool loops — down to 3x-8x in your editor, keeping normal
   speed only for the moment you're talking over it (permission prompt, `/undo`, the JSON output). This
   is what the timing column below assumes.
2. **Record a shorter subset** (drop the MCP and eval-suite segments, keep the rest) if you'd rather not
   edit video at all.

Either way, **do the one-time setup below before you press record** — don't burn recording time on
`pip install` or typing out JSON files.

---

## One-time setup (before recording)

Run once, not on camera:

```powershell
cd "C:\workspace\AI CODING HARNESS"

# 1. Make sure Forge itself is installed and authenticated (see README Quickstart if not already done)
pip install -e .
gcloud auth application-default login
$env:FORGE_PROJECT = "your-gcp-project-id"

# 2. Confirm the demo project's two bugs still reproduce (should crash both times)
cd examples\demo_project
python main.py cart.json          # -> Total: $-809.73  (discount math bug)
python main.py cart_badcode.json  # -> KeyError: 'WELCOME'  (unknown discount code bug)

# 3. Give the demo project its own skill, custom command, and MCP server config.
#    (project-level .forge/ — Forge reads it from the CURRENT directory, so this only
#    applies when you run `forge` from inside examples\demo_project.)
New-Item -ItemType Directory -Force .forge\skills\cart-style, .forge\commands | Out-Null

@'
---
name: cart-style
description: Style rules for editing this cart demo. Load before changing cart.py or discounts.py.
---
When fixing bugs in this project:
- Keep functions small and keep the existing docstrings; update them if the bug they describe is fixed.
- Prefer raising a clear error or falling back to a sane default over letting a KeyError/ZeroDivisionError
  reach the user.
- After a fix, re-run `python main.py cart.json` and `python main.py cart_badcode.json` to confirm both
  are fixed before saying so.
'@ | Set-Content -Encoding utf8 .forge\skills\cart-style\SKILL.md

@'
Find every bug in this small project, fix it, and add tests\test_cart.py covering both fixes.
Use the todo tool to plan your steps first. $ARGUMENTS
'@ | Set-Content -Encoding utf8 .forge\commands\fixbugs.md

$repoRoot = (Resolve-Path "..\..").Path.Replace('\', '\\')
@"
{
  "mcpServers": {
    "echo": { "command": "python", "args": ["$repoRoot\\tests\\fixtures\\echo_mcp_server.py"] }
  }
}
"@ | Set-Content -Encoding utf8 .forge\mcp.json

# 4. Reset the two bug files in case a previous rehearsal already fixed them.
git -C "..\.." checkout -- examples/demo_project/cart.py examples/demo_project/discounts.py 2>$null
Remove-Item tests -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .forge\sessions, .forge\checkpoints -Recurse -Force -ErrorAction SilentlyContinue
```

Open a terminal at a large font size (18-20pt) in `examples\demo_project`, start your screen recorder,
and begin the script below.

---

## Script

| Time (edited) | You type / do | What to say while it runs |
|---|---|---|
| 0:00-0:10 | *(blank terminal, `examples\demo_project` folder open in an editor tab so viewers see `cart.py`/`discounts.py`)* | "This is Forge — a Claude-Code-style coding agent I built from scratch in Python, running on Gemini. This folder has two real bugs. Let's fix them with it." |
| 0:10-0:15 | `forge` | "Starting the interactive REPL." *(banner prints: version, model, mode, cwd)* |
| 0:15-0:35 | `> what does this project do, and why does python main.py cart_badcode.json crash?` | While the answer **streams** token-by-token: "Notice the answer is streaming live — and it's calling `read_file`/`glob` on its own to look at the code before answering." Point out the tool-call lines Forge prints before the answer. |
| 0:35-1:10 | `> there are two separate bugs here (one in cart.py, one in discounts.py). Make a todo list, then fix both, then add tests/test_cart.py covering both.` | "This needs several steps, so it's using the `todo` tool to track its own plan — `/todo` shows it any time." *(run `/todo` in a quick cutaway once it's populated)* |
| 1:10-1:25 | *(permission prompt appears for the first `edit_file`/`write_file` call)* — type `y` | "Every write or shell command asks first in `ask` mode — y, n, or a for 'always allow this tool for the rest of the session.'" |
| 1:25-1:30 | *(second prompt appears)* — type `a` | "I'll say 'always' this time so it doesn't ask again for every remaining edit." |
| 1:30-1:45 | *(let it finish: edits `cart.py`, `discounts.py`, writes `tests/test_cart.py`, likely runs pytest via `run_shell`)* | "It fixes both files, writes a test file, and runs it to confirm — that's the `run_shell` tool." |
| 1:45-1:55 | `/cost` | "This shows token usage and estimated cost so far — real dollar tracking, not just token counts." |
| 1:55-2:10 | `/checkpoints` then `/undo` | "Forge snapshots every file before it's changed, grouped by turn — no git required. `/undo` reverts the last turn's writes instantly." *(show `cart.py` back to its buggy state in the editor tab, then re-run the same fix prompt, or just narrate that a redo would just be asking again)* |
| 2:10-2:20 | `/mcp` | "This lists tools from any MCP server in `.forge/mcp.json` — I wrote the MCP client itself, stdio JSON-RPC, no SDK." |
| 2:20-2:30 | `> use the echo MCP tool to say "forge demo" and the add tool to add 40 and 2` | "It picks the right remote tool by name, exactly like a local one." |
| 2:30-2:45 | `> use a sub-agent to explain, in 3 bullets, how the discount percentage flows from discounts.py into cart.py` | "This delegates research to a fresh sub-agent with its own read-only context — keeps the main conversation from filling up with file dumps." |
| 2:45-2:50 | `/exit` | "Session auto-saves — `forge --resume` picks it back up later, `/undo` included." |
| 2:50-3:00 | `forge -p "list the two files that were fixed" --json` (in the same folder) | "And headless mode for scripts — `--json` prints tokens, cost, model, and timing as one line, which is exactly what feeds the eval harness." *(cut to the printed JSON, point at `cost_usd` / `tool_calls`)* |
| 3:00-3:10 *(bonus, cut if tight)* | `cd ..\..` then `python evals\run.py --tasks bugfix-average-score-crash feature-slugify` | "This is the actual eval harness — 26 tasks total — running two of them headlessly and grading the result with a checker script per task." *(cut to the printed pass-rate summary / the `.md` report in `evals/results/`)* |

---

## Cleanup after recording

```powershell
cd "C:\workspace\AI CODING HARNESS\examples\demo_project"
git -C ..\.. checkout -- examples/demo_project/cart.py examples/demo_project/discounts.py
Remove-Item tests -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item .forge -Recurse -Force -ErrorAction SilentlyContinue
```

## Notes / troubleshooting

- If a tool call errors instead of running, it's almost always a stale `.forge/mcp.json` path — the
  `$repoRoot` substitution above needs backslashes escaped for JSON (`\\`), which the script already does.
- If `/undo` says "Nothing to undo," you're in a fresh session with no tracked writes yet in this
  process. Note `/undo` itself only exists as a REPL slash command — headless `-p` runs still snapshot
  files in memory (`write_file`/`edit_file` call `checkpoints.record()` either way) but the process exits
  right after the one prompt, so there's no way to invoke `/undo` on them (see `forge/checkpoints.py`).
- `run_shell` changes (e.g. a `pip install` the model runs) are **not** covered by `/undo` — only
  `write_file`/`edit_file` are tracked. Say this out loud if it comes up; it's a real, documented
  limitation, not a bug.
- If you want a fully unattended (no `y`/`n` typing) take for the fix-the-bugs segment, add `--yes` to
  skip permission prompts — but then you lose the permission-prompt demo, so do that as a *second*,
  separate take rather than for the main recording.
