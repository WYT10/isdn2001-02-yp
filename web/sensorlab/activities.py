"""A fixed, explicitly synthetic activity scenario; previews never write research data."""
from copy import deepcopy
from datetime import date, timedelta
import math

from flask import abort, jsonify, request

from .auth import require_roles
from .living import CATEGORIES, living, preview

MTR_SOURCE = "https://www.mtr.com.hk/sustainability/assets/pdf/en/2025/MTR_Sustainable_Finance_Rpt_2025.pdf"
MODES = {
    "mtr": {"name": "MTR", "factor": .041, "source": "MTR Sustainable Finance Report 2025, heavy rail operational GHG per passenger-km", "url": MTR_SOURCE, "region": "Hong Kong", "version": "2025"},
    "bus": {"name": "Bus", "factor": .08, "source": "Synthetic bus factor for interaction testing; not a researched HK estimate", "region": "Demo only", "version": "demo-1"},
    "car": {"name": "Car", "factor": .16, "source": "Synthetic car factor for interaction testing; occupancy and vehicle unknown", "region": "Demo only", "version": "demo-1"},
}
CATALOGUE = {
    "shampoo": {"name": "Shampoo, 500 mL", "quantity": "1 bottle · 500 mL", "packaging_g": 52, "refill_g": 14},
    "noodles": {"name": "Instant noodles, 5-pack", "quantity": "1 multipack · 500 g", "packaging_g": 22},
}


def scenario():
    common = {"classification": "synthetic", "status": "confirmed_demo", "co2e_kg": None,
              "lat": 22.3226, "lon": 114.1696, "owner": "Household", "scope": "inside",
              "source": "Synthetic scenario; not connected to your sensor or purchase history",
              "factor": None, "region": "Demo only", "version": "demo-1"}
    rows = [
        {"id": "shower-01", "name": "Bathroom shower", "kind": "water", "category": "water", "date": "2026-11-18", "litres": 48, "minutes": 8,
         "baseline": {"value": 40, "unit": "L", "sessions": 8, "name": "Same bathroom shower · eight prior demo sessions"},
         "source": "Simulated calibrated flow-sensor session, fixture assigned by the demo", "raw": "21,600 synthetic pulses ÷ 450 demo pulses/L = 48 L. Neither this coefficient nor fixture label applies to the physical board."},
        {"id": "hotpot-01", "name": "Kitchen hot pot", "kind": "electricity", "category": "energy", "date": "2026-11-18", "kwh": .25, "minutes": 25,
         "baseline": {"value": .24, "unit": "kWh", "sessions": 6, "name": "Same kitchen plug · six prior demo sessions"},
         "source": "Simulated appliance-meter session", "raw": "Energy would be integrated from timestamped power samples; 0.25 kWh is a synthetic session total."},
        {"id": "electricity-01", "name": "Other home electricity", "kind": "electricity", "category": "energy", "date": "2026-11-17", "kwh": 10,
         "source": "Synthetic separately metered home uses, excluding the hot pot", "raw": "10 kWh is a demo total, not a sum of live plug readings."},
        {"id": "rail-01", "name": "To campus", "kind": "trip", "category": "transport", "date": "2026-11-18", "scope": "outside", "owner": "Personal", "mode": "mtr", "km": 23.4,
         "lat": 22.3130, "lon": 114.1707, "quantity": "Walk + MTR + walk", "stations": "Sha Tin → Hang Hau (illustrative confirmed stops)",
         "legs": ["Walk · 8 min", "MTR · 23.4 km · 28 min", "Walk · 12 min"], "source": "Demo user-confirmed journey; distance and stops are illustrative, not route-API output"},
        {"id": "trip-02", "name": "Afternoon journey", "kind": "trip", "category": "transport", "date": "2026-11-17", "scope": "outside", "owner": "Personal", "mode": None, "km": 12,
         "lat": 22.3048, "lon": 114.1716, "status": "needs_mode", "source": "Synthetic ambiguous motion event; no actual GPS or activity-recognition service is running", "legs": ["Vehicle leg · mode unresolved"], "stations": "Not confirmed"},
        {"id": "shampoo-01", "name": "Shampoo, 500 mL", "kind": "purchase", "category": "shopping", "date": "2026-11-16", "scope": "outside", "quantity": "1 bottle · 500 mL", "catalogue": "shampoo", "packaging_g": 52, "refill_g": 14,
         "lat": 22.3185, "lon": 114.1689, "source": "Demo item name and packaging fields adapted from the supplied Shopping.json; weights are unverified examples, not a payment/API inference"},
        {"id": "purchase-02", "name": "Supermarket purchase", "kind": "purchase", "category": "shopping", "date": "2026-11-17", "scope": "outside", "spend_hkd": 45, "quantity": "Items not identified", "packaging_g": None,
         "lat": 22.3185, "lon": 114.1689, "status": "needs_items", "source": "Synthetic receipt total only. Spend does not establish product, packaging or footprint."},
        {"id": "food-01", "name": "Logged grocery items", "kind": "purchase", "category": "food", "date": "2026-11-16", "scope": "outside", "quantity": "0.5 kg · comparable food category", "packaging_g": 22, "co2e_kg": 2.6,
         "factor": 5.2, "factor_unit": "kg CO₂e/kg food", "lat": 22.3162, "lon": 114.1702, "source": "Synthetic receipt lines and comparable-product lifecycle factor; not an Agribalyse lookup", "raw": "0.5 kg × 5.2 demo kg CO₂e/kg = 2.6 kg CO₂e. Whole-product lifecycle scope; not packaging-only."},
        {"id": "jeans-01", "name": "Cotton denim jeans", "kind": "purchase", "category": "shopping", "date": "2026-11-16", "scope": "outside", "owner": "Personal", "quantity": "1 pair", "packaging_g": None, "co2e_kg": 5.4,
         "lat": 22.3201, "lon": 114.1708, "source": "Unverified synthetic product estimate from the supplied Shopping.json; not a verified lifecycle factor", "raw": "5.4 kg CO₂e per demo purchase. Counted once at purchase, with no daily amortization added."},
        {"id": "cafe-01", "name": "Cafe · Jordan", "kind": "purchase", "category": "food", "date": "2026-11-18", "scope": "outside", "owner": "Personal", "quantity": "1 coffee", "packaging_g": 12, "co2e_kg": .48,
         "lat": 22.3075, "lon": 114.1712, "source": "Synthetic cafe visit and assumed product estimate, not a merchant or lifecycle API", "raw": "0.48 demo kg CO₂e per coffee; 12 g example cup packaging. Unverified values with different scopes."},
        {"id": "lunch-01", "name": "Lunch · Yau Ma Tei", "kind": "purchase", "category": "food", "date": "2026-11-18", "scope": "outside", "owner": "Personal", "quantity": "1 meal", "packaging_g": 18, "co2e_kg": 1.1,
         "lat": 22.3129, "lon": 114.1719, "source": "Synthetic lunch and assumed product estimate", "raw": "1.1 demo kg CO₂e per meal; 18 g example packaging. No researched conversion factor."},
        {"id": "market-01", "name": "Market groceries", "kind": "purchase", "category": "shopping", "date": "2026-11-17", "scope": "outside", "quantity": "1 bag of produce", "packaging_g": None, "co2e_kg": .72,
         "lat": 22.3234, "lon": 114.1668, "source": "Synthetic market visit and assumed product estimate", "raw": "0.72 demo kg CO₂e per purchase. Packaging is unknown."},
        {"id": "refill-01", "name": "Detergent refill", "kind": "purchase", "category": "shopping", "date": "2026-11-17", "scope": "outside", "quantity": "1 refill pouch", "packaging_g": 14, "co2e_kg": .35,
         "lat": 22.3198, "lon": 114.1657, "source": "Synthetic refill purchase and assumed product estimate", "raw": "0.35 demo kg CO₂e per purchase; 14 g example packaging. No researched factor or measured packaging weight."},
        {"id": "bakery-01", "name": "Bakery stop", "kind": "purchase", "category": "food", "date": "2026-11-16", "scope": "outside", "owner": "Personal", "quantity": "2 buns", "packaging_g": 8, "co2e_kg": .28,
         "lat": 22.3157, "lon": 114.1671, "source": "Synthetic bakery purchase and assumed product estimate", "raw": "0.28 demo kg CO₂e per purchase; 8 g example packaging. Unverified scenario values."},
        {"id": "bus-03", "name": "Bus · Prince Edward", "kind": "trip", "category": "transport", "date": "2026-11-18", "scope": "outside", "owner": "Personal", "mode": "bus", "km": 3.2,
         "lat": 22.3269, "lon": 114.1674, "legs": ["Bus · 3.2 km"], "stations": "Illustrative stops", "source": "Synthetic bus journey; displayed location is an attribution point, not a tracked route"},
    ]
    result = [{**deepcopy(common), **deepcopy(row)} for row in rows]
    for row in result:
        if row["kind"] == "electricity":
            row.update(co2e_kg=row["kwh"] * .38, factor=.38, factor_unit="kg CO₂e/kWh", raw=row.get("raw", "") + " Carbon uses 0.38 demo kg CO₂e/kWh; no verified utility factor supplied.")
        if row["kind"] == "trip" and row["mode"]:
            apply_mode(row, row["mode"])
    # Separate historical records, with a deliberately higher energy reference.
    original = deepcopy(result)
    for weeks_ago, energy_extra in ((1, 3), (2, 4), (3, 5)):
        for base in original:
            if base["id"] in ("trip-02", "purchase-02"):
                continue
            row = deepcopy(base)
            row["id"] += f"-w{weeks_ago}"
            row["date"] = (date.fromisoformat(base["date"]) - timedelta(weeks=weeks_ago)).isoformat()
            if row["kind"] == "electricity" and base["id"] == "electricity-01":
                row["kwh"] += energy_extra / .38
                row["co2e_kg"] += energy_extra
                row["raw"] = f"{row['kwh']:.3f} synthetic kWh × 0.38 demo kg CO₂e/kWh. Separate uses exclude the hot pot."
            if row["kind"] == "water":
                row["litres"] = 40
                row["minutes"] = 7
                row["raw"] = "18,000 synthetic pulses ÷ 450 demo pulses/L = 40 L. No physical calibration implied."
            result.append(row)
    return result


def apply_mode(row, mode):
    metadata = MODES[mode]
    row.update(mode=mode, status="confirmed_demo", co2e_kg=row["km"] * metadata["factor"],
               factor=metadata["factor"], factor_unit="kg CO₂e/passenger-km", factor_source=metadata["source"],
               factor_url=metadata.get("url"), region=metadata["region"], version=metadata["version"])
    row["quantity"] = "Walk + MTR + walk" if mode == "mtr" and row["id"] == "rail-01" else metadata["name"]
    row["legs"] = row["legs"] if row["id"] == "rail-01" and mode == "mtr" else [metadata["name"] + " · " + str(row["km"]) + " km (demo distance)"]


def apply_corrections(rows, corrections):
    if not isinstance(corrections, list) or len(corrections) > 10:
        abort(400, description="Use at most ten demo corrections")
    by_id = {row["id"]: row for row in rows}
    seen = set()
    for change in corrections:
        if not isinstance(change, dict) or not isinstance(change.get("id"), str) or change["id"] not in by_id or change["id"] in seen:
            abort(400, description="Unknown or duplicate demo activity")
        row = by_id[change["id"]]
        if "-w" in row["id"]:
            abort(400, description="Reference activities cannot be edited in this demo")
        seen.add(row["id"])
        if row["kind"] == "trip" and set(change) == {"id", "mode"}:
            mode = change["mode"]
            if not isinstance(mode, str) or mode not in (*MODES, "skip"):
                abort(400, description="Choose MTR, bus, car or skip")
            if mode == "skip":
                row.update(mode=None, status="unresolved_skipped", co2e_kg=None, factor=None)
            else:
                apply_mode(row, mode)
        elif row["id"] == "purchase-02" and set(change) == {"id", "catalogue"}:
            item = change["catalogue"]
            if not isinstance(item, str) or item not in CATALOGUE:
                abort(400, description="Choose a demo catalogue item")
            row.update(**CATALOGUE[item], catalogue=item, status="confirmed_demo", co2e_kg=None,
                       source="Demo user-selected catalogue item; 52/14/22 g weights are unverified scenario inputs. Purchase footprint remains unknown.")
        elif row["id"] == "shower-01" and set(change) == {"id", "litres", "minutes"}:
            for field, upper in (("litres", 1000), ("minutes", 120)):
                if type(change[field]) not in (int, float) or not math.isfinite(change[field]) or not 0 < change[field] <= upper:
                    abort(400, description="Enter a positive bounded session quantity")
            row.update(litres=change["litres"], minutes=change["minutes"], status="corrected_demo",
                       source="Manual correction of the synthetic shower session", raw="Manual demo litres/duration override. No live readings or calibration were changed.")
        else:
            abort(400, description="Unsupported correction fields")
    return rows


def activity_preview(body):
    if not isinstance(body, dict) or set(body) - {"period", "scope", "category", "bandwidth_m", "corrections"}:
        abort(400, description="Unknown activity preview fields")
    period, scope, category = body.get("period", "week"), body.get("scope", "all"), body.get("category", "all")
    if period not in ("week", "fortnight") or scope not in ("all", "inside", "outside") or category not in ("all", *CATEGORIES):
        abort(400, description="Unknown date range or scope")
    rows = apply_corrections(scenario(), body.get("corrections", []))
    days = 7 if period == "week" else 14
    end = date(2026, 11, 22)
    start = end - timedelta(days=days-1)
    ref_end, ref_start = start-timedelta(days=1), start-timedelta(days=days)
    in_scope = lambda row: scope == "all" or row["scope"] == scope
    selected = [row for row in rows if start.isoformat() <= row["date"] <= end.isoformat() and in_scope(row)]
    reference = [row for row in rows if ref_start.isoformat() <= row["date"] <= ref_end.isoformat() and in_scope(row)]
    population = [row for row in selected if category == "all" or row["category"] == category]
    ref_population = [row for row in reference if category == "all" or row["category"] == category]
    estimate = lambda items: math.fsum(row["co2e_kg"] for row in items if row["co2e_kg"] is not None)
    total, ref_total = estimate(population), estimate(ref_population)
    ratio = (ref_total-total)/ref_total if ref_total else None
    mapped = [{key: row[key] for key in ("name", "category", "scope", "lat", "lon", "co2e_kg")}
              for row in population if row["co2e_kg"] is not None]
    footprint = preview(mapped, "all", "all", body.get("bandwidth_m", 150), "activity_demo")
    footprint.update(scope=scope, category=category)
    footprint["provenance"].update(source="Fixed synthetic activity scenario; sourced MTR factor applied only to demo rail distance",
                                   limitations="Incomplete demo coverage; unknown emissions are excluded, not zero. Point attribution is not a route or air-pollution measurement.")
    contributions = [{"category": name, "change_kg": estimate([r for r in ref_population if r["category"] == name])-estimate([r for r in population if r["category"] == name])}
                     for name in {row["category"] for row in population + ref_population}]
    trends = []
    for offset in (3, 2, 1, 0):
        last = end - timedelta(weeks=offset)
        first = last - timedelta(days=6)
        items = [r for r in rows if first.isoformat() <= r["date"] <= last.isoformat() and in_scope(r) and (category == "all" or r["category"] == category)]
        trends.append({"label": f"{first.day}–{last.day} {last.strftime('%b')}", "total_kg": estimate(items)})
    return {"classification": "synthetic", "records": selected, "footprint": footprint,
            "green_index": {"value": .35, "classification": "synthetic_manual", "definition": "Independent demo green index; scoring formula not defined. Not the period emission change."},
            "period": {"key": period, "start": start.isoformat(), "end": end.isoformat(), "reference_start": ref_start.isoformat(), "reference_end": ref_end.isoformat()},
            "comparison": {"total_kg": total, "reference_kg": ref_total, "change_fraction": ratio,
                           "largest_change": max(contributions, key=lambda r: abs(r["change_kg"]), default=None)},
            "coverage": {"pending_trips": sum(r["kind"] == "trip" and r["mode"] is None for r in population),
                         "pending_purchases": sum(r["status"] == "needs_items" for r in population),
                         "unknown_emissions": sum(r["co2e_kg"] is None for r in population),
                         "reference_unknown_emissions": sum(r["co2e_kg"] is None for r in ref_population),
                         "missing_plug_days": 1 if scope != "outside" and category in ("all", "energy") else 0,
                         "known_records": len(mapped), "total_records": len(population)},
            "trends": trends, "catalogue": CATALOGUE, "modes": MODES,
            "storage": "Corrections stay in this browser tab session; this API is a pure preview with no database writes."}


@living.get("/api/v1/living/activities")
@require_roles("viewer", "admin")
def demo_activities():
    return jsonify(activity_preview({}))


@living.post("/api/v1/living/activities/preview")
@require_roles("viewer", "admin")
def corrected_activities():
    return jsonify(activity_preview(request.get_json()))
