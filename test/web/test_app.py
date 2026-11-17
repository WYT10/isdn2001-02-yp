import copy
import io
import json
import os
import re
import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "web"))
from flowlab import create_app
from flowlab.db import get_db

KEYS = {"SECRET_KEY": "s" * 32, "ADMIN_TOKEN": "a" * 32, "VIEWER_TOKEN": "v" * 32, "DEVICE_TOKEN": "d" * 32}


def sample(seq=0, **values):
    result = {"seq": seq, "uptime_us": (seq + 1) * 250000, "dt_us": 250000,
              "pulses": 5, "total_pulses": (seq + 1) * 5, "frequency_hz": 20.0,
              "flow_lpm": None, "total_l": None, "pulse": None}
    result.update(values)
    return result


def payload(*samples, device="xiao-01", boot="boot-1"):
    return {"device_id": device, "boot_id": boot, "samples": list(samples or [sample()])}


def auth(role="admin"):
    return {"Authorization": "Bearer " + KEYS[role.upper() + "_TOKEN"]}


class AppTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config = {**KEYS, "DATABASE": str(Path(self.temp.name) / "test.sqlite3"),
                       "TESTING": True, "SESSION_COOKIE_SECURE": False}
        self.app = create_app(self.config)
        self.client = self.app.test_client()

    def ingest(self, body=None, role="device"):
        return self.client.post("/api/v1/readings", json=body or payload(), headers=auth(role))

    def rows(self):
        return self.client.get("/api/v1/readings", headers=auth()).json["items"]

    def login(self, role="admin"):
        html = self.client.get("/").get_data(as_text=True)
        csrf = re.search(r'name="csrf_token" value="([^"]+)"', html).group(1)
        return self.client.post("/login", data={"csrf_token": csrf, "token": KEYS[role.upper() + "_TOKEN"]})

    def test_health_and_database_ready_without_credentials(self):
        self.assertEqual(self.client.get("/healthz").json["status"], "ok")
        self.assertEqual(self.client.get("/readyz").json["database"], "ok")
        self.assertNotIn("DATABASE", self.client.get("/readyz").get_data(as_text=True))

    def test_private_instance_configuration_is_loaded_without_manual_key_overrides(self):
        import bootstrap
        folder = Path(self.temp.name) / "private-instance"
        with patch.dict(os.environ, {"FLOW_INSTANCE": str(folder)}), patch.object(sys, "argv", ["bootstrap.py", "--local"]), redirect_stdout(io.StringIO()):
            bootstrap.main()
            configured = create_app({"TESTING": True})
        self.assertTrue(configured.config["ADMIN_TOKEN"])
        self.assertEqual(configured.test_client().get("/readyz").status_code, 200)

    def test_admin_self_check_leaves_no_research_records(self):
        self.assertEqual(self.client.post("/api/v1/system/check", headers=auth("viewer")).status_code, 403)
        before = self.client.get("/api/v1/system", headers=auth()).json["counts"]
        result = self.client.post("/api/v1/system/check", headers=auth())
        self.assertEqual(result.status_code, 200)
        self.assertTrue(result.json["database_write_rollback"])
        self.assertEqual(before, self.client.get("/api/v1/system", headers=auth()).json["counts"])

    def test_access_boundaries(self):
        self.assertEqual(self.client.get("/api/v1/readings").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/system", headers=auth("viewer")).status_code, 403)
        self.assertEqual(self.client.get("/api/v1/readings", headers=auth("device")).status_code, 403)
        self.assertEqual(self.ingest(role="viewer").status_code, 403)
        self.assertEqual(self.client.get("/api/v1/feedback", headers=auth("viewer")).status_code, 403)

    def test_ingestion_survives_app_restart_and_retains_raw_fields(self):
        self.assertEqual(self.ingest(payload(sample(window_us=1000000))).status_code, 201)
        restarted = create_app(self.config).test_client()
        item = restarted.get("/api/v1/readings", headers=auth()).json["items"][0]
        self.assertEqual(item["raw"]["window_us"], 1000000)
        self.assertIsNone(item["flow_lpm"])
        self.assertIsNone(item["total_l"])

    def test_duplicate_retry_is_idempotent(self):
        body = payload(sample(), sample(1))
        self.assertEqual(self.ingest(body).json["inserted"], 2)
        retry = self.ingest(body)
        self.assertEqual(retry.status_code, 200)
        self.assertEqual(retry.json["duplicates"], 2)
        self.assertEqual(len(self.rows()), 2)

    def test_conflicting_retry_rolls_back_entire_batch(self):
        self.ingest()
        response = self.ingest(payload(sample(1), sample(0, frequency_hz=999)))
        self.assertEqual(response.status_code, 409)
        self.assertEqual(len(self.rows()), 1)

    def test_invalid_batch_does_not_create_partial_device_or_samples(self):
        result = self.ingest(payload(sample(), sample(1, dt_us=0)))
        self.assertEqual(result.status_code, 400)
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.client.get("/api/v1/devices", headers=auth()).json["items"], [])

    def test_numeric_edge_cases_never_turn_into_server_errors(self):
        for value in (True, -1, float("nan"), float("inf"), 10**500, "20"):
            with self.subTest(value_type=type(value).__name__):
                self.assertEqual(self.ingest(payload(sample(frequency_hz=value))).status_code, 400)
        self.assertEqual(self.ingest(payload(sample(seq=True))).status_code, 400)
        self.assertEqual(self.ingest(payload(sample(total_pulses=1))).status_code, 400)
        self.assertEqual(self.ingest(payload(sample(extra=float("nan")))).status_code, 400)

    def test_timestamps_validate_timezone_and_normalize(self):
        result = self.ingest(payload(sample(observed_at="2026-11-17T12:00:00+08:00")))
        self.assertEqual(result.status_code, 201)
        self.assertEqual(self.rows()[0]["observed_at"], "2026-11-17T04:00:00.000Z")
        for value in ("2026-11-17T12:00:00", "", 0):
            self.assertEqual(self.ingest(payload(sample(1, observed_at=value))).status_code, 400)

    def test_counter_resets_are_distinguished_by_boot_id(self):
        self.ingest(payload(sample(), boot="boot-a"))
        self.assertEqual(self.ingest(payload(sample(), boot="boot-b")).status_code, 201)
        self.assertEqual(len(self.rows()), 2)

    def test_zero_calibrated_flow_remains_distinct_from_unknown(self):
        self.ingest(payload(sample(), sample(1, flow_lpm=0, total_l=0)))
        items = self.rows()
        self.assertIsNone(items[0]["flow_lpm"])
        self.assertEqual(items[1]["flow_lpm"], 0)

    def test_pulse_shape_and_limits(self):
        pulse = {"hz": 75, "high_us": 6666.7, "low_us": 6666.7, "duty_pct": 50}
        self.assertEqual(self.ingest(payload(sample(pulse=pulse))).status_code, 201)
        self.assertEqual(self.rows()[0]["pulse"], pulse)
        self.assertEqual(self.ingest(payload(sample(1, pulse={**pulse, "duty_pct": 101}))).status_code, 400)

    def test_pagination_and_device_filter(self):
        self.ingest(payload(sample(), sample(1), sample(2)))
        self.ingest(payload(sample(), device="another"))
        first = self.client.get("/api/v1/readings?limit=2&device_id=xiao-01", headers=auth()).json
        self.assertTrue(first["has_more"])
        next_page = self.client.get("/api/v1/readings?device_id=xiao-01&after_id=" + str(first["next_after_id"]), headers=auth()).json
        self.assertEqual(len(next_page["items"]), 1)
        self.assertEqual(next_page["items"][0]["seq"], 2)

    def test_csv_has_cursor_headers_and_nulls_stay_empty(self):
        self.ingest(payload(sample(), sample(1)))
        response = self.client.get("/api/v1/readings.csv?limit=1", headers=auth())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["X-Has-More"], "true")
        self.assertEqual(response.headers["X-Next-After-Id"], "1")
        self.assertIn("frequency_hz,flow_lpm,total_l", response.get_data(as_text=True))
        self.assertNotIn("None", response.get_data(as_text=True))

    def test_analytics_keeps_devices_separate_and_excludes_null_calibration(self):
        self.ingest(payload(sample(frequency_hz=10), sample(1, frequency_hz=30, flow_lpm=4)))
        self.ingest(payload(sample(frequency_hz=99), device="another"))
        buckets = self.client.get("/api/v1/analytics", headers=auth()).json["items"]
        by_device = {row["device_id"]: row for row in buckets}
        self.assertEqual(by_device["xiao-01"]["mean_hz"], 20)
        self.assertEqual(by_device["xiao-01"]["mean_lpm"], 4)
        self.assertEqual(by_device["another"]["mean_hz"], 99)

    def test_feedback_links_to_correct_measurement(self):
        self.ingest()
        body = {"device_id": "xiao-01", "reading_id": self.rows()[0]["id"], "category": "sensor", "rating": 4, "message": "Steady flow observation"}
        self.assertEqual(self.client.post("/api/v1/feedback", json=body, headers=auth("viewer")).status_code, 201)
        self.assertEqual(self.client.get("/api/v1/feedback", headers=auth()).json["items"][0]["rating"], 4)
        self.assertEqual(self.client.post("/api/v1/feedback", json={**body, "device_id": None}, headers=auth()).status_code, 400)

    def test_browser_login_csrf_and_logout(self):
        self.assertEqual(self.login().status_code, 302)
        page = self.client.get("/").get_data(as_text=True)
        csrf = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
        self.assertIn("Follow the flow.", page)
        body = {"message": "Browser note"}
        self.assertEqual(self.client.post("/api/v1/feedback", json=body).status_code, 403)
        self.assertEqual(self.client.post("/api/v1/feedback", json=body, headers={"X-CSRF-Token": csrf}).status_code, 201)
        self.assertEqual(self.client.get("/api/v1/system", headers={"Authorization": "Bearer invalid"}).status_code, 401)
        self.assertEqual(self.client.post("/logout", data={"csrf_token": csrf}).status_code, 302)
        self.assertEqual(self.client.get("/api/v1/system").status_code, 401)

    def test_non_ascii_keys_and_csrf_fail_cleanly(self):
        self.assertEqual(self.client.get("/api/v1/system", headers={"Authorization": "Bearer \u00e9"}).status_code, 401)
        self.assertEqual(self.client.post("/login", data={"csrf_token": "\u00e9", "token": "\u00e9"}).status_code, 403)
        self.assertEqual(self.login("device").status_code, 401)

    def test_large_and_invalid_requests_are_bounded(self):
        self.assertEqual(self.client.post("/api/v1/readings", data=b"x" * 300000, content_type="application/json", headers=auth()).status_code, 413)
        self.assertEqual(self.client.post("/api/v1/readings", data="not json", content_type="application/json", headers=auth()).status_code, 400)
        self.assertEqual(self.ingest(payload(*[sample(i) for i in range(201)])).status_code, 400)
        self.assertEqual(self.ingest(payload(sample(), sample())).status_code, 400)
        self.assertEqual(self.client.get("/api/v1/readings?limit=1001", headers=auth()).status_code, 400)

    def test_unknown_schema_is_preserved_and_rejected(self):
        with closing(sqlite3.connect(self.config["DATABASE"])) as connection:
            connection.execute("PRAGMA user_version=2")
        with self.assertRaises(RuntimeError):
            create_app(self.config)
        with closing(sqlite3.connect(self.config["DATABASE"])) as connection:
            self.assertEqual(connection.execute("PRAGMA user_version").fetchone()[0], 2)

    def test_demo_is_labelled_idempotent_and_isolated(self):
        runner = self.app.test_cli_runner()
        self.assertEqual(runner.invoke(args=["seed-demo"]).exit_code, 0)
        self.assertEqual(runner.invoke(args=["seed-demo"]).exit_code, 0)
        dashboard = self.client.get("/api/v1/dashboard", headers=auth()).json
        self.assertEqual(dashboard["devices"][0]["is_demo"], 1)
        self.assertEqual(dashboard["summary"]["sample_count"], 120)
        self.assertEqual(self.ingest(payload(sample(), device="demo-xiao")).status_code, 409)

    def test_consistent_database_backup(self):
        self.ingest()
        destination = Path(self.temp.name) / "backup.sqlite3"
        result = self.app.test_cli_runner().invoke(args=["backup-db", str(destination)])
        self.assertEqual(result.exit_code, 0, result.output)
        with closing(sqlite3.connect(destination)) as copy_db:
            self.assertEqual(copy_db.execute("SELECT COUNT(*) FROM readings").fetchone()[0], 1)
        self.assertNotEqual(self.app.test_cli_runner().invoke(args=["backup-db", str(destination)]).exit_code, 0)

    def test_setup_never_overwrites_keys_or_database(self):
        import bootstrap
        folder = Path(self.temp.name) / "setup"
        with patch.dict(os.environ, {"FLOW_INSTANCE": str(folder)}), patch.object(sys, "argv", ["bootstrap.py", "--local"]), redirect_stdout(io.StringIO()):
            bootstrap.main()
            original = (folder / "config.py").read_bytes()
            (folder / "flowlab.sqlite3").write_bytes(b"research-sentinel")
            bootstrap.main()
        self.assertEqual(original, (folder / "config.py").read_bytes())
        self.assertEqual((folder / "flowlab.sqlite3").read_bytes(), b"research-sentinel")


if __name__ == "__main__":
    unittest.main()
