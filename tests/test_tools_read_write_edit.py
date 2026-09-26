import os

import pytest

from forge.tools import edit_file, read_file, write_file
from forge.tools.base import ToolError, files_read, resolve


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------
def test_read_file_basic_line_numbers(project_dir):
    (project_dir / "a.txt").write_text("one\ntwo\nthree\n", encoding="utf-8")
    out = read_file.read_file("a.txt")
    assert "     1\tone" in out
    assert "     2\ttwo" in out
    assert "     3\tthree" in out


def test_read_file_marks_file_as_read(project_dir):
    (project_dir / "a.txt").write_text("hi\n", encoding="utf-8")
    assert resolve("a.txt") not in files_read
    read_file.read_file("a.txt")
    assert resolve("a.txt") in files_read


def test_read_file_offset_and_limit(project_dir):
    lines = "\n".join(f"line{i}" for i in range(1, 11)) + "\n"
    (project_dir / "b.txt").write_text(lines, encoding="utf-8")
    out = read_file.read_file("b.txt", offset=3, limit=2)
    assert "     3\tline3" in out
    assert "     4\tline4" in out
    assert "line5" not in out
    assert "[showing lines 3-4 of 10]" in out


def test_read_file_missing_raises_tool_error(project_dir):
    with pytest.raises(ToolError):
        read_file.read_file("does_not_exist.txt")


def test_read_file_empty_file(project_dir):
    (project_dir / "empty.txt").write_text("", encoding="utf-8")
    assert read_file.read_file("empty.txt") == "(empty file)"


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------
def test_write_file_creates_new_file(project_dir):
    out = write_file.write_file("new.txt", "hello\nworld\n")
    assert "Wrote 2 lines" in out
    assert (project_dir / "new.txt").read_text(encoding="utf-8") == "hello\nworld\n"


def test_write_file_creates_parent_dirs(project_dir):
    write_file.write_file("sub/dir/new.txt", "content")
    assert (project_dir / "sub" / "dir" / "new.txt").is_file()


def test_write_file_refuses_overwrite_of_unread_file(project_dir):
    (project_dir / "existing.txt").write_text("original", encoding="utf-8")
    with pytest.raises(ToolError, match="already exists"):
        write_file.write_file("existing.txt", "clobbered")
    assert (project_dir / "existing.txt").read_text(encoding="utf-8") == "original"


def test_write_file_allows_overwrite_after_read(project_dir):
    (project_dir / "existing.txt").write_text("original", encoding="utf-8")
    read_file.read_file("existing.txt")
    write_file.write_file("existing.txt", "updated")
    assert (project_dir / "existing.txt").read_text(encoding="utf-8") == "updated"


def test_write_file_allows_overwrite_of_file_it_just_wrote(project_dir):
    write_file.write_file("x.txt", "v1")
    write_file.write_file("x.txt", "v2")
    assert (project_dir / "x.txt").read_text(encoding="utf-8") == "v2"


# ---------------------------------------------------------------------------
# edit_file
# ---------------------------------------------------------------------------
def test_edit_file_requires_prior_read(project_dir):
    (project_dir / "a.txt").write_text("hello world\n", encoding="utf-8")
    with pytest.raises(ToolError, match="Read"):
        edit_file.edit_file("a.txt", "hello", "hi")


def test_edit_file_not_found_path(project_dir):
    with pytest.raises(ToolError, match="File not found"):
        edit_file.edit_file("nope.txt", "a", "b")


def test_edit_file_old_string_not_found(project_dir):
    (project_dir / "a.txt").write_text("hello world\n", encoding="utf-8")
    read_file.read_file("a.txt")
    with pytest.raises(ToolError, match="not found"):
        edit_file.edit_file("a.txt", "goodbye", "hi")


def test_edit_file_non_unique_without_replace_all(project_dir):
    (project_dir / "a.txt").write_text("foo\nfoo\n", encoding="utf-8")
    read_file.read_file("a.txt")
    with pytest.raises(ToolError, match="appears 2 times"):
        edit_file.edit_file("a.txt", "foo", "bar")


def test_edit_file_replace_all(project_dir):
    (project_dir / "a.txt").write_text("foo\nfoo\nbaz\n", encoding="utf-8")
    read_file.read_file("a.txt")
    out = edit_file.edit_file("a.txt", "foo", "bar", replace_all=True)
    assert "2 replacement" in out
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "bar\nbar\nbaz\n"


def test_edit_file_single_replacement(project_dir):
    (project_dir / "a.txt").write_text("hello world\n", encoding="utf-8")
    read_file.read_file("a.txt")
    out = edit_file.edit_file("a.txt", "hello", "goodbye")
    assert "1 replacement" in out
    assert (project_dir / "a.txt").read_text(encoding="utf-8") == "goodbye world\n"


# ---------------------------------------------------------------------------
# Real bug: edit_file never matches an old_string copied from read_file's output
# on a CRLF file, because read_file normalizes line endings (text mode) while
# edit_file compares against the raw bytes (opened with newline="").
# See forge/tools/read_file.py:10 vs forge/tools/edit_file.py:12.
# ---------------------------------------------------------------------------
def test_edit_file_matches_crlf_file_using_lf_old_string(project_dir):
    path = project_dir / "crlf.txt"
    path.write_bytes(b"a\r\nb\r\nc\r\n")
    shown = read_file.read_file("crlf.txt")
    assert "\ta\n" in shown and "\tb\n" in shown  # this is what the model actually sees
    # The model, editing based on what it was shown, uses LF between the lines it saw.
    edit_file.edit_file("crlf.txt", "a\nb", "X")
