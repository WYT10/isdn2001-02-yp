import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web"))
from sensorlab import create_app

KEYS = {"SECRET_KEY": "s" * 32, "ADMIN_TOKEN": "a" * 32, "VIEWER_TOKEN": "v" * 32, "DEVICE_TOKEN": "d" * 32}


class ActivityTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.client = create_app({**KEYS, "DATABASE": str(Path(folder.name) / "test.sqlite3"),
                                  "TESTING": True, "SESSION_COOKIE_SECURE": False, "PUBLIC_DASHBOARD": False}).test_client()
        self.auth = {"Authorization": "Bearer " + KEYS["VIEWER_TOKEN"]}

    def preview(self, **body):
        return self.client.post("/api/v1/living/activities/preview", json=body, headers=self.auth)

    def test_one_record_population_drives_totals_map_and_coverage(self):
        data = self.preview().json
        self.assertEqual(data["classification"], "synthetic")
        self.assertEqual(len({r["id"] for r in data["records"]}), len(data["records"]))
        known = [r for r in data["records"] if r["co2e_kg"] is not None]
        self.assertAlmostEqual(data["comparison"]["total_kg"], sum(r["co2e_kg"] for r in known))
        self.assertAlmostEqual(data["footprint"]["total_kg"], data["comparison"]["total_kg"])
        self.assertAlmostEqual(data["footprint"]["grid"]["integrated_kg"], data["footprint"]["total_kg"], delta=.005)
        self.assertEqual(data["coverage"]["known_records"], len(known))
        self.assertEqual(data["coverage"]["unknown_emissions"], len(data["records"])-len(known))
        shower = next(r for r in data["records"] if r["id"] == "shower-01")
        self.assertEqual(shower["litres"], 48)
        self.assertEqual(shower["baseline"]["value"], 40)
        self.assertIsNone(shower["co2e_kg"])

    def test_mode_correction_changes_estimates_once_and_skip_preserves_unknown(self):
        before = self.preview().json
        changes = [{"id": "trip-02", "mode": "mtr"}]
        after = self.preview(corrections=changes).json
        self.assertAlmostEqual(after["comparison"]["total_kg"]-before["comparison"]["total_kg"], 12*.041)
        self.assertAlmostEqual(after["footprint"]["total_kg"], after["comparison"]["total_kg"])
        self.assertEqual(after["coverage"]["pending_trips"], 0)
        self.assertEqual(self.preview(corrections=changes).json, after)
        skipped = self.preview(corrections=[{"id": "trip-02", "mode": "skip"}]).json
        row = next(r for r in skipped["records"] if r["id"] == "trip-02")
        self.assertEqual(row["status"], "unresolved_skipped")
        self.assertIsNone(row["co2e_kg"])
        self.assertEqual(skipped["coverage"]["pending_trips"], 1)
        self.assertEqual(skipped["comparison"]["total_kg"], before["comparison"]["total_kg"])

    def test_purchase_confirmation_does_not_invent_carbon_from_spend(self):
        before = self.preview().json
        after = self.preview(corrections=[{"id": "purchase-02", "catalogue": "shampoo"}]).json
        row = next(r for r in after["records"] if r["id"] == "purchase-02")
        self.assertEqual(row["packaging_g"], 52)
        self.assertIsNone(row["co2e_kg"])
        self.assertEqual(after["coverage"]["pending_purchases"], 0)
        self.assertEqual(after["comparison"]["total_kg"], before["comparison"]["total_kg"])

    def test_shower_correction_is_shared_without_converting_water_to_carbon(self):
        data = self.preview(corrections=[{"id": "shower-01", "litres": 35, "minutes": 6}]).json
        shower = next(r for r in data["records"] if r["id"] == "shower-01")
        self.assertEqual((shower["litres"], shower["minutes"], shower["status"]), (35, 6, "corrected_demo"))
        self.assertEqual(data["comparison"]["total_kg"], self.preview().json["comparison"]["total_kg"])

    def test_date_scope_category_and_reference_have_the_same_grain(self):
        data = self.preview(scope="inside", category="energy", period="fortnight").json
        self.assertTrue(all(r["scope"] == "inside" and "2026-11-09" <= r["date"] <= "2026-11-22" for r in data["records"]))
        self.assertTrue(all(r["category"] == "energy" for r in data["footprint"]["activities"]))
        self.assertEqual(data["period"]["reference_start"], "2026-10-26")
        self.assertAlmostEqual(data["comparison"]["total_kg"], .095*2+3.8*2+3)
        self.assertAlmostEqual(data["comparison"]["reference_kg"], .095*2+3.8*2+4+5)
        outside = self.preview(scope="outside").json
        self.assertEqual(outside["coverage"]["missing_plug_days"], 0)
        empty = self.preview(scope="inside", category="transport").json
        self.assertIsNone(empty["footprint"]["grid"])
        self.assertIsNone(empty["comparison"]["change_fraction"])
        self.assertEqual(empty["coverage"]["total_records"], 0)

    def test_green_index_is_independent_and_compact_map_preserves_mass(self):
        data = self.preview().json
        self.assertEqual(data["green_index"]["value"], .35)
        self.assertEqual(data["green_index"]["classification"], "synthetic_manual")
        self.assertNotIn("index", data["comparison"])
        changed = self.preview(corrections=[{"id": "trip-02", "mode": "car"}]).json
        self.assertNotEqual(data["comparison"]["change_fraction"], changed["comparison"]["change_fraction"])
        self.assertEqual(data["green_index"], changed["green_index"])
        self.assertEqual(self.preview(scope="inside", category="transport").json["green_index"], data["green_index"])
        self.assertEqual(data["footprint"]["bandwidth_m"], 150)
        locations = {(r["lat"], r["lon"]) for r in data["footprint"]["activities"]}
        self.assertEqual(len(locations), 11)
        broad = self.preview(bandwidth_m=750).json["footprint"]
        self.assertEqual(data["footprint"]["total_kg"], broad["total_kg"])
        for field in (data["footprint"], broad):
            self.assertAlmostEqual(field["grid"]["integrated_kg"], field["total_kg"], delta=.005)

    def test_bad_fields_bounds_or_reference_edits_are_rejected(self):
        cases = [{"period": "year"}, {"category": []}, {"scope": "someone"}, {"bandwidth_m": 0},
                 {"extra": "field"}, {"corrections": "bad"}, {"corrections": [{"id": "shower-01", "litres": True, "minutes": 5}]},
                 {"corrections": [{"id": "shower-01", "litres": float("nan"), "minutes": 5}]},
                 {"corrections": [{"id": "trip-02", "mode": "plane"}]}, {"corrections": [{"id": "rail-01-w1", "mode": "car"}]},
                 {"corrections": [{"id": "purchase-02", "catalogue": "unverified-api"}]},
                 {"corrections": [{"id": "trip-02", "mode": "mtr", "co2e_kg": 0}]},
                 {"corrections": [{"id": "trip-02", "mode": "mtr"}]*2}]
        for body in cases:
            with self.subTest(body=body):
                self.assertEqual(self.preview(**body).status_code, 400)

    def test_subdivisions_reconcile_without_counting_unknowns_as_filler(self):
        data = self.preview().json
        self.assertEqual(len(data["records"]), 20)
        self.assertAlmostEqual(data["footprint"]["total_kg"], 18.3404)
        categories = {r["name"]: r for r in data["footprint"]["categories"]}
        self.assertEqual(set(categories), {"shopping", "food", "energy", "transport", "other"})
        for category, total in categories.items():
            children = [r for r in data["records"] if r["category"] == category and r["co2e_kg"] is not None]
            self.assertAlmostEqual(sum(r["co2e_kg"] for r in children), total["co2e_kg"])
            self.assertTrue(all(r["subcategory"] and r["tree_label"] for r in children))
        self.assertAlmostEqual(categories["other"]["co2e_kg"], .42)
        shopping = self.preview(category="shopping").json
        self.assertEqual(shopping["coverage"]["unknown_emissions"], 2)
        self.assertEqual(len(shopping["footprint"]["activities"]), 6)
        self.assertAlmostEqual(shopping["footprint"]["total_kg"], 8.35)
        self.assertIsNone(next(r for r in shopping["records"] if r["id"] == "purchase-02")["co2e_kg"])

    def test_roles_csrf_and_research_data_are_preserved(self):
        self.assertEqual(self.client.get("/api/v1/living/activities").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/living/activities", headers={"Authorization": "Bearer "+KEYS["DEVICE_TOKEN"]}).status_code, 403)
        admin = {"Authorization": "Bearer "+KEYS["ADMIN_TOKEN"]}
        before = self.client.get("/api/v1/system", headers=admin).json["counts"]
        with self.client.session_transaction() as session:
            session["role"] = "viewer"
            session["csrf"] = "browser-token"
        self.assertEqual(self.client.post("/api/v1/living/activities/preview", json={}).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/living/activities/preview", json={}, headers={"X-CSRF-Token": "browser-token"}).status_code, 200)
        self.preview(corrections=[{"id": "trip-02", "mode": "mtr"}])
        self.assertEqual(self.client.get("/api/v1/system", headers=admin).json["counts"], before)
        page = self.client.get("/").text
        self.assertNotIn('data-tab="home"', page)
        self.assertLess(page.index('data-tab="overall"'), page.index('data-tab="shopping"'))
        self.assertIn("flow-chart", self.client.get("/sensors").text)
        self.assertNotIn("tile.openstreetmap.org", self.client.get("/sensors").headers["Content-Security-Policy"])
