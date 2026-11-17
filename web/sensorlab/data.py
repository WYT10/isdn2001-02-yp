import json
import math
import re
from datetime import datetime, timezone

from werkzeug.exceptions import BadRequest, Conflict

from .db import get_db

IDENTIFIER = re.compile(r"[A-Za-z0-9_-]{1,64}\Z")


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def identifier(value, field):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise BadRequest(f"{field} must contain 1-64 letters, digits, underscores or hyphens")
    return value


def integer(value, field, minimum=0, maximum=2**63 - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise BadRequest(f"{field} must be an integer in [{minimum}, {maximum}]")
    return value


def number(value, field, nullable=False, maximum=1e12):
    if value is None and nullable:
        return None
    if type(value) not in (int, float) or not 0 <= value <= maximum or not math.isfinite(value):
        raise BadRequest(f"{field} must be a finite nonnegative number")
    return value


def timestamp(value, field):
    if not isinstance(value, str) or len(value) > 40:
        raise BadRequest(f"{field} must be an ISO 8601 timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    except ValueError as error:
        raise BadRequest(f"{field} must be an ISO 8601 timestamp with timezone") from error


def clean_sample(sample):
    if not isinstance(sample, dict):
        raise BadRequest("Each sample must be an object")
    required = ("seq", "uptime_us", "dt_us", "pulses", "total_pulses", "frequency_hz")
    if any(field not in sample for field in required):
        raise BadRequest("Each sample requires " + ", ".join(required))
    result = {
        "seq": integer(sample["seq"], "seq"),
        "uptime_us": integer(sample["uptime_us"], "uptime_us"),
        "dt_us": integer(sample["dt_us"], "dt_us", 1),
        "pulses": integer(sample["pulses"], "pulses"),
        "total_pulses": integer(sample["total_pulses"], "total_pulses"),
        "frequency_hz": number(sample["frequency_hz"], "frequency_hz", maximum=1e7),
        "flow_lpm": number(sample.get("flow_lpm"), "flow_lpm", nullable=True),
        "total_l": number(sample.get("total_l"), "total_l", nullable=True),
        "observed_at": timestamp(sample["observed_at"], "observed_at") if sample.get("observed_at") is not None else None,
    }
    if result["pulses"] > result["total_pulses"]:
        raise BadRequest("pulses cannot exceed total_pulses")
    pulse = sample.get("pulse")
    if pulse is not None:
        if not isinstance(pulse, dict) or set(pulse) != {"hz", "high_us", "low_us", "duty_pct"}:
            raise BadRequest("pulse requires hz, high_us, low_us and duty_pct")
        for field in ("hz", "high_us", "low_us"):
            number(pulse[field], "pulse." + field)
        number(pulse["duty_pct"], "pulse.duty_pct", maximum=100)
    result["pulse_json"] = json.dumps(pulse, allow_nan=False) if pulse is not None else None
    try:
        result["raw_json"] = json.dumps(sample, allow_nan=False, sort_keys=True, separators=(",", ":"))
    except (ValueError, TypeError, RecursionError) as error:
        raise BadRequest("Sample must contain finite JSON values") from error
    return result


def ingest(payload, *, demo=False, received_at=None):
    if not isinstance(payload, dict):
        raise BadRequest("Body must be a JSON object")
    device_id = identifier(payload.get("device_id"), "device_id")
    boot_id = identifier(payload.get("boot_id"), "boot_id")
    label = payload.get("label", device_id)
    if not isinstance(label, str) or not 1 <= len(label.strip()) <= 80:
        raise BadRequest("label must contain 1-80 characters")
    samples = payload.get("samples")
    if not isinstance(samples, list) or not 1 <= len(samples) <= 200:
        raise BadRequest("samples must contain 1-200 measurements")
    cleaned = [clean_sample(sample) for sample in samples]
    if len({sample["seq"] for sample in cleaned}) != len(cleaned):
        raise BadRequest("Duplicate seq within batch")
    # Validate before opening the transaction; conflicting retries roll back the whole batch.
    db = get_db()
    now = received_at or utc_now()
    inserted = 0
    with db:
        db.execute("BEGIN IMMEDIATE")
        existing_device = db.execute("SELECT is_demo FROM devices WHERE device_id=?", (device_id,)).fetchone()
        if existing_device and bool(existing_device["is_demo"]) != demo:
            raise Conflict("Device ID already belongs to a different data source")
        db.execute("INSERT OR IGNORE INTO devices VALUES (?,?,?,?,?)", (device_id, label.strip(), int(demo), now, now))
        for sample in cleaned:
            previous = db.execute(
                "SELECT raw_json FROM readings WHERE device_id=? AND boot_id=? AND seq=?",
                (device_id, boot_id, sample["seq"]),
            ).fetchone()
            if previous:
                if previous["raw_json"] != sample["raw_json"]:
                    raise Conflict("A measurement ID was reused with different data")
                continue
            db.execute(
                """INSERT INTO readings
                (device_id,boot_id,seq,received_at,observed_at,uptime_us,dt_us,pulses,total_pulses,
                 frequency_hz,flow_lpm,total_l,pulse_json,raw_json)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (device_id, boot_id, sample["seq"], now, sample["observed_at"], sample["uptime_us"],
                 sample["dt_us"], sample["pulses"], sample["total_pulses"], sample["frequency_hz"],
                 sample["flow_lpm"], sample["total_l"], sample["pulse_json"], sample["raw_json"]),
            )
            inserted += 1
        if inserted:
            db.execute("UPDATE devices SET label=?,last_seen=MAX(last_seen,?) WHERE device_id=?",
                       (label.strip(), now, device_id))
    return {"inserted": inserted, "duplicates": len(cleaned) - inserted, "received_at": now}


def reading_dict(row, include_raw=False):
    item = dict(row)
    item["pulse"] = json.loads(item.pop("pulse_json")) if item.get("pulse_json") else None
    item.pop("pulse_json", None)
    raw = item.pop("raw_json", None)
    if include_raw:
        item["raw"] = json.loads(raw)
    return item
