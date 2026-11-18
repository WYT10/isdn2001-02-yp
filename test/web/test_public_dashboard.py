import re
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web"))
from sensorlab import create_app

KEYS = {"SECRET_KEY": "s" * 32, "ADMIN_TOKEN": "a" * 32,
        "VIEWER_TOKEN": "v" * 32, "DEVICE_TOKEN": "d" * 32}


class PublicDashboardTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.app = create_app({**KEYS, "DATABASE": str(Path(folder.name) / "test.sqlite3"),
                               "TESTING": True, "SESSION_COOKIE_SECURE": False})
        self.client = self.app.test_client()

    def csrf(self):
        page = self.client.get("/").text
        return re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)

    def test_anonymous_pages_and_demo_data_open_without_a_viewer_session(self):
        for path in ("/", "/living"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn('id="title-overall"', response.text)
            self.assertIn("Research sign in", response.text)
            self.assertNotIn("Sign out", response.text)
            self.assertIn("tile.openstreetmap.org", response.headers["Content-Security-Policy"])
            for secret in KEYS.values():
                self.assertNotIn(secret, response.text)
        self.assertEqual(self.client.get("/api/v1/living/activities").json["classification"], "synthetic")
        with self.client.session_transaction() as browser:
            self.assertNotIn("role", browser)

    def test_public_corrections_require_csrf_are_bounded_and_never_saved(self):
        path = "/api/v1/living/activities/preview"
        self.assertEqual(self.client.post(path, json={}).status_code, 403)
        headers = {"X-CSRF-Token": self.csrf()}
        self.assertEqual(self.client.post(path, json={}, headers={"X-CSRF-Token": "wrong"}).status_code, 403)
        admin = {"Authorization": "Bearer " + KEYS["ADMIN_TOKEN"]}
        before = self.client.get("/api/v1/system", headers=admin).json["counts"]
        change = {"corrections": [{"id": "trip-02", "mode": "car"}]}
        response = self.client.post(path, json=change, headers=headers)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(next(r for r in response.json["records"] if r["id"] == "trip-02")["mode"], "car")
        fresh = self.client.get("/api/v1/living/activities").json
        self.assertIsNone(next(r for r in fresh["records"] if r["id"] == "trip-02")["mode"])
        self.assertEqual(self.client.post(path, json={"corrections": change["corrections"] * 11}, headers=headers).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/system", headers=admin).json["counts"], before)

    def test_real_sensor_data_admin_and_uploads_remain_protected(self):
        self.csrf()
        for path in ("readings", "readings.csv", "devices", "dashboard", "analytics", "feedback", "system", "living/example"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get("/api/v1/" + path).status_code, 401)
        for path in ("readings", "feedback", "system/check", "living/preview"):
            self.assertEqual(self.client.post("/api/v1/" + path, json={}, headers={"X-CSRF-Token": self.csrf()}).status_code, 401)
        self.assertEqual(self.client.get("/sensors").location, "/login")
        self.assertIn("Access key", self.client.get("/login").text)

    def test_explicit_credentials_are_checked_and_public_mode_can_be_disabled(self):
        path = "/api/v1/living/activities"
        for credential, status in (("invalid", 401), (KEYS["DEVICE_TOKEN"], 403), (KEYS["VIEWER_TOKEN"], 200)):
            self.assertEqual(self.client.get(path, headers={"Authorization": "Bearer " + credential}).status_code, status)
        self.app.config["PUBLIC_DASHBOARD"] = False
        self.assertIn("Access key", self.client.get("/").text)
        self.assertEqual(self.client.get("/living").status_code, 302)
        self.assertEqual(self.client.get(path).status_code, 401)

    def test_research_login_and_logout_do_not_change_public_access(self):
        page = self.client.get("/login").text
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', page).group(1)
        response = self.client.post("/login", data={"csrf_token": csrf, "token": KEYS["ADMIN_TOKEN"]})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/sensors").status_code, 200)
        self.assertEqual(self.client.post("/logout", data={"csrf_token": self.csrf()}).status_code, 302)
        self.assertIn('id="title-overall"', self.client.get("/").text)
        self.assertEqual(self.client.get("/api/v1/system").status_code, 401)
