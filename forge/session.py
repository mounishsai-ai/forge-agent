"""Save and resume conversations. Each session is one JSON file in .forge/sessions/ of the project."""
import datetime
import json
import os

from google.genai import types

SESSIONS_DIR = os.path.join(".forge", "sessions")


def new_session_id() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def save(session_id: str, agent) -> str:
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    path = os.path.join(SESSIONS_DIR, f"{session_id}.json")
    data = {
        "id": session_id,
        "model": agent.llm.model,
        "saved_at": datetime.datetime.now().isoformat(timespec="seconds"),
        # model_dump(mode="json") base64-encodes bytes such as Gemini's thought signatures.
        "history": [c.model_dump(mode="json", exclude_none=True) for c in agent.history],
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    return path


def load(session_id: str | None = None) -> tuple[str, list[types.Content]]:
    """Load a session by id, or the most recent one if id is None."""
    if session_id is None:
        ids = list_sessions()
        if not ids:
            raise FileNotFoundError("No saved sessions in this directory.")
        session_id = ids[-1]
    with open(os.path.join(SESSIONS_DIR, f"{session_id}.json"), encoding="utf-8") as f:
        data = json.load(f)
    return session_id, [types.Content.model_validate(c) for c in data["history"]]


def list_sessions() -> list[str]:
    if not os.path.isdir(SESSIONS_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(SESSIONS_DIR) if f.endswith(".json"))
