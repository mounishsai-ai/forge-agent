"""The `task` tool: the main agent can delegate a research job to a fresh sub-agent.

Why: exploring a big codebase fills the context with file dumps. A sub-agent does that
exploration in its OWN empty context and returns only a short report, so the main
conversation stays small. Sub-agents get read-only tools, so they can't change anything,
and they can't spawn further sub-agents (no recursion).
"""
from forge.permissions import Permissions
from forge.tools import READ_ONLY_TOOLS, Tool
from forge.ui import QuietUI

SUBAGENT_PROMPT = """You are a research sub-agent of Forge, a coding agent. You have read-only tools.
Investigate the task you are given thoroughly, then reply with a concise, factual report:
file paths, line numbers, and the specific findings the caller needs. No preamble."""


def make_task_tool(parent) -> Tool:
    def task(description: str) -> str:
        from forge.agent import Agent   # imported here to avoid a circular import

        child = Agent(llm=parent.llm, ui=QuietUI(verbose=True), permissions=Permissions("readonly"),
                      system_prompt=SUBAGENT_PROMPT + "\n\n" + parent.system_prompt.split("\n\n", 1)[1],
                      tools=READ_ONLY_TOOLS, max_turns=25)
        result = child.run(description)
        parent.usage.add(child.usage)           # the sub-agent's tokens count toward the session cost
        parent.tool_calls_made += child.tool_calls_made
        return result or "(sub-agent returned nothing)"

    return Tool(
        name="task",
        description=(
            "Delegate a read-only research task to a sub-agent with its own fresh context, e.g. "
            "'find where authentication is implemented and explain the flow'. Returns its report. "
            "Use it for broad exploration so your own context stays small."
        ),
        parameters={
            "type": "object",
            "properties": {"description": {"type": "string", "description": "Detailed task for the sub-agent."}},
            "required": ["description"],
        },
        run=task,
    )
