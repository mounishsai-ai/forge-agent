"""A second LLM provider: any OpenAI-compatible Chat Completions API.

That one API shape is spoken by most hosts of open models - OpenRouter, Together, Groq,
Fireworks, DeepSeek, Alibaba's Qwen API, Google's Model Garden "openapi" endpoint - and by
local servers (Ollama, vLLM, LM Studio). So this one file lets Forge drive Qwen, DeepSeek,
Llama, gpt-oss, ... as well as OpenAI's own models.

Design: the agent keeps its history in ONE format (google.genai `types.Content`), whichever
provider is used. This class translates at the edge: history -> OpenAI `messages` on the way
out, and the OpenAI reply -> a `types.Content` on the way back. So agent.py, context.py,
session.py and the tools never know which provider is behind the loop - it's the same
`generate(history, tools, system) -> LLMResponse` contract as GeminiLLM.

    forge --provider openai --base-url https://openrouter.ai/api/v1 --model qwen/qwen3-coder
    (API key from FORGE_API_KEY or OPENAI_API_KEY; not needed for local Ollama)
"""
import json
import os
import random
import time
import uuid

import httpx
from google.genai import types

from forge import pricing
from forge.llm import LLMResponse, ToolCall, Usage

RETRYABLE = {408, 409, 429, 500, 502, 503, 504}


class OpenAICompatLLM:
    def __init__(self, model: str, base_url: str, api_key: str | None = None, timeout: float = 120):
        self.model = model
        self.last_model_used = model
        self.fallbacks: list[str] = []   # same attributes as GeminiLLM, so the CLI treats both alike
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key or os.environ.get("FORGE_API_KEY") or os.environ.get("OPENAI_API_KEY")
        self.http = httpx.Client(timeout=timeout)

    # ---- the one method the agent calls -------------------------------------------------------
    def generate(self, history: list[types.Content], tools: list, system: str) -> LLMResponse:
        body = {"model": self.model, "messages": to_openai_messages(history, system)}
        if tools:
            body["tools"] = [{"type": "function", "function": {
                "name": t.name, "description": t.description, "parameters": t.parameters}} for t in tools]
        data = self._post_with_retry(body)
        return self._parse(data)

    # ---- HTTP ------------------------------------------------------------------------------------
    def _post_with_retry(self, body: dict, attempts: int = 6) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        last = None
        for attempt in range(attempts):
            try:
                r = self.http.post(self.url, json=body, headers=headers)
                if r.status_code < 400:
                    return r.json()
                last = RuntimeError(f"HTTP {r.status_code}: {r.text[:500]}")
                if r.status_code not in RETRYABLE:
                    raise last          # e.g. 400 bad request / 401 bad key: retrying won't help
            except (httpx.TransportError, OSError) as e:   # network drop, DNS, timeout
                last = e
            time.sleep(min(2 ** attempt, 30) + random.random())   # backoff with jitter, like llm.py
        raise last

    # ---- OpenAI reply -> Forge's format ----------------------------------------------------------
    def _parse(self, data: dict) -> LLMResponse:
        msg = (data.get("choices") or [{}])[0].get("message") or {}
        parts, calls = [], []
        text = msg.get("content") or ""
        if text:
            parts.append(types.Part(text=text))
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                # Open models sometimes emit broken JSON. Pass it on so the tool call fails with a
                # readable error the model can fix, instead of crashing the loop.
                args = {"_raw_arguments": fn.get("arguments")}
            call_id = tc.get("id") or f"call_{uuid.uuid4().hex[:12]}"
            calls.append(ToolCall(id=call_id, name=fn.get("name", ""), args=args))
            parts.append(types.Part(function_call=types.FunctionCall(id=call_id, name=fn.get("name"), args=args)))
        if not parts:
            reason = (data.get("choices") or [{}])[0].get("finish_reason", "no choices")
            parts = [types.Part(text=f"(empty response: {reason})")]

        u = data.get("usage") or {}
        usage = Usage(input_tokens=u.get("prompt_tokens", 0) or 0,
                      output_tokens=u.get("completion_tokens", 0) or 0,
                      thinking_tokens=0,   # reasoning tokens are already inside completion_tokens here
                      cached_tokens=((u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0))
        usage.cost_usd = pricing.cost(self.model, usage) or 0.0
        return LLMResponse(content=types.Content(role="model", parts=parts), text=text,
                           tool_calls=calls, usage=usage)


# ---- Forge's history -> OpenAI messages ----------------------------------------------------------
def to_openai_messages(history: list[types.Content], system: str) -> list[dict]:
    """Translate the agent's history into Chat Completions messages.

    Mapping:  user text            -> {"role": "user"}
              model text + calls   -> {"role": "assistant", "tool_calls": [...]}
              user function_response -> one {"role": "tool", "tool_call_id": ...} per result
    Gemini-only parts (thought signatures, thoughts) have no OpenAI equivalent and are dropped,
    which is harmless: they only matter to Gemini.
    """
    messages = [{"role": "system", "content": system}] if system else []
    for c in history:
        parts = c.parts or []
        if c.role == "model":
            text = "".join(p.text for p in parts if p.text and not p.thought)
            calls = [p.function_call for p in parts if p.function_call]
            msg = {"role": "assistant", "content": text or None}
            if calls:
                msg["tool_calls"] = [{"id": fc.id or _fallback_id(fc), "type": "function",
                                      "function": {"name": fc.name, "arguments": json.dumps(fc.args or {})}}
                                     for fc in calls]
            if text or calls:
                messages.append(msg)
        else:
            for p in parts:
                if p.function_response:
                    fr = p.function_response
                    resp = fr.response or {}
                    content = resp.get("output", resp.get("error", json.dumps(resp)))
                    messages.append({"role": "tool", "tool_call_id": fr.id or _fallback_id(fr),
                                     "content": content if isinstance(content, str) else json.dumps(content)})
            text = "".join(p.text for p in parts if p.text)
            if text:
                messages.append({"role": "user", "content": text})
    return messages


def _fallback_id(obj) -> str:
    """History made by Gemini may have calls without ids. OpenAI requires them and requires the
    call and its result to match, so derive the SAME id from the name for both sides."""
    return f"call_{obj.name}"
