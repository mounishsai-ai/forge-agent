"""MCP client: lets Forge use tools from external Model Context Protocol servers.

What MCP is: a standard way for an AI app (the *client*, here Forge) to talk to a *server*
that offers tools (GitHub, databases, browsers, ...). Anyone can write a server once and every
MCP-capable agent (Claude Code, Forge, ...) can use it.

How it works here (pure standard library, no `mcp` SDK):

    Forge                                        MCP server (a child process)
      |-- start process: command + args ----------> |
      |-- {"method":"initialize", ...}  (stdin) --> |
      | <-- {"result": {protocolVersion, ...}} ---- |  (stdout)
      |-- {"method":"notifications/initialized"} -> |
      |-- {"method":"tools/list"} ----------------> |
      | <-- {"result": {"tools": [...]}} ---------- |
      |   ... later, when the model calls a tool:   |
      |-- {"method":"tools/call", name, args} ----> |
      | <-- {"result": {"content": [...]}} -------- |

Wire format (MCP stdio transport, spec 2025-11-25): JSON-RPC 2.0 messages, UTF-8, one message
per line ("newline-delimited JSON"; a message MUST NOT contain a raw newline). The server's
stdout carries ONLY protocol messages; its stderr is free-form logging.

Config (same shape as Claude Code), in ~/.forge/mcp.json (user) and .forge/mcp.json (project;
wins on a name clash):
    {"mcpServers": {"fs": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."],
                           "env": {"SOME_TOKEN": "${SOME_TOKEN}"}}}}

Each remote tool becomes a normal Forge Tool named `mcp__<server>__<tool>`, so the agent loop,
permissions and hooks treat it exactly like a built-in tool. MCP tools always ask permission
(in `ask` mode): they are third-party code that can do anything.
"""
import atexit
import collections
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import threading

from forge.tools.base import Tool, ToolError, truncate

PROTOCOL_VERSION = "2025-11-25"          # the version we ask for; servers may answer with an older one
CONFIG_FILES = [os.path.join(os.path.expanduser("~"), ".forge", "mcp.json"),   # user-level
                os.path.join(".forge", "mcp.json")]                             # project-level
START_TIMEOUT = 30      # seconds for initialize + tools/list (npx may need to download on first run)
CALL_TIMEOUT = 120      # seconds for one tools/call

active_servers: list["MCPServer"] = []   # every server started this process (for /mcp and shutdown)


class MCPError(Exception):
    """Anything that went wrong talking to a server (process died, timeout, JSON-RPC error)."""


def warn(msg: str) -> None:
    """Warnings go to stderr so they never corrupt `forge -p --json` output on stdout."""
    try:
        print(f"[mcp] {msg}", file=sys.stderr, flush=True)
    except UnicodeEncodeError:   # e.g. a Windows cp1252 console and a server message with emoji
        print(f"[mcp] {msg}".encode("ascii", "replace").decode(), file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------------------------
# One connection to one server
# ---------------------------------------------------------------------------------------------
class MCPServer:
    def __init__(self, name: str, command: str, args: list[str] | None = None, env: dict | None = None):
        self.name = name
        self.command = command
        self.args = list(args or [])
        self.env = dict(env or {})
        self.proc: subprocess.Popen | None = None
        self.tools: list[dict] = []                 # raw tool descriptions from tools/list
        self.server_info: dict = {}
        self.protocol_version = ""
        self.error = ""                             # why it failed to start (shown by /mcp)
        self.stderr_tail = collections.deque(maxlen=50)   # last lines the server logged
        self._ids = itertools.count(1)              # JSON-RPC request ids: 1, 2, 3, ...
        self._pending: dict[int, dict] = {}         # id -> {"event": Event, "msg": response or None}
        self._lock = threading.Lock()               # guards _pending
        # A SEPARATE lock for writing to stdin. If one lock guarded both, a big write blocked on a
        # full pipe could stop the reader thread from draining stdout -> both sides wait forever.
        self._write_lock = threading.Lock()
        self._dead = False                          # set when the server's stdout closes (it exited)
        self._closed = False

    # --- process + background threads --------------------------------------------------------
    def start(self, timeout: float = START_TIMEOUT) -> None:
        """Launch the process, do the handshake and fetch the tool list. Raises MCPError on failure."""
        # shutil.which finds e.g. npx.cmd on Windows (Popen alone would not, without shell=True).
        exe = shutil.which(self.command) or self.command
        # MERGE with our environment, never replace it: servers need PATH, and on Windows SYSTEMROOT.
        env = {**os.environ, **{k: os.path.expandvars(str(v)) for k, v in self.env.items()}}
        try:
            self.proc = subprocess.Popen(
                [exe, *[os.path.expandvars(str(a)) for a in self.args]],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env=env, bufsize=0,   # binary pipes: we do the UTF-8 + newline framing ourselves
            )
        except OSError as e:
            raise MCPError(f"could not start '{self.command}': {e}") from e

        # Two daemon threads: one reads protocol messages from stdout, one drains stderr.
        # (If nobody reads stderr, the pipe buffer fills up and the server freezes.)
        threading.Thread(target=self._read_stdout, daemon=True, name=f"mcp-{self.name}-out").start()
        threading.Thread(target=self._read_stderr, daemon=True, name=f"mcp-{self.name}-err").start()

        # The MCP handshake: initialize -> (response) -> notifications/initialized.
        result = self.request("initialize", {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {},            # we don't offer roots/sampling/elicitation to servers
            "clientInfo": {"name": "forge", "version": _forge_version()},
        }, timeout=timeout)
        self.protocol_version = result.get("protocolVersion", "")
        self.server_info = result.get("serverInfo", {})
        self.notify("notifications/initialized")

        # tools/list can be paginated: keep asking while the server returns a nextCursor.
        cursor = None
        while True:
            page = self.request("tools/list", {"cursor": cursor} if cursor else {}, timeout=timeout)
            self.tools.extend(page.get("tools", []))
            cursor = page.get("nextCursor")
            if not cursor:
                break

    def _read_stdout(self) -> None:
        """Background thread: one JSON message per line; route responses to whoever is waiting."""
        for raw in iter(self.proc.stdout.readline, b""):
            line = raw.decode("utf-8", errors="replace").strip()   # strip also removes Windows \r
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                self.stderr_tail.append(f"(non-JSON on stdout) {line[:200]}")
                continue
            if not isinstance(msg, dict):
                continue
            if "method" in msg:                       # the server is talking to US
                if "id" in msg:                       # ...a request: we must answer it
                    if msg["method"] == "ping":
                        self._send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
                    else:
                        self._send({"jsonrpc": "2.0", "id": msg["id"],
                                    "error": {"code": -32601, "message": "Method not found"}})
                continue                              # ...a notification (logs, progress): ignore
            with self._lock:                          # a response to one of our requests
                waiter = self._pending.get(msg.get("id"))
            if waiter:
                waiter["msg"] = msg
                waiter["event"].set()
        # EOF: the process exited. Wake up every waiting request with an error.
        with self._lock:
            self._dead = True
            for waiter in self._pending.values():
                waiter["event"].set()                 # msg stays None -> "server exited"

    def _read_stderr(self) -> None:
        for raw in iter(self.proc.stderr.readline, b""):
            self.stderr_tail.append(raw.decode("utf-8", errors="replace").rstrip())

    # --- JSON-RPC ------------------------------------------------------------------------------
    def _send(self, msg: dict) -> None:
        # json.dumps without indent never emits a raw newline (newlines in strings become \n),
        # so one message = exactly one line, as the stdio transport requires.
        data = (json.dumps(msg, ensure_ascii=False) + "\n").encode("utf-8")
        with self._write_lock:
            try:
                self.proc.stdin.write(data)
                self.proc.stdin.flush()
            except (OSError, ValueError) as e:        # broken pipe / already closed
                raise MCPError(f"server '{self.name}' is not running ({e}){self._stderr_hint()}") from e

    def notify(self, method: str, params: dict | None = None) -> None:
        """A notification has no id and gets no response."""
        msg = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._send(msg)

    def request(self, method: str, params: dict | None = None, timeout: float = CALL_TIMEOUT) -> dict:
        """Send a request and block until its response arrives (matched by id) or we time out."""
        if self.proc is None or self._dead or self.proc.poll() is not None:
            raise MCPError(f"server '{self.name}' is not running{self._stderr_hint()}")
        req_id = next(self._ids)
        waiter = {"event": threading.Event(), "msg": None}
        with self._lock:
            self._pending[req_id] = waiter
        try:
            self._send({"jsonrpc": "2.0", "id": req_id, "method": method, "params": params or {}})
            if not waiter["event"].wait(timeout):
                # Spec: on timeout, tell the server we gave up so it can stop working on it.
                try:
                    self.notify("notifications/cancelled", {"requestId": req_id, "reason": "timeout"})
                except MCPError:
                    pass
                raise MCPError(f"'{method}' on server '{self.name}' timed out after {timeout}s")
        finally:
            with self._lock:
                self._pending.pop(req_id, None)
        msg = waiter["msg"]
        if msg is None:
            raise MCPError(f"server '{self.name}' exited during '{method}'{self._stderr_hint()}")
        if "error" in msg:
            err = msg["error"]
            raise MCPError(f"server '{self.name}' returned error {err.get('code')}: {err.get('message')}")
        return msg.get("result") or {}

    def call_tool(self, tool_name: str, arguments: dict, timeout: float = CALL_TIMEOUT) -> str:
        """Run a remote tool. Returns its text; raises ToolError if the tool reported an error."""
        try:
            result = self.request("tools/call", {"name": tool_name, "arguments": arguments}, timeout=timeout)
        except MCPError as e:
            raise ToolError(str(e)) from e
        text = content_to_text(result)
        if result.get("isError"):         # the tool ran but failed (e.g. file not found)
            raise ToolError(text or "MCP tool reported an error.")
        return truncate(text or "(no output)")

    def _stderr_hint(self) -> str:
        tail = [l for l in self.stderr_tail if l.strip()][-5:]
        return ("\nserver stderr:\n" + "\n".join(tail)) if tail else ""

    # --- shutdown --------------------------------------------------------------------------------
    def close(self) -> None:
        """Spec-recommended stdio shutdown: close stdin, wait, then terminate, then kill."""
        if self._closed or self.proc is None:
            return
        self._closed = True
        try:
            self.proc.stdin.close()               # most servers exit when their input ends
        except OSError:
            pass
        try:
            self.proc.wait(timeout=2)
            return
        except subprocess.TimeoutExpired:
            pass
        if os.name == "nt":
            # npx.cmd runs node as a grandchild; terminate() would only kill the cmd wrapper.
            # taskkill /T kills the whole process tree.
            subprocess.run(["taskkill", "/T", "/F", "/PID", str(self.proc.pid)],
                           capture_output=True, stdin=subprocess.DEVNULL)
        else:
            self.proc.terminate()
        try:
            self.proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def _forge_version() -> str:
    from forge import __version__
    return __version__


# ---------------------------------------------------------------------------------------------
# Converting MCP data <-> Forge data
# ---------------------------------------------------------------------------------------------
def content_to_text(result: dict) -> str:
    """A tools/call result has a list of content items; the model only needs the text."""
    out = []
    for item in result.get("content") or []:
        kind = item.get("type")
        if kind == "text":
            out.append(item.get("text", ""))
        elif kind == "resource" and "text" in (item.get("resource") or {}):
            out.append(item["resource"]["text"])
        else:   # image / audio / binary resource: we can't show it, but say it was there
            out.append(f"[{kind} content{', ' + item['mimeType'] if item.get('mimeType') else ''} omitted]")
    if not out and result.get("structuredContent") is not None:
        out.append(json.dumps(result["structuredContent"]))
    return "\n".join(out)


# Gemini function names: letters, digits, _ . : - ; must start with a letter or _; max 64 chars.
def tool_name(server: str, tool: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9_.:-]", "_", f"mcp__{server}__{tool}")
    return name[:64]


# JSON-Schema keywords that describe the schema document itself, not the arguments.
# Gemini's parameters_json_schema accepts most of JSON Schema; these are just noise.
_DROP_KEYS = {"$schema", "$id", "$comment"}


def sanitize_schema(schema) -> dict:
    """Make a server's inputSchema safe to hand to Gemini as function parameters."""
    def clean(node):
        if isinstance(node, dict):
            return {k: clean(v) for k, v in node.items() if k not in _DROP_KEYS}
        if isinstance(node, list):
            return [clean(v) for v in node]
        return node

    schema = clean(schema) if isinstance(schema, dict) else {}
    schema.setdefault("type", "object")
    schema.setdefault("properties", {})
    return schema


def make_tools(server: MCPServer) -> list[Tool]:
    """Wrap each remote tool in a Forge Tool whose run() forwards to tools/call."""
    tools = []
    for spec in server.tools:
        remote_name = spec.get("name", "")

        # **kwargs (not named params): the schema's argument names can be anything.
        # remote_name=remote_name freezes the current value (a classic Python closure-in-loop gotcha).
        def run(_remote_name=remote_name, **kwargs) -> str:
            return server.call_tool(_remote_name, kwargs)

        desc = (spec.get("description") or spec.get("title") or remote_name).strip()
        tools.append(Tool(
            name=tool_name(server.name, remote_name),
            description=f"[MCP server '{server.name}'] {desc}",
            parameters=sanitize_schema(spec.get("inputSchema")),
            run=run,
            needs_permission=True,     # third-party code: always ask (unless --yes / auto mode)
        ))
    return tools


# ---------------------------------------------------------------------------------------------
# Config loading + wiring into an agent
# ---------------------------------------------------------------------------------------------
def load_config(paths: list[str] | None = None) -> dict[str, dict]:
    """Merge mcpServers from the user file then the project file (project wins on a clash)."""
    servers: dict[str, dict] = {}
    for path in paths or CONFIG_FILES:
        if not os.path.isfile(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                servers.update(json.load(f).get("mcpServers", {}))
        except (OSError, json.JSONDecodeError, AttributeError) as e:
            warn(f"ignoring {path}: {e}")
    return servers


def start_servers(config: dict[str, dict], timeout: float = START_TIMEOUT) -> list[MCPServer]:
    """Start every configured server. A server that fails is reported and skipped, never fatal."""
    started = []
    for name, cfg in config.items():
        if cfg.get("disabled"):
            continue
        if cfg.get("type", "stdio") != "stdio" or "command" not in cfg:
            warn(f"server '{name}': only stdio servers (with a 'command') are supported; skipped")
            continue
        server = MCPServer(name, cfg["command"], cfg.get("args"), cfg.get("env"))
        active_servers.append(server)
        try:
            server.start(timeout=timeout)
            started.append(server)
        except MCPError as e:
            server.error = str(e)
            warn(f"server '{name}' failed to start: {e}")
            server.close()
    return started


def attach(agent, config: dict[str, dict] | None = None) -> list[Tool]:
    """Start the configured MCP servers and add their tools to `agent`. Returns the added tools."""
    from forge.tools import add_tools
    config = load_config() if config is None else config
    if not config:
        return []
    tools = [t for server in start_servers(config) for t in make_tools(server)]
    return add_tools(agent, tools)


def shutdown_all() -> None:
    for server in active_servers:
        server.close()


atexit.register(shutdown_all)   # clean shutdown of every server when Forge exits


def status() -> str:
    """Text for the /mcp slash command."""
    if not active_servers:
        return "No MCP servers configured. Add them to .forge/mcp.json or ~/.forge/mcp.json."
    lines = []
    for s in active_servers:
        if s.error:
            lines.append(f"{s.name}: FAILED - {s.error.splitlines()[0]}")
            continue
        alive = s.proc is not None and s.proc.poll() is None
        info = s.server_info.get("name", "?") + " " + s.server_info.get("version", "")
        lines.append(f"{s.name}: {'running' if alive else 'stopped'} ({info.strip()}, protocol {s.protocol_version})")
        for t in s.tools:
            desc = (t.get("description") or "").strip().split("\n")[0][:70]
            lines.append(f"  {tool_name(s.name, t.get('name', ''))} - {desc}")
    return "\n".join(lines)
