import csv
import io
import json
from datetime import datetime, timedelta, timezone

from flask import Blueprint, Response, abort, current_app, jsonify, request, session

from .auth import require_roles
from .data import identifier, ingest, integer, reading_dict, timestamp, utc_now
from .db import get_db

api = Blueprint("api", __name__, url_prefix="/api/v1")


def json_body():
    try:
        return request.get_json()
    except (RecursionError, OverflowError):
        abort(400, description="JSON nesting or numeric range is excessive")


def query_int(name, default, minimum, maximum):
    raw = request.args.get(name, str(default))
    try:
        return integer(int(raw), name, minimum, maximum)
    except ValueError:
        abort(400, description=f"{name} must be an integer")


def reading_filter():
    clauses, params = [], []
    device = request.args.get("device_id")
    if device:
        clauses.append("device_id=?")
        params.append(identifier(device, "device_id"))
    for field, operator in (("since", ">="), ("until", "<=")):
        if request.args.get(field):
            clauses.append(f"received_at{operator}?")
            params.append(timestamp(request.args[field], field))
    return clauses, params


@api.post("/readings")
@require_roles("device", "admin")
def add_readings():
    result = ingest(json_body())
    return jsonify(result), 201 if result["inserted"] else 200


@api.get("/readings")
@require_roles("viewer", "admin")
def readings():
    limit = query_int("limit", 200, 1, 1000)
    cursor = query_int("after_id", 0, 0, 2**63 - 1)
    clauses, params = reading_filter()
    clauses.append("id>?")
    rows = get_db().execute("SELECT * FROM readings WHERE " + " AND ".join(clauses) + " ORDER BY id LIMIT ?",
                            [*params, cursor, limit + 1]).fetchall()
    items = [reading_dict(row, include_raw=True) for row in rows[:limit]]
    return jsonify(items=items, next_after_id=items[-1]["id"] if items else cursor, has_more=len(rows) > limit)


@api.get("/readings.csv")
@require_roles("viewer", "admin")
def export_readings():
    clauses, params = reading_filter()
    limit = query_int("limit", 10000, 1, 10000)
    cursor = query_int("after_id", 0, 0, 2**63 - 1)
    clauses.append("id>?")
    rows = get_db().execute("SELECT * FROM readings WHERE " + " AND ".join(clauses) + " ORDER BY id LIMIT ?",
                            [*params, cursor, limit + 1]).fetchall()
    columns = ["id", "device_id", "boot_id", "seq", "received_at", "observed_at", "uptime_us", "dt_us",
               "pulses", "total_pulses", "frequency_hz", "flow_lpm", "total_l"]
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(columns)
    for row in rows[:limit]:
        writer.writerow([row[column] for column in columns])
    response = Response(output.getvalue(), mimetype="text/csv")
    response.headers["Content-Disposition"] = 'attachment; filename="flowlab-readings.csv"'
    response.headers["X-Has-More"] = str(len(rows) > limit).lower()
    response.headers["X-Next-After-Id"] = str(rows[min(len(rows), limit) - 1]["id"] if rows else cursor)
    return response


@api.get("/devices")
@require_roles("viewer", "admin")
def devices():
    return jsonify(items=[dict(row) for row in get_db().execute("SELECT * FROM devices ORDER BY last_seen DESC")])


@api.get("/dashboard")
@require_roles("viewer", "admin")
def dashboard():
    db = get_db()
    device_rows = [dict(row) for row in db.execute("SELECT * FROM devices ORDER BY last_seen DESC")]
    device = request.args.get("device_id") or (device_rows[0]["device_id"] if device_rows else None)
    if device:
        identifier(device, "device_id")
        if device not in {row["device_id"] for row in device_rows}:
            abort(404, description="Unknown device")
    hours = query_int("hours", 24, 1, 168)
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    series, latest, summary = [], None, {}
    if device:
        rows = db.execute("SELECT * FROM readings WHERE device_id=? AND received_at>=? ORDER BY id DESC LIMIT 240",
                          (device, since)).fetchall()
        series = [reading_dict(row) for row in reversed(rows)]
        last = db.execute("SELECT * FROM readings WHERE device_id=? ORDER BY id DESC LIMIT 1", (device,)).fetchone()
        latest = reading_dict(last) if last else None
        summary = dict(db.execute("""SELECT COUNT(*) AS sample_count, AVG(frequency_hz) AS mean_hz,
            MIN(frequency_hz) AS min_hz, MAX(frequency_hz) AS peak_hz, AVG(flow_lpm) AS mean_lpm,
            COUNT(flow_lpm) AS calibrated_samples FROM readings WHERE device_id=? AND received_at>=?""",
                                  (device, since)).fetchone())
    return jsonify(devices=device_rows, selected_device=device, latest=latest, series=series,
                   summary=summary, window_hours=hours, server_time=utc_now(), poll_seconds=3,
                   release=current_app.config["RELEASE"])


@api.get("/analytics")
@require_roles("viewer", "admin")
def analytics():
    clauses, params = reading_filter()
    minutes = query_int("bucket_minutes", 15, 1, 1440)
    # Bound the default research window; explicit time filters can address older data.
    if not request.args.get("since"):
        clauses.append("received_at>=?")
        params.append((datetime.now(timezone.utc) - timedelta(days=7)).isoformat(timespec="milliseconds").replace("+00:00", "Z"))
    interval = minutes * 60
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    rows = get_db().execute("""SELECT device_id,
        CAST(CAST(strftime('%s',received_at) AS INTEGER)/? AS INTEGER)*? AS bucket_epoch,
        COUNT(*) AS sample_count,AVG(frequency_hz) AS mean_hz,MIN(frequency_hz) AS min_hz,
        MAX(frequency_hz) AS max_hz,AVG(flow_lpm) AS mean_lpm,COUNT(flow_lpm) AS calibrated_samples
        FROM readings""" + where + " GROUP BY device_id,bucket_epoch ORDER BY bucket_epoch,device_id LIMIT 1001",
                            [interval, interval, *params]).fetchall()
    return jsonify(items=[dict(row) for row in rows[:1000]], bucket_minutes=minutes, truncated=len(rows) > 1000,
                   time_basis="server_received_at_utc", method="arithmetic sample means; null calibration excluded")


@api.post("/feedback")
@require_roles("viewer", "admin")
def add_feedback():
    data = json_body()
    if not isinstance(data, dict):
        abort(400, description="Body must be an object")
    message = data.get("message")
    category = data.get("category", "research")
    if not isinstance(message, str) or not 1 <= len(message.strip()) <= 2000:
        abort(400, description="message must contain 1-2000 characters")
    if category not in ("research", "sensor", "usability", "bug"):
        abort(400, description="Unknown feedback category")
    rating = data.get("rating")
    if rating is not None:
        integer(rating, "rating", 1, 5)
    device = data.get("device_id") or None
    reading_id = data.get("reading_id")
    db = get_db()
    if device and not db.execute("SELECT 1 FROM devices WHERE device_id=?", (identifier(device, "device_id"),)).fetchone():
        abort(400, description="Unknown device")
    if reading_id is not None:
        integer(reading_id, "reading_id", 1)
        reading = db.execute("SELECT device_id FROM readings WHERE id=?", (reading_id,)).fetchone()
        if not reading or reading["device_id"] != device:
            abort(400, description="reading_id must belong to the selected device")
    with db:
        row = db.execute("INSERT INTO feedback(device_id,reading_id,category,rating,message,created_at) VALUES (?,?,?,?,?,?)",
                         (device, reading_id, category, rating, message.strip(), utc_now()))
    return jsonify(id=row.lastrowid, status="saved"), 201


@api.get("/feedback")
@require_roles("admin")
def feedback():
    cursor = query_int("after_id", 0, 0, 2**63 - 1)
    limit = query_int("limit", 100, 1, 500)
    rows = get_db().execute("SELECT * FROM feedback WHERE id>? ORDER BY id LIMIT ?", (cursor, limit + 1)).fetchall()
    items = [dict(row) for row in rows[:limit]]
    return jsonify(items=items, has_more=len(rows) > limit, next_after_id=items[-1]["id"] if items else cursor)


@api.get("/system")
@require_roles("admin")
def system():
    db = get_db()
    counts = {name: db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] for name in ("devices", "readings", "feedback")}
    return jsonify(status="ok", database="ok", schema_version=db.execute("PRAGMA user_version").fetchone()[0],
                   counts=counts, release=current_app.config["RELEASE"], server_time=utc_now())


@api.get("/spec")
@require_roles("viewer", "admin")
def specification():
    return current_app.send_static_file("openapi.json")


@api.post("/system/check")
@require_roles("admin")
def self_check():
    db = get_db()
    db.execute("SAVEPOINT system_check")
    try:
        cursor = db.execute("INSERT INTO feedback(category,message,created_at) VALUES (?,?,?)",
                            ("research", "Internal rolled-back health probe", utc_now()))
        assert db.execute("SELECT 1 FROM feedback WHERE id=?", (cursor.lastrowid,)).fetchone()
    finally:
        db.execute("ROLLBACK TO system_check")
        db.execute("RELEASE system_check")
    return jsonify(status="ok", database_read=True, database_write_rollback=True,
                   schema_version=db.execute("PRAGMA user_version").fetchone()[0], release=current_app.config["RELEASE"])
