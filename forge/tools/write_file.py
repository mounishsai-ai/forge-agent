import os

from forge import checkpoints
from forge.tools.base import Tool, ToolError, files_read, resolve


def write_file(path: str, content: str) -> str:
    p = resolve(path)
    if os.path.exists(p) and p not in files_read:
        raise ToolError(f"{path} already exists. Read it first before overwriting, or use edit_file.")
    checkpoints.record(p)   # snapshot the old content (or "did not exist") so /undo can revert
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(content)
    files_read.add(p)
    return f"Wrote {len(content.splitlines())} lines to {path}"


TOOL = Tool(
    name="write_file",
    description="Create a new file or fully overwrite an existing one. Prefer edit_file for changing existing files.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "content": {"type": "string", "description": "The full file content."},
        },
        "required": ["path", "content"],
    },
    run=write_file,
    needs_permission=True,
)
