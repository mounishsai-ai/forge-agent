"""Shared fixtures for the offline Forge test suite.

Nothing in here (or anywhere in tests/) ever calls the real Gemini API. FakeLLM below
implements the same interface as forge.llm.GeminiLLM.generate(history, tools, system) ->
forge.llm.LLMResponse, driven by a scripted list of turns, and builds real
google.genai.types.Content objects so agent history stays valid across a whole run.
"""
import os
import sys

import pytest
from google.genai import types

from forge.llm import LLMResponse, ToolCall, Usage
from forge.tools import base as tools_base
from forge.tools import todo as todo_module
from forge.ui import QuietUI


# ---------------------------------------------------------------------------
# Isolation: shared module-level state must be reset between tests.
# ---------------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _reset_shared_state():
    """files_read and todo.current are module-level globals imported by name into several
    tool modules, so we clear them in place rather than rebinding (rebinding would leave
    the tool modules holding a reference to the old, stale object)."""
    tools_base.files_read.clear()
    todo_module.current.clear()
    yield
    tools_base.files_read.clear()
    todo_module.current.clear()


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    """A throwaway directory to run filesystem-touching tests in, as the tool's cwd."""
    monkeypatch.chdir(tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# FakeLLM: a scripted stand-in for GeminiLLM, real Content objects, no network.
# ---------------------------------------------------------------------------
class FakeLLM:
    """Drive the agent loop with pre-scripted model turns.

    Each item in `script` is a dict:
      {"text": "final answer"}                                  -> plain text turn, no tools
      {"calls": [{"name": "...", "args": {...}, "id": "..."}]}   -> one or more tool calls
      {"text": "...", "calls": [...]}                            -> both in the same turn
    An optional "usage" key (a forge.llm.Usage) overrides the default per-turn usage.
    """

    def __init__(self, script, model="fake-model"):
        self.script = list(script)
        self.model = model
        self.last_model_used = model
        self.calls = []   # every generate() invocation recorded: {"history", "tools", "system"}

    def generate(self, history, tools, system) -> LLMResponse:
        self.calls.append({"history": list(history), "tools": tools, "system": system})
        if not self.script:
            raise AssertionError("FakeLLM script exhausted: the agent asked for another turn "
                                  "than were scripted.")
        item = self.script.pop(0)
        text = item.get("text", "")
        raw_calls = item.get("calls", [])
        usage = item.get("usage") or Usage(input_tokens=10, output_tokens=5)

        parts = []
        if text:
            parts.append(types.Part(text=text))
        tool_calls = []
        for i, c in enumerate(raw_calls):
            cid = c.get("id") or f"call_{i}"
            parts.append(types.Part(function_call=types.FunctionCall(
                id=cid, name=c["name"], args=c.get("args", {}))))
            tool_calls.append(ToolCall(id=cid, name=c["name"], args=c.get("args", {})))
        if not parts:
            parts = [types.Part(text="")]

        content = types.Content(role="model", parts=parts)
        return LLMResponse(content=content, text=text, tool_calls=tool_calls, usage=usage)


@pytest.fixture
def fake_llm_factory():
    """Returns a constructor so each test can build its own scripted FakeLLM."""
    return FakeLLM


# ---------------------------------------------------------------------------
# FakeUI: records what the agent shows/asks, without touching a real terminal.
# ---------------------------------------------------------------------------
class FakeUI(QuietUI):
    def __init__(self, answers=None):
        super().__init__(verbose=False)
        self.answers = list(answers or [])
        self.asked = []
        self.infos = []
        self.errors = []
        self.assistant_texts = []

    def ask_permission(self, name, args):
        self.asked.append((name, args))
        return self.answers.pop(0) if self.answers else "n"

    def assistant_text(self, text):
        self.assistant_texts.append(text)

    def info(self, msg):
        self.infos.append(msg)

    def error(self, msg):
        self.errors.append(msg)


@pytest.fixture
def fake_ui():
    return FakeUI()


@pytest.fixture
def fake_ui_factory():
    """Returns the FakeUI class so a test can build several instances with different scripted answers."""
    return FakeUI


# ---------------------------------------------------------------------------
# Misc helpers
# ---------------------------------------------------------------------------
def py_exit_command(code: int) -> str:
    """A short cross-platform shell command that exits with a given code, for run_shell tests."""
    exe = sys.executable
    if os.name == "nt":
        return f'& "{exe}" -c "import sys; sys.exit({code})"'
    return f'"{exe}" -c "import sys; sys.exit({code})"'


def py_sleep_command(seconds: float) -> str:
    exe = sys.executable
    if os.name == "nt":
        return f'& "{exe}" -c "import time; time.sleep({seconds})"'
    return f'"{exe}" -c "import time; time.sleep({seconds})"'


@pytest.fixture
def exit_command():
    return py_exit_command


@pytest.fixture
def sleep_command():
    return py_sleep_command
