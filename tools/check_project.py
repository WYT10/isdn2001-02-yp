"""Check publication boundaries without requiring Flask, Git, or network access."""
import importlib.util
import json
import os
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {".git", ".pio", ".local", ".venv", "venv", ".vscode", "output", "dist", "__pycache__", ".pytest_cache"}


def main():
    files = []
    for folder, directories, names in os.walk(ROOT, followlinks=False):
        directories[:] = [name for name in directories if name not in IGNORED and not name.startswith(".playwright")]
        for name in names:
            path = Path(folder) / name
            if name.startswith("sdkconfig.") and name not in {
                "sdkconfig.defaults", "sdkconfig.defaults.esp32", "sdkconfig.defaults.esp32s3"
            }:
                continue
            files.append(path)
    markdown = {path.relative_to(ROOT).as_posix() for path in files if path.suffix.lower() == ".md"}
    assert markdown == {"agent.md", "readme.md"}, f"Unexpected Markdown documents: {sorted(markdown)}"
    forbidden = [re.compile(rb"[A-Za-z0-9._%+-]+@connect[.]ust[.]hk"),
                 re.compile(rb"FLOW_" + rb"EAP_(?:USERNAME|PASSWORD)"),
                 re.compile(rb"gh[pousr]_[A-Za-z0-9]{20,}")]
    failures = []
    for path in files:
        assert not path.is_symlink(), f"Unexpected source symlink: {path.relative_to(ROOT)}"
        if any(pattern.search(path.read_bytes()) for pattern in forbidden):
            failures.append(path.relative_to(ROOT).as_posix())
    assert not failures, "Possible old account/credential material in: " + ", ".join(failures)
    private_wifi = ROOT / ".local" / "wifi.json"
    if private_wifi.exists():
        private = json.loads(private_wifi.read_text(encoding="utf-8"))
        sensitive = [private.get(name, "").encode("utf-8") for name in ("username", "password")]
        exposed = [path.relative_to(ROOT).as_posix() for path in files
                   if any(len(value) >= 8 and value in path.read_bytes() for value in sensitive)]
        assert not exposed, "Private Wi-Fi values exposed in authored source: " + ", ".join(exposed)
    main_source = (ROOT / "src" / "main.c").read_text()
    assert re.search(r'\.ssid\s*=\s*"ABCD"', main_source)
    assert re.search(r'\.password\s*=\s*"00000000"', main_source)
    assert {p.name for p in (ROOT / "src").glob("*.c")} == {"main.c", "wifi.c", "flow_sensor.c", "cli.c"}
    assert {p.name for p in (ROOT / "include").glob("*.h")} == {"wifi.h", "flow_sensor.h", "cli.h"}
    for name in ("flow_reader", "flow_wifi", "flow_config", "wifi_config", "flow_math", "flow_bench"):
        for folder, suffix in (("src", ".c"), ("include", ".h")):
            assert not (ROOT / folder / (name + suffix)).exists(), "Obsolete module remains: " + name
    for path in (ROOT / ".local" / "wifi_secrets.h", ROOT / ".local" / "eduroam_secrets.h"):
        assert not path.exists(), "Obsolete private Wi-Fi configuration remains"
    ignore = (ROOT / ".gitignore").read_text().splitlines()
    for item in (".pio/", ".local/", ".venv/", "output/", "dist/", "web/instance/", "*.sqlite3", "**/*.md", "!/agent.md", "!/readme.md"):
        assert item in ignore, "Missing ignore rule: " + item
    spec = importlib.util.spec_from_file_location("sensorlab_deploy", ROOT / "tools" / "deploy_pythonanywhere.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    expected, release = module.sources()
    archive_path = ROOT / "dist" / "pythonanywhere-starter.zip"
    if archive_path.exists():
        with zipfile.ZipFile(archive_path) as archive:
            assert set(archive.namelist()) == set(expected), "ZIP contains unexpected or missing files"
            assert all(archive.read(name) == body for name, body in expected.items()), "ZIP is stale; rebuild it"
    print(f"Project audit passed: {len(files)} authored files; four firmware C files including CLI; exactly agent.md/readme.md; no old Wi-Fi account material.")
    print("Upload release:", release)


if __name__ == "__main__":
    main()
