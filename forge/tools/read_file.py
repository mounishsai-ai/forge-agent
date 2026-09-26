import os

from forge.tools.base import Tool, ToolError, files_read, resolve, truncate


def read_file(path: str, offset: int = 1, limit: int = 2000) -> str:
    p = resolve(path)
    if not os.path.isfile(p):
        raise ToolError(f"File not found: {path}")
    with open(p, encoding="utf-8", errors="replace") as f:
        lines = f.readlines()
    files_read.add(p)
    offset, limit = int(offset), int(limit)   # the model may send 10.0; slicing needs ints
    start = max(offset, 1) - 1
    chunk = lines[start:start + limit]
    # Line numbers help the model reference exact locations.
    numbered = "".join(f"{i:>6}\t{line}" for i, line in enumerate(chunk, start=start + 1))
    footer = f"\n[showing lines {start + 1}-{start + len(chunk)} of {len(lines)}]" if len(lines) > len(chunk) else ""
    return truncate(numbered + footer) or "(empty file)"


TOOL = Tool(
    name="read_file",
    description="Read a text file. Returns contents with line numbers. Use offset/limit for large files.",
    parameters={
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "File path, relative to the working directory or absolute."},
            "offset": {"type": "integer", "description": "1-based line to start from (default 1)."},
            "limit": {"type": "integer", "description": "Max lines to return (default 2000)."},
        },
        "required": ["path"],
    },
    run=read_file,
)
