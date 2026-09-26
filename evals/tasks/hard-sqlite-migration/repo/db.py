"""Small app module for reading/writing users in the sqlite3 database.

The schema is managed by migrate.py / migrations/, not by this module.
"""
import sqlite3


def get_connection(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def add_user(conn, name, email):
    conn.execute("INSERT INTO users (name, email) VALUES (?, ?)", (name, email))
    conn.commit()


def get_user(conn, user_id):
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    return dict(row) if row else None


def list_users(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM users ORDER BY id")]
