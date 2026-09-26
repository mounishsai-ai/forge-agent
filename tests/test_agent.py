import json

from google.genai import types

from forge.agent import Agent
from forge.permissions import Permissions
from forge.tools import ALL_TOOLS, list_dir, read_file
from forge.tools.base import Tool, ToolError


def make_agent(llm, ui, mode="auto", tools=None, max_turns=10, hooks=None):
    return Agent(llm=llm, ui=ui, permissions=Permissions(mode), system_prompt="sys",
                 tools=tools if tools is not None else ALL_TOOLS, max_turns=max_turns, hooks=hooks)


# ---------------------------------------------------------------------------
# Basic flow
# ---------------------------------------------------------------------------
def test_final_text_with_no_tools_returns_immediately(fake_llm_factory, fake_ui):
    llm = fake_llm_factory([{"text": "hello there"}])
    agent = make_agent(llm, fake_ui)
    result = agent.run("hi")
    assert result == "hello there"
    assert len(llm.calls) == 1


def test_tool_call_then_final_answer(project_dir, fake_llm_factory, fake_ui):
    (project_dir / "a.txt").write_text("hello\n", encoding="utf-8")
    llm = fake_llm_factory([
        {"calls": [{"name": "read_file", "args": {"path": "a.txt"}}]},
        {"text": "the file says hello"},
    ])
    agent = make_agent(llm, fake_ui)
    result = agent.run("read a.txt")
    assert result == "the file says hello"
    assert len(llm.calls) == 2

    # The tool result must have been appended to history as a function_response.
    tool_result_msg = agent.history[2]
    assert tool_result_msg.role == "user"
    fr = tool_result_msg.parts[0].function_response
    assert fr.name == "read_file"
    assert "hello" in fr.response["output"]


def test_unknown_tool_name_reported_as_error(fake_llm_factory, fake_ui):
    llm = fake_llm_factory([
        {"calls": [{"name": "does_not_exist", "args": {}}]},
        {"text": "done"},
    ])
    agent = make_agent(llm, fake_ui)
    agent.run("go")
    fr = agent.history[2].parts[0].function_response
    assert "error" in fr.response
    assert "Unknown tool" in fr.response["error"]


def test_tool_error_becomes_error_response(project_dir, fake_llm_factory, fake_ui):
    llm = fake_llm_factory([
        {"calls": [{"name": "read_file", "args": {"path": "missing.txt"}}]},
        {"text": "done"},
    ])
    agent = make_agent(llm, fake_ui)
    agent.run("go")
    fr = agent.history[2].parts[0].function_response
    assert "error" in fr.response
    assert "File not found" in fr.response["error"]


def test_bad_arguments_typeerror_handled(fake_llm_factory, fake_ui):
    # read_file requires 'path'; omitting it raises TypeError inside tool.run(**call.args).
    llm = fake_llm_factory([
        {"calls": [{"name": "read_file", "args": {}}]},
        {"text": "done"},
    ])
    agent = make_agent(llm, fake_ui)
    result = agent.run("go")
    fr = agent.history[2].parts[0].function_response
    assert "error" in fr.response
    assert "Bad arguments" in fr.response["error"]
    assert result == "done"   # the agent kept going instead of crashing


def test_permission_denied_result(project_dir, fake_llm_factory, fake_ui):
    llm = fake_llm_factory([
        {"calls": [{"name": "write_file", "args": {"path": "x.txt", "content": "y"}}]},
        {"text": "done"},
    ])
    agent = make_agent(llm, fake_ui, mode="readonly")
    agent.run("write a file")
    fr = agent.history[2].parts[0].function_response
    assert "error" in fr.response
    assert "read-only" in fr.response["error"]
    assert not (project_dir / "x.txt").exists()


def test_max_turns_cap_message(fake_llm_factory, fake_ui):
    # Every turn asks for the same harmless read-only tool call, never finishing.
    script = [{"calls": [{"name": "list_dir", "args": {"path": "."}}]} for _ in range(5)]
    llm = fake_llm_factory(script)
    agent = make_agent(llm, fake_ui, max_turns=5)
    result = agent.run("loop forever")
    assert result == "(stopped after 5 turns without finishing)"
    assert len(llm.calls) == 5


def test_loop_detection_message_injected_after_3_identical_calls(project_dir, fake_llm_factory, fake_ui):
    same_call = {"calls": [{"name": "list_dir", "args": {"path": "."}}]}
    llm = fake_llm_factory([same_call, same_call, same_call, {"text": "giving up"}])
    agent = make_agent(llm, fake_ui, max_turns=10)
    result = agent.run("keep listing")
    assert result == "giving up"

    # The message should have been appended somewhere in history, right after the 3rd identical call.
    found = any(
        p.text and "identical tool call 3 times" in p.text
        for content in agent.history for p in (content.parts or [])
    )
    assert found


def test_usage_accumulates_across_turns(project_dir, fake_llm_factory, fake_ui):
    from forge.llm import Usage
    (project_dir / "a.txt").write_text("hi\n", encoding="utf-8")
    llm = fake_llm_factory([
        {"calls": [{"name": "read_file", "args": {"path": "a.txt"}}], "usage": Usage(input_tokens=100, output_tokens=10)},
        {"text": "done", "usage": Usage(input_tokens=50, output_tokens=5)},
    ])
    agent = make_agent(llm, fake_ui)
    agent.run("go")
    assert agent.usage.input_tokens == 150
    assert agent.usage.output_tokens == 15
    assert agent.last_prompt_tokens == 50   # last turn's input tokens
    assert agent.tool_calls_made == 1


# ---------------------------------------------------------------------------
# KeyboardInterrupt / _repair_history
# ---------------------------------------------------------------------------
def boom_tool():
    def boom():
        raise KeyboardInterrupt()
    return Tool(name="boom", description="raises KeyboardInterrupt", parameters={"type": "object", "properties": {}},
                run=boom)


def test_repair_history_leaves_no_dangling_function_calls(fake_llm_factory, fake_ui):
    llm = fake_llm_factory([{"calls": [{"name": "boom", "args": {}, "id": "call_1"}]}])
    agent = make_agent(llm, fake_ui, tools=[boom_tool()])
    result = agent.run("do the dangerous thing")
    assert result == "(interrupted)"

    last = agent.history[-1]
    assert last.role == "user"
    calls_before = [p.function_call for p in agent.history[-2].parts if p.function_call]
    responses_after = {p.function_response.id for p in last.parts if p.function_response}
    assert {c.id for c in calls_before} == responses_after
    fr = last.parts[0].function_response
    assert fr.response == {"error": "Cancelled by user."}


def test_repair_history_keeps_real_result_of_a_tool_that_already_ran(project_dir, fake_llm_factory, fake_ui):
    """Ctrl+C during the 2nd call of a turn: the 1st call (a write) really ran, so the repaired
    history must report its REAL result; only the unfinished call is 'Cancelled by user.'.
    (Previously every call in the turn was marked cancelled, so history disagreed with reality.)"""
    llm = fake_llm_factory([{"calls": [
        {"name": "write_file", "args": {"path": "written.txt", "content": "real content"}, "id": "call_write"},
        {"name": "boom", "args": {}, "id": "call_boom"},
    ]}])
    agent = make_agent(llm, fake_ui, tools=[boom_tool()] + ALL_TOOLS)
    agent.run("write then blow up")

    # The write really happened...
    assert (project_dir / "written.txt").read_text(encoding="utf-8") == "real content"

    # ...and the repaired history says so; only the interrupted call is marked cancelled.
    last = agent.history[-1]
    responses = {p.function_response.id: p.function_response.response for p in last.parts if p.function_response}
    assert "output" in responses["call_write"]
    assert "Cancelled" not in responses["call_write"]["output"]
    assert responses["call_boom"] == {"error": "Cancelled by user."}


def test_no_repair_needed_when_history_does_not_end_on_a_model_turn(fake_llm_factory, fake_ui):
    # _repair_history should be a no-op if there's nothing dangling (e.g. empty history).
    llm = fake_llm_factory([])
    agent = make_agent(llm, fake_ui)
    agent._repair_history()   # should not raise
    assert agent.history == []
