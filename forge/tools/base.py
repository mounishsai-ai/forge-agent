"""What a tool is: a name, a description + JSON schema the model reads, and a Python function we run."""
import os
from dataclasses import dataclass
from typing import Callable

from google.genai import types

from forge import config


class ToolError(Exception):
    """Raised by a tool for expected failures (file missing, no match...). Sent back to the model as text."""


@dataclass
class Tool:
    name: str
    description: str           # the model decides WHEN to use a tool purely from this text
    parameters: dict           # JSON schema of the arguments
    run: Callable[..., str]    # the actual implementation; always returns a string
    needs_permission: bool = False   # True for anything that changes the machine (write, edit, shell)

    def declaration(self) -> types.FunctionDeclaration:
        return types.FunctionDeclaration(
            name=self.name, description=self.description, parameters_json_schema=self.parameters
        )


def resolve(path: str) -> str:
    """Turn a relative path into an absolute one, relative to the directory Forge was started in."""
    return os.path.abspath(os.path.join(os.getcwd(), os.path.expanduser(path)))


def truncate(text: str, limit: int = config.TOOL_OUTPUT_LIMIT) -> str:
    """Keep head and tail of long output so one huge result can't flood the context window."""
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n\n... [{len(text) - limit} chars truncated] ...\n\n{text[-half:]}"


# Directories that are never worth searching.
IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".forge", "dist", "build", ".mypy_cache"}

# Absolute paths the model has read this session. Editing/overwriting a file it has not seen
# is refused: this stops the model from clobbering code based on a guess of what is inside.
files_read: set[str] = set()
