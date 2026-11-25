"""Build a reproducible fictional timeline from the supplied reference patterns."""
import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
import json
from pathlib import Path
import random
import re
import xml.etree.ElementTree as ET
import zipfile
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def audit(folder):
    results = []
    for path in sorted(folder.glob("*.xlsx")):
        with zipfile.ZipFile(path) as book:
            strings = ["".join(x.itertext()) for x in ET.fromstring(book.read("xl/sharedStrings.xml")).findall("m:si", NS)] if "xl/sharedStrings.xml" in book.namelist() else []
            targets = {x.attrib["Id"]: x.attrib["Target"] for x in ET.fromstring(book.read("xl/_rels/workbook.xml.rels"))}
            sheets = []
            for sheet in ET.fromstring(book.read("xl/workbook.xml")).find("m:sheets", NS):
                target = targets[sheet.attrib["{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"]]
                xml = ET.fromstring(book.read(target.lstrip("/") if target.startswith("/") else "xl/" + target))
                rows = []
                for row in xml.findall(".//m:sheetData/m:row", NS):
                    values = {}
                    for cell in row.findall("m:c", NS):
                        value = cell.findtext("m:v", default="", namespaces=NS)
                        if cell.attrib.get("t") == "s":
                            value = strings[int(value)] if value else ""
                        elif cell.attrib.get("t") == "inlineStr":
                            value = "".join(cell.find("m:is", NS).itertext())
                        values[re.sub(r"\d", "", cell.attrib["r"])] = value
                    if any(values.values()):
                        rows.append(values)
                header = next((r for r in rows if any("Date" in v for v in r.values()) and any("Source" in v for v in r.values())), {})
                date_col = next((c for c, v in header.items() if "Date" in v), None)
                mode_col = next((c for c, v in header.items() if "Mode" in v), None)
                events = []
                for row in rows:
                    try:
                        serial = float(row.get(date_col, ""))
                        if 40000 <= serial < 60000:
                            events.append(row)
                    except ValueError:
                        pass
                sheets.append({"sheet": sheet.attrib["name"], "dated_rows": len(events), "headers": list(header.values()),
                               "mode_codes": dict(Counter(r.get(mode_col, "") for r in events)) if mode_col else {},
                               "formula_count": len(xml.findall(".//m:f", NS))})
            results.append({"file": path.name, "sheets": sheets})
    shopping = json.loads((folder / "Shopping.json").read_text(encoding="utf-8-sig"))
    return {"workbooks": results, "inventory_items": len(shopping["inventory_items"]),
            "decision": "Pattern-level synthesis for one fictional person; no original routes, merchants, identities or raw rows published. Conflicting diaries are not concatenated. Inventory is not charged as daily purchases."}


def build(profile):
    rng = random.Random(20261125)
    factors = []
    def factor(key, value, unit, boundary, demo=True, url=None):
        factors.append({"id": key, "value": value, "unit": unit, "boundary": boundary,
                        "classification": "synthetic" if demo else "published",
                        "region": "Demo only" if demo else "Hong Kong", "year": 2025 if not demo else 2026,
                        "version": "demo-1" if demo else "MTR-2025", "source_url": url,
                        "source": "Illustrative coefficient for the demo; not a researched footprint" if demo else "MTR Sustainable Finance Report 2025, heavy rail operational GHG per passenger-km"})
    factor("mtr-2025", .041, "passenger_km", "Rail operation, not vehicle/infrastructure lifecycle", False,
           "https://www.mtr.com.hk/sustainability/assets/pdf/en/2025/MTR_Sustainable_Finance_Rpt_2025.pdf")
    factor("bus-demo", .08, "passenger_km", "Illustrative vehicle operation")
    factor("car-demo", .16, "passenger_km", "Illustrative occupancy-adjusted operation")
    factor("walk-demo", 0, "passenger_km", "Direct vehicle operation only; excludes food/equipment")
    factor("electricity-demo", .38, "kwh", "Illustrative electricity supply")
    factor("water-demo", .00045, "litre", "Illustrative cold-water supply; excludes heating")
    for key, value in (("shampoo", 3.8), ("detergent", 4.2), ("noodles", 1.1), ("snacks", .9),
                       ("tissues", 2.8), ("jeans", 18), ("shirts", 9), ("underwear", 4), ("lunch", 1.6), ("coffee", .35)):
        factor(key + "-demo", value, "item", "Illustrative production-to-retail including packaging; excludes household-use energy; packaging is not added again")
    home = (22.3154, 114.2644)
    campus = (22.3364, 114.2655)
    places = {"home": home, "campus": campus, "mall": (22.3118,114.2648), "market": (22.3184,114.2632),
              "cafe": (22.3358,114.2648), "station": (22.3155,114.2641), "city": (22.3193,114.1707),
              "park": (22.3070,114.2600), "library": (22.3346,114.2630)}
    events = []
    def add(day, clock, kind, name, category, subcategory, quantity=None, unit=None, factor_id=None,
            share=1, place="home", minutes=5, items=None, amount=None, status="confirmed", metadata=None):
        started = datetime.combine(day, datetime.strptime(clock, "%H:%M").time(), ZoneInfo("Asia/Hong_Kong"))
        ended = started + timedelta(minutes=minutes)
        lat, lon = places[place]
        row = {"id": f"demo-{day:%Y%m%d}-{len(events):04d}", "kind": kind, "name": name, "category": category,
               "subcategory": subcategory, "occurred_at": started.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
               "ended_at": ended.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"), "timezone": "Asia/Hong_Kong",
               "quantity": quantity, "unit": unit, "factor_id": factor_id, "share": share, "status": status,
               "scope": "inside" if kind == "household" else "outside", "lat": lat, "lon": lon,
               "amount_minor": amount, "currency": "HKD" if amount is not None else None,
               "classification": "synthetic", "source_type": "demo_synthesis", "items": items or [],
               "metadata": {"fixture_or_context": subcategory, "duration_minutes": minutes,
                            "input_status": "fictional, not observed", **(metadata or {})}}
        events.append(row)
        return row
    catalogue = [("Shampoo, 500 mL", "Personal care", "shampoo", 52, 4800),
                 ("Laundry detergent, 2 L", "Home care", "detergent", 120, 7200),
                 ("Noodles, five-pack", "Groceries", "noodles", 22, 2600),
                 ("Mixed snacks", "Groceries", "snacks", 35, 3200),
                 ("Tissues, six-pack", "Home care", "tissues", 24, 3800),
                 ("Cotton jeans", "Clothing", "jeans", 18, 24900),
                 ("Cotton shirt", "Clothing", "shirts", 12, 9900),
                 ("Underwear pack", "Clothing", "underwear", 16, 7900)]
    start = date(2026, 10, 26)
    for offset in range(28):
        day = start + timedelta(days=offset)
        week = offset // 7
        litres = round(rng.uniform(40, 59) - week * 1.2, 1)
        add(day, "07:05", "household", "Morning shower", "water", "Bathroom", litres, "litre", "water-demo",
            minutes=round(litres / 6, 1), metadata={"pulses": round(litres * 450), "demo_pulses_per_litre": 450,
              "measurement_basis": "Synthetic calibrated session, unrelated to the physical board"})
        add(day, "19:45", "household", "Other tap use", "water", "Kitchen and taps", round(rng.uniform(20, 35),1),
            "litre", "water-demo", minutes=18, metadata={"excludes": "Morning shower"})
        add(day, "23:59", "household", "Shared home electricity", "energy", "Other appliances",
            round(rng.uniform(8, 11),3), "kwh", "electricity-demo", share=1/3, minutes=0,
            metadata={"household_members": 3, "measurement_basis": "Synthetic daily subtotal", "excludes": "Separately listed cooking energy"})
        if day.weekday() in (1,3,5):
            add(day, "19:00", "household", "Cooking session", "energy", "Hot pot / cooker", round(rng.uniform(.4,.8),3),
                "kwh", "electricity-demo", share=1/3, minutes=30,
                metadata={"household_members": 3, "measurement_basis": "Synthetic integrated plug session; not rated watts"})
        if day.weekday() < 5:
            for clock, origin, destination, label in (("08:15",home,campus,"To campus"),("17:40",campus,home,"Home from campus")):
                mode = "car" if week == 1 and day.weekday() == 2 else "bus"
                row = add(day,clock,"transport",label,"transport",mode.title(),4.7,"passenger_km",mode+"-demo",place="campus" if origin==home else "home",minutes=20,
                          metadata={"mode":mode,"origin":"Home" if origin==home else "Campus","destination":"Campus" if origin==home else "Home"})
                at = datetime.fromisoformat(row["occurred_at"].replace("Z","+00:00"))
                row["metadata"]["trace"] = [{"lat":round(origin[0]+(destination[0]-origin[0])*i/5,6),
                    "lon":round(origin[1]+(destination[1]-origin[1])*i/5,6),"at":(at+timedelta(minutes=4*i)).isoformat().replace("+00:00","Z")} for i in range(6)]
                row["metadata"]["trace_basis"] = "Interpolated fictional points, not a GPS measurement or road route"
            if day.weekday() in (0,2,4):
                add(day,"12:35","shopping","Campus lunch","food","Meals",place="campus",amount=4200,
                    items=[{"name":"Lunch set","quantity":1,"unit":"item","factor_id":"lunch-demo","packaging_g":12}],minutes=30)
        elif day.weekday() == 5:
            for clock, place, label in (("10:00","city","Weekend city trip"),("18:00","home","Home from city")):
                add(day,clock,"transport",label,"transport","MTR",22.4,"passenger_km","mtr-2025",place=place,minutes=40,
                    metadata={"mode":"mtr","distance_basis":"Fictional passenger distance; not a route API result"})
        else:
            add(day,"16:00","transport","Walk to the park","transport","Walking",2.1,"passenger_km","walk-demo",place="park",minutes=28,metadata={"mode":"walk"})
        if day.weekday() in (1,5):
            item = catalogue[(week * 2 + (day.weekday() == 5)) % len(catalogue)]
            add(day,"18:35" if day.weekday()==1 else "15:00","shopping",item[0],"shopping",item[1],place="market" if day.weekday()==1 else "city",
                amount=item[4],items=[{"name":item[0],"quantity":1,"unit":"item","factor_id":item[2]+"-demo","packaging_g":item[3]}],minutes=10,
                metadata={"catalogue_basis":"Product type adapted from supplied inventory; price/quantity/weight/factor are fictional"})
        if day.weekday() == 4:
            add(day,"15:20","shopping","Coffee","food","Cafe",place="cafe",amount=2800,
                items=[{"name":"Coffee","quantity":1,"unit":"item","factor_id":"coffee-demo","packaging_g":8}],minutes=10)
    add(date(2026,11,18),"18:10","shopping","Purchase awaiting receipt items","shopping","Unidentified",place="mall",amount=4500,status="needs_review")
    add(date(2026,11,19),"13:10","transport","Trip awaiting mode","transport","Unconfirmed",3.2,"passenger_km",place="library",minutes=15,status="needs_review",metadata={"mode":None})
    add(date(2026,11,20),"18:10","shopping","Wallet top-up","shopping","Transfer",place="station",amount=10000,status="excluded",metadata={"transaction_type":"topup","reason":"Transfer of funds; not an additional consumption event"})
    return {"schema_version":1,"dataset_id":"alex-demo-v1","classification":"synthetic","timezone":"Asia/Hong_Kong",
            "person":{"id":"demo-alex","name":"Alex · fictional","household_members":3,"is_demo":True},
            "period":{"start":"2026-10-26","end":"2026-11-22"},"green_index":{"value":.35,"method":"Manually assigned demo score, independent of calculated period change"},
            "provenance":{"method":profile["decision"],"source_workbooks":len(profile["workbooks"]),"source_inventory_items":profile["inventory_items"],
                          "rules":["All activity timestamps, prices, coordinates and quantities are fictional.","One coherent fictional daily schedule, not an assertion that the original diaries belong to one person.",
                                   "Household electricity allocated one third; personal shower allocated fully.","Product footprints booked once at purchase; no daily asset amortization.",
                                   "Demo factors are labelled; MTR factor is published but its activity inputs remain synthetic.","Top-ups excluded; missing items/mode have unknown emissions.","Cold-water factor excludes heating; separately listed energy subtotals do not overlap."]},
            "factors":factors,"events":sorted(events,key=lambda r:(r["occurred_at"],r["id"]))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--references",type=Path,default=ROOT/"database")
    args = parser.parse_args()
    profile = audit(args.references)
    target = ROOT/".local/research/source_audit.json"
    target.parent.mkdir(parents=True,exist_ok=True)
    target.write_bytes((json.dumps(profile,ensure_ascii=True,indent=2)+"\n").encode())
    dataset = build(profile)
    for destination in (ROOT/"web/sensorlab/datasets/alex.json",ROOT/"dist/livegreen-demo.json"):
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes((json.dumps(dataset,ensure_ascii=True,indent=2)+"\n").encode())
    print(json.dumps({"dataset":dataset["dataset_id"],"events":len(dataset["events"]),"factors":len(dataset["factors"]),"classification":"synthetic","period":dataset["period"]}))


if __name__ == "__main__":
    main()
