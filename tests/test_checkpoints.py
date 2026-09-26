"""File checkpoints + /undo (forge/checkpoints.py and its hooks in write_file/edit_file/cli)."""
import os

import pytest

from forge import checkpoints
from forge.agent import Agent
from forge.cli import handle_command
from forge.permissions import Permissions
from forge.tools import ALL_TOOLS
from forge.tools import base as tools_base
from forge.tools.edit_file import edit_file
from forge.tools.read_file import read_file
from forge.tools.write_file import write_file


@pytest.fixture(autouse=True)
def _fresh_store():
    checkpoints.reset()
    yield
    checkpoints.reset()


def _read(path):
    with open(path, "rb") as f:
        return f.read()


def test_undo_restores_edited_file(project_dir):
    (project_dir / "a.py").write_text("x = 1\n", encoding="utf-8")
    read_file("a.py")
    checkpoints.begin_turn("change x")
    edit_file("a.py", "x = 1", "x = 2")
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "x = 2\n"
    changes = checkpoints.undo()
    assert changes == [(str(project_dir / "a.py"), "restored")]
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "x = 1\n"


def test_undo_deletes_created_file(project_dir):
    checkpoints.begin_turn("make file")
    write_file("sub/new.txt", "hello")
    assert (project_dir / "sub" / "new.txt").exists()
    assert checkpoints.undo() == [(str(project_dir / "sub" / "new.txt"), "deleted")]
    assert not (project_dir / "sub" / "new.txt").exists()


def test_multiple_edits_in_one_turn_restore_pre_turn_state(project_dir):
    (project_dir / "a.py").write_text("v0", encoding="utf-8")
    read_file("a.py")
    checkpoints.begin_turn("t")
    edit_file("a.py", "v0", "v1")
    edit_file("a.py", "v1", "v2")
    write_file("a.py", "v3")
    assert len(checkpoints.list_turns()) == 1
    checkpoints.undo()
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "v0"


def test_undo_n_goes_back_several_turns(project_dir):
    (project_dir / "a.py").write_text("v0", encoding="utf-8")
    read_file("a.py")
    for i in range(1, 4):
        checkpoints.begin_turn(f"turn {i}")
        edit_file("a.py", f"v{i - 1}", f"v{i}")
    assert [t["prompt"] for t in checkpoints.list_turns()] == ["turn 1", "turn 2", "turn 3"]
    checkpoints.undo(1)
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "v2"
    checkpoints.undo(2)
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "v0"
    assert checkpoints.list_turns() == []
    assert checkpoints.undo() == []   # nothing left


def test_turn_without_writes_creates_no_checkpoint(project_dir):
    (project_dir / "a.py").write_text("v0", encoding="utf-8")
    read_file("a.py")
    checkpoints.begin_turn("edit")
    edit_file("a.py", "v0", "v1")
    checkpoints.begin_turn("just a question")   # no writes in this turn
    assert len(checkpoints.list_turns()) == 1
    checkpoints.undo()   # still undoes the edit turn, not the empty one
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "v0"


def test_failed_edit_records_nothing(project_dir):
    (project_dir / "a.py").write_text("v0", encoding="utf-8")
    read_file("a.py")
    checkpoints.begin_turn("t")
    with pytest.raises(tools_base.ToolError):
        edit_file("a.py", "not there", "x")
    assert checkpoints.list_turns() == []


def test_crlf_bytes_restored_exactly(project_dir):
    raw = b"line1\r\nline2\r\n"
    (project_dir / "w.txt").write_bytes(raw)
    read_file("w.txt")
    checkpoints.begin_turn("t")
    edit_file("w.txt", "line1", "changed")
    checkpoints.undo()
    assert _read(project_dir / "w.txt") == raw


def test_headless_without_begin_turn_still_records(project_dir):
    write_file("h.txt", "x")   # no begin_turn / set_session, like `forge -p`
    assert len(checkpoints.list_turns()) == 1
    assert not (project_dir / ".forge").exists()   # memory only: no files left in the workdir


def test_persisted_to_disk_and_reloaded(project_dir):
    (project_dir / "a.py").write_text("v0", encoding="utf-8")
    read_file("a.py")
    checkpoints.set_session("s1")
    checkpoints.begin_turn("edit a")
    edit_file("a.py", "v0", "v1")
    write_file("b.py", "new")
    assert (project_dir / ".forge" / "checkpoints" / "s1" / "1" / "manifest.json").exists()

    checkpoints.reset()                # simulate quitting Forge...
    checkpoints.set_session("s1")      # ...and `forge --resume s1`
    turns = checkpoints.list_turns()
    assert [t["prompt"] for t in turns] == ["edit a"]
    checkpoints.undo()
    assert (project_dir / "a.py").read_text(encoding="utf-8") == "v0"
    assert not (project_dir / "b.py").exists()
    assert not (project_dir / ".forge" / "checkpoints" / "s1" / "1").exists()   # undone turn is gone


def _agent(fake_llm_factory, ui):
    return Agent(llm=fake_llm_factory([]), ui=ui, permissions=Permissions("ask"), system_prompt="sys",
                 tools=ALL_TOOLS, max_turns=10)


def test_undo_command_reverts_and_tells_model(project_dir, fake_llm_factory, fake_ui):
    (project_dir / "a.py").write_text("v0", encoding="utf-8")
    read_file("a.py")
    checkpoints.begin_turn("t")
    edit_file("a.py", "v0", "v1")
    agent = _agent(fake_llm_factory, fake_ui)

    handle_command("/undo", agent, fake_ui)

    assert (project_dir / "a.py").read_text(encoding="utf-8") == "v0"
    # The model is told (as a user/model pair, keeping roles alternating)...
    assert [c.role for c in agent.history] == ["user", "model"]
    assert "/undo" in agent.history[0].parts[0].text and "a.py" in agent.history[0].parts[0].text
    # ...and must re-read the file before editing it again.
    assert str(project_dir / "a.py") not in tools_base.files_read
    with pytest.raises(tools_base.ToolError):
        edit_file("a.py", "v0", "v2")


def test_undo_command_with_nothing_and_bad_arg(project_dir, fake_llm_factory, fake_ui):
    agent = _agent(fake_llm_factory, fake_ui)
    handle_command("/undo", agent, fake_ui)
    assert any("Nothing to undo" in m for m in fake_ui.infos)
    handle_command("/undo abc", agent, fake_ui)
    handle_command("/undo 0", agent, fake_ui)
    assert len(fake_ui.errors) == 2
    assert agent.history == []


def test_undo_n_via_command(project_dir, fake_llm_factory, fake_ui):
    agent = _agent(fake_llm_factory, fake_ui)
    for i in range(3):
        checkpoints.begin_turn(f"t{i}")
        write_file(f"f{i}.txt", "x")
    handle_command("/undo 2", agent, fake_ui)
    assert os.path.exists("f0.txt") and not os.path.exists("f1.txt") and not os.path.exists("f2.txt")
    assert len(checkpoints.list_turns()) == 1


def test_checkpoints_command_runs(project_dir, fake_llm_factory, fake_ui):
    agent = _agent(fake_llm_factory, fake_ui)
    handle_command("/checkpoints", agent, fake_ui)
    assert any("No checkpoints" in m for m in fake_ui.infos)
    checkpoints.begin_turn("make [x]")   # brackets must not break rich markup
    write_file("f.txt", "x")
    assert handle_command("/checkpoints", agent, fake_ui) is None
