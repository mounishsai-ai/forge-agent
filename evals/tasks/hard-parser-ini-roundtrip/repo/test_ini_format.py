"""Basic sanity checks. The hidden grader covers many more edge cases
(escapes, continuation lines, duplicate-key line numbers, idempotent
round-trip) -- passing this file is necessary but not sufficient."""
import pytest

from ini_format import parse, IniError


def test_basic_roundtrip():
    text = "[server]\nhost = localhost\nport = 8080"
    doc = parse(text)
    assert doc.dumps() == text


def test_get_value():
    text = "[server]\nhost = localhost"
    doc = parse(text)
    assert doc.get("server", "host") == "localhost"


def test_comment_preserved():
    text = "; top comment\n[a]\nkey = 1"
    doc = parse(text)
    assert doc.dumps() == text


def test_duplicate_key_raises():
    text = "[a]\nkey = 1\nkey = 2"
    with pytest.raises(IniError):
        parse(text)


def test_root_section_key():
    text = "greeting = hi\n[a]\nkey = 1"
    doc = parse(text)
    assert doc.get("", "greeting") == "hi"
