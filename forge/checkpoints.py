"""File checkpoints and /undo (like Claude Code's checkpoints, but with no git required).

WHY: the model edits real files. If it goes off the rails, the user needs a one-command way to
put the files back without knowing git (or when the project isn't a git repo at all).

HOW:
  * write_file / edit_file call `record(path)` right BEFORE they change a file. We save the
    file's current bytes (or the fact that it did not exist yet).
  * Snapshots are grouped per USER TURN (one message typed at the `>` prompt), because that's the
    unit a user thinks in: "undo what you just did". cli.repl calls `begin_turn()` before agent.run.
  * Only the FIRST snapshot of a file in a turn is kept: if the model edits app.py 5 times in one
    turn, undo must restore the version from before the turn, not from before the 5th edit.
  * `undo(n)` restores the last n turns newest-first, so a file changed in several turns ends up
    at its oldest saved state. Files the turn created are deleted.

Stored in memory, and in the REPL also on disk under .forge/checkpoints/<session>/<turn>/
(manifest.json + one blob per file) so /undo still works after `forge --resume`.

LIMITATION (important, be upfront about it): only write_file and edit_file are tracked. Anything
run_shell does (`rm`, `git checkout`, `npm install`, a script that rewrites files, ...) is NOT
captured, because a shell command can touch any file and we can't know which ones in advance.
Snapshotting the whole project before every command would be too slow. MCP tools are not tracked
either. Git is still the real safety net; checkpoints are for quick "oops, undo that".
"""
import datetime
import json
import os
import shutil
import threading

CHECKPOINTS_DIR = os.path.join(".forge", "checkpoints")

# A lock because tool calls may run on worker threads (parallel read-only calls, sub-agents).
# Writes are normally serial, but a lock is cheap insurance against two snapshots racing.
_lock = threading.Lock()


class _Store:
    """Module-level state, like tools.base.files_read: the tools are plain functions with no
    access to the Agent object, so a shared module is the simplest way for them to reach it."""

    def __init__(self):
        self.session_id: str | None = None
        self.turns: list[dict] = []        # [{"id": int, "prompt": str, "time": str, "files": {path: bytes|None}}]
        self.pending_prompt: str | None = None   # set by begin_turn; a turn is only created on first write
        self.next_id = 1


_store = _Store()


def _session_dir() -> str | None:
    """Where this session's checkpoints live on disk, or None = memory only.

    Only the REPL calls set_session(). Headless runs (`forge -p`, evals) and the test suite stay
    in memory: the process exits right after, so nobody could /undo anyway, and we don't want to
    litter an eval's work directory with .forge/checkpoints files."""
    if _store.session_id is None:
        return None
    return os.path.join(CHECKPOINTS_DIR, _store.session_id)


def reset() -> None:
    """Forget everything in memory (used by tests; files on disk are left alone)."""
    global _store
    with _lock:
        _store = _Store()


def set_session(session_id: str) -> None:
    """Point the store at a session, loading any turns saved on disk (so --resume keeps /undo)."""
    with _lock:
        _store.session_id = session_id
        _store.turns = _load_turns(os.path.join(CHECKPOINTS_DIR, session_id))
        _store.next_id = max((t["id"] for t in _store.turns), default=0) + 1


def begin_turn(prompt: str) -> None:
    """Mark the start of a new user turn. Called by the REPL right before agent.run().

    We don't create the turn yet: most turns (questions, reading code) change no files, and an
    empty turn would make `/undo` do nothing visible. The turn is created on its first write."""
    with _lock:
        _store.pending_prompt = prompt


def record(path: str) -> None:
    """Snapshot `path` (absolute) before a tool modifies it. Call this BEFORE writing."""
    with _lock:
        if _store.pending_prompt is not None or not _store.turns:
            # First write since begin_turn (or ever, e.g. headless mode): open a new turn.
            _store.turns.append({
                "id": _store.next_id,
                "prompt": (_store.pending_prompt or "(headless)")[:200],
                "time": datetime.datetime.now().isoformat(timespec="seconds"),
                "files": {},
            })
            _store.next_id += 1
            _store.pending_prompt = None
        turn = _store.turns[-1]
        if path in turn["files"]:
            return   # keep the snapshot from BEFORE this turn, not from before a later edit in it
        if os.path.isfile(path):
            with open(path, "rb") as f:   # bytes, so CRLF/encoding come back exactly as they were
                turn["files"][path] = f.read()
        else:
            turn["files"][path] = None    # None = "did not exist": undo deletes it
        try:
            _save_turn(turn)
        except OSError:
            pass   # disk copy is a bonus (for --resume); never fail the user's edit because of it


def list_turns() -> list[dict]:
    """Turns that changed files, oldest first: [{"id", "prompt", "time", "files": [paths]}]."""
    with _lock:
        return [{"id": t["id"], "prompt": t["prompt"], "time": t["time"], "files": list(t["files"])}
                for t in _store.turns]


def undo(n: int = 1) -> list[tuple[str, str]]:
    """Revert the last n turns that changed files. Returns [(path, "restored" | "deleted")]."""
    changes: dict[str, str] = {}
    with _lock:
        for _ in range(min(n, len(_store.turns))):
            turn = _store.turns.pop()   # newest first, so older snapshots win for the same file
            for path, content in turn["files"].items():
                if content is None:
                    if os.path.isfile(path):
                        os.remove(path)
                    changes[path] = "deleted"
                else:
                    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)   # dir may have been removed
                    with open(path, "wb") as f:
                        f.write(content)
                    changes[path] = "restored"
            if _session_dir():
                shutil.rmtree(os.path.join(_session_dir(), str(turn["id"])), ignore_errors=True)
        _store.pending_prompt = None
    return sorted(changes.items())


# --- on-disk format: <session>/<turn id>/manifest.json + <i>.bin per file that existed ----------

def _save_turn(turn: dict) -> None:
    if _session_dir() is None:
        return
    d = os.path.join(_session_dir(), str(turn["id"]))
    os.makedirs(d, exist_ok=True)
    entries = []
    for i, (path, content) in enumerate(turn["files"].items()):
        blob = None
        if content is not None:
            blob = f"{i}.bin"
            if not os.path.exists(os.path.join(d, blob)):   # snapshots never change once taken
                with open(os.path.join(d, blob), "wb") as f:
                    f.write(content)
        entries.append({"path": path, "blob": blob})
    manifest = {"id": turn["id"], "prompt": turn["prompt"], "time": turn["time"], "files": entries}
    with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)


def _load_turns(session_dir: str) -> list[dict]:
    if not os.path.isdir(session_dir):
        return []
    turns = []
    for name in os.listdir(session_dir):
        manifest = os.path.join(session_dir, name, "manifest.json")
        if not os.path.isfile(manifest):
            continue
        try:
            with open(manifest, encoding="utf-8") as f:
                m = json.load(f)
            files = {}
            for e in m["files"]:
                if e["blob"] is None:
                    files[e["path"]] = None
                else:
                    with open(os.path.join(session_dir, name, e["blob"]), "rb") as f:
                        files[e["path"]] = f.read()
        except (OSError, ValueError, KeyError):
            continue   # a half-written/corrupt checkpoint is skipped, not fatal
        turns.append({"id": m["id"], "prompt": m["prompt"], "time": m["time"], "files": files})
    return sorted(turns, key=lambda t: t["id"])


def undo_note(changes: list[tuple[str, str]]) -> str:
    """Text told to the model after /undo. Without it, the model's memory of the files (in the
    history) would be stale and it might 'continue' from changes that no longer exist."""
    lines = "\n".join(f"- {os.path.relpath(p) if _same_drive(p) else p}: {what}" for p, what in changes)
    return ("[harness] The user ran /undo. These files were reverted to their earlier state "
            f"(your changes to them are gone):\n{lines}\nRe-read any of them before editing again.")


def _same_drive(p: str) -> bool:
    try:
        os.path.relpath(p)
        return True
    except ValueError:   # Windows: a path on another drive has no relative form
        return False
