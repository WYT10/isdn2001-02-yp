import copy
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web"))
from sensorlab import create_app
from sensorlab.living import EXAMPLE, density_grid

KEYS = {"SECRET_KEY": "s" * 32, "ADMIN_TOKEN": "a" * 32, "VIEWER_TOKEN": "v" * 32, "DEVICE_TOKEN": "d" * 32}


class LivingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.app = create_app({**KEYS, "DATABASE": str(Path(self.temp.name) / "test.sqlite3"),
                               "TESTING": True, "SESSION_COOKIE_SECURE": False})
        self.client = self.app.test_client()
        self.viewer = {"Authorization": "Bearer " + KEYS["VIEWER_TOKEN"]}

    def preview(self, rows, **filters):
        return self.client.post("/api/v1/living/preview", json={"activities": rows, **filters}, headers=self.viewer)

    def test_access_and_existing_database_are_preserved(self):
        self.assertEqual(self.client.get("/living").status_code, 302)
        self.assertEqual(self.client.get("/api/v1/living/example").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/living/example", headers={"Authorization": "Bearer " + KEYS["DEVICE_TOKEN"]}).status_code, 403)
        admin = {"Authorization": "Bearer " + KEYS["ADMIN_TOKEN"]}
        before = self.client.get("/api/v1/system", headers=admin).json["counts"]
        self.assertEqual(self.preview(EXAMPLE).status_code, 200)
        self.assertEqual(self.client.get("/api/v1/system", headers=admin).json["counts"], before)

    def test_totals_shares_and_filters_use_the_same_activity_population(self):
        data = self.client.get("/api/v1/living/example", headers=self.viewer).json
        self.assertEqual(data["classification"], "example")
        self.assertAlmostEqual(data["total_kg"], 30.15)
        self.assertAlmostEqual(data["inside_kg"] + data["outside_kg"], data["total_kg"])
        self.assertAlmostEqual(sum(r["share"] for r in data["categories"]), 1)
        self.assertAlmostEqual(sum(r["co2e_kg"] for r in data["categories"]), data["total_kg"])
        inside = self.client.get("/api/v1/living/example?scope=inside", headers=self.viewer).json
        self.assertAlmostEqual(inside["total_kg"], 12.15)
        self.assertEqual(len(inside["activities"]), 2)
        transport = self.client.get("/api/v1/living/example?scope=outside&category=transport", headers=self.viewer).json
        self.assertAlmostEqual(transport["total_kg"], 9.8)
        self.assertEqual(len(transport["activities"]), 3)

    def test_gaussian_density_conserves_mass_and_repeated_locations_add(self):
        one = density_grid(EXAMPLE[:1], 750)
        two = density_grid(EXAMPLE[:2], 750)
        self.assertEqual(one["unit"], "kg CO2e / km2")
        self.assertAlmostEqual(one["integrated_kg"], 12, delta=0.002)
        self.assertAlmostEqual(two["integrated_kg"], 12.15, delta=0.002)
        self.assertAlmostEqual(two["max"] / one["max"], 12.15 / 12)
        wider = density_grid(EXAMPLE[:1], 1500)
        self.assertAlmostEqual(wider["max"] * 4, one["max"])
        for sigma in (250, 750, 2000):
            grid = density_grid(EXAMPLE, sigma)
            self.assertAlmostEqual(grid["integrated_kg"], 30.15, delta=0.01)
            self.assertTrue(all(math.isfinite(v) and v >= 0 for v in grid["values"]))

    def test_empty_and_zero_activity_sets_have_no_fabricated_density(self):
        for rows in ([], [{**EXAMPLE[0], "co2e_kg": 0}]):
            data = self.preview(rows).json
            self.assertEqual(data["total_kg"], 0)
            self.assertIsNone(data["grid"])
            self.assertEqual(sum(c["share"] for c in data["categories"]), 0)

    def test_invalid_bounds_numbers_fields_and_filters_are_rejected(self):
        for field, value in (("lat", True), ("lat", 91), ("lon", -181), ("co2e_kg", -1),
                             ("co2e_kg", float("nan")), ("co2e_kg", float("inf")), ("co2e_kg", 10**300),
                             ("category", "unknown"), ("scope", "unknown"), ("name", "")):
            with self.subTest(field=field, value=str(value)[:20]):
                rows = copy.deepcopy(EXAMPLE[:1]); rows[0][field] = value
                self.assertEqual(self.preview(rows).status_code, 400)
        self.assertEqual(self.preview(EXAMPLE * 7).status_code, 400)
        self.assertEqual(self.preview([{**EXAMPLE[0], "lat": 0}, EXAMPLE[1]]).status_code, 400)
        self.assertEqual(self.preview(EXAMPLE, bandwidth_m=0).status_code, 400)
        self.assertEqual(self.preview(EXAMPLE, bandwidth_m=750.0).status_code, 400)
        self.assertEqual(self.preview(EXAMPLE, scope="unknown").status_code, 400)
        self.assertEqual(self.preview(EXAMPLE, extra="not allowed").status_code, 400)

    def test_browser_preview_requires_csrf_and_tile_policy_is_scoped(self):
        with self.client.session_transaction() as session:
            session["role"] = "viewer"; session["csrf"] = "browser-csrf"
        self.assertEqual(self.client.post("/api/v1/living/preview", json={"activities": EXAMPLE}).status_code, 403)
        response = self.client.post("/api/v1/living/preview", json={"activities": EXAMPLE}, headers={"X-CSRF-Token": "browser-csrf"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["classification"], "user_preview")
        page = self.client.get("/living")
        self.assertEqual(page.status_code, 200)
        self.assertIn("https://tile.openstreetmap.org", page.headers["Content-Security-Policy"])
        self.assertEqual(page.headers["Referrer-Policy"], "strict-origin-when-cross-origin")
        self.assertNotIn("tile.openstreetmap.org", self.client.get("/").headers["Content-Security-Policy"])
        self.assertIn("green-index-gauge", page.get_data(as_text=True))
