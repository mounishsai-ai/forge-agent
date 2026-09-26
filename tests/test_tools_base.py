import os

from forge.tools.base import resolve, truncate


def test_truncate_short_text_unchanged():
    assert truncate("hello", limit=100) == "hello"


def test_truncate_long_text_keeps_head_and_tail():
    text = "A" * 1000
    out = truncate(text, limit=100)
    assert out.startswith("A" * 50)
    assert out.endswith("A" * 50)
    assert "chars truncated" in out
    assert len(out) < len(text)


def test_resolve_relative_path(project_dir):
    p = resolve("sub/file.txt")
    assert p.endswith("file.txt")
    assert str(project_dir) in p


def test_resolve_expands_user():
    p = resolve("~/x.txt")
    assert "~" not in p
    assert os.path.isabs(p)
