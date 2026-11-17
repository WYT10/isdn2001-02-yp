import sqlite3
from pathlib import Path

from flask import current_app, g


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"], timeout=5)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
        g.db.execute("PRAGMA busy_timeout=5000")
    return g.db


def close_db(_error=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = get_db()
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version not in (0, 1):
        raise RuntimeError("Unsupported database schema; migrate before starting this release")
    if version == 0:
        db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
