"""User-defined hooks: shell commands that run before/after tool calls.

Configured in .forge/hooks.json, e.g.:
{
  "pre_tool":  [{"match": "run_shell", "command": "python check_cmd.py"}],
  "post_tool": [{"match": "edit_file|write_file", "command": "ruff format ."}]
}
The hook gets FORGE_TOOL and FORGE_ARGS (JSON) as env vars. A pre_tool hook that exits
non-zero BLOCKS the call and its output is shown to the model as the reason.
SECURITY: FORGE_ARGS is chosen by the model. Read it from the environment INSIDE your script
(os.environ["FORGE_ARGS"]); never expand it in the command string itself. On Windows the
command runs in cmd.exe, which pastes `%FORGE_ARGS%` into the command line BEFORE parsing it,
so an argument like `x & del *` would run as a command.
A broken hook (bad regex, missing key, crash) never crashes the agent: a broken pre_tool hook
blocks the call (fail closed - it may be a safety check); a broken post_tool hook is ignored.
This lets users enforce their own rules (auto-format, lint, audit logs) without touching Forge's code.
"""
import json
import os
import re
import subprocess

from forge.tools.run_shell import run_process

HOOKS_FILE = os.path.join(".forge", "hooks.json")


class Hooks:
    def __init__(self, config: dict):
        self.pre = config.get("pre_tool", [])
        self.post = config.get("post_tool", [])
        self.log: list[dict] = []   # every tool call with timing; handy for evals and debugging

    @classmethod
    def load(cls) -> "Hooks":
        if os.path.isfile(HOOKS_FILE):
            with open(HOOKS_FILE, encoding="utf-8") as f:
                return cls(json.load(f))
        return cls({})

    def pre_tool(self, name: str, args: dict) -> str | None:
        """Returns a reason string if any hook vetoes the call, else None."""
        for hook in self.pre:
            try:
                if re.fullmatch(hook["match"], name):
                    code, out = self._run(hook["command"], name, args)
                    if code != 0:
                        return out or f"hook '{hook['command']}' exited {code}"
            except Exception as e:   # misconfigured hook: fail closed
                return f"pre_tool hook {hook!r} is broken ({type(e).__name__}: {e})"
        return None

    def post_tool(self, name: str, args: dict, output: str, ok: bool, seconds: float) -> None:
        self.log.append({"tool": name, "ok": ok, "seconds": round(seconds, 2)})
        for hook in self.post:
            try:
                if re.fullmatch(hook["match"], name):
                    self._run(hook["command"], name, args)
            except Exception:
                pass   # the tool already ran; a broken post hook must not crash the agent

    @staticmethod
    def _run(command: str, name: str, args: dict) -> tuple[int, str]:
        env = {**os.environ, "FORGE_TOOL": name, "FORGE_ARGS": json.dumps(args)}
        try:
            # UTF-8 (not the locale code page): a decode error here used to crash the whole agent.
            # run_process also kills cmd.exe's children on a timeout instead of hanging.
            r = run_process(command, 60, shell=True, env=env)
            return r.returncode, (r.stdout + r.stderr).strip()
        except subprocess.TimeoutExpired:
            return 1, "hook timed out"
