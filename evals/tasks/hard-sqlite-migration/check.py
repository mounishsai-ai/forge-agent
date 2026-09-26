"""Hidden grader for hard-sqlite-migration."""
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

TIMEOUT_KWARGS = dict(encoding="utf-8", errors="replace")

# (name, expected_first, expected_last)
NAME_CASES = [
    ("Alice Smith", "Alice", "Smith"),
    ("Bob", "Bob", ""),
    ("Mary Jane Watson", "Mary", "Jane Watson"),
    ("  Carol   Jones  ", "Carol", "Jones"),
    ("Étienne Dupont", "Étienne", "Dupont"),
    ("Madonna", "Madonna", ""),
    ("", "", ""),
]


def run_visible_tests(cwd):
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "test_migrate.py", "-q"],
        cwd=cwd, capture_output=True, timeout=30, **TIMEOUT_KWARGS,
    )
    if result.returncode != 0:
        print("Visible test test_migrate.py did not pass:")
        print(result.stdout[-2000:])
        print(result.stderr[-2000:])
        sys.exit(1)


def make_old_schema_db(path):
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE
        )"""
    )
    for i, (name, _, _) in enumerate(NAME_CASES):
        conn.execute(
            "INSERT INTO users (name, email) VALUES (?, ?)", (name, f"user{i}@example.com")
        )
    conn.commit()
    conn.close()


def fail(msg):
    print(msg)
    sys.exit(1)


def main():
    cwd = os.getcwd()
    run_visible_tests(cwd)

    sys.path.insert(0, cwd)
    for mod in ("migrate", "db"):
        sys.modules.pop(mod, None)
    import migrate as migrate_mod

    migrations_dir = os.path.join(cwd, "migrations")
    if not os.path.isdir(migrations_dir):
        fail("migrations/ directory is missing")
    filenames = sorted(f for f in os.listdir(migrations_dir) if f.endswith(".py"))
    if not any("0002" in f or "split" in f for f in filenames):
        fail(f"expected a second migration (splitting name) in migrations/, found: {filenames}")

    workdir = tempfile.mkdtemp(prefix="sqlite-mig-")
    try:
        # 1. Old-schema DB with data -> migrate -> verify split.
        db_path = os.path.join(workdir, "old.db")
        make_old_schema_db(db_path)

        conn = sqlite3.connect(db_path)
        try:
            applied = migrate_mod.migrate(conn, migrations_dir=migrations_dir)
        except Exception as e:  # noqa: BLE001
            fail(f"migrate() raised on an old-schema DB with data: {e!r}")
        if applied != [2] and applied != [1, 2] and set(applied) != {2}:
            # Table already existed (no CREATE needed) so only version 2 should be new;
            # allow [2] as the strict expectation but don't hard-fail on cosmetic variance.
            if 2 not in applied:
                fail(f"expected version 2 to be applied, got {applied}")

        rows = {r[0]: dict(zip(("id", "name", "email", "first_name", "last_name"), r))
                for r in conn.execute(
                    "SELECT id, name, email, first_name, last_name FROM users ORDER BY id"
                )}
        if len(rows) != len(NAME_CASES):
            fail(f"expected {len(NAME_CASES)} rows, found {len(rows)}")
        for i, (name, exp_first, exp_last) in enumerate(NAME_CASES):
            row = rows[i + 1]
            if row["first_name"] != exp_first or row["last_name"] != exp_last:
                fail(f"name={name!r}: expected first={exp_first!r} last={exp_last!r}, "
                     f"got first={row['first_name']!r} last={row['last_name']!r}")

        cur = conn.execute("SELECT version FROM schema_version ORDER BY version")
        versions = [r[0] for r in cur.fetchall()]
        if versions != [1, 2]:
            fail(f"expected schema_version to record [1, 2], got {versions}")
        conn.close()

        # 2. Idempotency: run migrate again, nothing should change.
        conn = sqlite3.connect(db_path)
        try:
            applied_again = migrate_mod.migrate(conn, migrations_dir=migrations_dir)
        except Exception as e:  # noqa: BLE001
            fail(f"migrate() raised on an already-migrated DB (should be a no-op): {e!r}")
        if applied_again != []:
            fail(f"expected no migrations applied on second run, got {applied_again}")
        row = conn.execute(
            "SELECT first_name, last_name FROM users WHERE id = 1"
        ).fetchone()
        if tuple(row) != ("Alice", "Smith"):
            fail(f"data got corrupted on a second, idempotent migrate() call: {tuple(row)}")
        conn.close()

        # 3. Fresh, empty database (no users table at all yet).
        fresh_path = os.path.join(workdir, "fresh.db")
        conn = sqlite3.connect(fresh_path)
        try:
            applied_fresh = migrate_mod.migrate(conn, migrations_dir=migrations_dir)
        except Exception as e:  # noqa: BLE001
            fail(f"migrate() raised on a brand-new empty DB: {e!r}")
        if applied_fresh != [1, 2]:
            fail(f"expected [1, 2] applied on a fresh DB, got {applied_fresh}")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
        for needed in ("name", "email", "first_name", "last_name"):
            if needed not in cols:
                fail(f"fresh DB users table missing column {needed!r}: has {cols}")
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        if count != 0:
            fail(f"fresh DB should have 0 rows, has {count}")
        conn.close()

        # 4. A failing migration must roll back fully and not block re-runs.
        broken_dir = os.path.join(workdir, "migrations_broken")
        shutil.copytree(migrations_dir, broken_dir)
        with open(os.path.join(broken_dir, "0003_fail.py"), "w", encoding="utf-8") as f:
            f.write(
                "VERSION = 3\n\n"
                "def upgrade(conn):\n"
                "    conn.execute('ALTER TABLE users ADD COLUMN bogus TEXT')\n"
                "    conn.execute(\"UPDATE users SET bogus = 'x'\")\n"
                "    raise RuntimeError('boom')\n"
            )
        rollback_db = os.path.join(workdir, "rollback.db")
        conn = sqlite3.connect(rollback_db)
        raised = False
        try:
            migrate_mod.migrate(conn, migrations_dir=broken_dir)
        except Exception:
            raised = True
        if not raised:
            fail("migrate() should have raised when a migration's upgrade() raises")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
        if "bogus" in cols:
            fail("failing migration's ALTER TABLE was not rolled back")
        versions = [r[0] for r in conn.execute("SELECT version FROM schema_version ORDER BY version")]
        if versions != [1, 2]:
            fail(f"after a failed migration 3, schema_version should still be [1, 2], got {versions}")
        conn.close()

        # Re-run with the original (unbroken) migrations dir: should be a clean no-op.
        conn = sqlite3.connect(rollback_db)
        try:
            applied_after_failure = migrate_mod.migrate(conn, migrations_dir=migrations_dir)
        except Exception as e:  # noqa: BLE001
            fail(f"migrate() raised re-running after an earlier failed migration: {e!r}")
        if applied_after_failure != []:
            fail(f"expected [] re-running known-good migrations, got {applied_after_failure}")
        conn.close()

    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    print("OK")


if __name__ == "__main__":
    main()
