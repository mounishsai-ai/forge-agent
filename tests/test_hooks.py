import sys

from forge.hooks import Hooks


def py_command(code_str: str) -> str:
    return f'"{sys.executable}" -c "{code_str}"'


def test_pre_tool_veto_blocks_call():
    hooks = Hooks({"pre_tool": [{"match": "run_shell", "command": py_command("import sys; print('nope'); sys.exit(1)")}]})
    veto = hooks.pre_tool("run_shell", {"command": "echo hi"})
    assert veto is not None
    assert "nope" in veto


def test_pre_tool_allows_when_exit_zero():
    hooks = Hooks({"pre_tool": [{"match": "run_shell", "command": py_command("import sys; sys.exit(0)")}]})
    veto = hooks.pre_tool("run_shell", {"command": "echo hi"})
    assert veto is None


def test_pre_tool_only_matches_configured_tool():
    hooks = Hooks({"pre_tool": [{"match": "write_file", "command": py_command("import sys; sys.exit(1)")}]})
    veto = hooks.pre_tool("run_shell", {"command": "echo hi"})
    assert veto is None


def test_post_tool_logs_every_call():
    hooks = Hooks({})
    hooks.post_tool("read_file", {"path": "a.txt"}, "contents", True, 0.123)
    hooks.post_tool("write_file", {"path": "b.txt"}, "error", False, 0.5)
    assert len(hooks.log) == 2
    assert hooks.log[0] == {"tool": "read_file", "ok": True, "seconds": 0.12}
    assert hooks.log[1]["ok"] is False


def test_post_tool_runs_matching_hook_command(project_dir):
    marker = project_dir / "marker.txt"
    cmd = py_command(f"open(r'{marker}', 'w').write('ran')")
    hooks = Hooks({"post_tool": [{"match": "write_file", "command": cmd}]})
    hooks.post_tool("write_file", {"path": "x"}, "ok", True, 0.01)
    assert marker.read_text(encoding="utf-8") == "ran"


def test_hooks_load_returns_empty_when_no_file(project_dir):
    hooks = Hooks.load()
    assert hooks.pre == []
    assert hooks.post == []


def test_hooks_load_reads_config_file(project_dir):
    import json
    import os
    os.makedirs(".forge", exist_ok=True)
    with open(os.path.join(".forge", "hooks.json"), "w", encoding="utf-8") as f:
        json.dump({"pre_tool": [{"match": "x", "command": "echo hi"}]}, f)
    hooks = Hooks.load()
    assert hooks.pre == [{"match": "x", "command": "echo hi"}]
