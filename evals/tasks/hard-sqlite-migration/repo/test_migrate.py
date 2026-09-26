import os
import sqlite3

import pytest

from migrate import migrate


def test_fresh_database_gets_users_table(tmp_path):
    db_path = os.path.join(tmp_path, "fresh.db")
    conn = sqlite3.connect(db_path)
    try:
        applied = migrate(conn, migrations_dir="migrations")
        assert 1 in applied
        cols = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
        assert "name" in cols
        assert "email" in cols
    finally:
        conn.close()


def test_idempotent(tmp_path):
    db_path = os.path.join(tmp_path, "fresh2.db")
    conn = sqlite3.connect(db_path)
    try:
        first = migrate(conn, migrations_dir="migrations")
        assert first  # something was applied
        second = migrate(conn, migrations_dir="migrations")
        assert second == []
    finally:
        conn.close()
