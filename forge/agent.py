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
In the terminal the model's text is streamed live; several read-only tool calls in one
turn run in parallel threads (results still go back in the order the model asked).
"""
import json
import time
from concurrent.futures import Future, ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout   # = builtin TimeoutError only on 3.11+

from google.genai import types

from forge import config, context
from forge.llm import GeminiLLM, ToolCall, Usage
from forge.permissions import Permissions
from forge.tools import ALL_TOOLS, Tool, ToolError


def _response_part(call, output: str, ok: bool) -> types.Part:
    """Wrap one tool result in the format the model expects: a function_response part
    whose id/name match the function_call it answers."""
    return types.Part(function_response=types.FunctionResponse(
        id=call.id, name=call.name, response={"output" if ok else "error": output}))


def _wait(future: Future):
    """future.result(), but in short slices: on Windows a wait with no timeout can't be
    interrupted, so Ctrl+C would be ignored until the tool finished."""
    while True:
        try:
            return future.result(timeout=0.2)
        except FutureTimeout:
            continue


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
        self._finished: dict[int, tuple[str, bool]] = {}   # current turn: call index -> (output, ok)

    def run(self, user_text: str) -> str:
        """Handle one user message end-to-end. Returns the model's final text."""
        self.history.append(types.Content(role="user", parts=[types.Part(text=user_text)]))
        recent_calls: list[str] = []

        try:
            for _ in range(self.max_turns):
                context.maybe_compact(self)   # shrink history first if it's getting too big
                self._finished = {}           # this turn's completed tool results (for Ctrl+C repair)
                resp, shown_live = self._ask_model()
                self.history.append(resp.content)   # keep the raw message (incl. thought signatures)
                self.usage.add(resp.usage)
                self.last_prompt_tokens = resp.usage.input_tokens

                if resp.text and not shown_live:   # streamed text is already on screen; don't print twice
                    self.ui.assistant_text(resp.text)
                if not resp.tool_calls:
                    return resp.text          # no tools requested = the model is done

                results = []
                for call, (output, ok) in zip(resp.tool_calls, self._run_tool_calls(resp.tool_calls)):
                    results.append(_response_part(call, output, ok))
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
        except Exception:
            # e.g. the API failed after all retries. Leave the history valid (no unanswered
            # tool calls) so the user's NEXT message still works, then let the caller report it.
            self._repair_history()
            raise

    def _ask_model(self):
        """One model call. Returns (response, whether its text was already shown live).

        Interactive terminal (ConsoleUI.streams = True): stream, so text appears as it's written.
        Headless / evals / sub-agents / test fakes: plain generate() behind a spinner.
        """
        tools = list(self.tools.values())
        if getattr(self.ui, "streams", False) and hasattr(self.llm, "generate_stream"):
            shown: list[str] = []
            with self.ui.stream() as on_text:
                def show(chunk: str) -> None:
                    shown.append(chunk)
                    on_text(chunk)
                resp = self.llm.generate_stream(self.history, tools, self.system_prompt, show)
            return resp, bool(shown)   # False e.g. for an "(empty response)" placeholder: print it normally
        with self.ui.thinking():
            return self.llm.generate(self.history, tools, self.system_prompt), False

    # ---- running the tool calls of one model turn ------------------------------------------
    # Tools that must never run concurrently even though they don't ask permission:
    # `task` starts a whole sub-agent (slow, many API calls), `todo` rewrites one shared list.
    SEQUENTIAL_ONLY = {"task", "todo"}

    def _parallel_ok(self, call: ToolCall) -> bool:
        tool = self.tools.get(call.name)
        return tool is not None and not tool.needs_permission and tool.name not in self.SEQUENTIAL_ONLY

    def _run_tool_calls(self, calls: list[ToolCall]) -> list[tuple[str, bool]]:
        """Run all calls of one model turn; results come back in the SAME order as `calls`.

        The model often asks for several reads at once (e.g. read 3 files). Runs of consecutive
        read-only calls execute at the same time in threads; anything that can change the
        machine (and so may ask the user) runs alone, in its original position. Example:
            [read a, read b, edit c, read d]  ->  (read a || read b), then edit c, then read d
        Each finished result is also recorded in self._finished[index] right away, so if the
        user hits Ctrl+C halfway, _repair_history can report what really happened.
        """
        results: list[tuple[str, bool]] = []
        i = 0
        while i < len(calls):
            j = i
            while j < len(calls) and self._parallel_ok(calls[j]):
                j += 1
            if j - i >= 2:                    # 2+ read-only calls in a row: run them together
                results += self._execute_parallel(calls[i:j], first_index=i)
                i = j
            else:
                results.append(self._execute(calls[i]))
                self._finished[i] = results[-1]
                i += 1
        return results

    def _execute_parallel(self, calls: list[ToolCall], first_index: int = 0) -> list[tuple[str, bool]]:
        """Run read-only calls concurrently. Only tool.run() happens in the worker threads;
        checks, hooks and all printing stay on the main thread, in call order, so the
        screen output looks exactly like the sequential version."""
        checked = [self._prepare(call) for call in calls]   # permissions + pre_tool hooks, in order
        pool = ThreadPoolExecutor(max_workers=min(8, len(calls)))
        futures = [pool.submit(self._run_tool, tool, call) if tool else None
                   for call, (tool, _) in zip(calls, checked)]
        try:
            results = []
            for k, (call, (tool, refusal), future) in enumerate(zip(calls, checked, futures)):
                self.ui.tool_call(call.name, call.args)
                if refusal:
                    results.append(self._done(call, *refusal))
                else:
                    self.tool_calls_made += 1
                    results.append(self._finish(call, *_wait(future)))
                self._finished[first_index + k] = results[-1]
            return results
        except KeyboardInterrupt:
            # Keep the results of calls that DID finish in the background before the Ctrl+C.
            for k, future in enumerate(futures):
                if (first_index + k not in self._finished and future is not None and future.done()
                        and not future.cancelled() and future.exception() is None):
                    output, ok, _ = future.result()
                    self._finished[first_index + k] = (output, ok)
            raise
        finally:
            # On Ctrl+C: don't block until the other threads finish; drop calls not yet started.
            pool.shutdown(wait=False, cancel_futures=True)

    def _execute(self, call: ToolCall) -> tuple[str, bool]:
        """Run one tool call safely. Never raises: every failure becomes text the model can read."""
        self.ui.tool_call(call.name, call.args)
        tool, refusal = self._prepare(call)
        if refusal:
            return self._done(call, *refusal)
        self.tool_calls_made += 1
        return self._finish(call, *self._run_tool(tool, call))

    def _prepare(self, call: ToolCall) -> tuple[Tool | None, tuple[str, bool] | None]:
        """Checks before running: does the tool exist, is it allowed, does a hook veto it?
        Returns (tool, None) if it may run, or (None, (reason, False)) if not."""
        tool = self.tools.get(call.name)
        if tool is None:
            return None, (f"Unknown tool '{call.name}'. Available: {', '.join(self.tools)}", False)

        allowed, reason = self.permissions.check(tool, call.args, self.ui)
        if not allowed:
            return None, (reason, False)

        if self.hooks:
            veto = self.hooks.pre_tool(call.name, call.args)
            if veto:
                return None, (f"Blocked by pre_tool hook: {veto}", False)
        return tool, None

    @staticmethod
    def _run_tool(tool: Tool, call: ToolCall) -> tuple[str, bool, float]:
        """Actually run the tool. No UI, no shared agent state, so it is safe in a worker thread."""
        start = time.time()
        try:
            output, ok = tool.run(**call.args), True
        except ToolError as e:
            output, ok = str(e), False
        except TypeError as e:           # model sent wrong/missing arguments
            output, ok = f"Bad arguments for {call.name}: {e}", False
        except Exception as e:           # a bug in the tool itself; don't crash the agent
            output, ok = f"{type(e).__name__}: {e}", False
        return output, ok, time.time() - start

    def _finish(self, call: ToolCall, output: str, ok: bool, seconds: float) -> tuple[str, bool]:
        if self.hooks:
            self.hooks.post_tool(call.name, call.args, output, ok, seconds)
        return self._done(call, output, ok)

    def _done(self, call: ToolCall, output: str, ok: bool) -> tuple[str, bool]:
        self.ui.tool_result(call.name, output, ok)
        return output, ok

    def _repair_history(self) -> None:
        """After Ctrl+C mid-turn, the last model message may have tool calls with no results.
        The API rejects that, so every call gets a result: its REAL result if it had already
        finished (e.g. a file was written - the model must know that), else 'Cancelled by user.'"""
        last = self.history[-1] if self.history else None
        if last and last.role == "model":
            calls = [p.function_call for p in last.parts or [] if p.function_call]
            if calls:
                finished = getattr(self, "_finished", {})   # index in this turn -> (output, ok)
                self.history.append(types.Content(role="user", parts=[
                    _response_part(c, *finished.get(i, ("Cancelled by user.", False)))
                    for i, c in enumerate(calls)]))
