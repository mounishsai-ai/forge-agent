from google.genai import types

from forge import session


class FakeAgentForSession:
    def __init__(self, model, history):
        self.llm = type("L", (), {"model": model})()
        self.history = history


def test_save_creates_json_file(project_dir):
    agent = FakeAgentForSession("fake-model", [
        types.Content(role="user", parts=[types.Part(text="hello")]),
    ])
    path = session.save("sid1", agent)
    assert (project_dir / ".forge" / "sessions" / "sid1.json").is_file()
    assert path.endswith("sid1.json")


def test_save_load_round_trip_basic_text(project_dir):
    agent = FakeAgentForSession("fake-model", [
        types.Content(role="user", parts=[types.Part(text="hello")]),
        types.Content(role="model", parts=[types.Part(text="hi there")]),
    ])
    session.save("sid2", agent)
    sid, history = session.load("sid2")
    assert sid == "sid2"
    assert len(history) == 2
    assert history[0].role == "user"
    assert history[0].parts[0].text == "hello"
    assert history[1].parts[0].text == "hi there"


def test_save_load_round_trip_preserves_thought_signature_bytes(project_dir):
    sig = b"\x00\x01\xfe\xff"
    agent = FakeAgentForSession("fake-model", [
        types.Content(role="model", parts=[types.Part(text="thinking", thought_signature=sig)]),
    ])
    session.save("sid3", agent)
    _, history = session.load("sid3")
    assert history[0].parts[0].thought_signature == sig


def test_save_load_round_trip_function_call_and_response(project_dir):
    agent = FakeAgentForSession("fake-model", [
        types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(
            id="c1", name="read_file", args={"path": "a.txt"}))]),
        types.Content(role="user", parts=[types.Part(function_response=types.FunctionResponse(
            id="c1", name="read_file", response={"output": "contents"}))]),
    ])
    session.save("sid4", agent)
    _, history = session.load("sid4")
    assert history[0].parts[0].function_call.name == "read_file"
    assert history[0].parts[0].function_call.args == {"path": "a.txt"}
    assert history[1].parts[0].function_response.response == {"output": "contents"}


def test_load_without_id_loads_most_recent(project_dir):
    agent1 = FakeAgentForSession("fake-model", [types.Content(role="user", parts=[types.Part(text="first")])])
    agent2 = FakeAgentForSession("fake-model", [types.Content(role="user", parts=[types.Part(text="second")])])
    session.save("20200101-000000", agent1)
    session.save("20200101-000001", agent2)
    sid, history = session.load(None)
    assert sid == "20200101-000001"
    assert history[0].parts[0].text == "second"


def test_load_missing_session_raises(project_dir):
    import pytest
    with pytest.raises(FileNotFoundError):
        session.load(None)


def test_list_sessions_sorted(project_dir):
    assert session.list_sessions() == []
    agent = FakeAgentForSession("fake-model", [types.Content(role="user", parts=[types.Part(text="x")])])
    session.save("b-session", agent)
    session.save("a-session", agent)
    assert session.list_sessions() == ["a-session", "b-session"]


def test_new_session_id_format():
    sid = session.new_session_id()
    assert len(sid) == 15   # YYYYMMDD-HHMMSS
    assert sid[8] == "-"
