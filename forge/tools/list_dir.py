import os

from forge.tools.base import IGNORED_DIRS, Tool, ToolError, resolve


def list_dir(path: str = ".") -> str:
    p = resolve(path)
    if not os.path.isdir(p):
        raise ToolError(f"Not a directory: {path}")
    entries = []
    for name in sorted(os.listdir(p)):
        if name in IGNORED_DIRS:
            continue
        full = os.path.join(p, name)
        if os.path.isdir(full):
            entries.append(f"{name}/")
        else:
            try:
                entries.append(f"{name}  ({os.path.getsize(full)} bytes)")
            except OSError:   # broken symlink / locked file: still list it
                entries.append(name)
    return "\n".join(entries) or "(empty directory)"


TOOL = Tool(
    name="list_dir",
    description="List files and folders in a directory (non-recursive). Folders end with '/'.",
    parameters={
        "type": "object",
        "properties": {"path": {"type": "string", "description": "Directory (default: working directory)."}},
    },
    run=list_dir,
)
