import os
import subprocess

from forge import config
from forge.tools.base import Tool, truncate

IS_WINDOWS = os.name == "nt"
SHELL_NAME = "PowerShell" if IS_WINDOWS else "bash"


def run_process(args, timeout: float, **popen_kwargs) -> subprocess.CompletedProcess:
    """Like subprocess.run(args, capture_output=True, timeout=...) with UTF-8 text, but on a
    timeout (or Ctrl+C) it kills the whole process TREE before re-raising.

    Why not subprocess.run: on Windows it only kills the direct child (powershell / cmd), and
    then waits for the output pipes to close. A grandchild (e.g. `python server.py` started by
    powershell) still holds those pipes, so a "timeout=3" command could hang until the
    grandchild exits on its own - forever for a dev server."""
    proc = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            encoding="utf-8", errors="replace", **popen_kwargs)
    try:
        out, err = proc.communicate(timeout=timeout)
    except BaseException:
        _kill_tree(proc)
        raise
    return subprocess.CompletedProcess(args, proc.returncode, out, err)


def _kill_tree(proc: subprocess.Popen) -> None:
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)],
                       capture_output=True, stdin=subprocess.DEVNULL)
        try:
            proc.communicate(timeout=5)   # drain + close the pipes; never wait forever
        except subprocess.TimeoutExpired:
            pass
    else:
        proc.kill()                        # same as subprocess.run does on POSIX
        proc.wait()
        for pipe in (proc.stdout, proc.stderr):
            if pipe:
                pipe.close()


def run_shell(command: str, timeout: int = config.SHELL_TIMEOUT) -> str:
    # PowerShell on Windows, bash elsewhere. Each call is a fresh process (no state carries over).
    # FORGE_SHELL_INIT (optional) runs first every time, e.g. "source venv/bin/activate".
    if config.SHELL_INIT:
        command = f"{config.SHELL_INIT}\n{command}"
    if IS_WINDOWS:
        # PowerShell 5.1 writes to a pipe in the OEM/ANSI code page, so "é" came back as U+FFFD
        # after our UTF-8 decode. Make its own output UTF-8 (no BOM); guarded in case there's no console.
        command = ("try { [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding $false } catch {}\n"
                   + command)
        # Without this, PowerShell reports every failing program's exit code as just 1.
        command += "\nif ($LASTEXITCODE) { exit $LASTEXITCODE } elseif (-not $?) { exit 1 }"
        argv = ["powershell", "-NoProfile", "-NonInteractive", "-Command", command]
    else:
        argv = ["bash", "-c", command]
    try:
        r = run_process(argv, timeout)
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
