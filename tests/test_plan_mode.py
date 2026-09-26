"""Offline tests for plan mode: Permissions.enter_plan_mode/exit_plan_mode, the exit_plan tool
(forge/tools/exit_plan.py), and the cli.py wiring (/plan, --plan, build_agent, the /mode guard).

No network: agent-shaped tests build a real Agent with FakeLLM/FakeUI (same pattern as
tests/test_cli.py), and build_agent's own test monkeypatches cli.GeminiLLM so it never touches
the real API or requires FORGE_PROJECT.
"""
import forge.agent
from forge.agent import Agent
from forge.cli import build_agent, build_parser, handle_command
from forge.llm import ToolCall, Usage
from forge.permissions import Permissions
from forge.tools import ALL_TOOLS, exit_plan, read_file, write_file
from forge.tools.base import ToolError


def make_agent(llm, ui, mode="ask", system_prompt="base prompt"):
    agent = Agent(llm=llm, ui=ui, permissions=Permissions(mode), system_prompt=system_prompt,
                  tools=list(ALL_TOOLS), max_turns=10)
    agent.tools["exit_plan"] = exit_plan.make_exit_plan_tool(agent)
    return agent


# ---------------------------------------------------------------------------
# Permissions: the plan-mode state machine itself
# ---------------------------------------------------------------------------
def test_enter_plan_mode_forces_readonly_and_remembers_previous_mode():
    p = Permissions("ask")
    p.enter_plan_mode()
    assert p.plan_mode is True
    assert p.mode == "readonly"


def test_enter_plan_mode_is_idempotent():
    p = Permissions("auto")
    p.enter_plan_mode()
    p.enter_plan_mode()   # calling it again must not clobber the saved pre-plan mode
    p.exit_plan_mode(approved=True)
    assert p.mode == "auto"


def test_exit_plan_mode_approved_restores_previous_mode():
    p = Permissions("auto")
    p.enter_plan_mode()
    p.exit_plan_mode(approved=True)
    assert p.plan_mode is False
    assert p.mode == "auto"


def test_exit_plan_mode_rejected_stays_in_plan_mode():
    p = Permissions("ask")
    p.enter_plan_mode()
    p.exit_plan_mode(approved=False)
    assert p.plan_mode is True
    assert p.mode == "readonly"


def test_exit_plan_mode_noop_when_not_in_plan_mode():
    p = Permissions("ask")
    p.exit_plan_mode(approved=True)   # never entered plan mode: must not raise or change mode
    assert p.mode == "ask"
    assert p.plan_mode is False


def test_plan_mode_denies_writes(fake_ui_factory):
    p = Permissions("auto")
    p.enter_plan_mode()
    ok, reason = p.check(write_file.TOOL, {"path": "x.txt", "content": "y"}, fake_ui_factory())
    assert ok is False
    assert "read-only" in reason


def test_plan_mode_allows_reads(fake_ui_factory):
    p = Permissions("auto")
    p.enter_plan_mode()
    ok, _ = p.check(read_file.TOOL, {"path": "x.txt"}, fake_ui_factory())
    assert ok is True


# ---------------------------------------------------------------------------
# exit_plan tool
# ---------------------------------------------------------------------------
def test_exit_plan_raises_outside_plan_mode(fake_llm_factory, fake_ui):
    agent = make_agent(fake_llm_factory([]), fake_ui, mode="ask")
    assert agent.permissions.plan_mode is False
    try:
        agent.tools["exit_plan"].run(plan="do the thing")
        assert False, "expected a ToolError"
    except ToolError as e:
        assert "plan mode" in str(e)


def test_exit_plan_approved_restores_mode_and_shows_plan(fake_llm_factory, fake_ui_factory):
    ui = fake_ui_factory(answers=["y"])
    agent = make_agent(fake_llm_factory([]), ui, mode="ask")
    exit_plan.enter_plan_mode(agent)
    assert agent.permissions.plan_mode is True
    assert exit_plan.PLAN_MODE_NOTE in agent.system_prompt

    result = agent.tools["exit_plan"].run(plan="1. read the file\n2. fix the bug")

    assert "approved" in result.lower()
    assert agent.permissions.plan_mode is False
    assert agent.permissions.mode == "ask"                       # restored, not left on readonly
    assert exit_plan.PLAN_MODE_NOTE not in agent.system_prompt    # instruction cleaned up
    assert any("Proposed plan" in t for t in ui.assistant_texts)  # the plan was shown to the user
    assert ui.asked and ui.asked[0][0] == "exit_plan"


def test_exit_plan_approved_via_always_answer(fake_llm_factory, fake_ui_factory):
    ui = fake_ui_factory(answers=["a"])   # 'a' (always) should also count as approval
    agent = make_agent(fake_llm_factory([]), ui, mode="auto")
    exit_plan.enter_plan_mode(agent)
    result = agent.tools["exit_plan"].run(plan="do it")
    assert agent.permissions.plan_mode is False
    assert "approved" in result.lower()


def test_exit_plan_rejected_stays_in_plan_mode(fake_llm_factory, fake_ui_factory):
    ui = fake_ui_factory(answers=["n"])
    agent = make_agent(fake_llm_factory([]), ui, mode="ask")
    exit_plan.enter_plan_mode(agent)

    result = agent.tools["exit_plan"].run(plan="a bad plan")

    assert "rejected" in result.lower()
    assert agent.permissions.plan_mode is True
    assert agent.permissions.mode == "readonly"                # still effectively read-only
    assert exit_plan.PLAN_MODE_NOTE in agent.system_prompt      # instruction still in effect

    # Writes are still denied after a rejection, without a second /plan.
    ok, _ = agent.permissions.check(write_file.TOOL, {"path": "x", "content": "y"}, ui)
    assert ok is False


# ---------------------------------------------------------------------------
# forge/cli.py wiring
# ---------------------------------------------------------------------------
def test_plan_flag_parses():
    args = build_parser().parse_args(["--plan", "-p", "do the task"])
    assert args.plan is True


def test_plan_flag_defaults_false():
    args = build_parser().parse_args(["-p", "do the task"])
    assert args.plan is False


def test_build_agent_with_plan_flag_starts_in_plan_mode(monkeypatch, project_dir, fake_llm_factory, fake_ui):
    # build_agent() constructs a real GeminiLLM; swap it for FakeLLM so this test needs no
    # network access and no FORGE_PROJECT/GOOGLE_CLOUD_PROJECT env var.
    monkeypatch.setattr("forge.cli.GeminiLLM", lambda model, fallbacks: fake_llm_factory([], model=model))
    args = build_parser().parse_args(["--plan", "-p", "do the task"])

    agent = build_agent(args, fake_ui)

    assert agent.permissions.plan_mode is True
    assert agent.permissions.mode == "readonly"
    assert "exit_plan" in agent.tools
    assert exit_plan.PLAN_MODE_NOTE in agent.system_prompt


def test_build_agent_without_plan_flag_stays_out_of_plan_mode(monkeypatch, project_dir, fake_llm_factory, fake_ui):
    monkeypatch.setattr("forge.cli.GeminiLLM", lambda model, fallbacks: fake_llm_factory([], model=model))
    args = build_parser().parse_args(["-p", "do the task"])

    agent = build_agent(args, fake_ui)

    assert agent.permissions.plan_mode is False
    assert "exit_plan" in agent.tools   # tool is always registered, usable once /plan is used


def test_slash_plan_toggles_on_then_off(fake_llm_factory, fake_ui):
    agent = make_agent(fake_llm_factory([]), fake_ui, mode="ask")

    handle_command("/plan", agent, fake_ui)
    assert agent.permissions.plan_mode is True
    assert agent.permissions.mode == "readonly"
    assert exit_plan.PLAN_MODE_NOTE in agent.system_prompt
    assert any("Plan mode on" in m for m in fake_ui.infos)

    handle_command("/plan", agent, fake_ui)
    assert agent.permissions.plan_mode is False
    assert agent.permissions.mode == "ask"
    assert exit_plan.PLAN_MODE_NOTE not in agent.system_prompt
    assert any("Plan mode off" in m for m in fake_ui.infos)


def test_slash_mode_is_refused_while_in_plan_mode(fake_llm_factory, fake_ui):
    agent = make_agent(fake_llm_factory([]), fake_ui, mode="ask")
    handle_command("/plan", agent, fake_ui)

    handle_command("/mode auto", agent, fake_ui)

    assert agent.permissions.mode == "readonly"   # unchanged: the guard refused the switch
    assert any("plan mode" in m.lower() for m in fake_ui.errors)


def test_slash_mode_still_works_outside_plan_mode(fake_llm_factory, fake_ui):
    agent = make_agent(fake_llm_factory([]), fake_ui, mode="ask")
    handle_command("/mode readonly", agent, fake_ui)
    assert agent.permissions.mode == "readonly"
    assert agent.permissions.plan_mode is False


# ---------------------------------------------------------------------------
# Regressions caught in review: exit_plan must never run in a worker thread,
# and its plan-mode note must not leak into a `task` sub-agent's prompt.
# ---------------------------------------------------------------------------
def test_exit_plan_is_registered_as_sequential_only(fake_llm_factory, fake_ui):
    """exit_plan has needs_permission=False, so without this it would be eligible to run
    concurrently with other read-only calls in the same turn (Agent._parallel_ok) -- but its
    run() calls agent.ui.assistant_text/ask_permission (and maybe console.input), which must stay
    on the main thread per agent.py's own contract for a parallel batch."""
    agent = make_agent(fake_llm_factory([]), fake_ui)
    assert "exit_plan" in agent.SEQUENTIAL_ONLY
    assert agent._parallel_ok(ToolCall(id="1", name="exit_plan", args={"plan": "x"})) is False


def test_exit_plan_sequential_only_does_not_leak_to_other_agents(fake_llm_factory, fake_ui):
    """agent.SEQUENTIAL_ONLY |= {"exit_plan"} must create a new instance attribute, not mutate
    the Agent class attribute -- otherwise every Agent in the process would be affected."""
    make_agent(fake_llm_factory([]), fake_ui)   # registers exit_plan on its own agent instance
    other = Agent(llm=fake_llm_factory([]), ui=fake_ui, permissions=Permissions("ask"),
                   system_prompt="x", tools=list(ALL_TOOLS), max_turns=5)
    assert "exit_plan" not in other.SEQUENTIAL_ONLY
    assert Agent.SEQUENTIAL_ONLY == {"task", "todo"}


def test_exit_plan_rejection_collects_feedback_when_ui_is_interactive(fake_llm_factory, fake_ui_factory,
                                                                        monkeypatch):
    """On rejection the tool should return real feedback, not just the bare fact of rejection --
    but only when the UI is interactive (streams=True); see _collect_rejection_feedback."""
    class InteractiveFakeUI(fake_ui_factory):
        streams = True

    ui = InteractiveFakeUI(answers=["n"])
    agent = make_agent(fake_llm_factory([]), ui, mode="ask")
    exit_plan.enter_plan_mode(agent)
    monkeypatch.setattr("forge.tools.exit_plan.console.input", lambda *a, **k: "add more error handling")

    result = agent.tools["exit_plan"].run(plan="a plan")

    assert "add more error handling" in result
    assert agent.permissions.plan_mode is True   # still rejected -> still in plan mode


def test_exit_plan_rejection_skips_feedback_prompt_when_ui_is_headless(fake_llm_factory, fake_ui):
    """FakeUI (like QuietUI) has streams=False: there's no terminal to answer a feedback prompt,
    so this must not attempt to read one (which would hang against a real console.input)."""
    agent = make_agent(fake_llm_factory([]), fake_ui, mode="ask")
    exit_plan.enter_plan_mode(agent)

    result = agent.tools["exit_plan"].run(plan="a plan")

    assert "no further feedback" in result


def test_task_subagent_prompt_does_not_inherit_the_plan_instruction(monkeypatch, fake_llm_factory, fake_ui):
    """The `task` tool builds a fresh sub-agent whose prompt is
    `SUBAGENT_PROMPT + parent.system_prompt.partition("\\n\\n")[2]` (forge/subagent.py, out of
    scope for this feature). Plan mode's note must be structured so that slice drops it too --
    otherwise the child would be told to call exit_plan, a tool it doesn't have."""
    from forge.subagent import make_task_tool

    agent = make_agent(fake_llm_factory([]), fake_ui, mode="ask",
                        system_prompt="You are Forge...\n\nEnvironment: ...")
    exit_plan.enter_plan_mode(agent)
    assert agent.system_prompt.startswith(exit_plan.PLAN_MODE_INSTRUCTION)

    seen = {}

    class FakeChild:
        def __init__(self, **kw):
            seen.update(kw)
            self.usage = Usage()
            self.tool_calls_made = 0

        def run(self, description):
            return "child report"

    monkeypatch.setattr(forge.agent, "Agent", FakeChild)
    result = make_task_tool(agent).run(description="investigate")

    assert result == "child report"
    assert "exit_plan" not in seen["system_prompt"]
    assert "PLAN MODE" not in seen["system_prompt"]
