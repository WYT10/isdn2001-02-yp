import json
import os
import secrets
import sqlite3
from contextlib import closing
from datetime import timedelta
from pathlib import Path

import click
from flask import Flask, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException

from . import db
from .auth import check_csrf, csrf_token, token_role


def create_app(test_config=None):
    instance = os.environ.get("FLOW_INSTANCE", str(Path(__file__).resolve().parent.parent / "instance"))
    app = Flask(__name__, instance_path=str(Path(instance).resolve()), instance_relative_config=True)
    app.config.from_mapping(
        DATABASE=str(Path(app.instance_path) / "flowlab.sqlite3"),
        SECRET_KEY=None, ADMIN_TOKEN=None, VIEWER_TOKEN=None, DEVICE_TOKEN=None,
        PUBLIC_DASHBOARD=True,
        MAX_CONTENT_LENGTH=256 * 1024, SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax", SESSION_COOKIE_SECURE=True,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
    )
    app.config.from_pyfile("config.py", silent=True)
    app.config.from_prefixed_env(prefix="FLOW")
    if test_config:
        app.config.update(test_config)
    keys = [app.config.get(name) for name in ("SECRET_KEY", "ADMIN_TOKEN", "VIEWER_TOKEN", "DEVICE_TOKEN")]
    if any(not isinstance(key, str) or len(key) < 24 or not key.isascii() for key in keys):
        raise RuntimeError("Run python bootstrap.py to create private application keys, or set FLOW_* keys")
    if len(set(keys)) != len(keys):
        raise RuntimeError("Application keys must be distinct")
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    release_path = Path(__file__).parent.parent / "release.json"
    app.config["RELEASE"] = json.loads(release_path.read_text(encoding="utf-8"))["release"] if release_path.exists() else "development"
    db.init_app(app)
    app.jinja_env.globals["csrf_token"] = csrf_token

    @app.get("/")
    def index():
        if app.config["PUBLIC_DASHBOARD"] is True or session.get("role") in ("admin", "viewer") or session.get("activity_account_id"):
            return render_template("living.html", role=session.get("role"))
        return render_template("login.html")

    @app.get("/login")
    def login_page():
        return render_template("login.html")

    @app.get("/sensors")
    def sensors():
        return render_template("dashboard.html", role=session["role"]) if session.get("role") in ("admin", "viewer") else redirect(url_for("login_page"))

    @app.post("/login")
    def login():
        check_csrf(request.form.get("csrf_token"))
        role = token_role(request.form.get("token"))
        if role not in ("admin", "viewer"):
            return render_template("login.html", error="The access key was not accepted."), 401
        session.clear()
        session["role"] = role
        session["csrf"] = secrets.token_urlsafe(32)
        session.permanent = True
        return redirect(url_for("index"))

    @app.post("/logout")
    def logout():
        check_csrf(request.form.get("csrf_token"))
        session.clear()
        return redirect(url_for("index"))

    @app.get("/healthz")
    def health():
        return jsonify(status="ok", service="sensorlab", version="0.2.0", release=app.config["RELEASE"])

    @app.get("/readyz")
    def ready():
        try:
            version = db.get_db().execute("PRAGMA user_version").fetchone()[0]
            db.get_db().execute("SELECT 1 FROM readings LIMIT 1").fetchone()
            db.get_db().execute("SELECT 1 FROM activity_events LIMIT 1").fetchone()
            if version != 2:
                return jsonify(status="unavailable"), 503
        except sqlite3.Error:
            return jsonify(status="unavailable"), 503
        return jsonify(status="ok", database="ok", schema_version=version)

    @app.after_request
    def response_headers(response):
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        map_page = request.path == "/living" or (request.path == "/" and (app.config["PUBLIC_DASHBOARD"] is True or session.get("role") in ("admin", "viewer") or session.get("activity_account_id")))
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin" if map_page else "same-origin"
        images = "https://tile.openstreetmap.org" if map_page else ""
        response.headers["Content-Security-Policy"] = f"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data: {images}; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
        if not request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.errorhandler(HTTPException)
    def http_error(error):
        if request.path.startswith("/api/") or request.path in ("/healthz", "/readyz"):
            return jsonify(error=error.name, message=error.description), error.code
        return render_template("error.html", error=error), error.code

    @app.errorhandler(sqlite3.OperationalError)
    def database_error(error):
        app.logger.error("Database operation unavailable: %s", type(error).__name__)
        return jsonify(error="Database temporarily unavailable"), 503

    from .api import api
    app.register_blueprint(api)
    from .living import living
    from . import activities
    app.register_blueprint(living)
    from .activity_api import activity_api
    app.register_blueprint(activity_api)

    @app.cli.command("backup-db")
    @click.argument("destination", type=click.Path())
    def backup_database(destination):
        target = Path(destination).resolve()
        if target.exists() or target == Path(app.config["DATABASE"]).resolve():
            raise click.ClickException("Choose a new backup filename")
        with closing(sqlite3.connect(target)) as output:
            db.get_db().backup(output)
        click.echo(f"Consistent SQLite backup saved to {target}")

    return app
