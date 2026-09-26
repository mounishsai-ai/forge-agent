"""Tool registry: the single list of tools the agent can use. Add a tool = add one file + one line here."""
from forge.tools import edit_file, glob, grep, list_dir, read_file, run_shell, todo, write_file
from forge.tools.base import Tool, ToolError

ALL_TOOLS: list[Tool] = [
    read_file.TOOL,
    list_dir.TOOL,
    glob.TOOL,
    grep.TOOL,
    write_file.TOOL,
    edit_file.TOOL,
    run_shell.TOOL,
    todo.TOOL,
]

# Tools that cannot change anything. Sub-agents only get these.
# (todo is excluded: its list is shared state and belongs to the main agent.)
READ_ONLY_TOOLS: list[Tool] = [t for t in ALL_TOOLS if not t.needs_permission and t.name != "todo"]

__all__ = ["ALL_TOOLS", "READ_ONLY_TOOLS", "Tool", "ToolError"]
