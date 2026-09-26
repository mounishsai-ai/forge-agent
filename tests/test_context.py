from google.genai import types

from forge import config, context
from forge.agent import Agent
from forge.permissions import Permissions
from forge.tools import ALL_TOOLS


def make_agent(llm, ui):
    return Agent(llm=llm, ui=ui, permissions=Permissions("auto"), system_prompt="sys",
                 tools=ALL_TOOLS, max_turns=10)


def test_compact_replaces_history_with_two_messages(fake_llm_factory, fake_ui):
    llm = fake_llm_factory([{"text": "summary of everything"}])
    agent = make_agent(llm, fake_ui)
    agent.history = [
        types.Content(role="user", parts=[types.Part(text="msg1")]),
        types.Content(role="model", parts=[types.Part(text="reply1")]),
        types.Content(role="user", parts=[types.Part(text="msg2")]),
    ]
    result = context.compact(agent)
    assert "Compacted 3 messages" in result
    assert len(agent.history) == 2
    assert agent.history[0].role == "user"
    assert "summary of everything" in agent.history[0].parts[0].text
    assert agent.history[1].role == "model"
    assert agent.last_prompt_tokens == 0


def test_compact_with_no_history_is_a_noop(fake_llm_factory, fake_ui):
    llm = fake_llm_factory([])
    agent = make_agent(llm, fake_ui)
    agent.history = [types.Content(role="user", parts=[types.Part(text="only one")])]
    result = context.compact(agent)
    assert result == "Nothing to compact."
    assert len(llm.calls) == 0   # never asked the model
    assert len(agent.history) == 1


def test_maybe_compact_triggers_only_over_threshold(monkeypatch, fake_llm_factory, fake_ui):
    monkeypatch.setattr(config, "COMPACT_AT_TOKENS", 100)
    llm = fake_llm_factory([{"text": "summary"}])
    agent = make_agent(llm, fake_ui)
    agent.history = [
        types.Content(role="user", parts=[types.Part(text="msg1")]),
        types.Content(role="model", parts=[types.Part(text="reply1")]),
    ]

    agent.last_prompt_tokens = 50   # under threshold
    context.maybe_compact(agent)
    assert len(llm.calls) == 0
    assert len(agent.history) == 2

    agent.last_prompt_tokens = 150   # over threshold
    context.maybe_compact(agent)
    assert len(llm.calls) == 1
    assert len(agent.history) == 2   # replaced with the 2-message summary
