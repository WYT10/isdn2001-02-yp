import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("deploy", ROOT / "tools" / "deploy_pythonanywhere.py")
deploy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(deploy)


class FakeAPI:
    def __init__(self, storage, fail_at=None):
        self.storage = dict(storage)
        self.fail_at = fail_at
        self.writes = 0
        self.reloaded = []

    def get_file(self, path):
        return self.storage.get(path)

    def put_file(self, path, body):
        self.writes += 1
        if self.writes == self.fail_at:
            raise RuntimeError("Simulated upload failure")
        self.storage[path] = body

    def delete_file(self, path):
        self.storage.pop(path, None)

    def reload(self, domain):
        self.reloaded.append(domain)


class DeployTests(unittest.TestCase):
    def test_bundle_contains_only_public_web_source_and_manifest(self):
        files, release = deploy.sources()
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "starter.zip"
            deploy.bundle(target, files)
            with zipfile.ZipFile(target) as archive:
                names = archive.namelist()
                self.assertIn("app.py", names)
                self.assertIn("flask_app.py", names)
                self.assertIn("flowlab/schema.sql", names)
                self.assertFalse(any("instance/" in name or name.endswith((".md", ".sqlite3", ".bin")) for name in names))
                manifest = json.loads(archive.read("release.json"))
                self.assertEqual(manifest["release"], release)
                for name, digest in manifest["files"].items():
                    self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), digest)

    def test_extracted_zip_starts_with_pythonanywhere_default_entry_point(self):
        files, release = deploy.sources()
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp) / "mysite"
            folder.mkdir()
            target = Path(temp) / "starter.zip"
            deploy.bundle(target, files)
            with zipfile.ZipFile(target) as archive:
                archive.extractall(folder)
            subprocess.run([sys.executable, "bootstrap.py"], cwd=folder,
                           check=True, capture_output=True, timeout=20)
            code = (
                "from flask_app import app; from app import app as alias; "
                "assert alias is app; "
                "client=app.test_client(); "
                "assert client.get('/').status_code==200; "
                "assert client.get('/readyz').json['database']=='ok'; "
                f"assert client.get('/healthz').json['release']=={release!r}"
            )
            subprocess.run([sys.executable, "-c", code], cwd=folder,
                           check=True, capture_output=True, timeout=20)

    def test_unknown_api_host_is_rejected_before_token_can_be_sent(self):
        with self.assertRaises(ValueError):
            deploy.PythonAnywhere("researcher", "private-account-token", "untrusted.example")

    def test_official_file_api_uses_multipart_content_field(self):
        client = deploy.PythonAnywhere("researcher", "account-token", interval=0)
        with patch.object(deploy, "http", return_value=(201, b"")) as request:
            client.put_file("/home/researcher/flowlab/app.py", b"public code")
        args, kwargs = request.call_args
        self.assertEqual(args[0], "POST")
        self.assertIn("/api/v0/user/researcher/files/path/home/researcher/flowlab/app.py", args[1])
        self.assertEqual(kwargs["token"], "account-token")
        self.assertIn(b'name="content"', kwargs["data"])
        self.assertIn(b"public code", kwargs["data"])

    def test_public_health_checks_never_receive_account_credentials(self):
        responses = [(200, b'{"status":"ok","release":"expected"}'),
                     (200, b'{"status":"ok","database":"ok","schema_version":1}')]
        with patch.object(deploy, "http", side_effect=responses) as request:
            deploy.health_check("researcher.pythonanywhere.com", "expected")
        for call in request.call_args_list:
            self.assertNotIn("token", call.kwargs)

    def test_wrong_release_is_not_accepted_as_success(self):
        responses = [(200, b'{"status":"ok","release":"old"}'),
                     (200, b'{"status":"ok","database":"ok","schema_version":1}')]
        with patch.object(deploy, "http", side_effect=responses):
            with self.assertRaises(RuntimeError):
                deploy.health_check("researcher.pythonanywhere.com", "new")

    def test_failed_upload_restores_previous_files_and_preserves_data(self):
        original = {"/home/researcher/flowlab/app.py": b"old app", "/home/researcher/flowlab/instance/research.sqlite3": b"research-data"}
        client = FakeAPI(original, fail_at=2)
        files = {"app.py": b"new app", "new.py": b"new module", "release.json": b'{"release":"new"}'}
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(RuntimeError, "previous source files restored"):
                deploy.deploy_files(client, files, "new", "/home/researcher/flowlab", "researcher.pythonanywhere.com",
                                    Path(temp) / "snapshot", check=lambda *_: {})
        self.assertEqual(client.storage, original)
        self.assertEqual(client.reloaded, ["researcher.pythonanywhere.com"])

    def test_failed_health_check_rolls_back_including_release_marker(self):
        original = {"/home/researcher/flowlab/app.py": b"old", "/home/researcher/flowlab/release.json": b'{"release":"old","files":{}}'}
        client = FakeAPI(original)
        def unhealthy(*_):
            raise RuntimeError("New release failed readiness")
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaises(RuntimeError):
                deploy.deploy_files(client, {"app.py": b"new", "release.json": b'{"release":"new"}'}, "new",
                                    "/home/researcher/flowlab", "researcher.pythonanywhere.com", Path(temp) / "snapshot", check=unhealthy)
        self.assertEqual(client.storage, original)
        self.assertEqual(len(client.reloaded), 2)

    def test_unchanged_release_skips_file_upload_but_checks_running_app(self):
        digest = hashlib.sha256(b"same").hexdigest()
        manifest = json.dumps({"release": "same-release", "files": {"app.py": digest}}).encode()
        client = FakeAPI({"/home/researcher/flowlab/release.json": manifest, "/home/researcher/flowlab/app.py": b"same"})
        with tempfile.TemporaryDirectory() as temp:
            result = deploy.deploy_files(client, {"app.py": b"same", "release.json": manifest}, "same-release",
                                         "/home/researcher/flowlab", "researcher.pythonanywhere.com", Path(temp) / "snapshot", check=lambda *_: {"ok": True})
        self.assertEqual(result["uploaded_files"], 0)
        self.assertEqual(client.writes, 0)


if __name__ == "__main__":
    unittest.main()
