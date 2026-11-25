"""Account-owned activities, evidence, immutable estimates and time-series views."""
from collections import defaultdict
from datetime import date, datetime, timedelta
import hashlib
import json
import math
from pathlib import Path
import secrets
import uuid
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from werkzeug.exceptions import BadRequest, Conflict, NotFound

from .data import identifier, timestamp, utc_now
from .db import get_db

DEMO = "demo-alex"
FORMULA = "quantity-factor-share-v1"
CATEGORIES = ("shopping", "food", "transport", "water", "energy", "other")


def encoded(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (ValueError, TypeError, RecursionError):
        raise BadRequest("Use finite, bounded JSON values")


def bounded(value, name, low=0, high=1e9, nullable=False):
    if value is None and nullable:
        return None
    if type(value) not in (int, float) or not math.isfinite(value) or not low <= value <= high:
        raise BadRequest(f"{name} must be a finite number in [{low}, {high}]")
    return value


def label(value, name, maximum=120):
    if not isinstance(value, str) or not 1 <= len(value.strip()) <= maximum:
        raise BadRequest(f"{name} requires 1-{maximum} characters")
    return value.strip()


def account(account_id):
    row = get_db().execute("SELECT * FROM activity_accounts WHERE id=?", (account_id,)).fetchone()
    if not row:
        raise NotFound("Unknown account")
    return {"id": row["id"], "name": row["name"], "is_demo": bool(row["is_demo"]),
            "metadata": json.loads(row["metadata_json"])}


def factors():
    return {r["id"]: json.loads(r["payload_json"]) for r in get_db().execute("SELECT * FROM activity_factors ORDER BY id")}


def clean(body, owner):
    if not isinstance(body, dict):
        raise BadRequest("An activity must be an object")
    allowed = {"id", "kind", "name", "category", "subcategory", "occurred_at", "ended_at", "timezone", "quantity", "unit",
               "factor_id", "share", "status", "scope", "lat", "lon", "amount_minor", "currency", "classification", "source_type", "items", "metadata"}
    if set(body) - allowed:
        raise BadRequest("Unknown activity fields: " + ", ".join(sorted(set(body) - allowed)))
    row = dict(body)
    row["id"] = identifier(row.get("id", "event-" + uuid.uuid4().hex), "id")
    if row.get("kind") not in ("shopping", "transport", "household") or row.get("category") not in CATEGORIES:
        raise BadRequest("Unsupported kind or category")
    valid = {"shopping": ("shopping", "food", "other"), "transport": ("transport",), "household": ("water", "energy")}
    if row["category"] not in valid[row["kind"]]:
        raise BadRequest("Category does not match activity kind")
    row["name"] = label(row.get("name"), "name")
    row["subcategory"] = label(row.get("subcategory", "Other"), "subcategory")
    row["timezone"] = row.get("timezone", "Asia/Hong_Kong")
    if not isinstance(row["timezone"], str) or len(row["timezone"]) > 64:
        raise BadRequest("Invalid timezone")
    try:
        zone = ZoneInfo(row["timezone"])
    except (ZoneInfoNotFoundError, ValueError):
        raise BadRequest("Use a valid IANA timezone")
    for field in ("occurred_at", "ended_at"):
        row[field] = timestamp(row[field], field) if row.get(field) is not None else None
    if row["ended_at"] and (not row["occurred_at"] or row["ended_at"] < row["occurred_at"]):
        raise BadRequest("End must follow a known start")
    row["quantity"] = bounded(row.get("quantity"), "quantity", nullable=True)
    row["unit"] = row.get("unit")
    if row["unit"] not in (None, "litre", "kwh", "passenger_km", "item", "kg"):
        raise BadRequest("Unsupported unit")
    expected = {"water": "litre", "energy": "kwh", "transport": "passenger_km"}.get(row["category"])
    if expected and row["quantity"] is not None and row["unit"] != expected:
        raise BadRequest("Quantity unit does not match category")
    row["share"] = bounded(row.get("share", 1), "share", .000001, 1)
    row["status"] = row.get("status", "needs_review")
    if row["status"] not in ("confirmed", "needs_review", "excluded") or row.get("scope", "outside") not in ("inside", "outside"):
        raise BadRequest("Unsupported status or scope")
    row["scope"] = row.get("scope", "inside" if row["kind"] == "household" else "outside")
    row["lat"] = bounded(row.get("lat"), "lat", -75, 75, True)
    row["lon"] = bounded(row.get("lon"), "lon", -180, 180, True)
    if (row["lat"] is None) != (row["lon"] is None):
        raise BadRequest("Supply both latitude and longitude")
    amount = row.get("amount_minor")
    if amount is not None and (type(amount) is not int or abs(amount) > 10**10):
        raise BadRequest("amount_minor must be integer minor currency units")
    row["amount_minor"] = amount
    row["currency"] = row.get("currency")
    if amount is not None and row["currency"] not in ("HKD", "CNY", "USD", "EUR", "GBP"):
        raise BadRequest("Supply a supported currency")
    row["classification"] = "synthetic" if owner["is_demo"] else row.get("classification", "manual")
    if row["classification"] not in ("synthetic", "manual", "imported"):
        raise BadRequest("Unsupported classification")
    row["source_type"] = label(row.get("source_type", "manual"), "source_type", 64)
    row["metadata"] = row.get("metadata", {})
    if not isinstance(row["metadata"], dict) or len(encoded(row["metadata"])) > 24000:
        raise BadRequest("metadata must be a bounded object")
    trace = row["metadata"].get("trace", [])
    if not isinstance(trace, list) or len(trace) > 200:
        raise BadRequest("Use at most 200 trace points per activity")
    previous = None
    for point in trace:
        if not isinstance(point, dict) or set(point) != {"lat", "lon", "at"}:
            raise BadRequest("Trace points require lat, lon and at")
        bounded(point["lat"], "trace.lat", -75, 75)
        bounded(point["lon"], "trace.lon", -180, 180)
        at = timestamp(point["at"], "trace.at")
        if previous and at < previous or row["occurred_at"] and at < row["occurred_at"] or row["ended_at"] and at > row["ended_at"]:
            raise BadRequest("Trace timestamps must be ordered within the activity")
        previous = at
    row["factor_id"] = row.get("factor_id")
    catalogue = factors()
    def check_factor(key, unit):
        if key is not None and (not isinstance(key, str) or key not in catalogue or catalogue[key]["unit"] != unit):
            raise BadRequest("Unknown factor or mismatched factor unit")
    check_factor(row["factor_id"], row["unit"])
    items = row.get("items", [])
    if not isinstance(items, list) or len(items) > 40:
        raise BadRequest("Use at most 40 line items")
    normalized = []
    for item in items:
        if not isinstance(item, dict) or set(item) - {"name", "quantity", "unit", "factor_id", "packaging_g"}:
            raise BadRequest("Unsupported item fields")
        unit = item.get("unit", "item")
        if unit not in ("item", "kg", "litre"):
            raise BadRequest("Unsupported item unit")
        check_factor(item.get("factor_id"), unit)
        normalized.append({"name": label(item.get("name"), "item.name"), "quantity": bounded(item.get("quantity"), "item.quantity"),
                           "unit": unit, "factor_id": item.get("factor_id"), "packaging_g": bounded(item.get("packaging_g"), "packaging_g", high=1e6, nullable=True)})
    row["items"] = normalized
    if row["kind"] != "shopping" and normalized:
        raise BadRequest("Line items belong to shopping activities")
    local_date = datetime.fromisoformat(row["occurred_at"].replace("Z", "+00:00")).astimezone(zone).date().isoformat() if row["occurred_at"] else None
    return row, local_date


def calculate(row, owner):
    catalogue = factors()
    terms, missing = [], []
    inputs = row["items"] if row["kind"] == "shopping" else [row]
    if not inputs:
        missing.append("Item details are unknown")
    for item in inputs:
        factor = catalogue.get(item.get("factor_id"))
        if item.get("quantity") is None or not factor:
            missing.append("Quantity or matching factor is unknown")
        elif not owner["is_demo"] and factor["classification"] == "synthetic":
            missing.append("A demo factor cannot estimate a real account record")
        else:
            terms.append({"quantity": item["quantity"], "unit": item["unit"], "factor": factor,
                          "share": row["share"], "kg": item["quantity"] * factor["value"] * row["share"]})
    if row["status"] != "confirmed":
        missing.append("Activity is not confirmed or is excluded")
    kg = math.fsum(term["kg"] for term in terms) if not missing else None
    return kg, {"formula": "sum(quantity * kgCO2e per unit * personal share)", "terms": terms, "unknown_reasons": sorted(set(missing)),
                "classification": "synthetic" if owner["is_demo"] or row["classification"] == "synthetic" else "estimated",
                "boundary": "Purchase lifecycle at acquisition; water supply excludes heating; energy subtotals exclude separately listed cooking; no daily asset amortization"}


def save(body, owner, expected_revision=None, evidence_id=None):
    row, local_date = clean(body, owner)
    db, now = get_db(), utc_now()
    old = db.execute("SELECT * FROM activity_events WHERE id=? AND account_id=?", (row["id"], owner["id"])).fetchone()
    if expected_revision is None and old:
        if old["payload_json"] == encoded(row):
            return event(old), False
        raise Conflict("Activity ID was reused with different content")
    if expected_revision is not None and (not old or type(expected_revision) is not int or old["revision"] != expected_revision):
        raise Conflict("Activity changed; reload before saving")
    if not old and db.execute("SELECT 1 FROM activity_events WHERE id=?", (row["id"],)).fetchone():
        raise Conflict("Choose a different activity ID")
    if owner["id"] == DEMO and old:
        raise Conflict("The shared demo is read-only; edit a private copy")
    revision = old["revision"] + 1 if old else 1
    kg, details = calculate(row, owner)
    if old:
        updated = db.execute("""UPDATE activity_events SET occurred_at=?,local_date=?,kind=?,category=?,status=?,revision=?,payload_json=?,updated_at=?
                            WHERE id=? AND account_id=? AND revision=?""", (row["occurred_at"], local_date, row["kind"], row["category"], row["status"], revision, encoded(row), now, row["id"], owner["id"], expected_revision))
        if updated.rowcount != 1:
            raise Conflict("Activity changed; reload before saving")
        db.execute("DELETE FROM activity_items WHERE event_id=?", (row["id"],))
    else:
        db.execute("INSERT INTO activity_events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (row["id"], owner["id"], row["occurred_at"], local_date, row["kind"], row["category"], row["status"], revision, encoded(row), evidence_id, now, now))
    for position, item in enumerate(row["items"]):
        db.execute("INSERT INTO activity_items VALUES (?,?,?)", (row["id"], position, encoded(item)))
    db.execute("INSERT INTO activity_estimates VALUES (?,?,?,?,?,?)", (row["id"], revision, kg, FORMULA, encoded(details), now))
    db.execute("INSERT INTO activity_revisions VALUES (?,?,?,?)", (row["id"], revision, encoded(row), now))
    return event(db.execute("SELECT * FROM activity_events WHERE id=?", (row["id"],)).fetchone()), True


def event(stored):
    row = json.loads(stored["payload_json"])
    estimate = get_db().execute("SELECT * FROM activity_estimates WHERE event_id=? AND revision=?", (row["id"], stored["revision"])).fetchone()
    row.update(local_date=stored["local_date"], revision=stored["revision"], account_id=stored["account_id"], co2e_kg=estimate["co2e_kg"],
               estimate={"formula_version": estimate["formula_version"], **json.loads(estimate["details_json"])})
    return row


def dates(start=None, end=None):
    try:
        start, end = date.fromisoformat(start or "2026-11-16"), date.fromisoformat(end or "2026-11-22")
    except (ValueError, TypeError):
        raise BadRequest("Use ISO start/end dates")
    if not 0 <= (end - start).days <= 365:
        raise BadRequest("Choose an ordered range of at most 366 days")
    return start, end


def records(account_id, start=None, end=None):
    if start is None and end is None:
        rows = get_db().execute("SELECT * FROM activity_events WHERE account_id=? ORDER BY occurred_at,id", (account_id,))
    else:
        first, last = dates(start, end)
        rows = get_db().execute("SELECT * FROM activity_events WHERE account_id=? AND local_date BETWEEN ? AND ? ORDER BY occurred_at,id", (account_id, first.isoformat(), last.isoformat()))
    return [event(r) for r in rows]


def overview(account_id, start=None, end=None):
    first, last = dates(start, end)
    owner, rows = account(account_id), records(account_id, first.isoformat(), last.isoformat())
    days = defaultdict(lambda: {"co2e_kg": 0., "water_l": 0., "electricity_kwh": 0., "transport_km": 0., "records": 0, "unknown": 0, "by_category": defaultdict(float)})
    by_kind = defaultdict(lambda: {"records": 0, "co2e_kg": 0., "unknown": 0})
    currencies, packaging = defaultdict(float), 0.
    for row in rows:
        if row["status"] == "excluded":
            continue
        day, group = days[row["local_date"]], by_kind[row["kind"]]
        day["records"] += 1
        group["records"] += 1
        if row["co2e_kg"] is None:
            day["unknown"] += 1
            group["unknown"] += 1
        else:
            day["co2e_kg"] += row["co2e_kg"]
            day["by_category"][row["category"]] += row["co2e_kg"]
            group["co2e_kg"] += row["co2e_kg"]
        if row["quantity"] is not None:
            key = {"litre": "water_l", "kwh": "electricity_kwh", "passenger_km": "transport_km"}.get(row["unit"])
            if key:
                day[key] += row["quantity"] * row["share"]
        if row["kind"] == "shopping":
            if row["amount_minor"] is not None:
                currencies[row["currency"]] += row["amount_minor"] * row["share"] / 100
            packaging += sum((item["packaging_g"] or 0) * item["quantity"] * row["share"] for item in row["items"])
    series = [{"date": (first + timedelta(days=i)).isoformat(), **days[(first + timedelta(days=i)).isoformat()]} for i in range((last-first).days+1)]
    eligible = [r for r in rows if r["status"] != "excluded"]
    reference_end = first - timedelta(days=1)
    reference_start = first - timedelta(days=(last-first).days+1)
    previous = records(account_id, reference_start.isoformat(), reference_end.isoformat())
    known_sum = lambda items: math.fsum(r["co2e_kg"] for r in items if r["co2e_kg"] is not None and r["status"] != "excluded")
    total, reference = known_sum(eligible), known_sum(previous)
    categories = [{"category": c, "co2e_kg": math.fsum(r["co2e_kg"] for r in eligible if r["category"] == c and r["co2e_kg"] is not None)} for c in CATEGORIES]
    return {"account": owner, "classification": "synthetic" if owner["is_demo"] else "personal", "period": {"start":first.isoformat(),"end":last.isoformat()},
            "total_kg": total, "by_kind": dict(by_kind), "categories": categories, "series": series,
            "resources": {key: math.fsum(d[key] for d in series) for key in ("water_l", "electricity_kwh", "transport_km")},
            "shopping": {"spend_by_currency":dict(currencies),"packaging_g":packaging,"purchases":sum(r["kind"]=="shopping" for r in eligible)},
            "coverage": {"records":len(eligible),"known":sum(r["co2e_kg"] is not None for r in eligible),"unknown":sum(r["co2e_kg"] is None for r in eligible),
                         "excluded":len(rows)-len(eligible),"undated":get_db().execute("SELECT COUNT(*) FROM activity_events WHERE account_id=? AND occurred_at IS NULL",(account_id,)).fetchone()[0]},
            "comparison":{"reference_start":reference_start.isoformat(),"reference_end":reference_end.isoformat(),"reference_kg":reference,
                          "change_fraction":(reference-total)/reference if reference else None,"method":"Known estimates only; coverage may differ. No claim of measured behavior change."},
            "green_index": {"value": .35 if owner["is_demo"] else None,"method":"Manual synthetic placeholder; scoring formula undefined"},
            "formula_version":FORMULA}


def create_account(name, copy_demo=False):
    db, now = get_db(), utc_now()
    owner_id, token = "person-" + uuid.uuid4().hex, "lg_" + secrets.token_urlsafe(32)
    with db:
        db.execute("INSERT INTO activity_accounts VALUES (?,?,?,?,?)", (owner_id,label(name,"name"),int(copy_demo),encoded({"copied_from":DEMO} if copy_demo else {}),now))
        db.execute("INSERT INTO activity_tokens VALUES (?,?,?)", (hashlib.sha256(token.encode()).hexdigest(),owner_id,now))
        owner = account(owner_id)
        if copy_demo:
            for original in records(DEMO):
                row = {k:v for k,v in original.items() if k not in ("local_date","revision","account_id","co2e_kg","estimate")}
                row["id"] = "event-" + uuid.uuid4().hex
                save(row,owner)
    return owner, token


def seed_demo():
    db = get_db()
    if db.execute("SELECT 1 FROM activity_accounts WHERE id=?",(DEMO,)).fetchone():
        return
    dataset = json.loads(Path(__file__).with_name("datasets").joinpath("alex.json").read_text(encoding="utf-8"))
    with db:
        db.execute("INSERT OR IGNORE INTO activity_accounts VALUES (?,?,?,?,?)",(DEMO,dataset["person"]["name"],1,encoded({"dataset_id":dataset["dataset_id"],"provenance":dataset["provenance"],"period":dataset["period"]}),utc_now()))
        for factor in dataset["factors"]:
            db.execute("INSERT OR IGNORE INTO activity_factors VALUES (?,?)",(factor["id"],encoded(factor)))
        owner = account(DEMO)
        for row in dataset["events"]:
            save(row,owner)
