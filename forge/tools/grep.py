import fnmatch
import os
import re

from forge.tools.base import IGNORED_DIRS, Tool, ToolError, resolve, truncate

MAX_MATCHES = 200


def grep(pattern: str, path: str = ".", file_glob: str | None = None, ignore_case: bool = False) -> str:
    try:
        rx = re.compile(pattern, re.IGNORECASE if ignore_case else 0)
    except re.error as e:
        raise ToolError(f"Bad regex: {e}")
    root = resolve(path)
    files = [root] if os.path.isfile(root) else _walk(root)
    out = []
    for f in files:
        if file_glob and not fnmatch.fnmatch(os.path.basename(f), file_glob):
            continue
        try:
            with open(f, encoding="utf-8") as fh:
                for n, line in enumerate(fh, 1):
                    if rx.search(line):
                        out.append(f"{_display(f)}:{n}: {line.rstrip()[:300]}")
                        if len(out) >= MAX_MATCHES:
                            return truncate("\n".join(out) + f"\n[stopped at {MAX_MATCHES} matches]")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable file
    return truncate("\n".join(out)) if out else "No matches."


def _display(path: str) -> str:
    """Path relative to cwd when possible. On Windows relpath raises ValueError for a file on
    another drive (e.g. searching D:\\ from C:\\), which used to fail the whole grep."""
    try:
        return os.path.relpath(path)
    except ValueError:
        return path


def _walk(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]  # prune in place so os.walk skips them
        for name in filenames:
            yield os.path.join(dirpath, name)


TOOL = Tool(
    name="grep",
    description="Search file contents with a regex. Returns 'file:line: text'. Use file_glob like '*.py' to filter.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string", "description": "Python regular expression."},
            "path": {"type": "string", "description": "File or directory (default: working directory)."},
            "file_glob": {"type": "string", "description": "Only search files whose name matches, e.g. '*.py'."},
            "ignore_case": {"type": "boolean"},
        },
        "required": ["pattern"],
    },
    run=grep,
)
