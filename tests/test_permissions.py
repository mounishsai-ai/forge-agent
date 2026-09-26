import pytest

from forge.permissions import Permissions
from forge.tools import read_file, run_shell, write_file

DANGEROUS_COMMANDS = [
    "rm -rf /",
    "rm -rf ~",
    "git push --force origin main",
    "git push -f origin main",
    "format C:",
]


@pytest.mark.parametrize("cmd", DANGEROUS_COMMANDS)
@pytest.mark.parametrize("mode", ["ask", "auto", "readonly"])
def test_blocklist_blocks_dangerous_commands_in_every_mode(cmd, mode, fake_ui_factory):
    p = Permissions(mode)
    ok, reason = p.check(run_shell.TOOL, {"command": cmd}, fake_ui_factory())
    assert ok is False
    assert "Blocked" in reason


def test_readonly_denies_writes(fake_ui_factory):
    p = Permissions("readonly")
    ok, reason = p.check(write_file.TOOL, {"path": "x.txt", "content": "y"}, fake_ui_factory())
    assert ok is False
    assert "read-only" in reason


def test_readonly_allows_read_only_tools(fake_ui_factory):
    p = Permissions("readonly")
    ok, reason = p.check(read_file.TOOL, {"path": "x.txt"}, fake_ui_factory())
    assert ok is True


def test_auto_allows_writes_without_asking(fake_ui_factory):
    p = Permissions("auto")
    ui = fake_ui_factory()
    ok, reason = p.check(write_file.TOOL, {"path": "x.txt", "content": "y"}, ui)
    assert ok is True
    assert ui.asked == []


def test_ask_mode_prompts_and_respects_yes(fake_ui_factory):
    p = Permissions("ask")
    ui = fake_ui_factory(answers=["y"])
    ok, reason = p.check(write_file.TOOL, {"path": "x.txt", "content": "y"}, ui)
    assert ok is True
    assert ui.asked == [("write_file", {"path": "x.txt", "content": "y"})]


def test_ask_mode_prompts_and_respects_no(fake_ui_factory):
    p = Permissions("ask")
    ui = fake_ui_factory(answers=["n"])
    ok, reason = p.check(write_file.TOOL, {"path": "x.txt", "content": "y"}, ui)
    assert ok is False
    assert "denied" in reason


def test_ask_mode_always_is_remembered_for_the_tool(fake_ui_factory):
    p = Permissions("ask")
    ui = fake_ui_factory(answers=["a"])
    ok, _ = p.check(write_file.TOOL, {"path": "x.txt", "content": "y"}, ui)
    assert ok is True
    assert "write_file" in p.always_allowed

    # Second call for the same tool: no further prompt needed.
    ui2 = fake_ui_factory(answers=[])
    ok2, _ = p.check(write_file.TOOL, {"path": "y.txt", "content": "z"}, ui2)
    assert ok2 is True
    assert ui2.asked == []


def test_ask_mode_does_not_prompt_for_read_only_tools(fake_ui_factory):
    p = Permissions("ask")
    ui = fake_ui_factory(answers=[])
    ok, _ = p.check(read_file.TOOL, {"path": "x.txt"}, ui)
    assert ok is True
    assert ui.asked == []


# ---------------------------------------------------------------------------
# Real bugs in permissions.py
# ---------------------------------------------------------------------------
def test_readonly_overrides_a_previous_always_allow(fake_ui_factory):
    p = Permissions("ask")
    ui = fake_ui_factory(answers=["a"])
    ok, _ = p.check(write_file.TOOL, {"path": "x.txt", "content": "y"}, ui)
    assert ok is True

    p.mode = "readonly"
    ok2, reason2 = p.check(write_file.TOOL, {"path": "x.txt", "content": "y"}, fake_ui_factory())
    assert ok2 is False, "readonly mode should deny writes even if previously always-allowed"


def test_blocklist_does_not_false_positive_on_git_log_format(fake_ui_factory):
    p = Permissions("auto")
    ok, reason = p.check(run_shell.TOOL, {"command": "git log --pretty=format:%H"}, fake_ui_factory())
    assert ok is True, reason


def test_blocklist_does_not_false_positive_on_grep_for_shutdown(fake_ui_factory):
    p = Permissions("auto")
    ok, reason = p.check(run_shell.TOOL, {"command": "grep shutdown app.py"}, fake_ui_factory())
    assert ok is True, reason
