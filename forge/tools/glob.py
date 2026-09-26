import glob as _glob
import os

from forge.tools.base import IGNORED_DIRS, Tool, resolve


def glob(pattern: str, path: str = ".") -> str:
    root = resolve(path)
    matches = []
    for m in _glob.glob(pattern, root_dir=root, recursive=True):
        m = m.replace("\\", "/")
        if not any(part in IGNORED_DIRS for part in m.split("/")):
            matches.append(m)
    # Most recently modified first: usually the files you care about.
    matches.sort(key=lambda m: os.path.getmtime(os.path.join(root, m)), reverse=True)
    if not matches:
        return "No files matched."
    extra = f"\n... and {len(matches) - 200} more" if len(matches) > 200 else ""
    return "\n".join(matches[:200]) + extra


TOOL = Tool(
    name="glob",
    description="Find files by name pattern, e.g. '**/*.py' or 'src/**/test_*.js'. Newest first.",
    parameters={
        "type": "object",
        "properties": {
            "pattern": {"type": "string"},
            "path": {"type": "string", "description": "Directory to search from (default: working directory)."},
        },
        "required": ["pattern"],
    },
    run=glob,
)
