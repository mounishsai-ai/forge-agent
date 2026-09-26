import os

from forge import checkpoints
from forge.tools.base import Tool, ToolError, files_read, resolve


def edit_file(path: str, old_string: str, new_string: str, replace_all: bool = False) -> str:
    p = resolve(path)
    if not os.path.isfile(p):
        raise ToolError(f"File not found: {path}")
    if p not in files_read:
        raise ToolError(f"Read {path} with read_file before editing it.")
    with open(p, encoding="utf-8", newline="") as f:
        text = f.read()
    # read_file shows the model "\n" line endings, so match in that form and restore CRLF when saving.
    crlf = "\r\n" in text
    if crlf:
        text = text.replace("\r\n", "\n")
        old_string, new_string = old_string.replace("\r\n", "\n"), new_string.replace("\r\n", "\n")

    # Exact string match instead of line numbers or diffs: robust to the model miscounting lines,
    # and requiring a UNIQUE match stops it from editing the wrong occurrence.
    count = text.count(old_string)
    if count == 0:
        raise ToolError("old_string not found. It must match the file exactly, including whitespace/indentation.")
    if count > 1 and not replace_all:
        raise ToolError(f"old_string appears {count} times. Add surrounding lines to make it unique, or set replace_all.")

    text = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
    if crlf:
        text = text.replace("\n", "\r\n")
    checkpoints.record(p)   # only after all checks pass: a failed edit changes nothing, so no snapshot
    with open(p, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    return f"Edited {path} ({count if replace_all else 1} replacement(s))"


TOOL = Tool(
    name="edit_file",
    description=(
        "Replace an exact string in a file. old_string must match exactly (including indentation) and be "
        "unique in the file unless replace_all is true. You must read_file first."
    ),
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "old_string": {"type": "string", "description": "Exact text to find."},
            "new_string": {"type": "string", "description": "Replacement text."},
            "replace_all": {"type": "boolean", "description": "Replace every occurrence (default false)."},
        },
        "required": ["path", "old_string", "new_string"],
    },
    run=edit_file,
    needs_permission=True,
)
