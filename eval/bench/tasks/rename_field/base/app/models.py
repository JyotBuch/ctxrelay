import sqlite3
from pathlib import Path

MIGRATION = Path(__file__).resolve().parent.parent / "migrations" / "001_init.sql"


def connect():
    con = sqlite3.connect(":memory:")
    con.executescript(MIGRATION.read_text())
    return con


def add_user(con, user_id, name):
    con.execute("INSERT INTO users(user_id, name) VALUES (?, ?)", (user_id, name))


def get_user(con, user_id):
    return con.execute("SELECT user_id, name FROM users WHERE user_id = ?", (user_id,)).fetchone()
