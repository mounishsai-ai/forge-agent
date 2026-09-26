# Forge

A Claude-Code-style AI coding agent, built from scratch in Python — own agent loop, own permission
system, own context management, running on Gemini via the Gemini Enterprise Agent Platform (formerly
Vertex AI).

## Features

- **Own agent loop** (`forge/agent.py`) — no SDK auto function-calling; every tool call is checked,
  executed, and fed back explicitly, up to a max-turns safety cap.
- **File tools**: `read_file`, `list_dir`, `glob`, `grep`, `write_file`, and `edit_file` (unique
  exact-string replacement, with a read-before-edit/overwrite guard).
- **`run_shell`** — PowerShell (or bash) with a timeout and truncated output.
- **Permissions** — `ask` / `auto` / `readonly` modes, per-tool "always allow," plus a shell command
  blocklist checked in every mode.
- **Hooks** (`.forge/hooks.json`) — run your own shell commands before/after any tool call; a `pre_tool`
  hook can veto a call.
- **Project memory** — `FORGE.md` / `AGENTS.md`, loaded from your home directory and the project root
  into the system prompt.
- **Sessions** — JSON transcripts (including Gemini's thought-signature bytes, base64-encoded) you can
  resume in the REPL.
- **Context management** — tool output truncation plus automatic summarization ("compaction") once the
  prompt gets large; `/compact` and `/clear` to force it.
- **Sub-agent (`task` tool)** — delegate research to a fresh, read-only agent so exploring a big
  codebase doesn't fill up the main conversation.
- **Todo tool** — the model keeps its own visible task list for multi-step work.
- **Retry / fallback / circuit breaker** — exponential backoff with jitter, automatic fallback across
  models, and a breaker that skips a model that just failed instead of retrying it every turn.
- **Per-call cost tracking** and a headless `--json` mode for scripting and evals.

## Quickstart

```powershell
# 1. Authenticate to the Gemini Enterprise Agent Platform (Vertex AI)
gcloud auth application-default login

# 2. Point Forge at your GCP project (either env var works)
$env:FORGE_PROJECT = "your-gcp-project-id"
# or: $env:GOOGLE_CLOUD_PROJECT = "your-gcp-project-id"

# 3. Install
pip install -e .

# 4. Run
forge                                   # interactive REPL
forge -p "list the files in src/"       # one-shot, headless; prints the final answer
forge -p "..." --json                   # one-shot, machine-readable result (for scripts/evals)
forge -p "..." --yes                    # auto-approve writes/shell (mode=auto) — needed for -p to write anything
forge -p "..." --no-fallback            # never switch models mid-run (reproducible evals)
forge --mode readonly                   # refuse anything that changes the machine
forge --resume                          # continue your most recent REPL session
forge --resume 20260926-140501          # continue a specific session by id
```

`--resume` is interactive-REPL only — a headless `-p` run doesn't save or load a session. Without
`--yes`, headless mode can't approve any write/edit/shell call (it's always denied), so pass `--yes` (or
`--mode auto`) if the task needs to touch the filesystem.

## Slash commands (interactive REPL)

| Command | What it does |
|---|---|
| `/help` | Show the command list |
| `/clear` | Start a fresh conversation |
| `/compact` | Summarize the conversation now, to free up context |
| `/cost` | Show token usage and estimated cost so far |
| `/model [name]` | Show or switch the model for the rest of the session |
| `/tools` | List available tools |
| `/todo` | Show the current task list |
| `/mode [ask\|auto\|readonly]` | Show or change the permission mode |
| `/sessions` | List saved sessions |
| `/exit` | Quit (session is auto-saved) |

## Configuration

Read from environment variables (`forge/config.py`):

| Variable | Default | Meaning |
|---|---|---|
| `FORGE_PROJECT` / `GOOGLE_CLOUD_PROJECT` | *(none — required)* | GCP project for the Gemini Enterprise Agent Platform |
| `FORGE_LOCATION` | `global` | API location |
| `FORGE_MODEL` | `gemini-3.8-flash` | Default model |
| `FORGE_MAX_TURNS` | `50` | Max tool-call round trips per user message |
| `FORGE_COMPACT_AT` | `150000` | Prompt tokens at which auto-compaction kicks in |

Other tunables are constants in `forge/config.py` you edit directly rather than env vars:
`FALLBACK_MODELS` (`gemini-3.7-flash`, `gemini-3.5-flash`), `REQUEST_TIMEOUT` (60s per model call),
`TOOL_OUTPUT_LIMIT` (20,000 characters), `SHELL_TIMEOUT` (120s), `MEMORY_FILES`.

Relevant CLI flags: `--model`, `--mode {ask,auto,readonly}`, `-y`/`--yes`, `--max-turns`,
`--no-subagents`, `--no-fallback` (disable model fallback for reproducible runs), `--json`, `--verbose`.

## Hooks

Create `.forge/hooks.json` in your project to run your own commands around tool calls. `pre_tool` hooks
that exit non-zero **block** the call (their output becomes the reason shown to the model). Hook
commands run through `shell=True`, which is **cmd.exe** on Windows, not PowerShell.

```json
{
  "pre_tool": [
    { "match": "run_shell", "command": "python check_cmd.py" }
  ],
  "post_tool": [
    { "match": "edit_file|write_file", "command": "ruff format ." }
  ]
}
```

`match` is a regex tested against the tool name with `re.fullmatch`.

## Project memory

Drop a `FORGE.md` or `AGENTS.md` file in your home directory (`~/.forge/FORGE.md`) for user-level
instructions, or in your project root for project-level ones — both are loaded into the system prompt
at startup (`forge/prompts.py`).

## Project layout

```
forge/
  __init__.py       version
  __main__.py        python -m forge entry point
  cli.py              argument parsing, REPL, headless mode, slash commands
  agent.py            the agent loop
  llm.py              Gemini provider: generate(), retry, fallback, circuit breaker
  pricing.py           per-model $ / token table
  config.py            all tunables / env vars
  permissions.py       ask / auto / readonly modes + shell blocklist
  hooks.py             .forge/hooks.json pre_tool / post_tool
  context.py           tool output truncation + auto-compaction
  session.py           save/resume conversations as JSON
  prompts.py           system prompt + project memory loading
  subagent.py          the `task` tool (delegates to a fresh sub-agent)
  ui.py                ConsoleUI (interactive) / QuietUI (headless)
  tools/
    base.py             Tool/ToolError, resolve(), truncate(), files_read guard
    read_file.py, list_dir.py, glob.py, grep.py    (read-only)
    write_file.py, edit_file.py, run_shell.py       (need permission)
    todo.py             the model's own task list
docs/
  ARCHITECTURE.md     module-by-module design + lifecycle walkthrough
  INTERVIEW.md         interview Q&A grounded in this code
evals/                 (planned) headless eval suite; see Evals below
```

## Evals

`evals/` is a placeholder today — no runner or tasks are committed yet. The planned design: a small
set of self-contained coding tasks, each its own folder with a starter `repo/` and a hidden `check.py`
grading script. `python evals/run.py` will copy each task's `repo/` into a fresh temp directory, run
`forge -p "<task prompt>" --yes --json --model gemini-3.7-flash --no-fallback` against it headlessly
(`--yes` so it can actually write/edit without a human approving, `--json` to capture tokens/cost/which
model answered, `--no-fallback` pinned to one model so runs are comparable to each other), then run that
task's `check.py` against the resulting `repo/` to grade pass/fail. The runner will report pass rate,
tokens, and cost across the suite. **Results coming soon — see `evals/`.**

## SWE-bench

Not implemented yet. The plan is a small pilot on a subset of SWE-bench Verified instances, run inside
Docker on a disposable VM (to sandbox `run_shell` against real, larger repositories) using the same
`forge -p --json --no-fallback` headless path as the `evals/` runner above. No numbers exist yet —
this section will be filled in once that pilot has actually run.

## Docs

- [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) — how it's built and why, module by module, with the
  agent-loop and module-layout diagrams and a full request lifecycle walkthrough.
- [`docs/INTERVIEW.md`](docs/INTERVIEW.md) — interview questions and answers grounded in this code.
