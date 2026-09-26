"""Plan mode's exit hatch. Plan mode itself is a state on an Agent (its `permissions.plan_mode`
flag and a standing instruction folded into `agent.system_prompt`), toggled by `forge/cli.py`
(the `/plan` command and the `--plan` flag). This module owns:

  - the plan-mode system-prompt instruction (enter_plan_mode / leave_plan_mode below), and
  - the `exit_plan` tool itself, which the MODEL calls once it has a plan ready.

Why the instruction lives in `agent.system_prompt` and not, say, prefixed onto the next user
message in cli.repl: `llm.py` re-sends `system_prompt` on every single model call, so putting the
instruction there means it (a) survives `/compact` (which rewrites `agent.history` wholesale --
anything injected only into a past *user* message would be silently summarized away or dropped
the moment the conversation compacts) and (b) never needs cli.py to remember to re-inject it on
every later turn of the same conversation. It's also the smallest possible change: no edit to
agent.py, since `Agent._ask_model` already reads `self.system_prompt` fresh each call.

Why the note is PREPENDED, not appended: `subagent.make_task_tool` builds a sub-agent's prompt as
`SUBAGENT_PROMPT + parent.system_prompt.partition("\n\n")[2]` -- it keeps everything *after* the
parent's first paragraph (dropping just the "You are Forge..." role paragraph). Appending the plan
note would land inside that kept "rest" and leak "call exit_plan" into a child that has no such
tool. `PLAN_MODE_INSTRUCTION` has no blank line of its own, so prepending it and a single "\n\n"
makes it exactly the first paragraph; `partition("\n\n")[2]` then drops it together with the
original first paragraph, the same way it already drops that paragraph today. (The child ends up
with the original first paragraph appended instead, which is harmless duplication of role text --
far better than a sub-agent being told to call a tool it doesn't have.) subagent.py itself is out
of scope for this change, so this had to be solved from the shape of the string alone.

Why `exit_plan` needs a *factory* (`make_exit_plan_tool(agent)`) instead of a plain module-level
`TOOL`, unlike read_file.py/todo.py etc.: it has to read `agent.permissions.plan_mode`, show the
plan through `agent.ui`, and flip `agent.permissions`/`agent.system_prompt` back -- none of which
a tool's `run(**model_args)` can reach on its own. `forge/subagent.py`'s `make_task_tool(parent)`
is the existing precedent for this same shape.
"""
from forge.tools.base import Tool, ToolError
from forge.ui import console

PLAN_MODE_INSTRUCTION = (
    "You are in PLAN MODE. The permission mode is effectively read-only right now: any edit_file, "
    "write_file, or run_shell call will be denied. Use only read-only tools (read_file, list_dir, "
    "glob, grep, skill, task) to explore the codebase and understand the task. Do not attempt to "
    "make changes yet. Once you have a concrete, step-by-step plan, call the exit_plan tool with "
    "that plan. The user will approve or reject it. If approved, plan mode ends and you should "
    "carry out the plan. If rejected, you remain in plan mode: revise the plan and call exit_plan "
    "again -- do not just start editing."
)
# The exact substring added to / removed from agent.system_prompt while plan mode is active, as a
# PREFIX (see module docstring for why). Kept as one constant so enter/leave/tool-approval all add
# and strip the identical text.
PLAN_MODE_NOTE = PLAN_MODE_INSTRUCTION + "\n\n"


def enter_plan_mode(agent) -> None:
    """Turn plan mode on for one Agent: readonly-equivalent permissions + the standing
    instruction above. Used by cli.py for both `--plan` (at startup) and `/plan` (toggling on)."""
    agent.permissions.enter_plan_mode()
    if PLAN_MODE_NOTE not in agent.system_prompt:
        agent.system_prompt = PLAN_MODE_NOTE + agent.system_prompt


def leave_plan_mode(agent) -> None:
    """Manual exit: the `/plan` command toggling back off. Equivalent to an approved exit_plan
    call, but there's no plan text to show since the user asked to leave directly."""
    agent.permissions.exit_plan_mode(approved=True)
    _strip_note(agent)


def _strip_note(agent) -> None:
    if PLAN_MODE_NOTE in agent.system_prompt:
        agent.system_prompt = agent.system_prompt.replace(PLAN_MODE_NOTE, "")


def _collect_rejection_feedback(agent) -> str:
    """Best-effort: ask what should change, so a rejection can carry real feedback back to the
    model, not just the bare fact of rejection. `ui.ask_permission` only returns y/n/a, and adding
    a new method to ui.py is out of scope here, so this reads directly from `forge.ui.console`
    (already a shared singleton, not a new abstraction) -- but ONLY when `agent.ui.streams` is
    True (ConsoleUI; QuietUI/FakeUI/a sub-agent's UI are all False), since headless and test UIs
    have no human at a terminal to answer, and a blocking read there would hang forever."""
    if not getattr(agent.ui, "streams", False):
        return ""
    try:
        return console.input("[yellow]What should change? (Enter to skip): [/]").strip()
    except (EOFError, KeyboardInterrupt):
        return ""


def make_exit_plan_tool(agent) -> Tool:
    """Build the exit_plan tool bound to one Agent (see module docstring for why it must be a
    factory). Registered once in cli.build_agent, the same way subagent.make_task_tool is."""

    # exit_plan has needs_permission=False (see below) so agent._parallel_ok would otherwise let
    # it run in a worker thread alongside other read-only calls in the same model turn -- but its
    # run() calls agent.ui.assistant_text/ask_permission (and, on rejection, console.input()),
    # which must stay on the main thread (agent.py's own contract for parallel batches: "only
    # tool.run() goes to worker threads", never UI/printing). Adding the name to this Agent's own
    # SEQUENTIAL_ONLY set (shadowing the class attribute -- see Agent._parallel_ok) forces it to
    # always run alone, without editing agent.py.
    agent.SEQUENTIAL_ONLY = agent.SEQUENTIAL_ONLY | {"exit_plan"}

    def exit_plan(plan: str) -> str:
        if not agent.permissions.plan_mode:
            raise ToolError(
                "exit_plan is only available in plan mode. It looks like plan mode isn't active "
                "(the user would start it with /plan or --plan) -- there is no plan to approve.")

        agent.ui.assistant_text(f"### Proposed plan\n\n{plan}")
        answer = agent.ui.ask_permission("exit_plan", {"plan": plan})   # 'y'/'a' approve, 'n' reject

        if answer in ("y", "a"):
            agent.permissions.exit_plan_mode(approved=True)
            _strip_note(agent)
            return "The user approved the plan. Plan mode is now off -- proceed with the plan."

        feedback = _collect_rejection_feedback(agent)
        agent.permissions.exit_plan_mode(approved=False)   # no-op when already rejected-and-staying
        msg = "The user rejected the plan"
        msg += f", with this feedback: {feedback}" if feedback else " (no further feedback given)"
        return (f"{msg}. Stay in plan mode (read-only tools only): revise the plan accordingly and "
                "call exit_plan again once it's ready.")

    return Tool(
        name="exit_plan",
        description=(
            "Call this ONLY while in plan mode, once you have a concrete, step-by-step plan for "
            "the task. It shows the plan to the user for approval. Approved: plan mode ends and "
            "you proceed. Rejected: you stay in plan mode and should revise the plan, then call "
            "exit_plan again. Calling it outside plan mode is an error."
        ),
        parameters={
            "type": "object",
            "properties": {
                "plan": {
                    "type": "string",
                    "description": "The concrete, step-by-step plan to show the user for approval.",
                },
            },
            "required": ["plan"],
        },
        run=exit_plan,
        needs_permission=False,   # its own approval flow replaces the generic ask/auto/readonly gate
    )
