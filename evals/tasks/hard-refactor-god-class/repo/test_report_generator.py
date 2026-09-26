"""Basic sanity checks. The hidden grader compares output on several
fixtures against golden files captured from the ORIGINAL code, byte for
byte, and checks that the god class actually got split up -- passing this
file is necessary but not sufficient."""
import os

from report_generator import generate_report

HERE = os.path.dirname(os.path.abspath(__file__))


def test_csv_report_basic_shape():
    out = generate_report(os.path.join(HERE, "fixtures", "small.csv"), "csv")
    assert out.startswith("Section,Key,Quantity,Revenue\n")
    assert "Category,Electronics" in out
    assert "Total," in out


def test_html_report_basic_shape():
    out = generate_report(os.path.join(HERE, "fixtures", "small.csv"), "html")
    assert out.startswith("<html>")
    assert "<h2>By Category</h2>" in out


def test_unknown_format_raises():
    try:
        generate_report(os.path.join(HERE, "fixtures", "small.csv"), "xml")
        assert False, "expected ValueError for unknown format"
    except ValueError:
        pass
