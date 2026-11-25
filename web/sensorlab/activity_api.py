"""Persistent activity API shared by the dashboard and future native clients."""
from functools import wraps
import csv
import hashlib
import io
import json
import uuid

from flask import Blueprint, Response, abort, jsonify, render_template, request, session

from . import activity_store as store
from .auth import allow_public_dashboard, check_csrf, require_roles
from .data import utc_now
from .db import get_db

activity_api = Blueprint("activity_api", __name__)


def token_account(token):
    if not isinstance(token, str) or not token.isascii() or not 24 <= len(token) <= 200:
        return None
    row = get_db().execute("SELECT account_id FROM activity_tokens WHERE digest=?", (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    return store.account(row["account_id"]) if row else None


def owned(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        header = request.headers.get("Authorization")
        if header is not None:
            owner = token_account(header[7:]) if header.startswith("Bearer ") else None
        else:
            owner_id = session.get("activity_account_id")
            owner = store.account(owner_id) if owner_id else None
            if owner and request.method not in ("GET", "HEAD", "OPTIONS"):
                check_csrf(request.headers.get("X-CSRF-Token"))
        if not owner:
            abort(401, description="An account-specific activity key is required")
        return function(owner, *args, **kwargs)
    return wrapped


def body():
    try:
        value = request.get_json()
    except (RecursionError, OverflowError):
        abort(400, description="JSON nesting or numeric range is excessive")
    if not isinstance(value, dict):
        abort(400, description="JSON object required")
    return value


def export(account_id):
    rows = store.records(account_id)
    if request.args.get("format", "json") == "csv":
        stream = io.StringIO(newline="")
        columns = ("id", "local_date", "occurred_at", "kind", "category", "subcategory", "name", "quantity", "unit", "share", "amount_minor", "currency", "status", "co2e_kg", "classification", "revision")
        writer = csv.writer(stream)
        writer.writerow(columns)
        for row in rows:
            values = [row.get(key) for key in columns]
            writer.writerow(["'" + v if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r")) else v for v in values])
        return Response(stream.getvalue(), mimetype="text/csv", headers={"Content-Disposition": 'attachment; filename="livegreen-activities.csv"'})
    return jsonify(schema_version=1, account=store.account(account_id), factors=list(store.factors().values()), events=rows)


@activity_api.get("/workspace")
@allow_public_dashboard
def workspace():
    return render_template("workspace.html", can_copy=session.get("role") == "admin")


@activity_api.get("/api/v1/demo/overview")
@allow_public_dashboard
def demo_overview():
    return jsonify(store.overview(store.DEMO, request.args.get("start"), request.args.get("end")))


@activity_api.get("/api/v1/demo/events")
@allow_public_dashboard
def demo_events():
    return jsonify(items=store.records(store.DEMO, request.args.get("start"), request.args.get("end")))


@activity_api.get("/api/v1/demo/export")
@allow_public_dashboard
def demo_export():
    return export(store.DEMO)


@activity_api.post("/api/v1/activity-accounts")
@require_roles("admin")
def create_account():
    data = body()
    if set(data) - {"name", "copy_demo"} or type(data.get("copy_demo", False)) is not bool:
        abort(400, description="Use name and optional copy_demo boolean")
    owner, token = store.create_account(data.get("name"), data.get("copy_demo", False))
    return jsonify(account=owner, token=token, scopes=["activities:read", "activities:write", "imports:write"],
                   notice="Save this key privately. It cannot access sensor readings or system administration."), 201


@activity_api.post("/api/v1/activity-session")
def sign_in():
    check_csrf(request.headers.get("X-CSRF-Token"))
    owner = token_account(body().get("token"))
    if not owner:
        abort(401, description="Activity key was not accepted")
    session["activity_account_id"] = owner["id"]
    session.permanent = True
    return jsonify(account=owner)


@activity_api.get("/api/v1/activity-session")
def session_account():
    account_id = session.get("activity_account_id")
    return jsonify(account=store.account(account_id) if account_id else None)


@activity_api.delete("/api/v1/activity-session")
def sign_out():
    check_csrf(request.headers.get("X-CSRF-Token"))
    session.pop("activity_account_id", None)
    return jsonify(status="signed_out")


@activity_api.get("/api/v1/activity-account")
@owned
def current_account(owner):
    return jsonify(account=owner)


@activity_api.get("/api/v1/activity-factors")
def factor_list():
    def response():
        return jsonify(items=list(store.factors().values()), formula_version=store.FORMULA)
    header = request.headers.get("Authorization", "")
    if header.startswith("Bearer ") and token_account(header[7:]):
        return response()
    if not header and session.get("activity_account_id"):
        return response()
    return allow_public_dashboard(response)()


@activity_api.get("/api/v1/activity-overview")
@owned
def overview(owner):
    return jsonify(store.overview(owner["id"], request.args.get("start"), request.args.get("end")))


@activity_api.get("/api/v1/activity-events")
@owned
def events(owner):
    rows = store.records(owner["id"], request.args.get("start"), request.args.get("end"))
    if request.args.get("include_undated") == "1" and (request.args.get("start") or request.args.get("end")):
        rows += [r for r in store.records(owner["id"]) if r["occurred_at"] is None]
    return jsonify(items=rows)


@activity_api.post("/api/v1/activity-events")
@owned
def add(owner):
    with get_db():
        result, inserted = store.save(body(), owner)
    return jsonify(event=result), 201 if inserted else 200


@activity_api.patch("/api/v1/activity-events/<event_id>")
@owned
def edit(owner, event_id):
    existing = get_db().execute("SELECT * FROM activity_events WHERE id=? AND account_id=?", (event_id, owner["id"])).fetchone()
    if not existing:
        abort(404)
    data = body()
    revision = data.pop("expected_revision", None)
    if "id" in data:
        abort(400, description="Activity ID cannot be changed")
    if type(revision) is not int:
        abort(400, description="expected_revision integer required")
    payload = json.loads(existing["payload_json"])
    payload.update(data)
    if not isinstance(payload.get("metadata", {}), dict):
        abort(400, description="metadata must be an object")
    payload["source_type"] = "manual_correction"
    payload["metadata"] = {**payload.get("metadata", {}), "correction_basis": "User-edited values; original evidence and quantities retained in revision history"}
    with get_db():
        result, _ = store.save(payload, owner, revision)
    return jsonify(event=result)


@activity_api.get("/api/v1/activity-events/<event_id>/history")
@owned
def history(owner, event_id):
    if not get_db().execute("SELECT 1 FROM activity_events WHERE id=? AND account_id=?", (event_id, owner["id"])).fetchone():
        abort(404)
    return jsonify(items=[{"revision":r["revision"],"created_at":r["created_at"],"payload":json.loads(r["payload_json"])}
                          for r in get_db().execute("SELECT * FROM activity_revisions WHERE event_id=? ORDER BY revision",(event_id,))])


@activity_api.get("/api/v1/activity-events/<event_id>/evidence")
@owned
def evidence(owner, event_id):
    row = get_db().execute("SELECT e.payload_json FROM activity_events a LEFT JOIN activity_evidence e ON a.evidence_id=e.id AND e.account_id=a.account_id WHERE a.id=? AND a.account_id=?",(event_id,owner["id"])).fetchone()
    if not row:
        abort(404)
    return jsonify(evidence=json.loads(row[0]) if row[0] else None)


@activity_api.get("/api/v1/activity-export")
@owned
def owned_export(owner):
    return export(owner["id"])


@activity_api.get("/api/v1/activity-spec")
@allow_public_dashboard
def activity_spec():
    from flask import current_app
    return current_app.send_static_file("openapi.json")


@activity_api.post("/api/v1/activity-imports/record-today")
@owned
def import_transactions(owner):
    data = body()
    rows = data.get("transactions")
    if type(data.get("schemaVersion")) is not int or data["schemaVersion"] != 1 or not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        abort(400, description="Use Record Today schemaVersion 1 with 1-100 transactions")
    inserted, duplicates = 0, 0
    db = get_db()
    with db:
        for item in rows:
            if not isinstance(item, dict):
                abort(400, description="Each transaction must be an object")
            external_id = store.identifier(item.get("id"), "transaction.id")
            source = store.label(item.get("source"), "source", 64)
            raw = store.encoded(item)
            digest = hashlib.sha256(raw.encode()).hexdigest()
            old = db.execute("SELECT content_hash FROM activity_evidence WHERE account_id=? AND source_type=? AND external_id=?",(owner["id"],source,external_id)).fetchone()
            if old:
                if old["content_hash"] != digest:
                    abort(409, description="An imported transaction ID was reused with different evidence")
                duplicates += 1
                continue
            evidence_id = "evidence-" + uuid.uuid4().hex
            event_id = "import-" + hashlib.sha256((owner["id"]+":"+source+":"+external_id).encode()).hexdigest()[:48]
            metadata = {"time_basis":item.get("timeBasis"),"time_precision":item.get("timePrecision"),"captured_at":item.get("capturedAt"),
                        "input_method":item.get("inputMethod"),"transaction_kind":item.get("kind"),"location_evidence":item.get("location")}
            payload = {"id":event_id,"kind":"shopping","name":item.get("merchant") or "Payment awaiting item details","category":"shopping",
                       "subcategory":"Imported payment","occurred_at":item.get("eventAt"),"timezone":item.get("timeZone") or "Asia/Hong_Kong",
                       "amount_minor":item.get("amountMinor"),"currency":item.get("currency"),"classification":"imported",
                       "status":"needs_review","source_type":"record-today/"+source,"metadata":metadata}
            # Capture time and nearby GPS are evidence, never invented purchase time/location.
            store.clean(payload,owner)
            db.execute("INSERT INTO activity_evidence VALUES (?,?,?,?,?,?,?)",(evidence_id,owner["id"],source,external_id,digest,raw,utc_now()))
            store.save(payload,owner,evidence_id=evidence_id)
            inserted += 1
    return jsonify(inserted=inserted,duplicates=duplicates,notice="Payment drafts saved; item quantities and carbon remain unknown"), 201 if inserted else 200
