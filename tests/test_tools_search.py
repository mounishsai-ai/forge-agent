import os
import time

import pytest

from forge.tools import glob as glob_tool
from forge.tools import grep as grep_tool
from forge.tools import list_dir as list_dir_tool
from forge.tools.base import ToolError


# ---------------------------------------------------------------------------
# list_dir
# ---------------------------------------------------------------------------
def test_list_dir_basic(project_dir):
    (project_dir / "a.txt").write_text("hi", encoding="utf-8")
    (project_dir / "sub").mkdir()
    out = list_dir_tool.list_dir(".")
    assert "a.txt" in out
    assert "sub/" in out


def test_list_dir_ignores_dot_dirs(project_dir):
    (project_dir / ".git").mkdir()
    (project_dir / "node_modules").mkdir()
    out = list_dir_tool.list_dir(".")
    assert ".git" not in out
    assert "node_modules" not in out


def test_list_dir_empty(project_dir):
    assert list_dir_tool.list_dir(".") == "(empty directory)"


def test_list_dir_not_a_directory(project_dir):
    (project_dir / "f.txt").write_text("x", encoding="utf-8")
    with pytest.raises(ToolError, match="Not a directory"):
        list_dir_tool.list_dir("f.txt")


# ---------------------------------------------------------------------------
# glob
# ---------------------------------------------------------------------------
def test_glob_finds_matching_files(project_dir):
    (project_dir / "src").mkdir()
    (project_dir / "src" / "app.py").write_text("x", encoding="utf-8")
    (project_dir / "src" / "app.js").write_text("x", encoding="utf-8")
    out = glob_tool.glob("**/*.py")
    assert "src/app.py" in out
    assert "app.js" not in out


def test_glob_no_matches(project_dir):
    assert glob_tool.glob("**/*.nonexistent") == "No files matched."


def test_glob_ignores_node_modules_and_pycache(project_dir):
    (project_dir / "node_modules").mkdir()
    (project_dir / "node_modules" / "pkg.py").write_text("x", encoding="utf-8")
    (project_dir / "__pycache__").mkdir()
    (project_dir / "__pycache__" / "cached.py").write_text("x", encoding="utf-8")
    (project_dir / "real.py").write_text("x", encoding="utf-8")
    out = glob_tool.glob("**/*.py")
    assert "real.py" in out
    assert "pkg.py" not in out
    assert "cached.py" not in out


def test_glob_newest_first(project_dir):
    old = project_dir / "old.py"
    new = project_dir / "new.py"
    old.write_text("x", encoding="utf-8")
    new.write_text("x", encoding="utf-8")
    now = time.time()
    os.utime(old, (now - 100, now - 100))
    os.utime(new, (now, now))
    out = glob_tool.glob("*.py").splitlines()
    assert out.index("new.py") < out.index("old.py")


# ---------------------------------------------------------------------------
# grep
# ---------------------------------------------------------------------------
def test_grep_finds_matches_with_line_numbers(project_dir):
    (project_dir / "a.py").write_text("def foo():\n    return 1\n", encoding="utf-8")
    out = grep_tool.grep("def foo")
    assert "a.py:1:" in out


def test_grep_file_glob_filters(project_dir):
    (project_dir / "a.py").write_text("needle\n", encoding="utf-8")
    (project_dir / "b.js").write_text("needle\n", encoding="utf-8")
    out = grep_tool.grep("needle", file_glob="*.py")
    assert "a.py" in out
    assert "b.js" not in out


def test_grep_no_matches(project_dir):
    (project_dir / "a.py").write_text("hello\n", encoding="utf-8")
    assert grep_tool.grep("needle") == "No matches."


def test_grep_bad_regex_raises_tool_error(project_dir):
    with pytest.raises(ToolError, match="Bad regex"):
        grep_tool.grep("(unclosed[")


def test_grep_ignores_dot_git_and_node_modules(project_dir):
    (project_dir / ".git").mkdir()
    (project_dir / ".git" / "config").write_text("needle\n", encoding="utf-8")
    (project_dir / "node_modules").mkdir()
    (project_dir / "node_modules" / "lib.js").write_text("needle\n", encoding="utf-8")
    (project_dir / "real.py").write_text("needle\n", encoding="utf-8")
    out = grep_tool.grep("needle")
    assert "real.py" in out
    assert "config" not in out
    assert "lib.js" not in out


def test_grep_ignore_case(project_dir):
    (project_dir / "a.py").write_text("NEEDLE\n", encoding="utf-8")
    assert grep_tool.grep("needle") == "No matches."
    out = grep_tool.grep("needle", ignore_case=True)
    assert "NEEDLE" in out
