"""Offline tests for streaming (llm.generate_stream + agent/UI wiring) and parallel read-only tools.

No network: GeminiLLM is built without __init__ and given a fake client whose
generate_content_stream yields hand-made chunks shaped like the real API's (verified live:
text arrives in many small parts, the thought_signature rides on the first function_call
part, and a text-only answer ends with a text='' part carrying the signature).
"""
import threading
from contextlib import contextmanager

import pytest
from google.genai import errors, types

from forge.agent import Agent
from forge.llm import GeminiLLM, _merge_part
from forge.permissions import Permissions
from forge.tools.base import Tool

SIG = b"\x01\x02signature-bytes"


def make_llm(client):
    llm = object.__new__(GeminiLLM)
    llm.model = "model-a"
    llm.fallbacks = ["model-b"]
    llm.last_model_used = llm.model
    llm.broken_until = {}
    llm.client = client
    return llm


def chunk(*parts, finish=None, usage=None):
    cand = types.Candidate(content=types.Content(role="model", parts=list(parts)), finish_reason=finish)
    return types.GenerateContentResponse(candidates=[cand], usage_metadata=usage)


USAGE = types.GenerateContentResponseUsageMetadata(prompt_token_count=100, candidates_token_count=20)


class FakeStreamModels:
    """Each queue item is a list of chunks (or exceptions, raised when reached mid-stream)."""

    def __init__(self, queue):
        self.queue = list(queue)
        self.calls = []

    def generate_content_stream(self, model, contents, config):
        self.calls.append(model)
        items = self.queue.pop(0)

        def gen():   # lazy, like the real SDK: errors surface while iterating
            for item in items:
                if isinstance(item, BaseException):
                    raise item
                yield item
        return gen()


class FakeClient:
    def __init__(self, queue):
        self.models = FakeStreamModels(queue)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr("forge.llm.time.sleep", lambda *a, **k: None)


# ---------------------------------------------------------------------------
# generate_stream: assembly
# ---------------------------------------------------------------------------
def test_stream_text_is_emitted_live_and_merged():
    chunks = [chunk(types.Part(text="Hello")), chunk(types.Part(text=", world")),
              chunk(types.Part(text="", thought_signature=SIG), finish="STOP", usage=USAGE)]
    llm = make_llm(FakeClient([chunks]))
    seen = []
    resp = llm.generate_stream([], [], "sys", seen.append)
    assert seen == ["Hello", ", world"]
    assert resp.text == "Hello, world"
    parts = resp.content.parts
    assert parts[0].text == "Hello, world"                  # plain text chunks glued together
    assert parts[1].text == "" and parts[1].thought_signature == SIG   # signature part kept as-is
    assert resp.usage.input_tokens == 100 and resp.usage.output_tokens == 20


def test_stream_keeps_function_calls_and_signatures():
    fc1 = types.Part(function_call=types.FunctionCall(id="c1", name="read_file", args={"path": "a"}),
                     thought_signature=SIG)
    fc2 = types.Part(function_call=types.FunctionCall(id="c2", name="read_file", args={"path": "b"}))
    chunks = [chunk(types.Part(text="I will read")), chunk(types.Part(text=" both.")),
              chunk(fc1), chunk(fc2), chunk(types.Part(text=""), finish="STOP", usage=USAGE)]
    llm = make_llm(FakeClient([chunks]))
    resp = llm.generate_stream([], [], "sys", lambda t: None)
    parts = resp.content.parts
    assert len(parts) == 3                                  # trailing empty filler part dropped
    assert parts[0].text == "I will read both."
    assert parts[1].function_call.name == "read_file" and parts[1].thought_signature == SIG
    assert parts[2].function_call.id == "c2"
    assert [c.id for c in resp.tool_calls] == ["c1", "c2"]


def test_thought_text_not_emitted_nor_merged_with_answer():
    chunks = [chunk(types.Part(text="thinking...", thought=True)), chunk(types.Part(text="more", thought=True)),
              chunk(types.Part(text="Answer"), finish="STOP", usage=USAGE)]
    seen = []
    resp = make_llm(FakeClient([chunks])).generate_stream([], [], "sys", seen.append)
    assert seen == ["Answer"]
    assert resp.text == "Answer"
    assert resp.content.parts[0].thought and resp.content.parts[0].text == "thinking...more"
    assert resp.content.parts[1].text == "Answer"


def test_merge_part_never_merges_signed_text():
    parts = []
    _merge_part(parts, types.Part(text="a", thought_signature=SIG))
    _merge_part(parts, types.Part(text="b"))
    assert [p.text for p in parts] == ["a", "b"]


def test_empty_stream_gives_placeholder():
    resp = make_llm(FakeClient([[chunk(finish="MAX_TOKENS", usage=USAGE)]])).generate_stream([], [], "s", print)
    assert "empty response" in resp.text


# ---------------------------------------------------------------------------
# generate_stream: retry / fallback
# ---------------------------------------------------------------------------
def test_stream_retries_when_error_before_any_text():
    err = errors.ServerError(503, {"error": {"message": "overloaded"}})
    good = [chunk(types.Part(text="ok"), finish="STOP", usage=USAGE)]
    llm = make_llm(FakeClient([[err], good]))
    seen = []
    resp = llm.generate_stream([], [], "sys", seen.append)
    assert resp.text == "ok" and seen == ["ok"]             # no duplicate/partial text from the failed try
    assert llm.client.models.calls == ["model-a", "model-a"]


def test_stream_falls_back_on_504_before_text():
    err = errors.ServerError(504, {"error": {"message": "deadline"}})
    good = [chunk(types.Part(text="ok"), finish="STOP", usage=USAGE)]
    llm = make_llm(FakeClient([[err], good]))
    llm.generate_stream([], [], "sys", lambda t: None)
    assert llm.client.models.calls == ["model-a", "model-b"]
    assert llm.last_model_used == "model-b"


def test_stream_does_not_retry_after_text_was_shown():
    err = errors.ServerError(503, {"error": {"message": "overloaded"}})
    llm = make_llm(FakeClient([[chunk(types.Part(text="partial")), err]]))
    seen = []
    with pytest.raises(errors.ServerError):
        llm.generate_stream([], [], "sys", seen.append)
    assert seen == ["partial"]
    assert llm.client.models.calls == ["model-a"]


# ---------------------------------------------------------------------------
# Agent: streaming only when the UI supports it
# ---------------------------------------------------------------------------
class StreamUI:
    """Minimal streaming UI that records what the agent shows."""
    streams = True

    def __init__(self):
        self.live, self.printed, self.calls, self.results = [], [], [], []

    @contextmanager
    def stream(self):
        yield self.live.append

    @contextmanager
    def thinking(self):
        yield

    def assistant_text(self, text): self.printed.append(text)
    def tool_call(self, name, args): self.calls.append((name, args))
    def tool_result(self, name, output, ok): self.results.append((name, output))
    def ask_permission(self, name, args): return "y"
    def info(self, msg): pass
    def error(self, msg): pass


def test_agent_streams_and_does_not_print_twice():
    llm = make_llm(FakeClient([[chunk(types.Part(text="Hi "), usage=None),
                                chunk(types.Part(text="there"), finish="STOP", usage=USAGE)]]))
    ui = StreamUI()
    agent = Agent(llm=llm, ui=ui, permissions=Permissions("auto"), system_prompt="s", tools=[])
    assert agent.run("hello") == "Hi there"
    assert ui.live == ["Hi ", "there"]
    assert ui.printed == []                                 # already shown live


def test_agent_uses_plain_generate_with_quiet_ui(fake_llm_factory, fake_ui):
    # FakeLLM has no generate_stream and FakeUI (a QuietUI) has streams=False: plain generate().
    llm = fake_llm_factory([{"text": "done"}])
    agent = Agent(llm=llm, ui=fake_ui, permissions=Permissions("auto"), system_prompt="s", tools=[])
    assert agent.run("x") == "done"
    assert fake_ui.assistant_texts == ["done"]


# ---------------------------------------------------------------------------
# Parallel read-only tool calls
# ---------------------------------------------------------------------------
def barrier_tool(name, barrier, log):
    def run(tag: str) -> str:
        log.append(("start", tag))
        barrier.wait()          # only returns if BOTH tools are running at the same time
        return f"{name}:{tag}"
    return Tool(name=name, description=name, parameters={"type": "object", "properties": {}}, run=run)


def writer_tool(log):
    def run(tag: str) -> str:
        log.append(("write", tag))
        return f"wrote:{tag}"
    return Tool(name="writer", description="w", parameters={"type": "object", "properties": {}}, run=run,
                needs_permission=True)


def test_read_only_calls_run_concurrently_and_results_stay_ordered(fake_llm_factory, fake_ui_factory):
    barrier1, barrier2, log = threading.Barrier(2, timeout=5), threading.Barrier(2, timeout=5), []
    tools = [barrier_tool("r1", barrier1, log), barrier_tool("r2", barrier1, log),
             barrier_tool("r3", barrier2, log), barrier_tool("r4", barrier2, log), writer_tool(log)]
    llm = fake_llm_factory([
        {"calls": [{"name": "r1", "args": {"tag": "a"}, "id": "1"},
                   {"name": "r2", "args": {"tag": "b"}, "id": "2"},
                   {"name": "writer", "args": {"tag": "w"}, "id": "3"},
                   {"name": "r3", "args": {"tag": "c"}, "id": "4"},
                   {"name": "r4", "args": {"tag": "d"}, "id": "5"}]},
        {"text": "done"},
    ])
    ui = fake_ui_factory(answers=["y"])
    agent = Agent(llm=llm, ui=ui, permissions=Permissions("ask"), system_prompt="s", tools=tools)
    assert agent.run("go") == "done"

    responses = [(p.function_response.id, p.function_response.response) for p in agent.history[2].parts]
    assert responses == [("1", {"output": "r1:a"}), ("2", {"output": "r2:b"}), ("3", {"output": "wrote:w"}),
                         ("4", {"output": "r3:c"}), ("5", {"output": "r4:d"})]
    assert ui.asked == [("writer", {"tag": "w"})]           # exactly one prompt, for the write
    # The write happened after the first parallel pair and before the second.
    order = [e[1] for e in log]
    assert order.index("w") > max(order.index("a"), order.index("b"))
    assert order.index("w") < min(order.index("c"), order.index("d"))
    assert agent.tool_calls_made == 5


def test_parallel_ui_output_is_in_call_order(project_dir, fake_llm_factory):
    for n in "abc":
        (project_dir / f"{n}.txt").write_text(f"content {n}\n", encoding="utf-8")
    llm = fake_llm_factory([
        {"calls": [{"name": "read_file", "args": {"path": f"{n}.txt"}, "id": n} for n in "abc"]},
        {"text": "done"},
    ])
    ui = StreamUI()
    ui.streams = False
    from forge.tools import ALL_TOOLS
    agent = Agent(llm=llm, ui=ui, permissions=Permissions("auto"), system_prompt="s", tools=ALL_TOOLS)
    agent.run("read all")
    assert [a["path"] for _, a in ui.calls] == ["a.txt", "b.txt", "c.txt"]
    assert ["content " + n in out for (_, out), n in zip(ui.results, "abc")] == [True] * 3


def test_todo_and_unknown_tools_are_not_parallelized(fake_llm_factory, fake_ui):
    agent = Agent(llm=fake_llm_factory([]), ui=fake_ui, permissions=Permissions("auto"), system_prompt="s")
    from forge.llm import ToolCall
    assert not agent._parallel_ok(ToolCall(id=None, name="todo", args={}))
    assert not agent._parallel_ok(ToolCall(id=None, name="nope", args={}))
    assert not agent._parallel_ok(ToolCall(id=None, name="write_file", args={}))
    assert agent._parallel_ok(ToolCall(id=None, name="read_file", args={}))


def test_keyboard_interrupt_in_parallel_tool_repairs_history(fake_llm_factory, fake_ui):
    def boom():
        raise KeyboardInterrupt()
    tools = [Tool(name="ok", description="", parameters={}, run=lambda: "fine"),
             Tool(name="boom", description="", parameters={}, run=boom)]
    llm = fake_llm_factory([{"calls": [{"name": "ok", "args": {}, "id": "1"},
                                       {"name": "boom", "args": {}, "id": "2"}]}])
    agent = Agent(llm=llm, ui=fake_ui, permissions=Permissions("auto"), system_prompt="s", tools=tools)
    assert agent.run("go") == "(interrupted)"
    responses = {p.function_response.id: p.function_response.response for p in agent.history[-1].parts}
    assert responses == {"1": {"output": "fine"}, "2": {"error": "Cancelled by user."}}


def test_ctrl_c_while_waiting_keeps_results_finished_in_background(fake_llm_factory, fake_ui, monkeypatch):
    """Ctrl+C lands while the main thread waits on call 1; call 2 already finished in its
    thread -> its real result is kept, call 1 is reported as cancelled."""
    import forge.agent as agent_module
    release, fast_done = threading.Event(), threading.Event()

    def fast():
        fast_done.set()
        return "fast done"
    tools = [Tool(name="slow", description="", parameters={}, run=lambda: release.wait(5) and "slow done"),
             Tool(name="fast", description="", parameters={}, run=fast)]

    def interrupted_wait(future):   # simulates the user pressing Ctrl+C during the first wait
        assert fast_done.wait(5)
        import time
        time.sleep(0.5)             # fast()'s future is marked done just after fast() returns
        raise KeyboardInterrupt()
    monkeypatch.setattr(agent_module, "_wait", interrupted_wait)

    llm = fake_llm_factory([{"calls": [{"name": "slow", "args": {}, "id": "1"},
                                       {"name": "fast", "args": {}, "id": "2"}]}])
    agent = Agent(llm=llm, ui=fake_ui, permissions=Permissions("auto"), system_prompt="s", tools=tools)
    try:
        assert agent.run("go") == "(interrupted)"
    finally:
        release.set()
    responses = {p.function_response.id: p.function_response.response for p in agent.history[-1].parts}
    assert responses == {"1": {"error": "Cancelled by user."}, "2": {"output": "fast done"}}


def test_slow_parallel_tools_are_waited_for_and_ordered(fake_llm_factory, fake_ui):
    """Tools slower than _wait's 0.2s polling slice: exercises the timeout/retry path of _wait."""
    import time

    def slow(tag: str) -> str:
        time.sleep(0.5 if tag == "a" else 0.3)
        return "done " + tag
    tools = [Tool(name="slow", description="", parameters={}, run=slow)]
    llm = fake_llm_factory([{"calls": [{"name": "slow", "args": {"tag": t}, "id": t} for t in "ab"]},
                            {"text": "ok"}])
    agent = Agent(llm=llm, ui=fake_ui, permissions=Permissions("auto"), system_prompt="s", tools=tools)
    start = time.time()
    assert agent.run("go") == "ok"
    assert time.time() - start < 0.75                        # concurrent: ~0.5s, not 0.8s
    outputs = [p.function_response.response["output"] for p in agent.history[2].parts]
    assert outputs == ["done a", "done b"]
