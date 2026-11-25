"""Project saved activities into the approved dashboard's presentation contract."""
from datetime import date, timedelta
import math

from flask import abort, jsonify, request, session

from . import activity_store as store
from .auth import allow_public_dashboard
from .living import CATEGORIES, living, preview


def display(row):
    term = row["estimate"]["terms"][0] if row["estimate"]["terms"] else None
    factor = term["factor"] if term else {}
    kind = {"shopping":"purchase","transport":"trip"}.get(row["kind"], "water" if row["category"] == "water" else "electricity")
    quantity = row["quantity"] * row["share"] if row["quantity"] is not None else None
    result = {**row, "kind":kind,"date":row["local_date"],"owner":"Personal" if row["share"] == 1 else f"Personal share ({row['share']:.0%})",
              "source":row["source_type"]+" · saved database record · "+row["classification"],
              "status":"needs_items" if kind == "purchase" and not row["items"] else "needs_mode" if kind == "trip" and row["metadata"].get("mode") is None else row["status"],
              "tree_label":row["name"],"factor":factor.get("value"),"factor_unit":"kg CO₂e/"+factor.get("unit","unknown"),
              "factor_source":factor.get("source","No matching factor"),"factor_url":factor.get("source_url"),"region":factor.get("region","Unknown"),"version":factor.get("version","Unknown"),
              "raw":f"Formula {store.FORMULA}; personal share {row['share']:.6g}. "+row["estimate"]["boundary"],
              "quantity": "; ".join(f"{item['quantity']:g} {item['unit']} · {item['name']}" for item in row["items"]) or "Items not identified",
              "packaging_g":sum(item["packaging_g"]*item["quantity"]*row["share"] for item in row["items"] if item["packaging_g"] is not None) if row["items"] else None,
              "minutes":row["metadata"].get("duration_minutes",0), "spend_hkd":row["amount_minor"]/100*row["share"] if row["currency"]=="HKD" and row["amount_minor"] is not None else None}
    if kind == "water":
        result["litres"] = quantity or 0
    elif kind == "electricity":
        result["kwh"] = quantity or 0
    elif kind == "trip":
        mode = row["metadata"].get("mode")
        result.update(mode=mode,km=quantity or 0,quantity=(mode or "Unconfirmed mode").upper(),legs=[row["name"]],stations="See the saved record for source and trace")
    return result


def activity_preview(body):
    if not isinstance(body,dict) or set(body)-{"period","scope","category","bandwidth_m","corrections"}:
        abort(400,description="Unknown activity view fields")
    if body.get("corrections"):
        abort(400,description="Use the activity workspace to save corrections")
    period,scope,category=body.get("period","week"),body.get("scope","all"),body.get("category","all")
    if period not in ("week","fortnight","month") or scope not in ("all","inside","outside") or category not in ("all",*CATEGORIES):
        abort(400,description="Unknown date range or scope")
    account_id=session.get("activity_account_id",store.DEMO)
    owner=store.account(account_id)
    days={"week":7,"fortnight":14,"month":28}[period]
    end=date(2026,11,22)
    start=end-timedelta(days=days-1)
    ref_end,ref_start=start-timedelta(days=1),start-timedelta(days=days)
    all_rows=[display(r) for r in store.records(account_id) if r["status"]!="excluded"]
    in_scope=lambda r:scope=="all" or r["scope"]==scope
    selected=[r for r in all_rows if r["date"] and start.isoformat()<=r["date"]<=end.isoformat() and in_scope(r)]
    reference=[r for r in all_rows if r["date"] and ref_start.isoformat()<=r["date"]<=ref_end.isoformat() and in_scope(r)]
    population=[r for r in selected if category=="all" or r["category"]==category]
    ref_population=[r for r in reference if category=="all" or r["category"]==category]
    estimate=lambda items:math.fsum(r["co2e_kg"] for r in items if r["co2e_kg"] is not None)
    total,ref_total=estimate(population),estimate(ref_population)
    mapped=[{k:r[k] for k in ("name","category","scope","lat","lon","co2e_kg")} for r in population if r["co2e_kg"] is not None and r["lat"] is not None]
    footprint=preview(mapped,"all","all",body.get("bandwidth_m",150),"synthetic" if owner["is_demo"] else "personal")
    footprint.update(scope=scope,category=category)
    categories=[{"name":name,"co2e_kg":estimate([r for r in population if r["category"]==name])} for name in CATEGORIES if any(r["category"]==name for r in population)]
    for item in categories:
        item["share"]=item["co2e_kg"]/total if total else 0
    footprint.update(total_kg=total,categories=sorted(categories,key=lambda r:-r["co2e_kg"]),
                     inside_kg=estimate([r for r in population if r["scope"]=="inside"]),outside_kg=estimate([r for r in population if r["scope"]=="outside"]),
                     mapped_kg=math.fsum(r["co2e_kg"] for r in mapped),unlocated_records=sum(r["co2e_kg"] is not None and r["lat"] is None for r in population))
    footprint["provenance"].update(source=owner["name"]+" · persistent activity database",storage="Saved SQLite records; corrections and estimate revisions persist",
        limitations="Synthetic account inputs/factors are marked. Unknown emissions are excluded. Household shares are allocated once. Map points attribute activities, not atmospheric pollution or traced routes.")
    trends=[]
    for offset in (3,2,1,0):
        last=end-timedelta(weeks=offset)
        first=last-timedelta(days=6)
        items=[r for r in all_rows if r["date"] and first.isoformat()<=r["date"]<=last.isoformat() and in_scope(r) and (category=="all" or r["category"]==category)]
        trends.append({"label":f"{first.day}–{last.day} {last.strftime('%b')}","total_kg":estimate(items)})
    return {"classification":"synthetic" if owner["is_demo"] else "personal","records":selected,"footprint":footprint,"account":owner,
            "green_index":{"value":.35 if owner["is_demo"] else None,"classification":"synthetic_manual","definition":"Manual demo value; formula undefined"},
            "period":{"key":period,"start":start.isoformat(),"end":end.isoformat(),"reference_start":ref_start.isoformat(),"reference_end":ref_end.isoformat()},
            "comparison":{"total_kg":total,"reference_kg":ref_total,"change_fraction":(ref_total-total)/ref_total if ref_total else None,"largest_change":None},
            "coverage":{"pending_trips":sum(r["status"]=="needs_mode" for r in population),"pending_purchases":sum(r["status"]=="needs_items" for r in population),
                        "unknown_emissions":sum(r["co2e_kg"] is None for r in population),"reference_unknown_emissions":sum(r["co2e_kg"] is None for r in ref_population),
                        "missing_plug_days":0,"known_records":sum(r["co2e_kg"] is not None for r in population),"total_records":len(population)},
            "trends":trends,"catalogue":{},"modes":{},"storage":"Saved SQLite records; use /workspace to review and edit an account"}


@living.get("/api/v1/living/activities")
@allow_public_dashboard
def demo_activities():
    return jsonify(activity_preview({}))


@living.post("/api/v1/living/activities/preview")
@allow_public_dashboard
def corrected_activities():
    return jsonify(activity_preview(request.get_json()))
