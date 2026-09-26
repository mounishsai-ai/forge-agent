"""Versioned schema migrations for the users database.

Migration files live in a migrations directory (default: "migrations", but
migrate() must accept any path - it's just a directory of files on disk,
not necessarily an importable Python package, and it may be a temporary
copy elsewhere on disk). Each migration file is named NNNN_description.py
(NNNN is a zero-padded integer, e.g. 0001_create_users.py) and defines:

    VERSION = <int>       # must match the numeric filename prefix
    def upgrade(conn):    # applies the migration using the given
        ...                # sqlite3.Connection. Do not call conn.commit()
                           # or conn.close() yourself - migrate() manages
                           # the transaction and the connection's lifetime.

migrate(conn, migrations_dir="migrations") must:

  - Create a `schema_version` table if it doesn't already exist, with
    (at least) these exact column names: `version` (INTEGER, primary key)
    and `applied_at` (TEXT, e.g. an ISO timestamp).
  - Discover migration files directly from migrations_dir by listing its
    contents (do not rely on Python package/module imports resolving to
    migrations_dir - it will not always be on sys.path or importable as a
    package; load each file with e.g. importlib.util.spec_from_file_location
    + module_from_spec + exec_module), and sort them by their numeric
    filename prefix.
  - Apply only the migrations whose VERSION is not yet present in
    schema_version, strictly in ascending version order.
  - Run each migration's upgrade(conn) inside its own transaction: if
    upgrade() raises, every change it made (including schema/DDL changes)
    must be rolled back, the exception must propagate out of migrate(),
    and schema_version must not record that version. Migrations already
    applied earlier in the same migrate() call (or in a previous call)
    must remain applied - a later migration's failure must not undo them,
    and must not prevent them from being correctly recognized as applied
    if migrate() is called again.
    (Tip: sqlite3 connections don't reliably start an implicit transaction
    before DDL statements like ALTER TABLE/CREATE TABLE. For a real
    transaction boundary around each migration, consider setting
    `conn.isolation_level = None` and issuing explicit
    `BEGIN` / `COMMIT` / `ROLLBACK` statements yourself.)
  - Record (version, applied_at) in schema_version only after upgrade()
    for that version succeeds.
  - Be idempotent: calling migrate() again on an already-migrated database
    applies nothing and does not error.
  - Return the sorted list of version numbers that were newly applied
    during this call (an empty list if nothing needed to run).

Also runnable as a script: `python migrate.py <db_path> [migrations_dir]`.
"""


def migrate(conn, migrations_dir="migrations"):
    raise NotImplementedError


if __name__ == "__main__":
    import sys
    import sqlite3

    db_path = sys.argv[1]
    mig_dir = sys.argv[2] if len(sys.argv) > 2 else "migrations"
    conn = sqlite3.connect(db_path)
    try:
        applied = migrate(conn, mig_dir)
        print(f"Applied migrations: {applied}")
    finally:
        conn.close()
