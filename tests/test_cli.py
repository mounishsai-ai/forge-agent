from forge.agent import Agent
from forge.cli import handle_command
from forge.permissions import Permissions
from forge.tools import ALL_TOOLS


def make_agent(llm, ui):
    return Agent(llm=llm, ui=ui, permissions=Permissions("ask"), system_prompt="sys",
                 tools=ALL_TOOLS, max_turns=10)


def test_clear_empties_history(fake_llm_factory, fake_ui):
    agent = make_agent(fake_llm_factory([]), fake_ui)
    agent.history.append("anything")
    agent.last_prompt_tokens = 999
    result = handle_command("/clear", agent, fake_ui)
    assert result is None
    assert agent.history == []
    assert agent.last_prompt_tokens == 0
    assert any("cleared" in m for m in fake_ui.infos)


def test_model_shows_current_without_arg(fake_llm_factory, fake_ui):
    llm = fake_llm_factory([])
    agent = make_agent(llm, fake_ui)
    handle_command("/model", agent, fake_ui)
    assert any(agent.llm.model in m for m in fake_ui.infos)


def test_model_switches_model(fake_llm_factory, fake_ui):
    llm = fake_llm_factory([])
    agent = make_agent(llm, fake_ui)
    handle_command("/model gemini-3.5-flash", agent, fake_ui)
    assert agent.llm.model == "gemini-3.5-flash"
    assert any("gemini-3.5-flash" in m for m in fake_ui.infos)


def test_mode_readonly_switches_permission_mode(fake_llm_factory, fake_ui):
    agent = make_agent(fake_llm_factory([]), fake_ui)
    handle_command("/mode readonly", agent, fake_ui)
    assert agent.permissions.mode == "readonly"


def test_mode_rejects_unknown_value(fake_llm_factory, fake_ui):
    agent = make_agent(fake_llm_factory([]), fake_ui)
    handle_command("/mode nonsense", agent, fake_ui)
    assert agent.permissions.mode == "ask"   # unchanged


def test_unknown_command_reports_error(fake_llm_factory, fake_ui):
    agent = make_agent(fake_llm_factory([]), fake_ui)
    handle_command("/frobnicate", agent, fake_ui)
    assert any("Unknown command" in m for m in fake_ui.errors)


def test_exit_returns_exit_sentinel(fake_llm_factory, fake_ui):
    agent = make_agent(fake_llm_factory([]), fake_ui)
    assert handle_command("/exit", agent, fake_ui) == "exit"
    assert handle_command("/quit", agent, fake_ui) == "exit"
