import sqlite3
from pathlib import Path

MIGRATION = Path(__file__).resolve().parent.parent / "migrations" / "001_init.sql"


def connect():
    con = sqlite3.connect(":memory:")
    con.executescript(MIGRATION.read_text())
    return con


def add_user(con, account_id, name):
    con.execute("INSERT INTO users(account_id, name) VALUES (?, ?)", (account_id, name))


def get_user(con, account_id):
    return con.execute("SELECT account_id, name FROM users WHERE account_id = ?", (account_id,)).fetchone()
