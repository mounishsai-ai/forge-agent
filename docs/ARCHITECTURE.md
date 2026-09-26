# Forge Architecture

## Overview

Forge is a terminal-based AI coding agent, in the same shape as Claude Code: you type a request,
the agent reads and edits files in your project and runs shell commands on your behalf, and it keeps
going — calling tools, reading their output, calling more tools — until it has a final answer or hits
a safety cap. The model itself (Gemini, via the Gemini Enterprise Agent Platform, formerly Vertex AI)
never touches your disk or shell directly: it can only *ask* to run a tool by name with some arguments.
Everything that actually happens — checking permissions, running the tool, truncating huge output,
feeding the result back — is plain Python that this project owns and can explain line by line. That
control loop, not the model, is the part of this codebase worth defending in an interview.

## Diagram 1: the agent loop (`forge/agent.py`)

```
        user types a message
                |
                v
     Agent.run(user_text)
     append user_text to history
                |
                v
   .-----------------------------------------------------.
   |  loop, up to max_turns times:                        |
   |                                                       |
   |   context.maybe_compact()  <- shrink history first    |
   |          if it's already too big for this call        |
   |          |                                            |
   |          v                                            |
   |   llm.generate(history, tools, system)                |
   |          |                                            |
   |          v                                            |
   |   model wants tool calls? ----no----> return resp.text|
   |          |yes                              (done)     |
   |          v                                            |
   |   for each requested call:                            |
   |     Permissions.check()  -> denied? -> error string    |
   |     Hooks.pre_tool()     -> vetoed? -> error string     |
   |     tool.run(**args)     -> output (or ToolError text)  |
   |     Hooks.post_tool()                                   |
   |          |                                            |
   |          v                                            |
   |   append all results as ONE user message               |
   |   (+ a nudge if the same call repeated 3x)              |
   |          |                                            |
   |          '--------------- back to top ------------------'
   |                                                       |
   '-------------------------------------------------------'
                |
     (loop exhausted: "(stopped after N turns)")
```

## Diagram 2: module layout

`cli.py` is the wiring point. It is the only module that constructs everything else and hands the
finished pieces to one `Agent`. `agent.py` itself only imports `llm`, `context`, `permissions` and
`tools` — it does not know `cli`, `ui`, `hooks`, `session` or `subagent` exist; those are injected as
plain constructor arguments or method calls, which is what makes `Agent` easy to reuse (the sub-agent
in `subagent.py` builds a second, differently-configured `Agent` the exact same way).

```
                              cli.py (argparse, build_agent, repl / run_headless)
                                   |
        builds and injects:       |
   -------------------------------+-----------------------------------------
   |         |          |          |         |          |         |
   v         v          v          v         v          v         v
 llm.py  permissions  hooks.py  prompts.py  ui.py     session.py  subagent.py
 (Gemini)  .py                 (system                (save/load   (task tool:
   |                            prompt)     Console/    JSON w/     builds a
   v                                        QuietUI)    thought      2nd Agent)
 pricing.py                                             signatures)
 (cost per                        |
  model)                          v
                              forge/agent.py  <--- the loop itself
                                   |
                                   v
                              forge/tools/*  (registered in tools/__init__.py)
                              base.py (Tool, ToolError, resolve, truncate, files_read)
                              read_file / list_dir / glob / grep   (read-only)
                              write_file / edit_file / run_shell / todo  (needs_permission)

                              context.py (compaction) is called directly by agent.py and cli.py,
                              not by the tools.
```

## Module-by-module

### `forge/config.py` — settings
All tunables in one file. Five are read from environment variables at import time:
`FORGE_PROJECT` / `GOOGLE_CLOUD_PROJECT` (`PROJECT`, no hardcoded default — the agent refuses to run
without one), `FORGE_LOCATION` (`LOCATION`, default `"global"`), `FORGE_MODEL` (`MODEL`, default
`gemini-3.8-flash`), `FORGE_MAX_TURNS` (`MAX_TURNS`, default 50) and `FORGE_COMPACT_AT`
(`COMPACT_AT_TOKENS`, default 150,000). The rest are constants you edit in the file, not env vars:
`FALLBACK_MODELS`, `REQUEST_TIMEOUT` (60s), `TOOL_OUTPUT_LIMIT` (20,000 **characters**, not tokens),
`SHELL_TIMEOUT` (120s), `MEMORY_FILES`. **Why:** one place to tune behavior without hunting through
the codebase, and no secret or project ID baked into source that would leak if the repo is public.

### `forge/llm.py` — the only file that talks to the model
`GeminiLLM.generate(history, tools, system)` is the entire interface the rest of the app relies on:
give it the conversation so far, get back a provider-neutral `LLMResponse` (`text`, `tool_calls`,
`usage`, and the raw `content` to append to history unchanged). Internals:
- `_call_with_retry`: tries `self.model` then each model in `fallbacks`, skipping any model whose
  `broken_until[model]` timestamp is still in the future (the **circuit breaker** — a model that just
  failed is skipped for `BREAKER_SECONDS` = 600s, so a dead model doesn't cost a fresh timeout on every
  turn). For each healthy model it retries up to 2 attempts with exponential backoff + jitter
  (`min(2**attempt, 30) + random.random()`, so effectively ~1s then ~2s here since only 2 attempts run).
  A 504 or an `httpx.TimeoutException` skips straight to the next model (no point retrying a deadline
  that already used the full timeout); any other non-retryable `APIError` code (e.g. 400) raises
  immediately; codes in `RETRYABLE = {429, 500, 502, 503, 504}` get the retry+fallback treatment.
  `--no-fallback` passes `fallbacks=[]`, so only `self.model` is ever tried — useful for reproducible
  evals where you don't want a silent model swap.
- `_parse`: pulls token counts out of `usage_metadata`, prices the call via `pricing.cost(model, usage)`
  using the model that **actually answered** (important once fallback has kicked in), and separates
  `function_call` parts from plain-text parts (skipping `part.thought`, Gemini's internal reasoning
  trace, which is not shown to the user).
- **Why disable automatic function calling** (`AutomaticFunctionCallingConfig(disable=True)`): the
  `google-genai` SDK can run tool calls for you automatically, but then the interesting logic —
  permission checks, hooks, loop detection, truncation — would have to live inside SDK callbacks
  instead of in an explicit, readable loop. Writing the loop by hand is the entire point of this
  project as a portfolio piece.
- **`GeminiLLM.__init__` refuses to start without a project:** if `config.PROJECT` is empty (neither
  `FORGE_PROJECT` nor `GOOGLE_CLOUD_PROJECT` set), the constructor raises `SystemExit` immediately with
  a message telling the user which env var to set, rather than failing later with an opaque API error.
- **Limitation:** `pricing.PRICES` currently prices `gemini-3.8-flash` and `gemini-3.7-flash` (the first
  fallback), but not `gemini-3.5-flash` (the second fallback) or any other model. A turn answered by an
  unpriced model reports `cost_usd = 0` for that turn — `/cost` and the `--json` `cost_usd` field
  under-count whenever fallback has gone past the first fallback model. Cached tokens also aren't
  discounted in the cost formula.

### `forge/agent.py` — the loop
`Agent.run(user_text)` is described in the diagram above. Two more details worth naming:
- **Loop detection** (`recent_calls`): if the exact same tool name + JSON-serialized args repeats 3
  times in a row, a `[harness]` text part is appended telling the model to stop and try something
  else. This does **not** stop the loop — it's a nudge inside the next prompt, not a hard break.
- **Ctrl+C history repair** (`_repair_history`): if the user interrupts mid-turn, the last message in
  `history` may be a model turn that requested tool calls with no results yet. The Gemini API rejects a
  history where a `function_call` has no matching `function_response`, so `_repair_history` appends a
  synthetic `"Cancelled by user."` response for each dangling call so the next turn's request is valid.
- **`_execute`** never lets a tool crash the agent: `ToolError` (expected failures like "file not
  found") and bare `TypeError` (model passed bad arguments) are caught explicitly, and any other
  `Exception` is caught as a last resort — every failure becomes text the model reads back, not a
  Python traceback that kills the process.

### `forge/permissions.py` — the safety layer
Three modes: `ask` (writes/shell prompt the user; reads run free), `auto` (everything runs, used for
`--yes` and evals), `readonly` (anything with `needs_permission=True` is refused — this is what
sub-agents run under). The `BLOCKLIST` regex list is checked **first, in every mode including auto**,
and only against `run_shell` commands (it does not inspect `write_file`/`edit_file` arguments). Answers
from `ask_permission` (`y`/`n`/`a`) are cached per tool name in `always_allowed` for the rest of the
process (in memory only — a new run starts with a clean slate).
**Why exact-string patterns and not a sandbox:** a real sandbox (container, VM, restricted user) is out
of scope for a from-scratch harness project; the blocklist stops the most catastrophic single commands
someone might paste in, as a last line of defense, not a security boundary. **It is bypassable by
design** — see Known Limitations.

### `forge/hooks.py` — user-defined shell hooks
Loaded once from `.forge/hooks.json` at agent construction (`Hooks.load`). `pre_tool(name, args)` runs
after the permission check and can **veto** a call by exiting non-zero (its stdout+stderr becomes the
denial reason shown to the model). `post_tool` runs after the tool executes and just logs to
`Hooks.log` (in memory only, not persisted or included in `--json` output) — its own exit code and
output are not otherwise used. Matching is `re.fullmatch(hook["match"], tool_name)`, so a hook can
target one tool or a regex over several (e.g. `"edit_file|write_file"`). **Hooks run via
`subprocess.run(..., shell=True)`**, which on Windows means **cmd.exe**, not PowerShell, even though
`run_shell` itself uses PowerShell — a hook command written in PowerShell syntax won't work unmodified.
**Why:** this gives a user their own enforcement point (auto-formatting, linting, audit logging)
without touching Forge's own code, mirroring how real coding-agent harnesses expose hook points.

### `forge/context.py` — context window management
`maybe_compact` is called at the top of **every iteration** of the turn loop in `Agent.run` (i.e.
before each call to `llm.generate`, not just once per user message), and compares
`agent.last_prompt_tokens` (the input-token count from the *previous* API call) against
`COMPACT_AT_TOKENS`. `compact` asks the model itself to summarize the whole history using
`SUMMARY_PROMPT`, then replaces `agent.history` with two messages: the summary text and a short
model acknowledgment. **Why check before every model call instead of only once per user message:** a
single user request can trigger many tool-call round trips, and checking on every iteration catches
growth from tool output within that same turn, not just growth carried over from a previous one. It's
still a step behind in the sense that `last_prompt_tokens` reflects the *previous* call's size, not the
one about to be sent — so the check can only ever trigger one call late.

### `forge/tools/base.py` — what a tool is
`Tool` is a small dataclass: `name`, `description` (this is the **entire** signal the model uses to
decide when to call a tool — there's no other metadata), `parameters` (JSON schema), `run` (the actual
Python function), and `needs_permission`. `declaration()` turns it into a
`types.FunctionDeclaration` for the Gemini API. Two module-level helpers matter beyond the obvious:
- `resolve(path)`: relative paths resolve against `os.getcwd()` — there is **no jail/sandbox check**,
  so a tool can be pointed at an absolute path outside the project.
- `truncate(text, limit)`: keeps the head and tail of long output (`TOOL_OUTPUT_LIMIT` = 20,000 chars)
  so one huge result can't flood the context window. It is only applied inside `read_file`, `grep` and
  `run_shell`; `list_dir` and the `task` sub-agent's report are not truncated, and `glob` caps itself at
  200 matches instead of by character count.
- `files_read: set[str]` is a **module-level global** shared by every `Tool` instance in the process,
  including any sub-agent's tools. It backs the read-before-edit/overwrite guard described next.

### Read-before-edit guard (`edit_file.py`, `write_file.py`)
`edit_file` refuses to run unless the resolved path is already in `files_read`; `write_file` refuses to
overwrite an existing file unless it's in `files_read` (creating a brand-new file is always allowed).
**Why:** it stops the model from editing or clobbering a file based on a guess of what's inside it —
forcing "explore, then act." **Caveats worth knowing:** because `files_read` is a shared global, (1) a
sub-agent's `read_file` call marks a file as read for the *parent* agent too; (2) `/clear` does not
reset it, so mid-session it stays unlocked even after wiping the visible conversation; (3) a partial
read (via `offset`/`limit`) counts as a full read, and there's no staleness check if the file changes
on disk afterward.

### `edit_file.py` — exact-string, not diffs or line numbers
`edit_file(path, old_string, new_string, replace_all=False)` does `text.count(old_string)`: zero
matches is an error, more than one match is an error *unless* `replace_all=True` (forcing the caller —
the model — to add enough surrounding context to make the target unique). **Why exact-string matching
instead of unified diffs or line-number edits:** line numbers drift the instant the model miscounts or
another edit shifts things, and diffs need a diff-apply step that can itself fail to match context
lines. Exact-string substring matching is trivial to implement and impossible to apply to the "wrong"
place, because uniqueness is enforced before anything is written.

### `run_shell.py` — sandboxed by permission, not by process
Runs `powershell -NoProfile -NonInteractive -Command <command>` on Windows (`bash -c` elsewhere).
**Every call is a brand-new process** — `cd` or environment variables set in one call do not persist to
the next. Output is `stdout` + an appended `[stderr]` block + `[exit code N]`, then truncated; a
non-zero exit code is **not** turned into a tool failure — it's still returned as ordinary `output`
text with the exit code visible, and it's the model's job to notice and react. `needs_permission=True`
means it always goes through `Permissions.check` (blocklist + ask/auto/readonly).

### `forge/tools/todo.py` — planning tool that touches nothing
`current: list[dict]` is, like `files_read`, a **module-level global**. The model calls `todo` with the
full updated list each time (not a diff), and `/todo` in the REPL renders it. **Why a global and not
per-agent state:** simplicity — the tradeoff is that any agent instance in the process shares the same
list. `todo` has `needs_permission=False` (it changes nothing on disk), but `forge/tools/__init__.py`
deliberately excludes it from `READ_ONLY_TOOLS` by name (`t.name != "todo"`) with a comment noting its
list is shared state that belongs to the main agent — so a sub-agent does **not** get the `todo` tool
and can't overwrite the parent's plan.

### `forge/subagent.py` — the `task` tool
`make_task_tool(parent)` returns a `Tool` whose `run` builds a **second, fresh `Agent`**: same `llm`
(so it shares the parent's circuit-breaker/model state), `Permissions("readonly")`, `QuietUI(verbose=True)`,
`tools=READ_ONLY_TOOLS` (`read_file`, `list_dir`, `glob`, `grep` — `todo` is explicitly excluded, see
above), `max_turns=25`, no `hooks` (hooks are simply not passed in, so a
sub-agent's tool calls never trigger `.forge/hooks.json`), and **no `task` tool of its own**, which is
what prevents infinite sub-agent recursion. Its system prompt is `SUBAGENT_PROMPT` glued to the
parent's prompt *minus its first paragraph* (`parent.system_prompt.split("\n\n", 1)[1]`), so it still
inherits the "How to work" rules, environment facts, and project memory. After the child finishes,
`parent.usage.add(child.usage)` and `parent.tool_calls_made += child.tool_calls_made` — the sub-agent's
tokens count against the same session's cost. **Why:** exploring a large codebase (reading dozens of
files) fills the context with file dumps; delegating that to a sub-agent keeps only its short final
report in the main conversation, at the cost of tokens spent inside the child (which the parent still
pays for).

### `forge/ui.py` — output is never inline in the agent
`ConsoleUI` renders Markdown answers, syntax-highlighted shell previews, and interactive y/n/a prompts
via `rich`. `QuietUI` (used by `forge -p`) subclasses it and turns off everything except errors and,
with `--verbose`, the tool-call line; critically, **`QuietUI.ask_permission` always returns `"n"`** —
so a headless run without `--yes` (mode `auto`) can never approve a write, edit, or shell call; it will
always be denied and the model told so. **Why the split:** `Agent` never calls `print()` — it calls
`self.ui.*` — so the identical loop runs unattended in scripts/evals or interactively in a terminal
without any `if headless:` branching inside the loop itself.

### `forge/session.py` — save/resume
One JSON file per session at `.forge/sessions/<timestamp>.json` in the **current working directory**,
saved after every REPL turn and again on exit. `agent.model_dump(mode="json", exclude_none=True)` on
each `types.Content` is what makes this work for Gemini's **thought signatures** — opaque binary parts
attached to some model turns — because Pydantic's JSON mode base64-encodes bytes automatically; loading
back with `types.Content.model_validate(c)` reverses that. **What is *not* saved:** token usage, the
todo list, `files_read`, and `always_allowed` tools — a resumed session starts those fresh, and the
`model` field is recorded in the file but never actually applied back onto `agent.llm.model` on load
(the CLI's `--model`/default is what's used instead). **`--resume` only works in the interactive REPL**
(`cli.repl`) — `run_headless` (`forge -p`) never calls `session.load` or `session.save`, so one-shot
runs are not resumable.

### `forge/prompts.py` — building the system prompt
`build_system_prompt()` concatenates: `BASE` (role + house rules), an `Environment:` block (cwd, OS,
shell name, date), and `load_memory()` — the contents of `FORGE.md`/`AGENTS.md` from `~/.forge/` (user
level) then the current working directory (project level), each wrapped in an `<memory file="...">`
tag. **Why not walk up parent directories:** simplicity; it checks exactly those two locations, so a
memory file in a parent folder of the cwd is not picked up.

### `forge/pricing.py` — cost estimate
`cost(model, usage)` looks up a flat per-million-token input/output rate in `PRICES` and returns
`None` if the model isn't listed, in which case `llm.py` treats it as `0.0`. `PRICES` currently has
entries for `gemini-3.8-flash` and `gemini-3.7-flash` (both at the same introductory rate); the second
fallback (`gemini-3.5-flash`) and any model set manually via `/model` are unpriced and cost `$0` in the
report. Thinking tokens are billed at the output rate (`usage.output_tokens + usage.thinking_tokens`).

## Lifecycle of one request

1. User runs `forge -p "add a docstring to foo.py"` or types a line in the REPL.
2. `cli.main` parses args; either `run_headless(args)` or `repl(args)` is called.
3. `build_agent(args, ui)` constructs `GeminiLLM(model=args.model, fallbacks=...)`, `Permissions(mode)`,
   `build_system_prompt()`, `Hooks.load()`, wraps them in `Agent(...)`, and attaches the `task` tool
   from `make_task_tool(agent)` unless `--no-subagents`.
4. `agent.run(user_text)` is called. The user's text is appended to `self.history` immediately.
5. The turn loop begins (up to `max_turns` iterations):
   a. `context.maybe_compact(self)` checks the previous call's token count and summarizes history first
      if it's over `COMPACT_AT_TOKENS` — this check runs on every iteration, not just the first.
   c. `self.llm.generate(history, tools, system)` → `GeminiLLM._call_with_retry` picks a healthy model,
      calls `client.models.generate_content`, retries/falls back on transient errors, and
      `GeminiLLM._parse` turns the raw response into an `LLMResponse`.
   d. The raw `resp.content` is appended to `history` as-is (preserving thought signatures).
   e. If there's `resp.text`, `self.ui.assistant_text(text)` shows it.
   f. If there are no `resp.tool_calls`, `run` returns `resp.text` — done.
   g. Otherwise, for each call: `self.ui.tool_call(...)`, `Agent._execute(call)` → look up the `Tool`,
      `self.permissions.check(...)`, `self.hooks.pre_tool(...)`, `tool.run(**call.args)` inside a
      try/except that catches `ToolError`/`TypeError`/`Exception`, `self.hooks.post_tool(...)`,
      `self.ui.tool_result(...)`. The output is wrapped in a `function_response` Part.
   h. All results for this turn go back into `history` as a single `user`-role message; loop detection
      may append a `[harness]` nudge Part alongside them.
   i. Back to step 5a with the updated history.
6. When the model replies with no tool calls, `Agent.run` returns the final text. In the REPL,
   `session.save(sid, agent)` persists the conversation; in headless mode with `--json`, `run_headless`
   prints the result plus token/cost/timing fields.

## Known limitations / future work

- **No streaming.** `generate_content` is a single blocking call; the user (or script) sees nothing
  until the whole model turn is back, and the "thinking..." spinner is just a wait indicator.
- **Sequential tool execution.** When a model turn requests multiple tool calls, `agent.py` runs them
  one at a time in a Python `for` loop, even though nothing in principle stops them from being
  independent. Simpler to reason about and log, but slower for multi-file tasks.
- **No sandboxing beyond permissions.** There is no container, VM, or restricted OS user. `Permissions`
  and `BLOCKLIST` are the only barrier between the model and the real filesystem/shell.
- **The shell blocklist is bypassable by construction.** It's a small set of regexes checked only
  against `run_shell` commands. An earlier version was bypassed by `rm -rf /*` and `rm -r -f /`
  (found by testing); the `rm` pattern now handles any flag order/splitting and `/*`, but the approach
  is still defeatable (e.g. `find / -delete`, `python -c "import shutil; shutil.rmtree('/')"`). It also does not inspect
  `write_file`/`edit_file` arguments at all, so a destructive edit written through those tools is not
  screened.
- **Compaction is checked against a one-call-stale token count.** `maybe_compact` runs before every
  model call in the loop (not just once per user message), but it compares `last_prompt_tokens` from
  the *previous* API call against `COMPACT_AT_TOKENS` — so it's always judging the size of the request
  that already went out, not the one about to be sent, and can trigger at most one call late.
- **Cost tracking under-counts once the second fallback fires.** `pricing.PRICES` has real numbers for
  `gemini-3.8-flash` and `gemini-3.7-flash`; a turn answered by `gemini-3.5-flash` (the second fallback)
  or any other model set via `/model` reports `$0` for that turn.
- **Global mutable state (`files_read`, `todo.current`)** is shared across the parent agent and any
  sub-agent in the same process, with the cross-contamination effects described above.
- **No per-path sandbox in `tools/base.resolve`** — a tool can act on any path the OS user can reach,
  not just inside the project directory.
- **Hooks run through `cmd.exe`-style `shell=True`** on Windows, not the PowerShell used for
  `run_shell`, which is an easy footgun when writing a hook command.
- **No formal eval suite yet** — `evals/` exists as a placeholder; `--json` and `--no-fallback` were
  added specifically to support running reproducible headless evals against it.
