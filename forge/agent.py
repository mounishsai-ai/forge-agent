"""The agent loop: the core of the harness.

    user message
        -> model  --(wants tools?)--no--> final answer, stop
                        |yes
                        v
           check permission -> run tool -> append result
                        |
                        +-----> back to model (repeat, max N turns)

The model never touches the machine. It only *asks* for tool calls; this file decides
whether to run them, runs them, and feeds the results back as the next message.
"""
import json
import time

from google.genai import types

from forge import config, context
from forge.llm import GeminiLLM, ToolCall, Usage
from forge.permissions import Permissions
from forge.tools import ALL_TOOLS, Tool, ToolError


class Agent:
    def __init__(self, llm: GeminiLLM, ui, permissions: Permissions, system_prompt: str,
                 tools: list[Tool] = ALL_TOOLS, max_turns: int = config.MAX_TURNS, hooks=None):
        self.llm = llm
        self.ui = ui
        self.permissions = permissions
        self.system_prompt = system_prompt
        self.tools = {t.name: t for t in tools}
        self.max_turns = max_turns
        self.hooks = hooks
        self.history: list[types.Content] = []   # the whole conversation, in the model's own format
        self.usage = Usage()                     # running token totals (for /cost)
        self.last_prompt_tokens = 0              # size of the most recent request = current context size
        self.tool_calls_made = 0

    def run(self, user_text: str) -> str:
        """Handle one user message end-to-end. Returns the model's final text."""
        self.history.append(types.Content(role="user", parts=[types.Part(text=user_text)]))
        recent_calls: list[str] = []

        try:
            for _ in range(self.max_turns):
                context.maybe_compact(self)   # shrink history first if it's getting too big
                with self.ui.thinking():
                    resp = self.llm.generate(self.history, list(self.tools.values()), self.system_prompt)
                self.history.append(resp.content)   # keep the raw message (incl. thought signatures)
                self.usage.add(resp.usage)
                self.last_prompt_tokens = resp.usage.input_tokens

                if resp.text:
                    self.ui.assistant_text(resp.text)
                if not resp.tool_calls:
                    return resp.text          # no tools requested = the model is done

                results = []
                for call in resp.tool_calls:
                    output, ok = self._execute(call)
                    results.append(types.Part(function_response=types.FunctionResponse(
                        id=call.id, name=call.name, response={"output" if ok else "error": output})))
                    recent_calls.append(call.name + json.dumps(call.args, sort_keys=True))

                # Loop detection: the same exact call 3 times in a row usually means the model is stuck.
                if len(recent_calls) >= 3 and len(set(recent_calls[-3:])) == 1:
                    results.append(types.Part(text="[harness] You have made the identical tool call 3 times. "
                                                   "Stop and try a different approach."))
                self.history.append(types.Content(role="user", parts=results))

            return f"(stopped after {self.max_turns} turns without finishing)"
        except KeyboardInterrupt:
            self._repair_history()
            self.ui.error("Interrupted.")
            return "(interrupted)"

    def _execute(self, call: ToolCall) -> tuple[str, bool]:
        """Run one tool call safely. Never raises: every failure becomes text the model can read."""
        self.ui.tool_call(call.name, call.args)
        tool = self.tools.get(call.name)
        if tool is None:
            return self._done(call, f"Unknown tool '{call.name}'. Available: {', '.join(self.tools)}", False)

        allowed, reason = self.permissions.check(tool, call.args, self.ui)
        if not allowed:
            return self._done(call, reason, False)

        if self.hooks:
            veto = self.hooks.pre_tool(call.name, call.args)
            if veto:
                return self._done(call, f"Blocked by pre_tool hook: {veto}", False)

        self.tool_calls_made += 1
        start = time.time()
        try:
            output, ok = tool.run(**call.args), True
        except ToolError as e:
            output, ok = str(e), False
        except TypeError as e:           # model sent wrong/missing arguments
            output, ok = f"Bad arguments for {call.name}: {e}", False
        except Exception as e:           # a bug in the tool itself; don't crash the agent
            output, ok = f"{type(e).__name__}: {e}", False

        if self.hooks:
            self.hooks.post_tool(call.name, call.args, output, ok, time.time() - start)
        return self._done(call, output, ok)

    def _done(self, call: ToolCall, output: str, ok: bool) -> tuple[str, bool]:
        self.ui.tool_result(call.name, output, ok)
        return output, ok

    def _repair_history(self) -> None:
        """After Ctrl+C mid-turn, the last model message may have tool calls with no results.
        The API rejects that, so add a 'cancelled' result for each dangling call."""
        last = self.history[-1] if self.history else None
        if last and last.role == "model":
            calls = [p.function_call for p in last.parts or [] if p.function_call]
            if calls:
                self.history.append(types.Content(role="user", parts=[
                    types.Part(function_response=types.FunctionResponse(
                        id=c.id, name=c.name, response={"error": "Cancelled by user."})) for c in calls]))
