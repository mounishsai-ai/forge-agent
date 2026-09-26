"""A planning tool. The model writes its own task list; we show it to the user and echo it back.

It does nothing to the machine. Its value is that it makes the model plan multi-step work
and keeps the plan visible in context, so it doesn't lose track on long tasks.
"""
from forge.tools.base import Tool, ToolError

current: list[dict] = []
MARKS = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]"}


def todo(items: list[dict]) -> str:
    for it in items:
        if it.get("status") not in MARKS or not it.get("task"):
            raise ToolError("Each item needs 'task' and 'status' in pending|in_progress|done.")
    current[:] = items
    return render()


def render() -> str:
    return "\n".join(f"{MARKS[i['status']]} {i['task']}" for i in current) or "(no todos)"


TOOL = Tool(
    name="todo",
    description=(
        "Maintain your task list for multi-step work. Send the FULL updated list each time. "
        "Use it for any task with 3+ steps; mark exactly one item in_progress while working on it."
    ),
    parameters={
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "task": {"type": "string"},
                        "status": {"type": "string", "enum": ["pending", "in_progress", "done"]},
                    },
                    "required": ["task", "status"],
                },
            }
        },
        "required": ["items"],
    },
    run=todo,
)
