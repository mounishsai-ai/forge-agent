"""Regression tests for bugs found in the code review (one test per fix)."""
import io
import json
import os
import sys
import threading
import time

import pytest
from google.genai import types

from forge import config, context, session, skills
from forge.hooks import Hooks
from forge.llm import Usage
from forge.mcp_client import MCPServer
from forge.tools import glob as glob_tool
from forge.tools import grep as grep_tool
from forge.tools import list_dir as list_dir_tool
from forge.tools import read_file as read_file_tool
from forge.tools import run_shell


def py_command(code_str: str) -> str:
    return f'"{sys.executable}" -c "{code_str}"'


# --- run_shell --------------------------------------------------------------------------------
def test_run_shell_timeout_kills_grandchild_instead_of_hanging(project_dir, sleep_command):
    # On Windows the sleeping python is a child of powershell; subprocess.run only killed
    # powershell and then waited ~30s for python to release the output pipe.
    start = time.time()
    out = run_shell.run_shell(sleep_command(30), timeout=1)
    assert "timed out after 1s" in out
    assert time.time() - start < 15


@pytest.mark.skipif(os.name != "nt", reason="PowerShell code-page issue is Windows-only")
def test_run_shell_powershell_output_is_utf8(project_dir):
    out = run_shell.run_shell("Write-Output 'héllo'")
    assert "héllo" in out
    assert "[exit code 0]" in out


# --- hooks ------------------------------------------------------------------------------------
def test_hook_with_non_utf8_output_does_not_crash():
    # Byte 0x81 is undecodable in cp1252 and in UTF-8: the old locale decode raised.
    hooks = Hooks({"pre_tool": [{"match": "run_shell", "command": py_command(
        "import sys; sys.stdout.buffer.write(bytes([0x81])); sys.exit(1)")}]})
    veto = hooks.pre_tool("run_shell", {"command": "x"})
    assert veto is not None


def test_broken_pre_hook_fails_closed():
    assert "broken" in Hooks({"pre_tool": [{"match": "(", "command": "echo"}]}).pre_tool("x", {})
    assert "broken" in Hooks({"pre_tool": [{"command": "echo"}]}).pre_tool("x", {})


def test_broken_post_hook_is_ignored():
    hooks = Hooks({"post_tool": [{"match": "["}, {"command": "echo"}]})
    hooks.post_tool("x", {}, "out", True, 0.1)   # must not raise
    assert len(hooks.log) == 1


# --- context (compaction) -----------------------------------------------------------------------
class CompactAgent:
    def __init__(self, llm, ui, history):
        self.llm, self.ui, self.history = llm, ui, history
        self.system_prompt = "sys"
        self.usage = Usage()
        self.last_prompt_tokens = 0


def user(text):
    return types.Content(role="user", parts=[types.Part(text=text)])


def model(text):
    return types.Content(role="model", parts=[types.Part(text=text)])


def test_compact_answers_dangling_function_call(fake_llm_factory, fake_ui):
    llm = fake_llm_factory([{"text": "summary"}])
    call = types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
        id="c1", name="read_file", args={"path": "a"}))])
    agent = CompactAgent(llm, fake_ui, [user("hi"), call])
    context.compact(agent)
    sent_last = llm.calls[0]["history"][-1]
    assert sent_last.role == "user"
    assert sent_last.parts[0].function_response.id == "c1"
    assert sent_last.parts[-1].text == context.SUMMARY_PROMPT


def test_compact_merges_prompt_into_trailing_user_message(fake_llm_factory, fake_ui):
    llm = fake_llm_factory([{"text": "summary"}])
    agent = CompactAgent(llm, fake_ui, [user("a"), model("b"), user("c")])
    context.compact(agent)
    sent = llm.calls[0]["history"]
    assert len(sent) == 3 and [p.text for p in sent[-1].parts] == ["c", context.SUMMARY_PROMPT]
    assert len(agent.history) == 2   # /compact itself keeps the 2-message shape


@pytest.mark.parametrize("empty", ["", "(empty response: SAFETY)"])
def test_compact_keeps_history_when_summary_is_empty(fake_llm_factory, fake_ui, empty):
    llm = fake_llm_factory([{"text": empty}])
    history = [user("a"), model("b"), user("c")]
    agent = CompactAgent(llm, fake_ui, list(history))
    result = context.compact(agent)
    assert "failed" in result
    assert agent.history == history


def test_maybe_compact_keeps_pending_user_request(monkeypatch, fake_llm_factory, fake_ui):
    monkeypatch.setattr(config, "COMPACT_AT_TOKENS", 10)
    agent = CompactAgent(fake_llm_factory([{"text": "summary"}]), fake_ui,
                         [user("a"), model("b"), user("do the thing")])
    agent.last_prompt_tokens = 100
    context.maybe_compact(agent)
    assert agent.history[-1].role == "user"
    assert agent.history[-1].parts[0].text == "do the thing"


def test_maybe_compact_after_tool_results_ends_with_continue(monkeypatch, fake_llm_factory, fake_ui):
    monkeypatch.setattr(config, "COMPACT_AT_TOKENS", 10)
    call = types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
        id="c1", name="read_file", args={}))])
    result = types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
        id="c1", name="read_file", response={"output": "x"}))])
    agent = CompactAgent(fake_llm_factory([{"text": "summary"}]), fake_ui, [user("a"), call, result])
    agent.last_prompt_tokens = 100
    context.maybe_compact(agent)
    last = agent.history[-1]
    assert last.role == "user" and last.parts[0].function_response is None
    assert "Continue" in last.parts[0].text


# --- mcp_client -------------------------------------------------------------------------------
class ClosedStdinProc:
    def __init__(self, stdout_lines):
        self.stdout = io.BytesIO(b"".join(json.dumps(m).encode() + b"\n" for m in stdout_lines))
        self.stdin = io.BytesIO()
        self.stdin.close()   # writes raise ValueError -> _send raises MCPError

    def poll(self):
        return None


def test_mcp_reader_survives_ping_after_stdin_closed_and_wakes_waiters():
    server = MCPServer("fake", "fake")
    server.proc = ClosedStdinProc([
        {"jsonrpc": "2.0", "id": 99, "method": "ping"},     # reply fails: stdin closed
        {"jsonrpc": "2.0", "id": [1], "result": {}},        # unhashable id
    ])
    waiter = {"event": threading.Event(), "msg": None}
    server._pending[1] = waiter
    server._read_stdout()   # used to raise MCPError / TypeError and never set _dead
    assert server._dead
    assert waiter["event"].is_set() and waiter["msg"] is None


# --- subagent ---------------------------------------------------------------------------------
class Parent:
    def __init__(self, prompt):
        self.llm = object()
        self.system_prompt = prompt
        self.usage = Usage()
        self.tool_calls_made = 0


def _fake_agent_class(behaviour, seen):
    class FakeChild:
        def __init__(self, **kw):
            seen.update(kw)
            self.usage = Usage(input_tokens=7, output_tokens=3)
            self.tool_calls_made = 2

        def run(self, description):
            return behaviour()
    return FakeChild


def test_subagent_prompt_without_blank_line_and_usage_on_crash(monkeypatch):
    import forge.agent
    from forge.subagent import SUBAGENT_PROMPT, make_task_tool

    def boom():
        raise RuntimeError("api down")
    seen = {}
    monkeypatch.setattr(forge.agent, "Agent", _fake_agent_class(boom, seen))
    parent = Parent("sys")                       # no "\n\n": used to raise IndexError
    with pytest.raises(RuntimeError):
        make_task_tool(parent).run(description="look")
    assert seen["system_prompt"] == SUBAGENT_PROMPT
    assert parent.usage.input_tokens == 7 and parent.tool_calls_made == 2


def test_subagent_interrupt_propagates_to_parent(monkeypatch):
    import forge.agent
    from forge.subagent import make_task_tool
    monkeypatch.setattr(forge.agent, "Agent", _fake_agent_class(lambda: "(interrupted)", {}))
    with pytest.raises(KeyboardInterrupt):
        make_task_tool(Parent("a\n\nb")).run(description="look")


# --- tools ------------------------------------------------------------------------------------
def test_grep_survives_relpath_value_error(project_dir, monkeypatch):
    (project_dir / "a.txt").write_text("needle\n", encoding="utf-8")

    def cross_drive(*a, **k):
        raise ValueError("path is on mount 'D:', start on mount 'C:'")
    monkeypatch.setattr(os.path, "relpath", cross_drive)
    assert "needle" in grep_tool.grep("needle")


def test_glob_survives_getmtime_error(project_dir, monkeypatch):
    (project_dir / "a.py").write_text("", encoding="utf-8")

    def gone(path):
        raise FileNotFoundError(path)
    monkeypatch.setattr(os.path, "getmtime", gone)
    assert "a.py" in glob_tool.glob("*.py")


def test_list_dir_survives_getsize_error(project_dir, monkeypatch):
    (project_dir / "a.txt").write_text("x", encoding="utf-8")

    def gone(path):
        raise FileNotFoundError(path)
    monkeypatch.setattr(os.path, "getsize", gone)
    assert "a.txt" in list_dir_tool.list_dir(".")


def test_read_file_accepts_float_offset_and_limit(project_dir):
    (project_dir / "a.txt").write_text("1\n2\n3\n", encoding="utf-8")
    out = read_file_tool.read_file("a.txt", offset=2.0, limit=1.0)
    assert "2" in out and "3\n" not in out.split("[")[0]


# --- session ----------------------------------------------------------------------------------
class SessionAgent:
    def __init__(self, text):
        self.llm = type("L", (), {"model": "m"})()
        self.history = [user(text)]


def test_session_save_is_atomic(project_dir, monkeypatch):
    session.save("s1", SessionAgent("old"))

    def crash(data, f):
        f.write("{")
        raise KeyboardInterrupt
    with monkeypatch.context() as m, pytest.raises(KeyboardInterrupt):
        m.setattr(session.json, "dump", crash)
        session.save("s1", SessionAgent("new"))
    _, history = session.load("s1")
    assert history[0].parts[0].text == "old"
    assert session.list_sessions() == ["s1"]


# --- skills -----------------------------------------------------------------------------------
def test_unclosed_frontmatter_is_not_swallowed():
    meta, body = skills._parse_frontmatter("---\nname: x\nthe real body")
    assert meta == {}
    assert "the real body" in body
