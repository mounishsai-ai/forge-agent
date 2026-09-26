---
name: write-tests
description: Conventions for writing pytest tests in this repo — load before adding or editing anything under tests/.
---

# Writing tests for this project

Follow these so a new test file reads like the rest of a well-kept suite. If this repo already
has a `tests/conftest.py`, read it first and reuse whatever fakes/fixtures it defines instead of
writing your own.

- Framework: pytest. One test file per module under test, named `test_<module>.py`, in `tests/`.
- Never call a real network or LLM API in a test. If the code under test calls out to one, fake
  it — a small stand-in object with the same method signature the real call site uses, driven by
  a scripted list of return values, is enough; check `tests/conftest.py` for an existing one
  before writing a new fake from scratch.
- Any shared module-level state (a `set`/`list` used as a global) must be reset between tests via
  an **autouse** fixture that clears it **in place** (`.clear()`), not by rebinding — other
  modules already hold a reference to the same object, so `x = []` in a fixture would leave them
  pointing at stale data.
- Anything that touches the filesystem uses `tmp_path` plus `monkeypatch.chdir(tmp_path)` — never
  write into the real project directory from a test.
- One behavior per test function, named `test_<thing>_<expected_behavior>`.
- Assert on a function's return value or a raised exception, not on anything printed to stdout.
- Run the whole suite with `pytest -q`; one file with `pytest -q tests/test_foo.py`.
