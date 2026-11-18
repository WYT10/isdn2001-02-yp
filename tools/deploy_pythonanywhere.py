"""Bundle, update, reload and health-check a PythonAnywhere WSGI web app."""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
TOP_LEVEL = {"app.py", "flask_app.py", "wsgi.py", "bootstrap.py", "requirements.txt", "sample_payload.json"}
SUFFIXES = {".py", ".sql", ".html", ".css", ".js", ".svg", ".json"}


def sources(folder=WEB):
    files = {}
    for path in sorted(folder.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(folder)
        allowed = relative.as_posix() in TOP_LEVEL or (
            relative.parts[0] == "sensorlab" and (path.suffix in SUFFIXES or
                relative.as_posix() in {"sensorlab/static/vendor/leaflet-license.txt", "sensorlab/static/vendor/d3-license.txt",
                                        "sensorlab/static/vendor/three-license.txt"})
            and "__pycache__" not in relative.parts
        )
        if not allowed:
            continue
        if path.is_symlink() or not path.resolve().is_relative_to(folder.resolve()):
            raise ValueError("Source symlinks are not supported")
        content = path.read_bytes()
        if path.suffix == ".py":
            compile(content, str(relative), "exec")
        files[relative.as_posix()] = content
    if not {"app.py", "flask_app.py", "sensorlab/__init__.py", "sensorlab/schema.sql", "requirements.txt"} <= files.keys():
        raise ValueError("Incomplete web source directory")
    hashes = {name: hashlib.sha256(content).hexdigest() for name, content in files.items()}
    release = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    files["release.json"] = (json.dumps({"release": release, "version": "0.1.0", "files": hashes}, indent=2) + "\n").encode()
    return files, release


def bundle(destination, files):
    destination.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in sorted(files.items()):
            archive.writestr(name, content)


def http(method, url, *, token=None, data=None, content_type=None, timeout=20):
    headers = {"User-Agent": "SensorLab-deploy/0.1"}
    if token:
        headers["Authorization"] = "Token " + token
    if content_type:
        headers["Content-Type"] = content_type
    request = Request(url, method=method, data=data, headers=headers)
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


class PythonAnywhere:
    def __init__(self, username, token, host="www.pythonanywhere.com", interval=1.6):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", username):
            raise ValueError("Invalid PythonAnywhere username")
        if host not in ("www.pythonanywhere.com", "eu.pythonanywhere.com"):
            raise ValueError("Use the official US or EU PythonAnywhere API host")
        self.base = f"https://{host}/api/v0/user/{quote(username)}/"
        self.token = token
        self.interval = interval
        self.previous_request = 0

    def call(self, method, path, data=None, content_type=None, expected=(200,), timeout=20):
        wait = self.interval - (time.monotonic() - self.previous_request)
        if wait > 0:
            time.sleep(wait)
        self.previous_request = time.monotonic()
        status, body = http(method, self.base + path, token=self.token, data=data, content_type=content_type, timeout=timeout)
        if status not in expected:
            raise RuntimeError(f"PythonAnywhere API returned HTTP {status} for {method}; check API token, account and rate limits")
        return status, body

    def get_file(self, path):
        status, body = self.call("GET", "files/path" + quote(path, safe="/"), expected=(200, 404))
        return body if status == 200 else None

    def put_file(self, path, content):
        boundary = "sensorlab-" + uuid.uuid4().hex
        data = (f'--{boundary}\r\nContent-Disposition: form-data; name="content"; filename="source"\r\n'
                'Content-Type: application/octet-stream\r\n\r\n').encode() + content + f"\r\n--{boundary}--\r\n".encode()
        self.call("POST", "files/path" + quote(path, safe="/"), data,
                  "multipart/form-data; boundary=" + boundary, expected=(200, 201))

    def delete_file(self, path):
        self.call("DELETE", "files/path" + quote(path, safe="/"), expected=(204, 404))

    def reload(self, domain):
        # The provider can wait for workers to finish before answering a reload.
        self.call("POST", "webapps/" + quote(domain, safe="") + "/reload/", data=b"", expected=(200, 201), timeout=90)


def health_check(domain, expected_release=None):
    if not re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?", domain):
        raise ValueError("Invalid website domain")
    results = {}
    # Public checks deliberately use no PythonAnywhere account authorization header.
    for endpoint in ("healthz", "readyz"):
        status, body = http("GET", f"https://{domain}/{endpoint}")
        if status != 200:
            raise RuntimeError(f"{endpoint} returned HTTP {status}")
        result = json.loads(body)
        if result.get("status") != "ok":
            raise RuntimeError(f"{endpoint} is not healthy")
        results[endpoint] = result
    if expected_release and results["healthz"].get("release") != expected_release:
        raise RuntimeError("The running release does not match the uploaded files")
    if results["readyz"].get("database") != "ok" or results["readyz"].get("schema_version") != 1:
        raise RuntimeError("Database readiness check failed")
    return results


def wait_healthy(domain, release):
    deadline = time.monotonic() + 35
    while True:
        try:
            return health_check(domain, release)
        except (RuntimeError, OSError, ValueError):
            if time.monotonic() >= deadline:
                raise
            time.sleep(2)


def account_check(client, remote_dir, domain, expected_release):
    """Verify account API access using GET only; return no source or private settings."""
    manifest = client.get_file(remote_dir + "/release.json")
    client.call("GET", "webapps/" + quote(domain, safe="") + "/")
    try:
        release = json.loads(manifest or b"{}").get("release")
    except (ValueError, AttributeError):
        release = None
    return {"authenticated": True, "domain": domain, "remote_dir": remote_dir,
            "source_manifest_found": manifest is not None,
            "release_matches_local": release == expected_release}


def deploy_files(client, files, release, remote_dir, domain, backup_dir, check=wait_healthy):
    old_manifest = client.get_file(remote_dir + "/release.json")
    try:
        previous = json.loads(old_manifest or b"{}").get("files", {})
    except (ValueError, TypeError):
        previous = {}
    changed = [name for name, content in files.items() if name != "release.json" and
               previous.get(name) != hashlib.sha256(content).hexdigest()]
    if changed or old_manifest != files["release.json"]:
        changed.append("release.json")
    before = {}
    for name in changed:
        before[name] = old_manifest if name == "release.json" else client.get_file(remote_dir + "/" + name)
    backup_dir.mkdir(parents=True, exist_ok=False)
    for name, content in before.items():
        if content is not None:
            target = backup_dir / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
    (backup_dir / "snapshot.json").write_text(json.dumps({"missing": [name for name, body in before.items() if body is None]}, indent=2))
    attempted = []
    try:
        for name in changed:
            attempted.append(name)
            client.put_file(remote_dir + "/" + name, files[name])
        client.reload(domain)
        result = check(domain, release)
    except Exception as error:
        rollback_errors = []
        for name in reversed(attempted):
            try:
                if before[name] is None:
                    client.delete_file(remote_dir + "/" + name)
                else:
                    client.put_file(remote_dir + "/" + name, before[name])
            except Exception:
                rollback_errors.append(name)
        try:
            client.reload(domain)
        except Exception:
            rollback_errors.append("webapp reload")
        if rollback_errors:
            raise RuntimeError("Update failed and rollback needs attention; see private snapshot " + str(backup_dir)) from error
        raise RuntimeError("Update failed; previous source files restored and reload requested. Snapshot: " + str(backup_dir)) from error
    return {"release": release, "uploaded_files": len(changed), "health": result}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "bundle", "auth", "deploy", "check"))
    parser.add_argument("--config", type=Path, default=ROOT / ".local" / "pythonanywhere.json")
    args = parser.parse_args()
    if args.action in ("plan", "bundle", "deploy"):
        files, release = sources()
        if args.action == "plan":
            print(json.dumps({"release": release, "files": sorted(files)}, indent=2))
            return
        if args.action == "bundle":
            target = ROOT / "dist" / "pythonanywhere-starter.zip"
            bundle(target, files)
            print(f"Upload-ready ZIP: {target} ({target.stat().st_size} bytes)")
            return
    settings = json.loads(args.config.read_text()) if args.config.exists() else {}
    username = os.environ.get("PA_USERNAME", settings.get("username", ""))
    token = os.environ.get("PA_API_TOKEN", settings.get("api_token", ""))
    host = os.environ.get("PA_API_HOST", settings.get("api_host", "www.pythonanywhere.com"))
    domain = os.environ.get("PA_DOMAIN", settings.get("domain", username + ".pythonanywhere.com"))
    if args.action == "check":
        print(json.dumps(health_check(domain), indent=2))
        return
    if not username or not token:
        raise ValueError("Set PA_USERNAME / PA_API_TOKEN, or fill ignored .local/pythonanywhere.json")
    remote_dir = settings.get("remote_dir", f"/home/{username}/mysite")
    remote = PurePosixPath(remote_dir)
    home = PurePosixPath("/home") / username
    if ".." in remote.parts or not remote.is_relative_to(home) or remote == home:
        raise ValueError("remote_dir must be a project directory below the account home")
    if args.action == "auth":
        print(json.dumps(account_check(PythonAnywhere(username, token, host), str(remote), domain,
                                       sources()[1]), indent=2))
        return
    # A deploy always tests the local backend before changing remote files.
    subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "test/web", "-v"], cwd=ROOT, check=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    result = deploy_files(PythonAnywhere(username, token, host), files, release, str(remote), domain,
                          ROOT / "output" / "deploy" / stamp)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as error:
        raise SystemExit(str(error))
