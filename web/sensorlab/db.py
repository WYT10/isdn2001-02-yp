import sqlite3
from pathlib import Path
from datetime import datetime, timezone
import uuid
from contextlib import closing

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
    if version not in (0, 1, 2):
        raise RuntimeError("Unsupported database schema; migrate before starting this release")
    if version == 0:
        db.executescript(Path(__file__).with_name("schema.sql").read_text(encoding="utf-8"))
    if version == 1:
        folder = Path(current_app.instance_path) / "backups"
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / ("schema1-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8] + ".sqlite3")
        with closing(sqlite3.connect(target)) as backup:
            db.backup(backup)
    if version in (0, 1):
        db.executescript(Path(__file__).with_name("activities.sql").read_text(encoding="utf-8"))
    from .activity_store import seed_demo
    seed_demo()


def init_app(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
