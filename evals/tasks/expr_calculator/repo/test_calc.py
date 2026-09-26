import pytest
from calc import evaluate


def test_simple_add():
    assert evaluate("1+2") == 3


def test_precedence():
    assert evaluate("2+3*4") == 14


def test_parens():
    assert evaluate("(2+3)*4") == 20


def test_malformed_raises():
    with pytest.raises(ValueError):
        evaluate("1+")
