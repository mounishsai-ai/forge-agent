import pytest

from forge.tools import todo as todo_module
from forge.tools.base import ToolError


def test_todo_render_empty():
    assert todo_module.render() == "(no todos)"


def test_todo_sets_and_renders():
    out = todo_module.todo([
        {"task": "write tests", "status": "in_progress"},
        {"task": "ship it", "status": "pending"},
    ])
    assert "[~] write tests" in out
    assert "[ ] ship it" in out
    assert out == todo_module.render()


def test_todo_done_mark():
    todo_module.todo([{"task": "a", "status": "done"}])
    assert todo_module.render() == "[x] a"


def test_todo_replaces_previous_list():
    todo_module.todo([{"task": "a", "status": "pending"}])
    todo_module.todo([{"task": "b", "status": "pending"}])
    out = todo_module.render()
    assert "a" not in out
    assert "b" in out


def test_todo_missing_task_field_raises():
    with pytest.raises(ToolError):
        todo_module.todo([{"status": "pending"}])


def test_todo_bad_status_raises():
    with pytest.raises(ToolError):
        todo_module.todo([{"task": "a", "status": "later"}])
