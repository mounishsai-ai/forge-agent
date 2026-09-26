import os
import subprocess

from forge import config
from forge.tools.base import Tool, truncate

IS_WINDOWS = os.name == "nt"
SHELL_NAME = "PowerShell" if IS_WINDOWS else "bash"


def run_shell(command: str, timeout: int = config.SHELL_TIMEOUT) -> str:
    # PowerShell on Windows, bash elsewhere. Each call is a fresh process (no state carries over).
    if IS_WINDOWS:
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        argv = ["bash", "-c", command]
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           encoding="utf-8", errors="replace", stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return f"Command timed out after {timeout}s."
    out = r.stdout or ""
    if r.stderr and r.stderr.strip():
        out += f"\n[stderr]\n{r.stderr}"
    return truncate(f"{out.strip()}\n[exit code {r.returncode}]".strip())


TOOL = Tool(
    name="run_shell",
    description=(
        f"Run a {SHELL_NAME} command in the working directory; returns stdout/stderr and exit code. "
        "Use for running tests, git, installing packages, etc. "
        "Not interactive: never run commands that wait for input."
    ),
    parameters={
        "type": "object",
        "properties": {
            "command": {"type": "string"},
            "timeout": {"type": "integer", "description": f"Seconds (default {config.SHELL_TIMEOUT})."},
        },
        "required": ["command"],
    },
    run=run_shell,
    needs_permission=True,
)
