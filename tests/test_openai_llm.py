"""OpenAI-compatible provider, tested against a fake Chat Completions server on localhost (no network)."""
import json
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest
from google.genai import types

from forge.agent import Agent
from forge.openai_llm import OpenAICompatLLM, to_openai_messages
from forge.permissions import Permissions
from forge.tools import ALL_TOOLS
from forge.ui import QuietUI


class FakeOpenAI:
    """Serves scripted replies in order and records every request body it receives."""

    def __init__(self, replies):
        self.replies, self.requests = list(replies), []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                fake.requests.append(body)
                status, payload = fake.replies.pop(0)
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *a):
                pass

        self.server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}/v1"


def reply(content=None, tool_calls=None, prompt=10, completion=5):
    msg = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return 200, {"choices": [{"index": 0, "message": msg, "finish_reason": "stop"}],
                 "usage": {"prompt_tokens": prompt, "completion_tokens": completion}}


def call(cid, name, args):
    return {"id": cid, "type": "function", "function": {"name": name, "arguments": json.dumps(args)}}


@pytest.fixture
def server():
    servers = []
    yield lambda replies: servers.append(FakeOpenAI(replies)) or servers[-1]
    for s in servers:
        s.server.shutdown()


def test_agent_loop_runs_a_tool_through_openai_provider(server, project_dir):
    (project_dir / "notes.txt").write_text("the answer is 42\n")
    fake = server([reply(tool_calls=[call("call_1", "read_file", {"path": "notes.txt"})]),
                   reply(content="It says 42.")])
    llm = OpenAICompatLLM(model="qwen-test", base_url=fake.base_url, api_key="k")
    agent = Agent(llm, QuietUI(), Permissions("auto"), "You are a test.", tools=ALL_TOOLS)

    assert agent.run("What is in notes.txt?") == "It says 42."
    second = fake.requests[1]["messages"]
    assert second[0] == {"role": "system", "content": "You are a test."}
    assistant = next(m for m in second if m["role"] == "assistant")
    assert assistant["tool_calls"][0]["id"] == "call_1"
    tool_msg = next(m for m in second if m["role"] == "tool")
    assert tool_msg["tool_call_id"] == "call_1" and "the answer is 42" in tool_msg["content"]
    assert agent.usage.input_tokens == 20 and agent.usage.output_tokens == 10
    assert {t["function"]["name"] for t in fake.requests[0]["tools"]} >= {"read_file", "run_shell"}


def test_retries_a_503_then_succeeds(server, monkeypatch):
    monkeypatch.setattr("forge.openai_llm.time.sleep", lambda s: None)
    fake = server([(503, {"error": "busy"}), reply(content="ok")])
    llm = OpenAICompatLLM(model="m", base_url=fake.base_url)
    assert llm.generate([types.Content(role="user", parts=[types.Part(text="hi")])], [], "").text == "ok"
    assert len(fake.requests) == 2


def test_400_is_not_retried(server, monkeypatch):
    monkeypatch.setattr("forge.openai_llm.time.sleep", lambda s: None)
    fake = server([(400, {"error": "bad"})])
    llm = OpenAICompatLLM(model="m", base_url=fake.base_url)
    with pytest.raises(RuntimeError, match="HTTP 400"):
        llm.generate([types.Content(role="user", parts=[types.Part(text="hi")])], [], "")


def test_broken_json_arguments_do_not_crash(server):
    bad = {"id": "c1", "type": "function", "function": {"name": "read_file", "arguments": "{not json"}}
    fake = server([reply(tool_calls=[bad])])
    resp = OpenAICompatLLM(model="m", base_url=fake.base_url).generate(
        [types.Content(role="user", parts=[types.Part(text="hi")])], [], "")
    assert resp.tool_calls[0].args == {"_raw_arguments": "{not json"}


def test_gemini_history_without_ids_gets_matching_ids():
    history = [
        types.Content(role="user", parts=[types.Part(text="go")]),
        types.Content(role="model", parts=[types.Part(text="thinking", thought=True),
                                           types.Part(function_call=types.FunctionCall(name="grep", args={"pattern": "x"}))]),
        types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            name="grep", response={"output": "no matches"}))]),
    ]
    msgs = to_openai_messages(history, "")
    assert msgs[1]["content"] is None   # the Gemini thought is dropped, not shown as text
    assert msgs[1]["tool_calls"][0]["id"] == msgs[2]["tool_call_id"] == "call_grep"
    assert msgs[2]["content"] == "no matches"


def test_cli_headless_with_openai_provider(server, project_dir):
    fake = server([reply(content="hello from qwen", prompt=7, completion=3)])
    out = subprocess.run([sys.executable, "-m", "forge", "-p", "hi", "--json", "--provider", "openai",
                          "--base-url", fake.base_url, "--model", "qwen/qwen3-coder"],
                         capture_output=True, text=True, timeout=60, cwd=project_dir)
    data = json.loads(out.stdout.strip().splitlines()[-1])
    assert data["result"] == "hello from qwen" and data["input_tokens"] == 7
