"""Hidden grader for hard-multi-file-feature-cli-todo."""
import datetime
import json
import os
import subprocess
import sys

TIMEOUT_KWARGS = dict(encoding="utf-8", errors="replace")


def run_visible_tests(cwd):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_cli.py", "-q"],
        cwd=cwd, capture_output=True, timeout=60, **TIMEOUT_KWARGS,
    )
    if result.returncode != 0:
        print("Visible test test_cli.py did not pass:")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        sys.exit(1)


def run_cli(args, cwd):
    return subprocess.run(
        [sys.executable, "main.py"] + args,
        cwd=cwd, capture_output=True, timeout=30, **TIMEOUT_KWARGS,
    )


def fail(msg):
    print(msg)
    sys.exit(1)


def main():
    cwd = os.getcwd()
    run_visible_tests(cwd)

    sys.path.insert(0, cwd)
    for m in ("models", "storage", "formatting", "cli", "main"):
        sys.modules.pop(m, None)
    from models import Task
    import formatting

    today = datetime.date.today()
    d = lambda n: (today + datetime.timedelta(days=n)).isoformat()  # noqa: E731

    # --- unit-level checks on filter_and_sort_tasks ---
    tasks = [
        Task(id=1, title="Alpha", due_date=d(-5)),   # overdue, not done
        Task(id=2, title="Bravo", due_date=d(5)),    # future
        Task(id=3, title="Charlie", due_date=None),  # no due date
        Task(id=4, title="Delta", due_date=d(-2), done=True),  # overdue but done
        Task(id=5, title="Echo", due_date=d(-1)),    # overdue, not done
    ]

    overdue = formatting.filter_and_sort_tasks(tasks, overdue_only=True, today=today.isoformat())
    overdue_ids = sorted(t.id for t in overdue)
    if overdue_ids != [1, 5]:
        fail(f"expected overdue ids [1, 5], got {overdue_ids}")

    sorted_tasks = formatting.filter_and_sort_tasks(tasks, sort_by_due=True)
    sorted_ids = [t.id for t in sorted_tasks]
    if sorted_ids != [1, 4, 5, 2, 3]:
        fail(f"expected sort-by-due order [1, 4, 5, 2, 3] (undated last), got {sorted_ids}")

    unchanged = formatting.filter_and_sort_tasks(tasks)
    if [t.id for t in unchanged] != [1, 2, 3, 4, 5]:
        fail("filter_and_sort_tasks with no flags should preserve input order")

    # from_dict backward compatibility (missing due_date key entirely)
    old_task = Task.from_dict({"id": 9, "title": "Old", "done": False, "created_at": "x"})
    if getattr(old_task, "due_date", "MISSING") is not None:
        fail(f"Task.from_dict on a record without due_date must default it to None, "
             f"got {old_task.due_date!r}")

    # --- end-to-end CLI: old-format file (no due_date keys at all) still works ---
    old_file = os.path.join(cwd, "old_tasks.json")
    with open(old_file, "w", encoding="utf-8") as f:
        json.dump([
            {"id": 1, "title": "Legacy One", "done": False, "created_at": "2020-01-01"},
            {"id": 2, "title": "Legacy Two", "done": True, "created_at": "2020-01-02"},
        ], f)

    r = run_cli(["--file", old_file, "list"], cwd)
    if r.returncode != 0:
        fail(f"CLI crashed loading an old-format file (no due_date keys):\n{r.stdout}\n{r.stderr}")
    if "Legacy One" not in r.stdout or "Legacy Two" not in r.stdout:
        fail(f"old-format tasks missing from `list` output:\n{r.stdout}")

    r = run_cli(["--file", old_file, "add", "New Legacy Task"], cwd)
    if r.returncode != 0:
        fail(f"`add` on an old-format file failed:\n{r.stdout}\n{r.stderr}")

    # --- end-to-end CLI: new-format file with due dates ---
    new_file = os.path.join(cwd, "new_tasks.json")
    with open(new_file, "w", encoding="utf-8") as f:
        json.dump([
            {"id": 1, "title": "Foxtrot", "done": False, "created_at": "x", "due_date": d(-3)},
            {"id": 2, "title": "Golf", "done": False, "created_at": "x", "due_date": d(3)},
            {"id": 3, "title": "Hotel", "done": False, "created_at": "x", "due_date": None},
            {"id": 4, "title": "India", "done": False, "created_at": "x", "due_date": d(-1)},
        ], f)

    r = run_cli(["--file", new_file, "list", "--overdue"], cwd)
    if r.returncode != 0:
        fail(f"`list --overdue` failed:\n{r.stdout}\n{r.stderr}")
    out = r.stdout
    if "Foxtrot" not in out or "India" not in out:
        fail(f"`list --overdue` missing expected overdue tasks:\n{out}")
    if "Golf" in out or "Hotel" in out:
        fail(f"`list --overdue` included a non-overdue task:\n{out}")

    r = run_cli(["--file", new_file, "list", "--sort-by", "due"], cwd)
    if r.returncode != 0:
        fail(f"`list --sort-by due` failed:\n{r.stdout}\n{r.stderr}")
    out = r.stdout
    positions = {name: out.find(name) for name in ("Foxtrot", "India", "Golf", "Hotel")}
    if any(p == -1 for p in positions.values()):
        fail(f"`list --sort-by due` is missing a task in its output:\n{out}")
    ordered = sorted(positions, key=lambda k: positions[k])
    if ordered != ["Foxtrot", "India", "Golf", "Hotel"]:
        fail(f"`list --sort-by due` order wrong: got {ordered}, "
             f"expected ['Foxtrot', 'India', 'Golf', 'Hotel']")

    r = run_cli(["--file", new_file, "list"], cwd)
    out = r.stdout
    plain_positions = [out.find(name) for name in ("Foxtrot", "Golf", "Hotel", "India")]
    if plain_positions != sorted(plain_positions):
        fail(f"plain `list` (no flags) should preserve insertion order:\n{out}")

    print("OK")


if __name__ == "__main__":
    main()
