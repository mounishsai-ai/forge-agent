import os
import subprocess
import sys


def main():
    cwd = os.getcwd()

    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_slugify.py", "-q"],
        cwd=cwd, capture_output=True, text=True, timeout=30,
    )
    if result.returncode != 0:
        print("Visible test test_slugify.py did not pass:")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        sys.exit(1)

    sys.path.insert(0, cwd)
    sys.modules.pop("slugify", None)
    from slugify import slugify

    cases = [
        (("Hello, World!",), {}, "hello-world"),
        (("  Multiple   spaces  ",), {}, "multiple-spaces"),
        (("café naïve",), {}, "cafe-naive"),
        (("a---b__c",), {}, "a-b-c"),
        (("Trailing---",), {"max_length": 9}, "trailing"),
        (("",), {}, ""),
        (("!!!",), {}, ""),
        (("___",), {}, ""),
        (("Already-Slugged",), {}, "already-slugged"),
        (("123 Go!",), {}, "123-go"),
        (("hello world foo",), {"max_length": 6}, "hello"),
        (("hello world foo",), {"max_length": 8}, "hello-wo"),
        (("ÀÉÎÕÜ",), {}, "aeiou"),
        (("no-cut-needed",), {"max_length": 100}, "no-cut-needed"),
        (("  -- leading and trailing -- ",), {}, "leading-and-trailing"),
    ]

    for args, kwargs, expected in cases:
        got = slugify(*args, **kwargs)
        assert got == expected, f"slugify{args!r}, kwargs={kwargs!r} -> {got!r}, expected {expected!r}"

    # max_length should never be exceeded.
    long_result = slugify("this is a fairly long piece of text to slugify", max_length=10)
    assert len(long_result) <= 10, f"result exceeds max_length: {long_result!r}"
    assert not long_result.endswith("-"), f"result has dangling trailing hyphen: {long_result!r}"

    print("OK")


if __name__ == "__main__":
    main()
