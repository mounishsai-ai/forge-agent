import pytest

from forge.tools import run_shell


def test_run_shell_exit_code_success(project_dir, exit_command):
    out = run_shell.run_shell(exit_command(0))
    assert "[exit code 0]" in out


def test_run_shell_exit_code_nonzero(project_dir, exit_command):
    out = run_shell.run_shell(exit_command(3))
    assert "[exit code 3]" in out


def test_run_shell_captures_stdout(project_dir):
    import sys
    if run_shell.IS_WINDOWS:
        cmd = f'& "{sys.executable}" -c "print(1+1)"'
    else:
        cmd = f'"{sys.executable}" -c "print(1+1)"'
    out = run_shell.run_shell(cmd)
    assert "2" in out
    assert "[exit code 0]" in out


def test_run_shell_timeout(project_dir, sleep_command):
    out = run_shell.run_shell(sleep_command(5), timeout=1)
    assert "timed out after 1s" in out
