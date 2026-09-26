"""Basic sanity checks. The hidden grader covers conflicts, cycles, and
cases that require backtracking -- passing this file is necessary but not
sufficient."""
import pytest

from dependency_resolver import resolve, parse_version, satisfies, ConflictError


def test_parse_version():
    assert parse_version("1.2.3") == (1, 2, 3)


def test_satisfies_exact():
    assert satisfies((1, 2, 3), "1.2.3") is True
    assert satisfies((1, 2, 4), "1.2.3") is False


def test_satisfies_caret():
    assert satisfies((1, 5, 0), "^1.2.0") is True
    assert satisfies((2, 0, 0), "^1.2.0") is False


def test_resolve_picks_highest_no_conflict():
    index = {"a": {"1.0.0": {"dependencies": {}}, "1.2.0": {"dependencies": {}}}}
    result = resolve({"a": ">=1.0.0"}, index)
    assert result["a"] == "1.2.0"


def test_resolve_conflict_raises():
    index = {
        "a": {"1.0.0": {"dependencies": {"shared": ">=2.0.0"}}},
        "b": {"1.0.0": {"dependencies": {"shared": "<2.0.0"}}},
        "shared": {"1.0.0": {"dependencies": {}}, "2.0.0": {"dependencies": {}}},
    }
    with pytest.raises(ConflictError):
        resolve({"a": ">=1.0.0", "b": ">=1.0.0"}, index)
