"""The LLM provider layer: the ONLY file that talks to the model API.

The agent loop calls `llm.generate(history, tools, system)` and gets back a
provider-neutral `LLMResponse` (text + tool calls + token usage). Swapping
Gemini for another provider means writing another class with this method.
"""
import random
import time
from dataclasses import dataclass, field

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

    def generate(self, history: list[types.Content], tools: list, system: str) -> LLMResponse:
        cfg = types.GenerateContentConfig(
            system_instruction=system,
            tools=[types.Tool(function_declarations=[t.declaration() for t in tools])] if tools else None,
            # We run tools ourselves in agent.py, so the SDK must never auto-call anything.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        raw = self._call_with_retry(history, cfg)
        return self._parse(raw, self.last_model_used)

    def _call_with_retry(self, history, cfg, attempts_per_model: int = 2):
        """Retry transient errors with backoff; if a model keeps failing, fall back to the next one.

        Circuit breaker: a model that just failed is skipped for BREAKER_SECONDS, so we don't
        pay the timeout again on every single turn while it's overloaded.
        """
        now = time.time()
        models = [self.model] + [m for m in self.fallbacks if m != self.model]
        healthy = [m for m in models if self.broken_until.get(m, 0) < now] or models
        last_error = None
        for model in healthy:
            for attempt in range(attempts_per_model):
                try:
                    raw = self.client.models.generate_content(model=model, contents=history, config=cfg)
                    self.last_model_used = model
                    return raw
                except errors.APIError as e:
                    if e.code not in RETRYABLE:
                        raise              # e.g. 400 bad request: retrying won't help
                    last_error = e
                    if e.code == 504:
                        break              # deadline exceeded: we already waited long, don't retry this model
                except httpx.TimeoutException as e:
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
