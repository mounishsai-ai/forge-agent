import pytest
from google.genai import errors, types

from forge import config
from forge.llm import GeminiLLM, Usage


def make_llm():
    """Build a GeminiLLM without running __init__ (which would require a real project id
    and construct a real genai.Client). Tests set only the attributes they need."""
    llm = object.__new__(GeminiLLM)
    llm.model = "gemini-3.8-flash"
    llm.fallbacks = ["gemini-3.7-flash", "gemini-3.5-flash"]
    llm.last_model_used = llm.model
    llm.broken_until = {}
    return llm


# ---------------------------------------------------------------------------
# GeminiLLM.__init__ requires config.PROJECT
# ---------------------------------------------------------------------------
def test_init_raises_systemexit_without_project(monkeypatch):
    monkeypatch.setattr(config, "PROJECT", None)
    with pytest.raises(SystemExit):
        GeminiLLM()


# ---------------------------------------------------------------------------
# _parse
# ---------------------------------------------------------------------------
def _raw_response(parts, finish_reason="STOP", usage=None, no_candidates=False):
    usage = usage or types.GenerateContentResponseUsageMetadata(
        prompt_token_count=100, candidates_token_count=20, thoughts_token_count=5, cached_content_token_count=0)
    if no_candidates:
        return types.GenerateContentResponse(candidates=[], usage_metadata=usage)
    candidate = types.Candidate(content=types.Content(role="model", parts=parts), finish_reason=finish_reason)
    return types.GenerateContentResponse(candidates=[candidate], usage_metadata=usage)


def test_parse_extracts_text():
    raw = _raw_response([types.Part(text="hello world")])
    llm = make_llm()
    resp = llm._parse(raw, "gemini-3.8-flash")
    assert resp.text == "hello world"
    assert resp.tool_calls == []


def test_parse_excludes_thought_parts():
    raw = _raw_response([
        types.Part(text="internal reasoning", thought=True),
        types.Part(text="final answer"),
    ])
    llm = make_llm()
    resp = llm._parse(raw, "gemini-3.8-flash")
    assert resp.text == "final answer"
    assert "internal reasoning" not in resp.text


def test_parse_extracts_tool_calls():
    raw = _raw_response([
        types.Part(function_call=types.FunctionCall(id="c1", name="read_file", args={"path": "a.txt"})),
    ])
    llm = make_llm()
    resp = llm._parse(raw, "gemini-3.8-flash")
    assert resp.text == ""
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "read_file"
    assert resp.tool_calls[0].args == {"path": "a.txt"}
    assert resp.tool_calls[0].id == "c1"


def test_parse_usage_and_cost():
    raw = _raw_response([types.Part(text="hi")], usage=types.GenerateContentResponseUsageMetadata(
        prompt_token_count=1000, candidates_token_count=200, thoughts_token_count=50, cached_content_token_count=10))
    llm = make_llm()
    resp = llm._parse(raw, "gemini-3.8-flash")
    assert resp.usage.input_tokens == 1000
    assert resp.usage.output_tokens == 200
    assert resp.usage.thinking_tokens == 50
    assert resp.usage.cached_tokens == 10
    expected_cost = round((1000 * 0.75 + (200 + 50) * 3.75) / 1_000_000, 6)
    assert resp.usage.cost_usd == expected_cost


def test_parse_unknown_model_cost_is_zero():
    raw = _raw_response([types.Part(text="hi")])
    llm = make_llm()
    resp = llm._parse(raw, "some-unpriced-model")
    assert resp.usage.cost_usd == 0.0


def test_parse_empty_candidates_gives_placeholder_text():
    raw = _raw_response([], no_candidates=True)
    llm = make_llm()
    resp = llm._parse(raw, "gemini-3.8-flash")
    assert "empty response" in resp.text
    assert resp.tool_calls == []


def test_parse_finish_reason_no_content_gives_placeholder():
    usage = types.GenerateContentResponseUsageMetadata(prompt_token_count=1, candidates_token_count=1)
    candidate = types.Candidate(content=None, finish_reason="MAX_TOKENS")
    raw = types.GenerateContentResponse(candidates=[candidate], usage_metadata=usage)
    llm = make_llm()
    resp = llm._parse(raw, "gemini-3.8-flash")
    assert "empty response" in resp.text
    assert "MAX_TOKENS" in resp.text


# ---------------------------------------------------------------------------
# _call_with_retry: fallback chain + circuit breaker
# ---------------------------------------------------------------------------
class FakeModels:
    """Stands in for client.models. `responses` is a list of exceptions/values consumed
    in order, one per call to generate_content, keyed by nothing -- just a flat queue."""

    def __init__(self, queue):
        self.queue = list(queue)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(model)
        item = self.queue.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class FakeClient:
    def __init__(self, queue):
        self.models = FakeModels(queue)


def _ok_response():
    usage = types.GenerateContentResponseUsageMetadata(prompt_token_count=1, candidates_token_count=1)
    candidate = types.Candidate(content=types.Content(role="model", parts=[types.Part(text="ok")]),
                                 finish_reason="STOP")
    return types.GenerateContentResponse(candidates=[candidate], usage_metadata=usage)


def test_retry_falls_back_to_next_model_on_504(monkeypatch):
    monkeypatch.setattr("forge.llm.time.sleep", lambda *a, **k: None)
    llm = make_llm()
    llm.client = FakeClient([
        errors.ServerError(504, {"error": {"message": "deadline"}}),   # primary: no retry, straight fallback
        _ok_response(),                                                 # first fallback succeeds
    ])
    raw = llm._call_with_retry(history=[], cfg=None)
    assert raw is not None
    assert llm.last_model_used == "gemini-3.7-flash"
    assert llm.client.models.calls == ["gemini-3.8-flash", "gemini-3.7-flash"]


def test_retry_retries_503_twice_before_falling_back(monkeypatch):
    sleeps = []
    monkeypatch.setattr("forge.llm.time.sleep", lambda s: sleeps.append(s))
    llm = make_llm()
    llm.client = FakeClient([
        errors.ServerError(503, {"error": {"message": "overloaded"}}),
        errors.ServerError(503, {"error": {"message": "overloaded"}}),
        _ok_response(),
    ])
    raw = llm._call_with_retry(history=[], cfg=None)
    assert llm.client.models.calls == ["gemini-3.8-flash", "gemini-3.8-flash", "gemini-3.7-flash"]
    assert len(sleeps) == 2   # one backoff sleep per failed attempt on the primary model


def test_retry_does_not_retry_non_retryable_400(monkeypatch):
    monkeypatch.setattr("forge.llm.time.sleep", lambda *a, **k: None)
    llm = make_llm()
    llm.client = FakeClient([errors.ClientError(400, {"error": {"message": "bad request"}})])
    with pytest.raises(errors.ClientError):
        llm._call_with_retry(history=[], cfg=None)
    assert llm.client.models.calls == ["gemini-3.8-flash"]   # never tried a fallback


def test_retry_timeout_exception_skips_to_next_model(monkeypatch):
    import httpx
    monkeypatch.setattr("forge.llm.time.sleep", lambda *a, **k: None)
    llm = make_llm()
    llm.client = FakeClient([httpx.ReadTimeout("timed out"), _ok_response()])
    raw = llm._call_with_retry(history=[], cfg=None)
    assert llm.client.models.calls == ["gemini-3.8-flash", "gemini-3.7-flash"]


def test_circuit_breaker_skips_broken_model(monkeypatch):
    import time as time_module
    monkeypatch.setattr("forge.llm.time.sleep", lambda *a, **k: None)
    llm = make_llm()
    llm.broken_until = {"gemini-3.8-flash": time_module.time() + 600}
    llm.client = FakeClient([_ok_response()])
    raw = llm._call_with_retry(history=[], cfg=None)
    # The broken primary model should be skipped entirely; only the healthy fallback is called.
    assert llm.client.models.calls == ["gemini-3.7-flash"]


def test_circuit_breaker_expired_entry_is_retried(monkeypatch):
    import time as time_module
    monkeypatch.setattr("forge.llm.time.sleep", lambda *a, **k: None)
    llm = make_llm()
    llm.broken_until = {"gemini-3.8-flash": time_module.time() - 1}   # already expired
    llm.client = FakeClient([_ok_response()])
    raw = llm._call_with_retry(history=[], cfg=None)
    assert llm.client.models.calls == ["gemini-3.8-flash"]


def test_all_models_broken_still_tries_all(monkeypatch):
    import time as time_module
    monkeypatch.setattr("forge.llm.time.sleep", lambda *a, **k: None)
    llm = make_llm()
    future = time_module.time() + 600
    llm.broken_until = {m: future for m in [llm.model] + llm.fallbacks}
    llm.client = FakeClient([_ok_response()])
    raw = llm._call_with_retry(history=[], cfg=None)
    # `healthy` falls back to the full model list when every model is broken.
    assert llm.client.models.calls == ["gemini-3.8-flash"]


def test_generate_builds_declarations_and_returns_llmresponse(monkeypatch):
    """Exercises generate() end-to-end against a fake client, including building real
    FunctionDeclaration objects from every real tool in ALL_TOOLS -- catches schema bugs
    that only show up when Tool.declaration() actually runs."""
    from forge.tools import ALL_TOOLS
    monkeypatch.setattr("forge.llm.time.sleep", lambda *a, **k: None)
    llm = make_llm()
    llm.client = FakeClient([_ok_response()])
    history = [types.Content(role="user", parts=[types.Part(text="hi")])]
    resp = llm.generate(history, ALL_TOOLS, "system prompt")
    assert resp.text == "ok"
    assert llm.last_model_used == "gemini-3.8-flash"
