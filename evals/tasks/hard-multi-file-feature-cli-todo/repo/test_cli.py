import json
import os
import subprocess
import sys


def run(args, cwd):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def test_add_list_done_remove(tmp_path):
    cwd = str(tmp_path)
    for f in ("models.py", "storage.py", "formatting.py", "cli.py", "main.py"):
        src = os.path.join(os.path.dirname(__file__), f)
        dst = os.path.join(cwd, f)
        with open(src, "r", encoding="utf-8") as s, open(dst, "w", encoding="utf-8") as d:
            d.write(s.read())

    data_file = os.path.join(cwd, "tasks.json")
    r = run(["--file", data_file, "add", "Buy milk"], cwd)
    assert r.returncode == 0, r.stderr
    assert "#1" in r.stdout

    r = run(["--file", data_file, "add", "Walk dog"], cwd)
    assert r.returncode == 0, r.stderr
    assert "#2" in r.stdout

    r = run(["--file", data_file, "list"], cwd)
    assert "Buy milk" in r.stdout
    assert "Walk dog" in r.stdout

    r = run(["--file", data_file, "done", "1"], cwd)
    assert r.returncode == 0, r.stderr

    with open(data_file, encoding="utf-8") as f:
        data = json.load(f)
    assert any(t["id"] == 1 and t["done"] for t in data)
