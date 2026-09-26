# Forge — Interview Prep

## 60-second elevator pitch

"Forge is a Claude-Code-style coding agent I built from scratch in Python — no agent SDK doing the
work for me. It's a REPL where you type a task, and an agent loop repeatedly asks an LLM (Gemini, via
the Gemini Enterprise Agent Platform) what to do next, executes the tool calls it requests — reading
files, editing them with exact-string replacement, running shell commands, searching with glob/grep —
and feeds the results back until the model gives a final answer. Everything a real harness needs is
there: a permission system with a blocklist so it can't nuke your filesystem, hooks so you can plug in
your own linting/formatting, context compaction so long sessions don't blow the context window, JSON
sessions you can resume, a sub-agent tool for delegating research into a fresh context, and retry logic
with exponential backoff, model fallback, and a circuit breaker so a single overloaded model doesn't
stall the whole thing. I wrote my own loop instead of using the SDK's automatic function calling
specifically so I could explain every line of it in an interview."

## Core concepts

**Q: What is an agent harness, in your own words?**
A: The scaffolding around an LLM that turns it from a text-completion API into something that can act:
a loop that sends the model the conversation plus a list of tools it's allowed to call, lets the model
ask for a tool call by name and arguments, actually executes that call against the real machine, and
feeds the result back as the next message — repeating until the model stops asking for tools. The
model never touches the filesystem or shell itself; the harness (`forge/agent.py`) does, on its behalf.

**Q: Walk me through the loop.**
A: `Agent.run(user_text)` in `forge/agent.py`: append the user's message to history, then loop up to
`max_turns`. Each iteration calls `llm.generate(history, tools, system)`, appends the raw model message
back to history (so thought signatures round-trip), shows any text, and if there are no tool calls,
returns — done. Otherwise, for every requested call it checks permissions, runs any pre-tool hook,
executes the tool inside a try/except that can't crash the process, runs any post-tool hook, and
collects the output. All of that turn's tool results go back into history as one message, and the loop
repeats with the model seeing what happened.

**Q: Why write your own loop instead of using the SDK's automatic function calling?**
A: `google-genai` can execute your tools for you (`AutomaticFunctionCallingConfig`), but then permission
checks, hooks, loop detection, and truncation would have to be hidden inside SDK callbacks I don't
control end-to-end. I explicitly set `disable=True` on that config in `llm.py` and drive the loop myself
in `agent.py` so the control flow is fully visible, testable, and — for this project's purpose —
explainable line by line.

**Q: How do you stop the agent from deleting files or wiping the disk?**
A: Layered, not absolute. `Permissions.check` in `forge/permissions.py` runs a regex `BLOCKLIST`
against every `run_shell` command in *every* mode (even `auto`), catching things like `rm -rf /`,
`format`/`mkfs`/`diskpart`, `shutdown`/`reboot`, and force-push. Beyond the blocklist, any tool with
`needs_permission=True` (`write_file`, `edit_file`, `run_shell`) asks the user y/n/always unless mode is
`auto` or `readonly`. I'm upfront that this is not a sandbox — it's regex string matching, and I can show
bypasses: `rm -rf /*` and `rm -r -f /` beat the first version (I fixed that pattern), and things like
`find / -delete` or a Python one-liner calling `shutil.rmtree` still get past any regex. A real
production system would need an actual sandboxed execution environment on top of this.

**Q: How do you handle the context window filling up?**
A: Three layers, in `forge/context.py` and `forge/tools/base.py`. First, tool output is truncated at
the source — `truncate()` keeps head and tail up to `TOOL_OUTPUT_LIMIT` (20,000 characters) so one huge
file dump can't flood things. Second, `context.maybe_compact` runs before every single model call inside
the turn loop in `agent.py` (not just once per user message), and once the previous call's prompt token
count passes `COMPACT_AT_TOKENS` (150k by default), asks the model to summarize the whole conversation
and replaces history with that summary plus a short acknowledgment. Third, the user can force it with
`/compact` or wipe everything with `/clear`.

**Q: Why exact-string edits instead of diffs or line numbers?**
A: `edit_file` (`forge/tools/edit_file.py`) does `text.count(old_string)`: it fails if the string isn't
found, and fails if it's found more than once unless `replace_all=True` — forcing the model to include
enough surrounding context to make the target unique before anything is written. Line numbers drift
the moment the model miscounts or a previous edit shifted things; unified diffs need a diff-apply step
that can itself fail to match. Exact substring matching with a uniqueness check is simple to implement
and, because it's verified unique before writing, can't silently land on the wrong occurrence.

**Q: Why require reading a file before editing or overwriting it?**
A: `files_read`, a set in `forge/tools/base.py`, is populated by `read_file`. `edit_file` refuses to run
if the target path isn't in that set, and `write_file` refuses to overwrite an existing file that isn't
in it (creating a brand-new file is always fine). It stops the model from editing based on a guess of
file contents. Caveat I'd volunteer: it's a process-wide global, so a sub-agent reading a file also
unlocks it for the parent, and `/clear` doesn't reset it.

**Q: What happens when the API rate-limits you or a model is overloaded?**
A: `GeminiLLM._call_with_retry` in `llm.py`. Retryable HTTP codes (`429, 500, 502, 503, 504`) get up to
2 attempts per model with exponential backoff plus random jitter (`min(2**attempt, 30) + random.random()`).
A 504 or an `httpx` timeout skips straight to the next model instead of retrying, since the full
timeout was already spent waiting. If a model exhausts its attempts, it's marked "broken" for
`BREAKER_SECONDS` (600s) — the circuit breaker — so subsequent turns skip straight past it to a
fallback instead of paying that timeout again on every single call. Non-retryable errors (like a 400)
raise immediately.

**Q: What's a circuit breaker and why did you need one?**
A: A pattern where, after something fails, you stop calling it for a while instead of retrying every
time. `GeminiLLM.broken_until: dict[str, float]` records a "don't try again until" timestamp per model.
Without it, an overloaded model would eat a full `REQUEST_TIMEOUT` (60s) on *every* turn before falling
back, which is brutal in an interactive REPL.

**Q: What are thought signatures, and why do they matter here?**
A: Opaque parts Gemini attaches to some model turns as part of its internal reasoning trace. The
harness treats them as inert bytes: `agent.py` appends `resp.content` back into history completely
unchanged (never editing or dropping parts), and `session.py` relies on `model_dump(mode="json")` to
base64-encode them when saving to JSON and `model_validate` to decode them back on load. I've verified
empirically that switching models mid-conversation works — the same history, thought signatures
included, was accepted after moving from 3.7 to 3.5 to 3.1-pro to 2.5 flash — which is what makes model
fallback safe to do transparently inside a single ongoing conversation.

**Q: How would you add a new tool?**
A: One new file in `forge/tools/`, following the pattern in e.g. `read_file.py`: a plain Python function
that returns a string (or raises `ToolError` for expected failures), and a module-level `TOOL = Tool(name=...,
description=..., parameters=<JSON schema>, run=that_function, needs_permission=...)`. Then add it to the
`ALL_TOOLS` list in `forge/tools/__init__.py`. The model only ever sees the `name`, `description`, and
`parameters` schema — the description is the entire signal it uses to decide when to call it, so it has
to be precise.

**Q: How would you support another LLM provider (e.g. OpenAI)?**
A: `llm.py`'s docstring calls itself "the only file that talks to the model," but that's only half true
today: `GeminiLLM.generate()` is the interface the rest of the app calls, but `agent.py`, `context.py`,
`session.py`, and `Tool.declaration()` all construct or consume Gemini's own `google.genai.types`
objects (`types.Content`, `types.Part`, `types.FunctionDeclaration`) directly. So the honest answer is:
the *call* interface (`generate(history, tools, system) -> LLMResponse`) is already provider-neutral,
but the *message format* flowing through history is Gemini-shaped. Supporting a second provider
properly would mean introducing a provider-neutral message/part type that both providers translate
to/from, not just adding a second `generate()` implementation.

**Q: How do sessions work, and what's saved?**
A: `forge/session.py` writes one JSON file per session to `.forge/sessions/<timestamp>.json` in the
working directory, saved after every REPL turn and again on exit. It saves the full `history` (as
`types.Content.model_dump(mode="json")`, which is what base64-encodes any thought signature bytes) and
the model name. It does *not* save token usage, the todo list, `files_read`, or "always allow" choices —
a resumed session starts those fresh. Also worth knowing: `--resume` only works in the interactive REPL;
`forge -p` (headless) never saves or loads a session.

**Q: What's the sub-agent / `task` tool for?**
A: `forge/subagent.py`'s `make_task_tool` lets the main agent spin up a second `Agent` with its own
empty history, `Permissions("readonly")`, and only the read-only tools (`read_file`, `list_dir`, `glob`,
`grep`) — no `write_file`/`edit_file`/`run_shell`, no `task` tool of its own (so it can't recurse), and
no `todo` either: `forge/tools/__init__.py` excludes `todo` from `READ_ONLY_TOOLS` by name specifically
so a sub-agent can't touch the parent's shared task list. It's for broad exploration ("find where X is implemented") that would otherwise dump a lot of
file content into the main conversation; the sub-agent does that reading in its own context and returns
one short report. Its token usage is added back onto the parent's `Usage`, so cost tracking still
reflects the real total.

**Q: How does permission mode `auto` differ from just trusting the model?**
A: `auto` skips the "ask the user" step for tools with `needs_permission=True`, but the `BLOCKLIST`
regex check in `Permissions.check` still runs first, in every mode — it's the one check that's never
bypassed by mode. `auto` is what `--yes`/`-y` sets, and it's what evals/headless runs need since there's
no human to answer a y/n prompt.

**Q: How does the REPL differ from headless mode (`-p`)?**
A: Both build the identical `Agent`; the difference is the `UI` object. `ConsoleUI` (`forge/ui.py`)
prints Markdown, syntax-highlighted previews, and interactive prompts via `rich`. `QuietUI` — used for
`-p` — suppresses everything except errors (and tool-call lines under `--verbose`), and critically,
`QuietUI.ask_permission` always returns `"n"`: a headless run without `--yes` can't approve *any*
write/edit/shell call, it'll just be denied. `Agent` itself never calls `print()`; it only calls
`self.ui.*`, so no branching for headless mode lives inside the loop.

**Q: What does the `todo` tool actually do?**
A: Nothing to the machine — it just stores whatever list the model sends (`forge/tools/todo.py`,
`needs_permission=False`) in a module-level `current` list and renders it back. Its value is behavioral:
the system prompt tells the model to keep one for any 3+ step task and mark exactly one item
"in_progress," which measurably keeps longer multi-step tasks from losing the plot. Caveat: it's a
module-level global, so any agent sharing the process would share the same list — which is exactly why
`forge/tools/__init__.py` deliberately excludes `todo` from the tools it hands to a sub-agent.

**Q: How do hooks work?**
A: `.forge/hooks.json` defines `pre_tool` and `post_tool` lists, each `{"match": <regex on tool name>,
"command": <shell command>}`. `Hooks.pre_tool` runs after the permission check; if the command exits
non-zero, the call is vetoed and its output becomes the denial reason shown to the model — e.g. you
could block any `run_shell` call that doesn't pass a custom checker script. `post_tool` just runs after
the tool executes (for auto-formatting, logging) and its result isn't otherwise inspected. They run via
`subprocess.run(..., shell=True)`, which is `cmd.exe` on Windows — different from the PowerShell that
`run_shell` itself uses, so a hook command has to be written for the right shell.

**Q: What's the loop detection for?**
A: If the exact same tool name plus the same JSON-serialized arguments appears 3 times in a row,
`agent.py` appends a `[harness]` text part telling the model to stop and try a different approach. It's
a nudge inside the next prompt, not an actual break — the loop keeps running up to `max_turns` regardless.

**Q: What happens on Ctrl+C?**
A: At the input prompt, it exits the REPL (session is still saved). Mid-turn, `Agent.run` catches
`KeyboardInterrupt` and calls `_repair_history`: if the last history entry is a model turn with pending
tool calls that never got a response, it appends a synthetic `"Cancelled by user."`
`function_response` for each one — the Gemini API rejects a history with an unanswered `function_call`,
so this keeps the next request valid.

**Q: How would you evaluate whether this agent is actually good?**
A: The plan (see `evals/`, currently a placeholder) is a small suite of coding tasks, each with a
checker script that verifies the result, run headlessly via `forge -p --json` (which reports tool call
count, token usage, cost, and which model actually answered) and `--no-fallback` for reproducibility
across runs. I'd report pass rate, tokens, and cost per task. I'd also want to benchmark against a
standard like SWE-bench eventually, but I don't have numbers to share yet — that's explicitly future
work, not something I'd claim is done.

**Q: What was the hardest bug you hit building this?**
A: `gemini-3.8-flash` returning intermittent `504` (deadline exceeded) under load — a plain retry made
it worse because retrying the same overloaded model just burned the same timeout again. The fix was in
`llm.py`: treat 504 as "don't retry this model further, move to a fallback immediately" rather than
backing off and retrying it, plus the circuit breaker (`broken_until`) so once a model has failed it's
skipped outright for 10 minutes instead of being retried on every subsequent user turn.

## Security / risk questions

**Q: What's your biggest security concern with this design?**
A: Prompt injection via file contents. The model reads files with `read_file` and treats their contents
as data to reason about, but if a file (or a shell command's output) contains text engineered to look
like instructions, nothing currently distinguishes "content I should analyze" from "instructions I
should follow" — there's no isolation between tool output and instructions in the prompt. Second is
`run_shell`: it's a general-purpose shell escape hatch gated only by the permission system and a small,
bypassable regex blocklist, not a sandbox.

**Q: How would you mitigate prompt injection from file/tool content?**
A: I haven't implemented this, but the standard approaches are: clearly delimit tool output from
instructions in the prompt (already partially true since results come back as `function_response`
parts, not free text merged into the user's message) and never treat data returned by a tool as
containing new permissions; a stricter version would have the harness itself flag suspicious patterns in
tool output before it reaches the model, or restrict what a sub-agent can act on based on where content
came from.

**Q: The blocklist is regex on shell commands — how do you know it's not just security theater?**
A: I don't oversell it. It's explicitly a last line of defense, not a sandbox. Testing found that
`rm -rf /*` and `rm -r -f /` slipped past my first `rm` pattern; I fixed the regex, but the same command
can always be expressed differently (`find / -delete`, `python -c "shutil.rmtree('/')"`). It also
only inspects `run_shell` command strings, not `write_file`/`edit_file` arguments. The honest fix is a
real sandbox (container/VM/restricted user), which is out of scope for this project but is exactly the
kind of gap I'd flag in a design review.

## Comparisons

**Q: How does this compare to Claude Code / Cursor / Aider?**
A: Same fundamental shape — an LLM-driven loop with file/shell tools and a permission layer — built
from scratch rather than on top of an agent framework, specifically so every part of the loop is mine to
explain. It's far smaller in scope: no IDE integration, no streaming UI, no multi-file diff review UX,
one provider family (Gemini) instead of pluggable providers, and no sandboxed execution environment.
What it does have that's directly comparable: exact-match file editing (similar spirit to how these
tools avoid line-number drift), a permission/approval flow, project memory files (`FORGE.md`/`AGENTS.md`,
the same idea as `CLAUDE.md`/`AGENTS.md`), session resume, and a sub-agent/task-delegation pattern.

**Q: Why Gemini instead of Claude or OpenAI for the model layer?**
A: Access and cost during development — Gemini via the Gemini Enterprise Agent Platform (Vertex AI),
using the `google-genai` SDK with `vertexai=True`. The design goal was that the *agent loop* is provider-
agnostic in spirit (see the "another provider" answer above for the honest caveat about message-format
coupling today).

## Grab-bag / rapid fire

**Q: What's `Usage` and where does cost tracking happen?**
A: A small dataclass in `llm.py` accumulating `input_tokens`, `output_tokens`, `thinking_tokens`,
`cached_tokens`, and `cost_usd`, added up call-by-call on `agent.usage` and shown via `/cost` or the
`--json` output. `pricing.cost(model, usage)` prices each call using the model that actually answered
(important once fallback changes which model that is mid-session); `pricing.PRICES` today has real
numbers for `gemini-3.8-flash` and its first fallback `gemini-3.7-flash`, so only a turn answered by the
second fallback (`gemini-3.5-flash`) or a manually chosen model reports `$0`.

**Q: Why does `ConsoleUI`/`QuietUI` matter as a design choice?**
A: It keeps `Agent` free of any I/O decisions — it calls `self.ui.thinking()`, `self.ui.tool_call()`,
`self.ui.ask_permission()`, etc., and never `print()` directly. That's what lets the exact same loop run
interactively with rich formatting or silently in a script/eval with zero conditional logic inside
`agent.py` itself.

**Q: What's the `max_turns` cap for?**
A: A hard ceiling (default 50, `config.MAX_TURNS` / `--max-turns`) on how many model-call-then-tool-call
round trips one user message can trigger, so a model stuck in a bad pattern can't burn API credits
indefinitely — it eventually returns `"(stopped after N turns without finishing)"` instead of running
forever.

**Q: Are tool calls within one model turn run in parallel?**
A: No — `agent.py` iterates over `resp.tool_calls` in a plain Python `for` loop and executes them one at
a time, then bundles all their results into a single `function_response`-bearing message before the
next model call. Simpler to reason about, log, and debug; the tradeoff is latency on tasks with several
independent tool calls in one turn.
