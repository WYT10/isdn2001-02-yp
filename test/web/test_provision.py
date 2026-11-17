import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("provision", ROOT / "tools/generate_wifi_config.py")
provision = importlib.util.module_from_spec(spec)
spec.loader.exec_module(provision)


class ProvisionTests(unittest.TestCase):
    def test_public_build_has_no_private_network_or_cloud_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            provision.generate(base / "wifi.json", base / "private.h", base / "cloud.json")
            header = (base / "private.h").read_text()
            self.assertIn("SENSORLAB_PRIVATE_ENTERPRISE 0", header)
            self.assertIn("SENSORLAB_PRIVATE_CLOUD 0", header)

    def test_cloud_profile_accepts_only_https_device_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            base = Path(folder)
            profile = base / "cloud.json"
            for url in ("http://example.org/api", "https://user:pass@example.org/api", "https://example.org/#bad"):
                profile.write_text(json.dumps({"url": url, "device_token": "d" * 32}))
                with self.assertRaises(ValueError):
                    provision.generate(base / "absent", base / "private.h", profile)
            profile.write_text(json.dumps({"url": "https://example.org/api/v1/readings", "device_token": "d" * 32}))
            provision.generate(base / "absent", base / "private.h", profile)
            self.assertIn("SENSORLAB_PRIVATE_CLOUD 1", (base / "private.h").read_text())
            profile.write_text(json.dumps({"url": "https://example.org/api", "device_token": "d" * 32, "admin_token": "a" * 32}))
            with self.assertRaises(ValueError):
                provision.generate(base / "absent", base / "private.h", profile)
