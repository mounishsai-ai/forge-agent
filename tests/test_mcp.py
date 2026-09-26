"""Offline tests for forge/mcp_client.py, using the stdlib MCP server in tests/fixtures/."""
import json
import os
import sys

import pytest

from forge import mcp_client
from forge.agent import Agent
from forge.permissions import Permissions
from forge.tools import ALL_TOOLS, ToolError, add_tools

FIXTURE = os.path.join(os.path.dirname(__file__), "fixtures", "echo_mcp_server.py")
ECHO_CFG = {"echo": {"command": sys.executable, "args": [FIXTURE]}}


@pytest.fixture(autouse=True)
def _cleanup_servers():
    """Every test starts with no servers and kills whatever it started."""
    mcp_client.shutdown_all()
    mcp_client.active_servers.clear()
    yield
    mcp_client.shutdown_all()
    mcp_client.active_servers.clear()


@pytest.fixture
def echo_server():
    servers = mcp_client.start_servers(ECHO_CFG, timeout=20)
    assert len(servers) == 1
    return servers[0]


def tools_by_name(server):
    return {t.name: t for t in mcp_client.make_tools(server)}


# --- handshake + tool discovery ------------------------------------------------------------
def test_handshake_and_tools_list(echo_server):
    assert echo_server.server_info["name"] == "echo-mcp-server"
    assert echo_server.protocol_version == mcp_client.PROTOCOL_VERSION
    assert [t["name"] for t in echo_server.tools] == ["echo", "add"]
    assert "echo-mcp-server starting" in echo_server.stderr_tail   # stderr was captured


def test_tools_are_wrapped_as_forge_tools(echo_server):
    tools = tools_by_name(echo_server)
    assert set(tools) == {"mcp__echo__echo", "mcp__echo__add"}
    add = tools["mcp__echo__add"]
    assert add.needs_permission is True
    assert add.parameters["properties"]["a"] == {"type": "number"}
    assert "$schema" not in tools["mcp__echo__echo"].parameters   # sanitized
    assert add.declaration().name == "mcp__echo__add"             # valid Gemini declaration


# --- tools/call ------------------------------------------------------------------------------
def test_call_add_and_echo(echo_server):
    tools = tools_by_name(echo_server)
    assert tools["mcp__echo__add"].run(a=2.0, b=40.0) == "42"
    assert tools["mcp__echo__echo"].run(text="hello\nworld") == "hello\nworld"   # newline survives framing


def test_is_error_result_raises_tool_error(echo_server):
    with pytest.raises(ToolError, match="add needs two numbers"):
        tools_by_name(echo_server)["mcp__echo__add"].run(a="x", b=1)


def test_jsonrpc_error_becomes_tool_error(echo_server):
    with pytest.raises(ToolError, match="Unknown tool"):
        echo_server.call_tool("nope", {})


def test_many_sequential_calls_match_ids(echo_server):
    add = tools_by_name(echo_server)["mcp__echo__add"]
    assert [add.run(a=i, b=1) for i in range(20)] == [str(i + 1) for i in range(20)]



def test_concurrent_calls_on_one_server(echo_server):
    """Parallel tool calls (e.g. from threads) must each get their own answer, matched by id."""
    import threading
    add = tools_by_name(echo_server)["mcp__echo__add"]
    results = {}
    threads = [threading.Thread(target=lambda i=i: results.__setitem__(i, add.run(a=i, b=1000)))
               for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    assert results == {i: str(i + 1000) for i in range(10)}

# --- failure handling ------------------------------------------------------------------------
def test_missing_command_warns_and_continues(capsys):
    cfg = {"broken": {"command": "definitely-not-a-real-command-xyz"}, **ECHO_CFG}
    servers = mcp_client.start_servers(cfg, timeout=20)
    assert [s.name for s in servers] == ["echo"]            # the good one still started
    assert "broken" in capsys.readouterr().err               # warning went to stderr, not stdout
    assert "broken: FAILED" in mcp_client.status()


def test_server_that_exits_immediately():
    cfg = {"dies": {"command": sys.executable, "args": ["-c", "import sys; print('boom', file=sys.stderr)"]}}
    assert mcp_client.start_servers(cfg, timeout=10) == []
    err = mcp_client.active_servers[0].error
    assert "boom" in err or "not running" in err or "exited" in err


def test_request_timeout():
    # A "server" that reads stdin forever and never answers.
    silent = {"silent": {"command": sys.executable, "args": ["-c", "import sys\nfor _ in sys.stdin: pass"]}}
    assert mcp_client.start_servers(silent, timeout=1) == []
    assert "timed out" in mcp_client.active_servers[0].error


def test_non_stdio_server_is_skipped(capsys):
    assert mcp_client.start_servers({"web": {"type": "http", "url": "https://x"}}) == []
    assert "only stdio" in capsys.readouterr().err


def test_close_stops_process(echo_server):
    echo_server.close()
    assert echo_server.proc.poll() is not None
    with pytest.raises(ToolError, match="not running"):
        echo_server.call_tool("echo", {"text": "x"})


# --- config + helpers ------------------------------------------------------------------------
def test_load_config_project_overrides_user(tmp_path):
    user, proj = tmp_path / "user.json", tmp_path / "proj.json"
    user.write_text(json.dumps({"mcpServers": {"a": {"command": "u"}, "b": {"command": "u"}}}))
    proj.write_text(json.dumps({"mcpServers": {"b": {"command": "p"}}}))
    cfg = mcp_client.load_config([str(user), str(proj), str(tmp_path / "missing.json")])
    assert cfg == {"a": {"command": "u"}, "b": {"command": "p"}}


def test_load_config_bad_json_is_ignored(tmp_path, capsys):
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert mcp_client.load_config([str(bad)]) == {}
    assert "ignoring" in capsys.readouterr().err


def test_tool_name_is_gemini_safe():
    assert mcp_client.tool_name("my server", "do/thing") == "mcp__my_server__do_thing"
    assert len(mcp_client.tool_name("s", "x" * 100)) == 64


def test_sanitize_schema_defaults():
    assert mcp_client.sanitize_schema(None) == {"type": "object", "properties": {}}
    s = mcp_client.sanitize_schema({"$schema": "x", "type": "object",
                                    "properties": {"p": {"$comment": "c", "type": "string"}}})
    assert s == {"type": "object", "properties": {"p": {"type": "string"}}}


def test_content_to_text():
    result = {"content": [{"type": "text", "text": "a"}, {"type": "image", "mimeType": "image/png", "data": "..."},
                          {"type": "resource", "resource": {"uri": "f", "text": "b"}}]}
    assert mcp_client.content_to_text(result) == "a\n[image content, image/png omitted]\nb"
    assert mcp_client.content_to_text({"content": [], "structuredContent": {"x": 1}}) == '{"x": 1}'


# --- wiring into the agent -------------------------------------------------------------------
def make_agent(llm, ui, mode):
    return Agent(llm=llm, ui=ui, permissions=Permissions(mode), system_prompt="sys", tools=ALL_TOOLS, max_turns=5)


def test_add_tools_never_replaces_existing(fake_llm_factory, fake_ui, echo_server):
    agent = make_agent(fake_llm_factory([]), fake_ui, "auto")
    fake = mcp_client.make_tools(echo_server)[0]
    fake.name = "read_file"
    assert add_tools(agent, [fake]) == []
    assert agent.tools["read_file"] is not fake


def test_agent_calls_mcp_tool_end_to_end(fake_llm_factory, fake_ui):
    llm = fake_llm_factory([
        {"calls": [{"name": "mcp__echo__add", "args": {"a": 2, "b": 40}}]},
        {"text": "The answer is 42."},
    ])
    agent = make_agent(llm, fake_ui, "auto")
    added = mcp_client.attach(agent, ECHO_CFG)
    assert {t.name for t in added} == {"mcp__echo__echo", "mcp__echo__add"}
    assert "mcp__echo__add" in agent.tools
    assert agent.run("add 2 and 40") == "The answer is 42."
    # The tool result sent back to the model on turn 2:
    fr = llm.calls[1]["history"][-1].parts[0].function_response
    assert fr.name == "mcp__echo__add" and fr.response == {"output": "42"}


def test_mcp_tools_ask_permission_in_ask_mode(fake_llm_factory, fake_ui_factory):
    ui = fake_ui_factory(answers=["n"])
    llm = fake_llm_factory([
        {"calls": [{"name": "mcp__echo__echo", "args": {"text": "hi"}}]},
        {"text": "ok"},
    ])
    agent = make_agent(llm, ui, "ask")
    mcp_client.attach(agent, ECHO_CFG)
    agent.run("echo hi")
    assert ui.asked == [("mcp__echo__echo", {"text": "hi"})]
    assert "error" in llm.calls[1]["history"][-1].parts[0].function_response.response

