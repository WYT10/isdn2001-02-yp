"""Read-only green-living previews. No personal activity or sensor DB writes."""
import math

from flask import Blueprint, abort, jsonify, redirect, render_template, request, session, url_for

from .auth import require_roles

living = Blueprint("living", __name__)
CATEGORIES = ("energy", "water", "transport", "shopping", "food", "other")
BANDWIDTHS = (150, 250, 500, 750, 1250, 2000)
EXAMPLE = [
    {"name": "Home energy", "category": "energy", "scope": "inside", "lat": 22.3364, "lon": 114.2655, "co2e_kg": 12},
    {"name": "Home water", "category": "water", "scope": "inside", "lat": 22.3364, "lon": 114.2655, "co2e_kg": 0.15},
    {"name": "Road commute", "category": "transport", "scope": "outside", "lat": 22.3280, "lon": 114.2460, "co2e_kg": 8.5},
    {"name": "Cafe", "category": "food", "scope": "outside", "lat": 22.3158, "lon": 114.2645, "co2e_kg": 1.2},
    {"name": "Grocery shop", "category": "shopping", "scope": "outside", "lat": 22.3075, "lon": 114.2600, "co2e_kg": 2.6},
    {"name": "Clothes shopping", "category": "shopping", "scope": "outside", "lat": 22.3120, "lon": 114.2510, "co2e_kg": 4.4},
    {"name": "Rail journey", "category": "transport", "scope": "outside", "lat": 22.3220, "lon": 114.2580, "co2e_kg": 0.45},
    {"name": "Bus journey", "category": "transport", "scope": "outside", "lat": 22.3325, "lon": 114.2580, "co2e_kg": 0.85},
]


def validate_activities(rows):
    if not isinstance(rows, list) or len(rows) > 50:
        abort(400, description="Use an array of at most 50 activities")
    result = []
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"name", "category", "scope", "lat", "lon", "co2e_kg"}:
            abort(400, description="Each activity needs name, category, scope, lat, lon and co2e_kg")
        if not isinstance(row["name"], str) or not 1 <= len(row["name"].strip()) <= 80:
            abort(400, description="Activity names must contain 1–80 characters")
        if row["category"] not in CATEGORIES or row["scope"] not in ("inside", "outside"):
            abort(400, description="Unknown category or inside/outside scope")
        for key, low, high in (("lat", -75, 75), ("lon", -180, 180), ("co2e_kg", 0, 1000000)):
            value = row[key]
            if type(value) not in (float, int) or not low <= value <= high or not math.isfinite(value):
                abort(400, description=f"{key} is outside the supported numeric range")
        result.append({**row, "name": row["name"].strip()})
    if result:
        latitudes, longitudes = [r["lat"] for r in result], [r["lon"] for r in result]
        if max(latitudes) - min(latitudes) > 0.8 or max(longitudes) - min(longitudes) > 0.8:
            abort(400, description="This city-scale preview supports a span of at most 0.8 degrees per axis")
    return result


def density_grid(rows, bandwidth, size=96):
    """Mass-weighted isotropic Gaussian kernels in a local metre projection."""
    if not rows or not any(r["co2e_kg"] > 0 for r in rows):
        return None
    radius = 6371008.8
    lat0 = sum(r["lat"] for r in rows) / len(rows)
    lon0 = sum(r["lon"] for r in rows) / len(rows)
    metres_lat = radius * math.pi / 180
    metres_lon = metres_lat * math.cos(math.radians(lat0))
    points = [((r["lon"] - lon0) * metres_lon, (r["lat"] - lat0) * metres_lat, r["co2e_kg"]) for r in rows]
    padding = 4 * bandwidth
    west, east = min(p[0] for p in points) - padding, max(p[0] for p in points) + padding
    south, north = min(p[1] for p in points) - padding, max(p[1] for p in points) + padding
    dx, dy = (east - west) / size, (north - south) / size
    normalizer = 1000000 / (2 * math.pi * bandwidth**2)
    values = []
    for y in range(size):
        py = north - (y + 0.5) * dy
        for x in range(size):
            px = west + (x + 0.5) * dx
            values.append(sum(weight * normalizer * math.exp(-((px - ax)**2 + (py - ay)**2) /
                          (2 * bandwidth**2)) for ax, ay, weight in points))
    return {"size": size, "values": values, "max": max(values),
            "bounds": [[lat0 + south / metres_lat, lon0 + west / metres_lon],
                       [lat0 + north / metres_lat, lon0 + east / metres_lon]],
            "cell_area_km2": dx * dy / 1000000,
            "integrated_kg": math.fsum(values) * dx * dy / 1000000,
            "unit": "kg CO2e / km2"}


def preview(rows, scope, category, bandwidth, classification):
    if scope not in ("all", "inside", "outside") or category not in ("all", *CATEGORIES):
        abort(400, description="Unknown filter")
    if type(bandwidth) is not int or bandwidth not in BANDWIDTHS:
        abort(400, description="Choose a supported smoothing distance")
    rows = validate_activities(rows)
    selected = [r for r in rows if (scope == "all" or r["scope"] == scope) and
                (category == "all" or r["category"] == category)]
    total = math.fsum(r["co2e_kg"] for r in selected)
    categories = [{"name": name, "co2e_kg": math.fsum(r["co2e_kg"] for r in selected if r["category"] == name)}
                  for name in CATEGORIES if any(r["category"] == name for r in selected)]
    for item in categories:
        item["share"] = item["co2e_kg"] / total if total else 0
    return {"activities": selected, "categories": sorted(categories, key=lambda r: -r["co2e_kg"]),
            "total_kg": total, "inside_kg": math.fsum(r["co2e_kg"] for r in selected if r["scope"] == "inside"),
            "outside_kg": math.fsum(r["co2e_kg"] for r in selected if r["scope"] == "outside"),
            "grid": density_grid(selected, bandwidth), "scope": scope, "category": category,
            "bandwidth_m": bandwidth, "classification": classification,
            "provenance": {"source": "Illustrative inputs; not measured personal emissions" if classification == "example" else
                           "User-supplied preview; emission estimates are not independently verified",
                           "grain": "One activity with a single attributed location and kg CO2e amount",
                           "method": "Sum mass-weighted 2D Gaussian kernels in local equirectangular metres; sigma is the selected smoothing distance; grid padded by four sigma",
                           "limitations": "Point attribution, not a GPS route or air-pollution measurement. No emission conversion factors or uncertainty intervals have been supplied.",
                           "storage": "Preview only; no database writes"}}


@living.get("/living")
def page():
    if session.get("role") not in ("admin", "viewer"):
        return redirect(url_for("index"))
    return render_template("living.html", role=session["role"])


@living.get("/api/v1/living/example")
@require_roles("viewer", "admin")
def example():
    try:
        bandwidth = int(request.args.get("bandwidth_m", 750))
    except ValueError:
        abort(400, description="Invalid smoothing distance")
    return jsonify(preview(EXAMPLE, request.args.get("scope", "all"), request.args.get("category", "all"), bandwidth, "example"))


@living.post("/api/v1/living/preview")
@require_roles("viewer", "admin")
def custom():
    body = request.get_json()
    if not isinstance(body, dict) or set(body) - {"activities", "scope", "category", "bandwidth_m"}:
        abort(400, description="Invalid preview fields")
    return jsonify(preview(body.get("activities"), body.get("scope", "all"), body.get("category", "all"),
                           body.get("bandwidth_m", 750), "user_preview"))
