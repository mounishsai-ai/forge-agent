# Forge Study Guide

**Purpose of this document:** you built Forge, but building code and being able to defend every
line of it out loud, under interview pressure, are different skills. `docs/ARCHITECTURE.md` and
`docs/INTERVIEW.md` already explain *what each module does and why* in depth — this guide does not
repeat that. Instead it teaches you *how to read Forge's code*: the Python language features it
leans on, the LLM/agent vocabulary an interviewer will use, one request traced step by step with
realistic data, a reading order, hands-on "explain this code" drills, and a glossary. Read this
first if a snippet on screen makes you nervous; read the other two docs for the deep "why" behind
a design decision.

**A note on accuracy:** Forge's codebase was under active, fast-moving development while this
guide was written (several files — `llm.py`, `permissions.py`, `cli.py`, `mcp_client.py`, and
others — changed more than once in the course of researching this document, including a whole new
"plan mode" feature landing mid-write). Every file:line reference below was checked against the
repository at commit `ff7f429` (2026-09-26). Line numbers can drift the next time someone edits
these files; if a reference looks off by a few lines, the surrounding function name is the more
durable anchor — search for it.

---

## 1. Python concepts used in this codebase

Each concept below: what it means in plain English, then a real example from Forge.

### Dataclasses (`@dataclass`)

A class decorated with `@dataclass` gets a free `__init__`, `__repr__`, and `__eq__` generated
from its field list — you write the fields, Python writes the boilerplate. Forge uses this for
every small "bag of fields" object that gets passed around:

- `forge/llm.py:23` — `class ToolCall:` (`id`, `name`, `args`): what one requested tool call
  looks like, independent of Gemini's own wire format.
- `forge/llm.py:30` — `class Usage:`: running token/cost totals, with default values (`= 0`) and
  its own `add()` method for combining two `Usage` objects (used when a sub-agent's usage is
  folded into its parent's).
- `forge/tools/base.py:16` — `class Tool:`: a tool's `name`, `description`, JSON `parameters`,
  the `run` callable, and `needs_permission: bool = False`.
- `forge/skills.py:43` — `class Skill:`: name, description, and the two paths a skill needs.

**Why dataclasses instead of dicts?** Attribute access (`call.name`) instead of key access
(`call["name"]`) catches typos at the IDE/type-checker level, and `__repr__` makes these objects
print usefully when debugging — a `dict` would too, but a dataclass documents the exact shape.

### Type hints

`list[types.Content]`, `dict[str, float]`, `str | None` (the `|` union syntax is Python 3.10+) —
these are annotations only; Python does not enforce them at runtime. Forge uses them everywhere
as documentation for a reader (and for a type checker, if one were run):

- `forge/agent.py:56` — `self.history: list[types.Content] = []`
- `forge/llm.py:89` — `self.broken_until: dict[str, float] = {}` (model name → "don't retry
  before this timestamp")

Note nothing stops a caller from putting the wrong type in either list at runtime — these hints
are a contract with the *reader*, not a runtime guard.

### Context managers (`@contextmanager`, `with`)

A context manager guarantees setup-then-teardown around a block, with teardown running even if
the block raises. `@contextlib.contextmanager` turns a generator function into one: code before
`yield` is the "enter," code after `yield` (inside a `try`/`finally`) is the "exit."

- `forge/ui.py:68` — `ConsoleUI.thinking()`: `with console.status("[dim]thinking...[/]",
  spinner="dots"): yield` — shows a spinner for exactly the duration of the block (one model
  call), then removes it, whether or not the call raised.
- `forge/ui.py:72` — `ConsoleUI.stream()`: the more elaborate version. It yields an `on_text`
  callback, and its `finally` block (`forge/ui.py:96`, `status.stop()` / `if live is not None:`)
  stops both the spinner and the `rich.live.Live` view no matter how the block ends — Ctrl+C, an
  API error, or a normal return — so a broken terminal state never lingers.
- Plain `with open(...) as f:` appears constantly (e.g. `forge/tools/read_file.py`,
  `forge/hooks.py`) — the built-in file-object context manager that closes the file automatically.

### Decorators

A decorator wraps a callable to add behavior without changing its body.

- `@staticmethod` — `forge/agent.py:212` (decorating `_run_tool` at line 213): a method that
  takes no `self`. It's called as `Agent._run_tool(tool, call)` from inside a worker thread
  (`forge/agent.py:160`'s `ThreadPoolExecutor`); making it static is a signal — not an enforced
  guarantee — that it doesn't touch shared `Agent` state, which is exactly what you need for
  something running concurrently with other tool calls.
- `@classmethod` — `forge/hooks.py:34` (decorating `load` at line 35): an alternate constructor,
  called as `Hooks.load()` on the *class*, not an instance, because there's no `Hooks` object yet
  when you're trying to build the first one from a config file.
- `@contextmanager` and `@dataclass` — covered above.

### Closures

A closure is an inner function that keeps access to variables from the function that defined it,
even after the outer function has returned.

- `forge/subagent.py:18` — `def task(description: str) -> str:` inside `make_task_tool(parent)`.
  The model can only pass `description` (that's the tool's declared schema), but the closure
  still has `parent` in scope, so it can reach `parent.llm`, `parent.usage`, `parent.system_prompt`.
- `forge/mcp_client.py:328` — `def run(_remote_name=remote_name, **kwargs) -> str:` inside
  `make_tools`'s `for spec in server.tools:` loop. This is the classic "closure in a loop" trap
  and its fix in one line: without `_remote_name=remote_name` as a *default argument* (evaluated
  once, when `run` is defined), every wrapped tool's closure would share the SAME `remote_name`
  variable, and by the time any of them actually ran, that variable would hold whatever the LAST
  loop iteration left it — every tool would silently call the last server tool in the list. Binding
  it as a default parameter captures the value at definition time instead of the variable by
  reference.
- `forge/ui.py:84` — `def on_text(chunk: str) -> None:` inside `stream()`, using `nonlocal live` to
  mutate a variable in the enclosing scope.
- `forge/llm.py:155` — the default `def request(model):` closure inside `_call_with_retry`, over
  `self`, `history`, `cfg`.

### Exceptions & custom exceptions

Custom `Exception` subclasses act as typed signals that a specific caller catches on purpose,
instead of a generic `except Exception` catching everything indiscriminately.

- `forge/tools/base.py:11` — `class ToolError(Exception):` — the one exception every tool is
  supposed to raise for an *expected* failure ("file not found," "old_string not found"). Caught
  in `Agent._run_tool` (`forge/agent.py:213`) and turned into text handed back to the model — the
  agent never crashes because a tool failed.
- `forge/mcp_client.py:55` — `class MCPError(Exception):` — protocol/transport failures talking
  to an MCP server; converted to `ToolError` at the boundary (`MCPServer.call_tool`) so the rest of
  the harness only ever has to know about `ToolError`.
- `forge/skills.py:36` — `class SkillNotFound(Exception):` — raised by `load_skill`, caught and
  converted to `ToolError` in `forge/tools/skill.py`.

### Threading / `ThreadPoolExecutor`

Python threads don't give CPU parallelism (the GIL prevents two threads from running Python
bytecode at once), but they *do* give real concurrency for I/O-bound waiting — disk reads, network
calls, waiting on a subprocess — which is exactly what tool calls are. That's why Forge can use
plain threads productively:

- `forge/agent.py:160` — `pool = ThreadPoolExecutor(max_workers=min(8, len(calls)))` inside
  `_execute_parallel`, running a batch of consecutive read-only tool calls concurrently, capped at
  8 workers.
- `forge/mcp_client.py:84` — `self._lock = threading.Lock()  # guards _pending`, protecting a
  dict that both the thread issuing a request and the background `_read_stdout` thread touch.
- `forge/checkpoints.py:35` — `_lock = threading.Lock()` at module level, because "tool calls may
  run on worker threads" (its own comment) and two parallel `write_file`/`edit_file` calls could
  otherwise race on the shared snapshot store.

### `subprocess`

A `subprocess` spawns a real OS-level child process — a different program entirely — as opposed
to a thread, which is still your own Python process. Forge uses it for two very different jobs:

- Running the user's shell commands: `forge/tools/run_shell.py:11` — `def run_process(args,
  timeout, **popen_kwargs) -> subprocess.CompletedProcess:` wraps `subprocess.Popen` +
  `.communicate(timeout=...)`, and on timeout calls `_kill_tree` (`forge/tools/run_shell.py:29`)
  which uses Windows `taskkill /T /F` to kill the *entire* process tree — a plain `Popen.kill()`
  only kills the direct child (`powershell.exe`), leaving any grandchild it spawned (e.g. a dev
  server) running and holding the output pipes open forever.
- Running an MCP server as a long-lived child process: `forge/mcp_client.py:101` —
  `self.proc = subprocess.Popen(...)` with binary pipes that the code frames itself (see JSON
  section below).

### Regex (`re`)

- `forge/permissions.py:15` — the `BLOCKLIST`, a list of regex patterns checked with
  `re.search(pattern, cmd, re.IGNORECASE)` against every `run_shell` command string, in every
  permission mode.
- `forge/tools/grep.py:12` — `rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)` — the
  `grep` tool quite literally *is* a thin wrapper around Python's `re` module.
- `forge/hooks.py` — `re.fullmatch(hook["match"], name)`: note `fullmatch` (the *whole* tool name
  must match, e.g. `"edit_file|write_file"`) versus `re.search` in permissions.py (match
  *anywhere* in a shell command string) — different methods for different jobs.

### JSON

- `forge/agent.py:84` — `json.dumps(call.args, sort_keys=True)`: turns a call's argument dict into
  a canonical string purely so two calls with identical arguments (regardless of key order) can be
  compared for loop detection.
- `forge/session.py:23` — `c.model_dump(mode="json", exclude_none=True)`: Gemini's `types.Content`
  is a Pydantic model, and Pydantic's JSON mode automatically base64-encodes raw bytes fields
  (this is how a thought signature survives being written to a `.json` session file).
- `cli.py`'s `--json` flag builds a plain result dict and calls `json.dumps` on it for
  machine-readable headless output (used by `evals/`).

### `os.path` (not `pathlib`)

Forge does not use `pathlib` anywhere in `forge/` — every path operation goes through `os.path`.
The core helper: `forge/tools/base.py:29-31`,
```python
def resolve(path: str) -> str:
    return os.path.abspath(os.path.join(os.getcwd(), os.path.expanduser(path)))
```
`expanduser` turns `~/notes.md` into an absolute home-directory path; `os.path.join` combines the
current working directory with `path` — and is "smart" about it: if `path` is already absolute,
`join` discards the first argument entirely, which is exactly why `resolve` correctly handles both
relative and absolute input with one line; `abspath` then normalizes `..`/`.` segments.
If asked "why not `pathlib.Path`, the modern stdlib way?" — the honest answer is simply that this
codebase was written with `os.path` throughout and never switched; `pathlib` would be a reasonable
refactor, not a requirement it's missing for a functional reason.

### Generators (`yield`)

`forge/tools/grep.py:33` (originally `_walk`, now still there, see `forge/tools/grep.py:42` in the
current file after a small refactor added a `_display` helper above it):
```python
def _walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for name in filenames:
            yield os.path.join(dirpath, name)
```
Calling `_walk(root)` runs none of this code immediately — it returns a generator object, and each
path is produced lazily, one at a time, as `grep`'s `for f in files:` loop asks for the next one.
Two things worth being able to explain:
1. **Why a generator here and not a list:** `grep` filters and searches each file as it arrives
   and can bail out early once `MAX_MATCHES` is hit — with a generator, `os.walk` never has to
   finish walking a huge tree it might not even need to fully traverse.
2. **`dirnames[:] = [...]` versus `dirnames = [...]`:** the slice-assignment form mutates the
   *same list object* `os.walk` is holding a reference to, in place — which is the documented way
   to prune which subdirectories `os.walk` descends into next. Plain reassignment (`dirnames =
   [...]`) would just rebind the local name to a new list; `os.walk` would keep using its own
   original list and still walk into `.git`, `node_modules`, etc.

### f-strings

`forge/tools/base.py:39`, inside `truncate`:
```python
return f"{text[:half]}\n\n... [{len(text) - limit} chars truncated] ...\n\n{text[-half:]}"
```
Arbitrary expressions (slicing, arithmetic) evaluate inline inside `{}`. Used almost everywhere in
Forge in place of `.format()` or `%`-formatting purely for readability.

### `**kwargs` unpacking

`forge/agent.py:217`, inside the static `_run_tool`:
```python
output, ok = tool.run(**call.args), True
```
`call.args` is a plain `dict` the model produced from JSON, e.g. `{"path": "calc.py"}`.
`**call.args` unpacks it into keyword arguments matching the tool function's own parameter names
(`def read_file(path: str, offset: int = 1, limit: int = 2000)`). This line is the exact boundary
where "arbitrary JSON an LLM generated" becomes "a real Python function call" — and it's exactly
why this call sits inside a `try`/`except TypeError` (`forge/agent.py:220`,
`except TypeError as e:  # model sent wrong/missing arguments`): if the model invents an argument
name that doesn't exist, or omits a required one, Python's own argument binding raises `TypeError`
before the function body ever runs, and the harness turns that into an error string for the model
instead of crashing.

### Class vs. module-level state

Instance (per-object) state: `forge/agent.py:56`, `self.history: list[types.Content] = []` — every
`Agent()` you construct gets its *own* list. A parent agent and a sub-agent (`forge/subagent.py`)
never see each other's history, because each is a separate `Agent` instance.

Module-level (global, shared) state: `forge/tools/base.py:47`, `files_read: set[str] = set()`, and
`forge/tools/todo.py:8`, `current: list[dict] = []`. These are created once, when the module is
first imported, and shared by *every* `Tool` function call and every `Agent` in the same Python
process — including a sub-agent's tools, since tool functions are plain module-level functions
with no `self` and nowhere else to keep state. `forge/checkpoints.py:49`'s own `_Store`/`_store`
says this outright in its class docstring: *"Module-level state, like tools.base.files_read: the
tools are plain functions with no access to the Agent object, so a shared module is the simplest
way for them to reach it."*

**The gotcha to be ready to defend:** because `files_read` is one global set, a sub-agent's
`read_file` call marks that path as "read" for the *parent* agent too — an unrelated Agent
instance. This is a deliberate simplicity trade-off, not an oversight, but you should be able to
name it unprompted.

### Circular import avoidance (import inside a function)

The one place this is solving a **real, live** cycle in the current import graph:
`forge/skills.py:39`, inside `SkillNotFound`'s own docstring: *"this module stays free of any
tools/ import so it can also be used from prompts.py and cli.py without a circular import."*
Trace it: `forge/tools/skill.py` does `from forge.skills import SkillNotFound, load_skill` at
module level. If `forge/skills.py` ever imported anything from `forge.tools` at module level too,
loading either module would deadlock Python's import machinery (skills → tools → tools.skill →
skills, arriving back at a module that hasn't finished being defined yet). `skills.py` avoids the
whole problem by simply never importing from `forge.tools` — no local import trick needed here at
all; the *avoidance* is architectural.

Two more `import` statements that look like the same pattern but, checked against today's actual
import graph, are **defensive/stylistic**, not required by a live cycle:
- `forge/subagent.py:19` — `from forge.agent import Agent  # imported here to avoid a circular
  import`. But `forge/agent.py` itself only imports `config`, `context`, `llm`, `permissions`, and
  `tools` — never `subagent`. So there is no cycle today; importing lazily costs nothing and
  guards against one appearing later.
- `forge/mcp_client.py:382` — `from forge.tools import add_tools` inside `attach()`. Same story:
  `forge/tools/__init__.py` doesn't import `mcp_client` at module level today.
Be precise about this distinction if asked — don't claim all three exist for the identical reason.

---

## 2. LLM / agent concepts

- **Tokens** — the unit the model actually bills and limits itself by (roughly a word-piece, not
  a whole word). Forge tracks real counts pulled straight from the API's own accounting:
  `forge/llm.py:194`, `u = raw.usage_metadata`, feeding the `Usage` dataclass.
- **Context window** — the maximum size, in tokens, of everything sent to the model in one call
  (system prompt + entire history). Forge's practical trigger for managing it is
  `forge/config.py:12`, `COMPACT_AT_TOKENS` (default 150,000) — see `context.py` below.
- **System prompt** — fixed instructions resent on *every* call, kept separate from the
  conversation itself. Built once per agent by `forge/prompts.py:36`, `build_system_prompt()`.
- **Function calling / tool use** — instead of only returning text, the model can return a
  structured "call this function with these arguments" request. Forge declares each tool's shape
  via `Tool.declaration()` (`forge/tools/base.py:23`) and explicitly turns off the SDK's own
  ability to execute those calls for you (`forge/llm.py:95`'s `_config`,
  `AutomaticFunctionCallingConfig(disable=True)`) so `forge/agent.py`'s own loop decides what
  actually happens on the machine.
- **JSON schema** — the `parameters` dict every `Tool` carries (e.g. `{"type": "object",
  "properties": {...}, "required": [...]}`). The model never sees Python type hints — only this
  schema — and its whole job when calling a tool is to produce arguments matching it.
- **Thought signatures** — opaque, encrypted blobs Gemini attaches to some response parts as part
  of its internal reasoning chain; they must be sent back byte-for-byte on the next call. Forge
  never inspects them: `_merge_part` (`forge/llm.py:53`) is careful to keep any part carrying one
  exactly as it arrived, and `session.py`'s `model_dump(mode="json")` is what lets them survive a
  round trip to a JSON file on disk (see the JSON section above).
- **Streaming** — showing the answer as it's generated instead of waiting for the whole response.
  `generate_stream` (`forge/llm.py:108`) plus `ui.py`'s `stream()` context manager
  (`forge/ui.py:72`). Only used in the interactive REPL; headless mode uses the plain
  non-streaming `generate()`.
- **Determinism (or the lack of it)** — `_config` (`forge/llm.py:95`) sets no `temperature` and no
  seed, so outputs are **not** reproducible run-to-run even given an identical prompt — that's the
  model's default sampling behavior, unmodified. `--no-fallback` exists for evals, but it only
  pins *which model* answers (for cost/behavior consistency); it does not make the model's actual
  output deterministic.
- **Prompt injection** — text inside data the model reads (a file, a fetched web page) crafted to
  look like an instruction. Forge's `web_fetch` tool (`forge/tools/web_fetch.py:228`) explicitly
  prefixes every fetched page with a warning telling the model to treat it as untrusted data, not
  instructions — `read_file` and `run_shell` output carry no equivalent label today.
- **Rate limits: 429 vs. 504** — 429 means "you're calling too fast" (an actual rate limit); 504
  means "deadline exceeded" (the server took too long — not a rate limit, and retrying the *same*
  model just burns another full timeout for nothing). `RETRYABLE = {429, 500, 502, 503, 504}`
  (`forge/llm.py:75`) treats both as worth retrying, but `_call_with_retry`
  (`forge/llm.py:144`) skips a 504 straight to a fallback model when one is configured
  (`has_fallback`), rather than retrying it in place.
- **Exponential backoff with jitter** — after a failure, wait progressively longer (1s, 2s, 4s...)
  plus a small random amount, so a burst of simultaneous retries doesn't all retry at the exact
  same instant. `forge/llm.py:189` — `time.sleep(min(2 ** attempt, 30) + random.random())`.
- **Circuit breaker** — once something has failed, stop calling it for a while instead of retrying
  every single time. `forge/llm.py:190` — `self.broken_until[model] = time.time() +
  BREAKER_SECONDS`, with `BREAKER_SECONDS = 600` (`forge/llm.py:79`): a model that just exhausted
  its retries is skipped outright for the next 10 minutes.
- **MCP (Model Context Protocol)** — an open standard letting one client (Forge) use tools any
  compliant server exposes (GitHub, a filesystem, a database...) with zero custom integration code
  per server. Forge's client lives in `forge/mcp_client.py`; `attach()` (line 380) is the wiring
  point called from `cli.build_agent`.
- **Progressive disclosure** — don't spend tokens on information the model might not need for
  *this* task; show a cheap index, let it ask for the full thing when it decides it's relevant.
  `render_skill_index()` (`forge/skills.py:111`) is Forge's concrete example: only `name:
  description` per installed skill goes into every system prompt; a skill's full `SKILL.md` body
  is loaded only when the model calls the `skill` tool with that exact name.

---

## 3. Trace one request: `forge -p "fix the bug in calc.py" --yes`

Walking the exact function calls, in order, with what the data looks like at each step.

**1.** `main()` (`forge/cli.py:82`) sees `args.prompt` is set → calls `run_headless(args)`
(`forge/cli.py:87`).

**2.** `run_headless` builds `ui = QuietUI(verbose=args.verbose)` — `QuietUI.streams = False`, so
this run will never stream text live, it goes through the plain `generate()` path. It calls
`build_agent(args, ui)` (`forge/cli.py:43`).

**3.** `build_agent`: `mode = "auto" if args.yes else args.mode` (`forge/cli.py:45`) — because
`--yes` was passed, `mode = "auto"`. It constructs `GeminiLLM`, `Permissions("auto")`,
`build_system_prompt()`, `Hooks.load()`, wraps them in one `Agent(...)`, registers the `task` tool,
and (unconditionally, per `forge/cli.py:53`) the `exit_plan` tool — though plan mode itself stays
off here since `--plan` wasn't passed. `mcp_client.attach(agent)` starts any configured MCP
servers (none in this example).

*Headless-mode caveat worth knowing:* `checkpoints.set_session()` and `checkpoints.begin_turn()`
are only ever called from `repl()` (`forge/cli.py:119` and `:136`) — never from `run_headless`. So
any `edit_file`/`write_file` call in this run still calls `checkpoints.record()` (that call is
inside the tools themselves, not gated on headless-vs-REPL), but it opens an **in-memory-only**
turn tagged `"(headless)"` (`forge/checkpoints.py:94`) that vanishes the instant the process exits
— there is no `/undo` reachable in headless mode at all.

**4.** `agent.run("fix the bug in calc.py")` (`forge/agent.py:62`) begins. First line
(`forge/agent.py:64`) appends the user's message to history.

History so far (as `session.py` would serialize it):
```json
[
  {"role": "user", "parts": [{"text": "fix the bug in calc.py"}]}
]
```

**5.** Loop iteration 1: `context.maybe_compact(self)` (`forge/agent.py:69`) is a no-op —
`last_prompt_tokens` is still 0, nothing has been sent yet. `_ask_model()`
(`forge/agent.py:103`) checks `getattr(self.ui, "streams", False)`, which is `False` for `QuietUI`
— so it takes the plain branch: `with self.ui.thinking(): return self.llm.generate(...), False`.

**6.** `GeminiLLM.generate` (`forge/llm.py:104`) builds a `GenerateContentConfig` and calls
`_call_with_retry` (`forge/llm.py:144`), which tries `gemini-3.8-flash` (the configured default)
via `client.models.generate_content(...)`.

**7.** Say the model — following its own system prompt's "explore before changing" instruction —
asks for **two** tool calls in the same turn: `read_file(path="calc.py")` and
`glob(pattern="test_*.py")`. `_parse` (`forge/llm.py:193`) turns the raw API response into an
`LLMResponse` whose `tool_calls` is a list of two `ToolCall` objects.

The raw model message appended to history at `forge/agent.py:72` looks like (`function_call.id` is
typed `str | None` in `ToolCall` at `forge/llm.py:23` and may not always be present — shown here
for illustration):
```json
{
  "role": "model",
  "parts": [
    {"function_call": {"id": "call-1", "name": "read_file", "args": {"path": "calc.py"}}},
    {"function_call": {"id": "call-2", "name": "glob", "args": {"pattern": "test_*.py"}}}
  ]
}
```

**8.** `resp.tool_calls` is non-empty, so `_run_tool_calls` (`forge/agent.py:130`) inspects the two
calls: both `read_file` and `glob` have `needs_permission=False` and aren't in `SEQUENTIAL_ONLY`
(`{"task", "todo"}`), so `_parallel_ok` accepts both, and because there are 2+ consecutive
read-only calls, they run together via `_execute_parallel` (`forge/agent.py:155`). Permission
checks and hooks run up front, in order, on the main thread — `_prepare` (`forge/agent.py:195`)
calls `Permissions.check` (`forge/permissions.py:54`, instant allow, neither tool needs
permission) and `Hooks.pre_tool` (`forge/hooks.py:41`, no matching hook configured) — then both
`tool.run(**call.args)` calls (`forge/agent.py:217`, inside the static `_run_tool`) execute
concurrently in the `ThreadPoolExecutor` (`forge/agent.py:160`). `read_file` marks `calc.py`'s
resolved absolute path as read (`files_read.add(p)`, `forge/tools/read_file.py:12`) — this is what
will let `edit_file` run later without being refused.

**9.** Both results return in the SAME order the model asked (`_response_part`,
`forge/agent.py:29`), wrapped as `function_response` parts, appended as ONE new `user`-role
message (`forge/agent.py:90`):
```json
{
  "role": "user",
  "parts": [
    {"function_response": {"id": "call-1", "name": "read_file",
      "response": {"output": "     1\tdef add(a, b):\n     2\t    return a - b\n"}}},
    {"function_response": {"id": "call-2", "name": "glob",
      "response": {"output": "test_calc.py"}}}
  ]
}
```

**10.** Loop iteration 2: the model sees the bug (`add()` returns `a - b`) and the test file's
existence. On a later turn it calls `edit_file(path="calc.py", old_string="return a - b",
new_string="return a + b")`.

**11.** This time `needs_permission=True`. `Permissions.check` (`forge/permissions.py:54`):
`tool.name != "run_shell"`, so the `BLOCKLIST` is skipped entirely (it only ever inspects
`run_shell` command strings — never `edit_file`/`write_file` arguments); `tool.needs_permission`
is `True`, but `self.mode == "auto"`, so `check` returns `(True, "")` immediately — no y/n prompt
(`QuietUI.ask_permission` would have returned `"n"` unconditionally had mode been `"ask"`).

**12.** `edit_file()` (`forge/tools/edit_file.py`) resolves the path (line 8), confirms it's in
`files_read` (line 12 — it is, from step 8), counts `old_string` occurrences (line 23,
`count = text.count(old_string)` — exactly 1 here), then calls `checkpoints.record(p)`
(`forge/tools/edit_file.py:32`) — *after* every validation has passed, so a failed edit never
leaves a stray checkpoint — before writing the fixed line to disk.

**13.** A later turn calls `run_shell(command="python -m pytest test_calc.py")` to verify. This
time `Permissions.check` *does* run the `BLOCKLIST` (`tool.name == "run_shell"`) — no pattern
matches a pytest invocation — then again short-circuits to allowed because `mode == "auto"`.
`run_shell` (`forge/tools/run_shell.py`) builds a PowerShell command, runs it through
`run_process` (line 11, `subprocess.Popen` + `.communicate(timeout=...)`), and appends the exit
code to the returned text. A non-zero exit code is **not** itself a `ToolError` — it's just text
in the output; noticing it and reacting is left to the model.

**14.** Eventually the model replies with plain text and no tool calls. `resp.tool_calls` is empty
(`forge/agent.py:78`, `if not resp.tool_calls:`), so `Agent.run` returns `resp.text` immediately —
e.g. `"Fixed calc.py: add() was returning a - b instead of a + b. Ran test_calc.py and it now
passes."`

**15.** Back in `run_headless` (`forge/cli.py:87`): `result = agent.run(...)` succeeds. Since
`--json` wasn't passed in this example, it just does `print(error or result)`. `session.save` is
never called anywhere in this path — that only happens inside `repl()`.

---

## 4. Reading order

Read in this order — foundational pieces first, tools next (grouped by risk), the safety layer,
then the loop itself (once everything it calls is already familiar), then supporting systems, and
finally the wiring file that ties everything together.

1. **`forge/config.py`** — every tunable setting and its env var. 3-line read, orients you to the
   whole project's knobs before anything else.
2. **`forge/tools/base.py`** — what a `Tool` *is* (`Tool`, `ToolError`, `resolve`, `truncate`,
   `files_read`). Every single tool file depends on this one.
3. **`forge/tools/read_file.py`, `write_file.py`, `edit_file.py`** — the file-editing trio. Read
   together: they share `files_read` and (as of this writing) the new `checkpoints` module.
4. **`forge/tools/list_dir.py`, `glob.py`, `grep.py`** — the read-only exploration trio.
   `grep.py`'s `_walk` generator is the one worth lingering on.
5. **`forge/tools/run_shell.py`** — the general shell escape hatch; its `run_process`/`_kill_tree`
   helpers are a good subprocess deep-dive.
6. **`forge/tools/todo.py`, `skill.py`** — two small, low-risk tools; quick reads.
7. **`forge/tools/web_fetch.py`** — the longest single tool file: an SSRF guard plus a hand-rolled
   HTML-to-text parser. Read once you're comfortable with the smaller tools.
8. **`forge/tools/exit_plan.py`** — plan mode's model-facing tool; read alongside `permissions.py`
   below, since the two halves of plan mode live in different files on purpose.
9. **`forge/permissions.py`** — the safety layer: `ask`/`auto`/`readonly` modes, the shell
   `BLOCKLIST`, and plan mode's `enter_plan_mode`/`exit_plan_mode`.
10. **`forge/llm.py`** — the only file that talks to the model API: retries, the circuit breaker,
    streaming, thought-signature handling.
11. **`forge/agent.py`** — the loop itself. Deliberately read *after* `llm.py` and
    `permissions.py`, so every piece it orchestrates is already familiar.
12. **`forge/context.py`** — auto-compaction, called at the top of every loop iteration.
13. **`forge/checkpoints.py`** — the `/undo` snapshot store; a second example of a module-level
    global standing in for shared state plain tool functions can't otherwise reach.
14. **`forge/hooks.py`** — user-defined pre/post-tool veto hooks from `.forge/hooks.json`.
15. **`forge/subagent.py`** — the `task` tool: how a second, independent `Agent` gets built.
16. **`forge/mcp_client.py`** — the biggest file in the project; a full JSON-RPC-over-stdio client
    written with no dependency but the standard library. Save it for when you're comfortable with
    everything it plugs into (`Tool`, `ToolError`, permissions, `add_tools`).
17. **`forge/skills.py`** — skills + custom slash commands, and progressive disclosure.
18. **`forge/prompts.py`** — assembles the system prompt from `skills.py` + memory files +
    environment facts; ties several earlier modules together.
19. **`forge/session.py`** — save/resume JSON, including the atomic temp-file-then-`os.replace`
    write.
20. **`forge/ui.py`** — `ConsoleUI`/`QuietUI`; how the same loop renders differently or silently.
21. **`forge/pricing.py`** — the per-model cost table.
22. **`forge/cli.py`** — read *last*. It imports and wires together nearly every other module by
    name, so it will make the most sense once you've met each piece individually.

---

## 5. Fifteen "explain this code" exercises

Each snippet is copied verbatim from the current codebase. Cover the answer, answer out loud, then
check yourself.

---

**1.** `forge/agent.py:217` (inside `_run_tool`)
```python
output, ok = tool.run(**call.args), True
```
> **Q: What happens if the model calls `read_file` with an argument name that doesn't exist, like
> `filepath` instead of `path`?**
>
> A: `**call.args` unpacks the model's argument dict as keyword arguments into the real Python
> function. An unrecognized keyword (or a missing required one) makes Python's own argument
> binding raise `TypeError` before `read_file`'s body ever executes. That's caught two lines below
> by `except TypeError as e: output, ok = f"Bad arguments for {call.name}: {e}", False` — the
> agent never crashes; the model just gets an error string back and can retry with corrected
> arguments.

---

**2.** `forge/tools/edit_file.py` (guard, around line 12) + `forge/tools/base.py:47`
```python
files_read: set[str] = set()
...
if p not in files_read:
    raise ToolError(f"Read {path} with read_file before editing it.")
```
> **Q: Why refuse instead of just editing the file?**
>
> A: It forces "explore, then act" — the model can't blindly guess at a file's contents and edit
> based on that guess; it must have called `read_file` on this exact resolved path first. Caveat
> worth volunteering: `files_read` is a *module-level* global, not per-`Agent` state, so a
> sub-agent's `read_file` call also unlocks the file for the *parent* agent, and neither `/clear`
> nor anything else in the REPL resets it mid-session.

---

**3.** `forge/tools/grep.py` (the `_walk` generator)
```python
def _walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for name in filenames:
            yield os.path.join(dirpath, name)
```
> **Q: What does `dirnames[:] = [...]` do that `dirnames = [...]` would not?**
>
> A: `[:]` is slice assignment — it mutates the *same list object* in place. `os.walk` keeps its
> own reference to that exact list and consults it before descending further, so mutating it in
> place actually prunes which subdirectories get walked next (e.g. skips `.git`, `node_modules`).
> Plain `dirnames = [...]` would only rebind the local name `dirnames` to a brand-new list —
> `os.walk`'s own internal reference would be untouched, and it would still walk into every
> ignored directory.

---

**4.** `forge/mcp_client.py` (inside `make_tools`, the loop over `server.tools`)
```python
def run(_remote_name=remote_name, **kwargs) -> str:
    return server.call_tool(_remote_name, kwargs)
```
> **Q: Why is `_remote_name=remote_name` there instead of just using `remote_name` directly in the
> body?**
>
> A: Without it, every `run` closure created in this loop shares the *same* `remote_name`
> variable by reference, not by value — Python closures capture variables, not their
> point-in-time values. By the time any wrapped tool's `run` actually gets called (long after the
> loop has finished), `remote_name` holds whatever the *last* iteration left it, so every single
> MCP tool would silently call the last server tool in the list. Making `_remote_name` a default
> *parameter* forces Python to evaluate and bind it once, at the moment this specific `run`
> function is defined — freezing that iteration's value.

---

**5.** `forge/llm.py:53` (`_merge_part`, called while assembling a streamed response)
> **Q: Why can't `generate_stream` just concatenate every part's text together into one string?**
>
> A: Gemini attaches "thought signatures" — opaque encrypted state — to specific parts, often the
> first `function_call` part or a final empty-text part, and those must be sent back to the API
> byte-for-byte on the next turn or later calls can break. `_merge_part` only glues together
> *plain* text-or-thought parts (nothing else in their field set); any part carrying a
> `function_call` or anything beyond plain text is appended untouched, preserving its signature
> exactly.

---

**6.** `forge/llm.py:189` + the surrounding retry loop
```python
time.sleep(min(2 ** attempt, 30) + random.random())
```
> **Q: Walk through what happens on repeated 504s with a fallback model configured.**
>
> A: 504 means "deadline exceeded" — the server already made you wait the full timeout, so
> retrying the *same* model wastes another full timeout for nothing. `_call_with_retry` checks
> `has_fallback`; if a healthy fallback exists, a 504 breaks out of the retry loop for that model
> immediately (no backoff sleep needed for this model) and marks it `broken_until` for
> `BREAKER_SECONDS` (600s) before moving to the next model in the list. If there's no fallback at
> all, it instead becomes more patient (more attempts) and does sleep with backoff+jitter between
> tries, since there's nowhere else to go.

---

**7.** `forge/permissions.py:15` (first `BLOCKLIST` pattern)
```python
r"\brm\s+(?=(?:[^;&|]*\s)?-[a-zA-Z]*[rR])[^;&|]*\s(/|/\*|~/?|~/\*|\$HOME/?|\*)(\s|;|&|\||$)"
```
> **Q: What does this block, and what might slip past it?**
>
> A: It blocks `rm` invocations that have a recursive-looking flag (any single-letter flag
> containing `r`/`R`, in any order or split across multiple flag groups) AND end up targeting `/`,
> `/*`, `~`, `$HOME`, or a bare `*` — i.e. "delete everything." It's checked with `re.search`
> against the whole command string, in *every* permission mode including `auto`. What slips past:
> anything that deletes without literally calling a command matching `\brm`, e.g. `find / -delete`
> or a Python one-liner (`python -c "import shutil; shutil.rmtree('/')"`) run through `run_shell`
> — the blocklist only pattern-matches strings, it has no understanding of what a command
> actually *does*.

---

**8.** `forge/tools/edit_file.py:23` (the uniqueness check)
```python
count = text.count(old_string)
if count == 0:
    raise ToolError(...)
if count > 1 and not replace_all:
    raise ToolError(f"old_string appears {count} times. ...")
```
> **Q: Why refuse when `old_string` appears twice, instead of just replacing the first match?**
>
> A: Silently picking "the first occurrence" is a guess, and a wrong guess here means editing code
> the model didn't intend to touch — with no diff review step, that could land unnoticed. Forcing
> the model to either add enough surrounding context to make its target string unique, or
> explicitly opt into `replace_all=True`, moves the "which occurrence did you mean" decision to
> the caller instead of the tool silently choosing for it.

---

**9.** `forge/tools/base.py:39` (`truncate`)
```python
return f"{text[:half]}\n\n... [{len(text) - limit} chars truncated] ...\n\n{text[-half:]}"
```
> **Q: Why keep both the head AND the tail of long output, instead of just the first N
> characters?**
>
> A: The end of a tool's output is often the most relevant part — the last few lines of a test run
> (pass/fail summary), the tail of a stack trace, the final section of a long file. Keeping only
> the head would systematically hide exactly the information a model most needs to react to.

---

**10.** `forge/tools/run_shell.py` (`_kill_tree`)
```python
def _kill_tree(proc: subprocess.Popen) -> None:
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], ...)
```
> **Q: Why not just call `proc.kill()`? What's the Windows-specific problem?**
>
> A: On Windows, `Popen.kill()`/`.terminate()` only kills the direct child process — e.g.
> `powershell.exe` — not anything *that* process spawned in turn (a grandchild, like a dev server
> the command started). The grandchild keeps running and keeps holding the stdout/stderr pipes
> open, so `.communicate(timeout=...)` can hang indefinitely waiting for pipes that will never
> close. `taskkill /T` (`/T` = tree) kills the whole process tree rooted at that PID, which
> actually frees the pipes.

---

**11.** `forge/skills.py:39` (inside `SkillNotFound`'s docstring)
> **Q: Trace the actual import cycle this avoids.**
>
> A: `forge/tools/skill.py` does `from forge.skills import SkillNotFound, load_skill` at module
> level. If `forge/skills.py` also imported something from `forge.tools` at module level, loading
> either module first would require finishing the other one first, which requires finishing the
> first one first — Python's import machinery can't resolve that, and you'd get an
> `ImportError`/`AttributeError` depending on which one loads first. `skills.py`'s actual fix is
> simpler than a local import: it just never imports from `forge.tools` at all, at any point in
> the file.

---

**12.** `forge/ui.py:72` (`ConsoleUI.stream`, abbreviated)
```python
status = console.status("[dim]thinking...[/]", spinner="dots")
status.start()
...
if live is None:
    status.stop()
    live = Live(Markdown(""), console=console, refresh_per_second=12)
    live.start()
```
> **Q: Why does the spinner have to be stopped before the `Live` view starts?**
>
> A: The `rich` library only allows ONE live-updating display on the terminal at a time — a
> spinner counts as one, a `Live` view counts as another. Trying to run both simultaneously either
> raises an error or corrupts the terminal output. So the code shows the spinner only until the
> first real text chunk arrives, then explicitly tears it down before handing control to the
> `Live` Markdown renderer for the rest of the streamed answer.

---

**13.** `forge/tools/edit_file.py` and `forge/tools/write_file.py` — checkpoint ordering
```python
# edit_file: validation happens first, THEN:
checkpoints.record(p)   # only after all checks pass...
with open(p, "w", ...) as f:
    f.write(text)
```
> **Q: Why is `checkpoints.record()` called after all validation, right before the write, in both
> tools?**
>
> A: `checkpoints.record()` snapshots the file's *current* (pre-change) bytes so `/undo` can
> restore them later. If it ran before validation and validation then failed (file not read yet,
> `old_string` not found or ambiguous), you'd have recorded a checkpoint for a change that never
> actually happened — a wasted, misleading snapshot with no corresponding edit to undo it from.
> Recording immediately before the write guarantees a checkpoint exists if and only if a write is
> actually about to succeed.

---

**14.** `forge/tools/web_fetch.py` (inside the fetch/redirect loop)
```python
while resp is None:
    check_url_is_safe(current_url)
    try:
        resp = _open(current_url)
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 303, 307, 308):
            ...
            current_url = urljoin(current_url, location)
            continue
```
> **Q: Why re-run the SSRF check on every redirect hop instead of just checking the original URL
> once?**
>
> A: A URL that resolves to a perfectly public, safe address can still redirect somewhere private
> (an internal service, `169.254.169.254`'s cloud metadata endpoint) — checking only the URL the
> model originally supplied would miss that entirely. Forge deliberately disables urllib's
> automatic redirect-following (`_NoRedirectHandler`) specifically so it can inspect and re-check
> every single hop itself, one at a time, capped at `MAX_REDIRECTS`.

---

**15.** `forge/permissions.py` (`enter_plan_mode`)
```python
def enter_plan_mode(self) -> None:
    if self.plan_mode:
        return
    self._pre_plan_mode = self.mode
    self.plan_mode = True
    self.mode = "readonly"
```
> **Q: Why guard against calling this twice with `if self.plan_mode: return`?**
>
> A: Idempotency. `enter_plan_mode` can be triggered by both `--plan` at startup and `/plan`
> toggled on mid-session; if it ran its body a second time while already in plan mode, it would
> overwrite `self._pre_plan_mode` — which is supposed to remember the *original* mode to restore
> on exit — with `"readonly"` (the value `self.mode` holds *while already in plan mode*). Exiting
> plan mode would then incorrectly restore `"readonly"` instead of whatever mode the user was
> actually in before plan mode ever started.

---

## 6. Glossary

- **Agent** — the object (`forge/agent.py`) that owns one conversation's loop: history, usage
  totals, and the logic that turns model tool requests into real actions.
- **Agent loop** — the repeated cycle of "ask the model → run any requested tools → feed results
  back" until the model stops asking for tools or a turn cap is hit.
- **BLOCKLIST** — the regex list in `permissions.py` that vetoes especially dangerous `run_shell`
  commands, checked in every permission mode.
- **Checkpoint** — a saved snapshot of a file's pre-edit bytes (`forge/checkpoints.py`), grouped
  per user turn, that `/undo` can restore.
- **Circuit breaker** — skip calling something that just failed for a cooldown period, instead of
  retrying it every time.
- **Closure** — a function that retains access to variables from its enclosing scope after that
  scope has returned.
- **Compaction** — replacing the conversation history with a model-generated summary once it
  passes a token threshold, to keep future requests within the context window.
- **Context window** — the maximum number of tokens a model call can include.
- **Dataclass** — a class whose `__init__`/`__repr__`/`__eq__` are auto-generated from its
  declared fields.
- **Exponential backoff (+ jitter)** — waiting progressively longer between retries, with a
  random amount added to avoid many retries colliding at once.
- **Function calling / tool use** — a model response that requests a named function be called
  with structured arguments, instead of (or alongside) plain text.
- **Function response** — the harness's answer to one function call, fed back into history as a
  `function_response` part.
- **GIL (Global Interpreter Lock)** — the mechanism that prevents two Python threads from
  executing Python bytecode at the same instant; the reason threads help with I/O waits but not
  CPU-bound work.
- **Hooks** — user-configured shell commands (`.forge/hooks.json`) that run before/after a tool
  call and can veto it.
- **JSON schema** — the structural description of a tool's expected arguments, given to the model
  instead of Python type hints.
- **MCP (Model Context Protocol)** — an open standard for connecting an AI client to external tool
  servers over a common protocol (here: JSON-RPC 2.0 over stdio).
- **Module-level global** — state defined at import time in a module (not inside any class),
  shared by every caller of that module in the process.
- **Permission mode** — `ask` / `auto` / `readonly`; governs whether a tool that
  `needs_permission` must prompt the user, always runs, or is always refused.
- **Plan mode** — a mode where permissions are forced read-only and the model is instructed to
  propose a plan (via the `exit_plan` tool) for the user to approve before making any changes.
  Yes, this is a new feature, added to the codebase after this guide's first draft — see
  `forge/permissions.py`'s `enter_plan_mode`/`exit_plan_mode` and `forge/tools/exit_plan.py`.
  This guide's line references reflect it.
- **Progressive disclosure** — showing a cheap summary up front and loading the expensive full
  content only once it's actually needed.
- **Prompt injection** — text inside data the model reads that's crafted to be mistaken for an
  instruction.
- **Rate limit (429)** — "you are calling too frequently"; distinct from a 504 (server-side
  timeout).
- **SSRF (Server-Side Request Forgery)** — tricking a server-side fetch into hitting an internal
  or private address (localhost, cloud metadata endpoints) instead of the intended public target;
  `web_fetch.py`'s `check_url_is_safe` exists specifically to prevent this.
- **System prompt** — fixed instructions resent with every model call, separate from the
  conversation history.
- **Thought signature** — an opaque, encrypted blob Gemini attaches to some response parts,
  representing internal reasoning state, which must be echoed back unmodified on later turns.
- **Token** — the unit of text the model actually counts/bills in; roughly a word-piece.
- **ToolError** — the one exception type every Forge tool should raise for an expected failure;
  caught by the agent loop and turned into text for the model instead of crashing the process.
- **ThreadPoolExecutor** — a pool of worker threads used here to run several read-only tool calls
  concurrently within one model turn.

---

## Where to go next

- **`docs/ARCHITECTURE.md`** — module-by-module design rationale, the full lifecycle diagram, and
  the project's own list of known limitations.
- **`docs/INTERVIEW.md`** — a Q&A rehearsal format covering the same ground from an interviewer's
  angle, plus security/comparison questions this guide doesn't cover.

**One honest note about those two docs:** an earlier version of this guide flagged a round of drift
in them (stale pricing coverage, `evals/` described as a placeholder, an imprecise 504-fallback
claim) — that round has since been fixed in both files as of this pass. Docs can still drift again
as the code keeps moving faster than they do; if a specific claim in either one ever looks off
against the code you're reading, trust the code and treat the mismatch as worth fixing, the same
way the previous round was.
