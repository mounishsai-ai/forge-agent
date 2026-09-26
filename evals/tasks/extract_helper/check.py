"""Grader for extract_helper.

Checks (all must pass):
  1. Behavior of create_user/update_user/register_user is unchanged across many inputs
     (including edge cases and an input that raises TypeError, not ValueError).
  2. The distinctive validation-message literal no longer appears 3 times in the file
     (duplication was removed).
  3. None of the three functions still contains a `raise` statement directly in its own
     body (the raising now happens inside a shared helper).
  4. There is some function, called by all three of create_user/update_user/register_user,
     that is not one of those three itself (i.e. a real shared helper exists).
"""
import ast
import json
import os
import subprocess
import sys

WORKDIR = os.getcwd()
SRC = os.path.join(WORKDIR, "user_ops.py")
TARGET_FUNCS = {"create_user", "update_user", "register_user"}


def fail(msg):
    print(f"FAIL: {msg}")
    sys.exit(1)


# ---- reference behavior (kept independent of the workdir file) ----------

def reference(fn, name, age, email):
    action = {"create_user": "created", "update_user": "updated", "register_user": "registered"}[fn]
    if not name:
        raise ValueError("name is required")
    if not isinstance(age, int) or age < 0 or age > 150:
        raise ValueError("age must be an integer between 0 and 150")
    if "@" not in email:
        raise ValueError("email must contain '@'")
    return {"name": name, "age": age, "email": email, "action": action}


CASES = [
    ("create_user", "Alice", 30, "alice@example.com"),
    ("update_user", "Bob", 30, "bob@example.com"),
    ("register_user", "Cara", 30, "cara@example.com"),
    ("create_user", "", 30, "a@b.com"),
    ("create_user", None, 30, "a@b.com"),
    ("update_user", "Dan", -1, "d@x.com"),
    ("update_user", "Dan", 151, "d@x.com"),
    ("register_user", "Eve", 150, "e@x.com"),
    ("register_user", "Eve", 0, "e@x.com"),
    ("create_user", "Fay", True, "f@x.com"),
    ("create_user", "Gus", 150.0, "g@x.com"),
    ("update_user", "Hal", 30, "no-at-sign.com"),
    ("register_user", "Ivy", 30, None),
    ("create_user", "", -5, "no-at-sign"),
    ("update_user", "Jan", -5, "no-at-sign"),
]


def outcome(fn, *args):
    try:
        return {"ok": fn(*args)}
    except Exception as e:
        return {"err_type": type(e).__name__, "err_msg": str(e)}


def compare(expected, actual, case):
    if "ok" in expected:
        if actual.get("ok") != expected["ok"]:
            fail(f"case {case}: expected return {expected['ok']!r}, got {actual}")
    else:
        if actual.get("err_type") != expected["err_type"]:
            fail(f"case {case}: expected exception {expected['err_type']}, got {actual}")
        if expected["err_type"] == "ValueError" and actual.get("err_msg") != expected["err_msg"]:
            fail(f"case {case}: expected ValueError message {expected['err_msg']!r}, got {actual.get('err_msg')!r}")


def main():
    if not os.path.isfile(SRC):
        fail("user_ops.py is missing")
    with open(SRC, encoding="utf-8") as f:
        src_text = f.read()

    # --- 1. behavior, run in a child process so a bad edit can't hang the checker ---
    probe = r"""
import sys, json
sys.path.insert(0, r"%s")
import user_ops

cases = %r
out = []
for fn_name, name, age, email in cases:
    fn = getattr(user_ops, fn_name)
    try:
        out.append({"ok": fn(name, age, email)})
    except Exception as e:
        out.append({"err_type": type(e).__name__, "err_msg": str(e)})
print(json.dumps(out))
""" % (WORKDIR.replace("\\", "\\\\"), CASES)

    try:
        result = subprocess.run([sys.executable, "-c", probe], cwd=WORKDIR,
                                 capture_output=True, text=True, timeout=30)
    except subprocess.TimeoutExpired:
        fail("running user_ops.py timed out")

    if result.returncode != 0:
        fail(f"importing/running user_ops.py raised an error:\n{result.stderr[-1500:]}")

    try:
        actual_list = json.loads(result.stdout.strip().splitlines()[-1])
    except Exception:
        fail(f"could not parse behavior output: {result.stdout!r} {result.stderr!r}")

    for case, actual in zip(CASES, actual_list):
        fn_name, name, age, email = case
        expected = outcome(lambda *a: reference(fn_name, *a), name, age, email)
        compare(expected, actual, case)

    # --- 2. duplication removed ---
    marker = "age must be an integer between 0 and 150"
    count = src_text.count(marker)
    if count >= 3:
        fail(f"validation message {marker!r} still appears {count} times (looks unextracted)")

    # --- 3. none of the 3 functions raises directly anymore ---
    tree = ast.parse(src_text, filename="user_ops.py")
    func_nodes = {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in TARGET_FUNCS}
    missing = TARGET_FUNCS - set(func_nodes)
    if missing:
        fail(f"function(s) missing from user_ops.py: {missing}")

    call_names_by_func = {}
    for name, node in func_nodes.items():
        for sub in ast.walk(node):
            if isinstance(sub, ast.Raise):
                fail(f"{name} still contains a direct `raise` — validation wasn't fully extracted")
        calls = set()
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                if isinstance(sub.func, ast.Name):
                    calls.add(sub.func.id)
                elif isinstance(sub.func, ast.Attribute):
                    calls.add(sub.func.attr)
        call_names_by_func[name] = calls

    # --- 4. a shared helper (not one of the 3 target funcs, not a builtin) is called by all three ---
    builtins_ignore = {"isinstance", "len", "str", "int", "float", "bool", "dict", "list", "print"}
    common = set.intersection(*call_names_by_func.values()) if call_names_by_func else set()
    helper_candidates = common - TARGET_FUNCS - builtins_ignore
    if not helper_candidates:
        fail("no shared helper function is called by all three of create_user/update_user/register_user")

    print("PASS")
    sys.exit(0)


if __name__ == "__main__":
    main()
