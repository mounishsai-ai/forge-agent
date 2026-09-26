"""The LLM provider layer: the ONLY file that talks to the model API.

The agent loop calls `llm.generate(history, tools, system)` and gets back a
provider-neutral `LLMResponse` (text + tool calls + token usage). The interactive
REPL uses `llm.generate_stream(...)` instead, which returns the same LLMResponse but
shows the text live while it arrives. Swapping
Gemini for another provider means writing another class with this method.
"""
import random
import time
from dataclasses import dataclass, field
from typing import Callable

import httpx
from google import genai
from google.genai import errors, types

from forge import config, pricing


@dataclass
class ToolCall:
    id: str | None
    name: str
    args: dict


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0
    cached_tokens: int = 0
    cost_usd: float = 0.0          # priced per call, using the model that actually answered

    def add(self, other: "Usage") -> None:
        self.cost_usd += other.cost_usd
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.thinking_tokens += other.thinking_tokens
        self.cached_tokens += other.cached_tokens


@dataclass
class LLMResponse:
    content: types.Content                 # raw model message; goes back into history as-is
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


def _merge_part(parts: list[types.Part], part: types.Part) -> None:
    """Add one streamed part to the message being assembled.

    A streamed answer arrives as many tiny text parts ("I will", " read the", ...). Plain text
    pieces are glued together so history looks like a normal reply. Everything else is kept
    exactly as it came: function calls, and any part carrying a `thought_signature` (Gemini's
    encrypted reasoning state, which MUST be sent back untouched or later turns break). The
    signature often arrives on its own final chunk as text='' + signature; that part is kept too.
    """
    fields = part.model_dump(exclude_none=True)
    if not fields or fields == {"text": ""}:
        return                                  # empty filler chunk: nothing worth keeping
    plain = set(fields) <= {"text", "thought"}  # just text (maybe a thought summary), no signature
    prev = parts[-1] if parts else None
    if (prev is not None and plain and set(prev.model_dump(exclude_none=True)) <= {"text", "thought"}
            and prev.text is not None and bool(prev.thought) == bool(part.thought)):
        parts[-1] = types.Part(text=prev.text + (part.text or ""), thought=prev.thought)
    else:
        parts.append(part)


# HTTP codes worth retrying: rate limit and transient server errors.
RETRYABLE = {429, 500, 502, 503, 504}
BREAKER_SECONDS = 600


class GeminiLLM:
    def __init__(self, model: str = config.MODEL, fallbacks: list[str] = config.FALLBACK_MODELS):
        if not config.PROJECT:
            raise SystemExit("Set FORGE_PROJECT (or GOOGLE_CLOUD_PROJECT) to your Google Cloud project id.")
        self.model = model
        self.fallbacks = fallbacks
        self.last_model_used = model
        self.broken_until: dict[str, float] = {}   # model -> time until which we skip it
        self.client = genai.Client(
            vertexai=True, project=config.PROJECT, location=config.LOCATION,
            http_options=types.HttpOptions(timeout=config.REQUEST_TIMEOUT * 1000),  # milliseconds
        )

    def _config(self, tools: list, system: str) -> types.GenerateContentConfig:
        """Request settings shared by generate() and generate_stream(), so the two can't drift apart."""
        return types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=[t.declaration() for t in tools])] if tools else None,
            # We run tools ourselves in agent.py, so the SDK must never auto-call anything.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    def generate(self, history: list[types.Content], tools: list, system: str) -> LLMResponse:
        raw = self._call_with_retry(history, self._config(tools, system))
        return self._parse(raw, self.last_model_used)

    def generate_stream(self, history: list[types.Content], tools: list, system: str,
                        on_text: Callable[[str], None]) -> LLMResponse:
        """Same result as generate(), but visible text is handed to `on_text` as it arrives,
        so the user watches the answer being typed instead of staring at a spinner.

        The model's reply arrives as many small chunks. We show the text chunks live, and at
        the end glue all chunks back into ONE Content message for the history (see _merge_part).
        """
        cfg = self._config(tools, system)
        emitted = False   # once the user has seen text, a retry would show it twice -> no retries

        def stream_once(model: str):
            nonlocal emitted
            parts: list[types.Part] = []      # fresh per attempt, so a retry can't duplicate parts
            usage, finish = None, None
            # The stream is lazy: errors (429/503/timeouts) can appear while iterating, so the whole
            # loop runs inside _call_with_retry's try-block, not just the call that opens it.
            for chunk in self.client.models.generate_content_stream(model=model, contents=history, config=cfg):
                usage = chunk.usage_metadata or usage          # token counts come on the last chunk
                cand = chunk.candidates[0] if chunk.candidates else None
                if cand is None:
                    continue
                finish = cand.finish_reason or finish
                for part in (cand.content.parts if cand.content and cand.content.parts else []):
                    if part.text and not part.thought and not part.function_call:
                        emitted = True
                        on_text(part.text)
                    _merge_part(parts, part)
            # Rebuild a normal (non-streaming) response object so _parse can treat it identically.
            cand = types.Candidate(content=types.Content(role="model", parts=parts) if parts else None,
                                   finish_reason=finish)
            return types.GenerateContentResponse(candidates=[cand], usage_metadata=usage)

        raw = self._call_with_retry(history, cfg, request=stream_once, can_retry=lambda: not emitted)
        return self._parse(raw, self.last_model_used)

    def _call_with_retry(self, history, cfg, attempts_per_model: int = 2,
                         request: Callable | None = None, can_retry: Callable[[], bool] = lambda: True):
        """Retry transient errors with backoff; if a model keeps failing, fall back to the next one.

        Circuit breaker: a model that just failed is skipped for BREAKER_SECONDS, so we don't
        pay the timeout again on every single turn while it's overloaded.
        `request(model)` does the actual API call (default: one non-streaming generate_content).
        `can_retry()` lets streaming say "text already reached the screen, don't retry": a retry
        would print the same words twice, so the error is raised to the caller instead.
        """
        if request is None:
            def request(model):
                return self.client.models.generate_content(model=model, contents=history, config=cfg)
        now = time.time()
        models = [self.model] + [m for m in self.fallbacks if m != self.model]
        healthy = [m for m in models if self.broken_until.get(m, 0) < now] or models
        last_error = None
        if len(models) == 1:
            attempts_per_model = max(attempts_per_model, 6)   # no fallback to switch to: be more patient
        for model in healthy:
            for attempt in range(attempts_per_model):
                try:
                    raw = request(model)
                    self.last_model_used = model
                    return raw
                except errors.APIError as e:
                    if e.code not in RETRYABLE or not can_retry():
                        raise              # e.g. 400 bad request: retrying won't help
                    last_error = e
                    if e.code == 504:
                        break              # deadline exceeded: we already waited long, don't retry this model
                except httpx.TimeoutException as e:
                    if not can_retry():
                        raise
                    last_error = e
                    break                  # already waited REQUEST_TIMEOUT; go straight to the next model
                # Exponential backoff with jitter (1s, 2s, 4s... + random) so retries don't stampede.
                time.sleep(min(2 ** attempt, 30) + random.random())
            self.broken_until[model] = time.time() + BREAKER_SECONDS
        raise last_error

    def _parse(self, raw, model: str) -> LLMResponse:
        u = raw.usage_metadata
        usage = Usage(
            input_tokens=(u.prompt_token_count or 0) if u else 0,
            output_tokens=(u.candidates_token_count or 0) if u else 0,
            thinking_tokens=(u.thoughts_token_count or 0) if u else 0,
            cached_tokens=(u.cached_content_token_count or 0) if u else 0,
        )
        usage.cost_usd = pricing.cost(model, usage) or 0.0
        cand = raw.candidates[0] if raw.candidates else None
        content = cand.content if cand and cand.content and cand.content.parts else None
        if content is None:
            # Empty reply (safety block, max tokens, etc). Keep history valid with a placeholder.
            reason = cand.finish_reason if cand else "no candidates"
            content = types.Content(role="model", parts=[types.Part(text=f"(empty response: {reason})")])

        texts, calls = [], []
        for part in content.parts:
            if part.function_call:
                fc = part.function_call
                calls.append(ToolCall(id=fc.id, name=fc.name, args=dict(fc.args or {})))
            elif part.text and not part.thought:
                texts.append(part.text)
        return LLMResponse(content=content, text="".join(texts), tool_calls=calls, usage=usage)
