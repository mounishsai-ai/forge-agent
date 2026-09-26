"""Tool registry: the single list of tools the agent can use. Add a tool = add one file + one line here."""
from forge.tools import edit_file, glob, grep, list_dir, read_file, run_shell, skill, todo, write_file
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
    skill.TOOL,
]

# Tools that cannot change anything. Sub-agents only get these.
# (todo is excluded: its list is shared state and belongs to the main agent.)
READ_ONLY_TOOLS: list[Tool] = [t for t in ALL_TOOLS if not t.needs_permission and t.name != "todo"]


def add_tools(agent, extra: list[Tool]) -> list[Tool]:
    """Add runtime tools (e.g. from MCP servers) to one agent, without touching ALL_TOOLS.
    A name that is already taken is skipped, so an extra tool can never replace a built-in."""
    added = []
    for t in extra:
        if t.name not in agent.tools:
            agent.tools[t.name] = t
            added.append(t)
    return added


__all__ = ["ALL_TOOLS", "READ_ONLY_TOOLS", "Tool", "ToolError", "add_tools"]
