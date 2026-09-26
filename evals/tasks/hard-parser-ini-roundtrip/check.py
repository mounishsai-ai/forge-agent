import os
import re
import subprocess
import sys


def main():
    cwd = os.getcwd()

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_ini_format.py", "-q"],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print("Visible test test_ini_format.py did not pass:")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        sys.exit(1)

    sys.path.insert(0, cwd)
    sys.modules.pop("ini_format", None)
    from ini_format import parse, IniError

    failures = []

    def check(label, cond):
        if not cond:
            failures.append(label)

    Q = '"'
    B = "\\"

    # ---- Fixture 1: sections, reopened section, comments, quoted value
    # with escapes, multiline continuation. ----
    quoted_value = B + Q + "east" + B + Q  # -> \"east\"
    lines = [
        "; config file",
        "[server]",
        "name = " + Q + "prod " + quoted_value + Q,   # name = "prod \"east\""
        "host = localhost",
        "welcome = hello",
        "  world",
        "  again",
        "[server]",
        "extra = 1",
        "# trailing comment",
    ]
    text = "\n".join(lines)

    try:
        doc = parse(text)
    except Exception as e:
        print(f"parse() raised on well-formed fixture 1: {e!r}")
        sys.exit(1)

    check("f1.dumps exact roundtrip", doc.dumps() == text)
    check("f1.get quoted+escaped value", doc.get("server", "name") == 'prod "east"')
    check("f1.get plain value", doc.get("server", "host") == "localhost")
    check("f1.get continuation joined", doc.get("server", "welcome") == "hello\nworld\nagain")
    check("f1.get key from reopened section", doc.get("server", "extra") == "1")
    check("f1.sections() includes server once", doc.sections() == ["server"])

    # Idempotency: re-parsing dumped output gives the same dump again.
    try:
        doc2 = parse(doc.dumps())
        check("f1.idempotent roundtrip", doc2.dumps() == text)
    except Exception as e:
        failures.append(f"f1.idempotent roundtrip raised: {e!r}")

    # ---- Fixture 2: root-section key + duplicate key in root ----
    text_root_dup = "g = 1\ng = 2"
    try:
        parse(text_root_dup)
        failures.append("f2.duplicate root key: expected IniError")
    except IniError as e:
        check("f2.duplicate root key mentions line 2", "2" in re.findall(r"\d+", str(e)))
    except Exception as e:
        failures.append(f"f2.duplicate root key: wrong exception type {e!r}")

    text_root_ok = "greeting = hi\n[a]\nkey = 1"
    doc3 = parse(text_root_ok)
    check("f2.root get", doc3.get("", "greeting") == "hi")
    check("f2.roundtrip root+section", doc3.dumps() == text_root_ok)

    # ---- Fixture 3: duplicate key across a reopened section, line number
    # refers to the SECOND occurrence. ----
    lines3 = ["[a]", "x = 1", "[b]", "z = 1", "[a]", "x = 2"]
    text3 = "\n".join(lines3)  # duplicate "x" is on line 6
    try:
        parse(text3)
        failures.append("f3.duplicate across reopened section: expected IniError")
    except IniError as e:
        nums = re.findall(r"\d+", str(e))
        check("f3.duplicate error mentions line 6", "6" in nums)
        check("f3.duplicate error mentions key name", "x" in str(e))
    except Exception as e:
        failures.append(f"f3.duplicate across reopened section: wrong exception type {e!r}")

    # ---- Fixture 4: malformed line (no spaces around '=') ----
    text4 = "[a]\nbad=1"
    try:
        parse(text4)
        failures.append("f4.malformed line: expected IniError")
    except IniError as e:
        check("f4.malformed line mentions line 2", "2" in re.findall(r"\d+", str(e)))
    except Exception as e:
        failures.append(f"f4.malformed line: wrong exception type {e!r}")

    # ---- Fixture 5: unterminated quoted value ----
    text5 = "[a]\nx = " + Q + "abc"
    try:
        parse(text5)
        failures.append("f5.unterminated quote: expected IniError")
    except IniError as e:
        check("f5.unterminated quote mentions line 2", "2" in re.findall(r"\d+", str(e)))
    except Exception as e:
        failures.append(f"f5.unterminated quote: wrong exception type {e!r}")

    # ---- Fixture 6: invalid escape sequence inside a quoted value ----
    text6 = "[a]\nx = " + Q + "a" + B + "q" + Q
    try:
        parse(text6)
        failures.append("f6.invalid escape: expected IniError")
    except IniError as e:
        check("f6.invalid escape mentions line 2", "2" in re.findall(r"\d+", str(e)))
    except Exception as e:
        failures.append(f"f6.invalid escape: wrong exception type {e!r}")

    if failures:
        print("FAILED checks:")
        for f in failures:
            print(" -", f)
        sys.exit(1)

    print("OK")


if __name__ == "__main__":
    main()
