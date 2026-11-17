"""Create private keys once. Existing settings and research data are preserved."""
import argparse
import os
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--local", action="store_true", help="Allow session cookies on local HTTP")
    args = parser.parse_args()
    folder = Path(os.environ.get("FLOW_INSTANCE", str(Path(__file__).parent / "instance"))).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / "config.py"
    if path.exists():
        print("Private configuration already exists; no keys or database were replaced.")
        return
    keys = {name: secrets.token_urlsafe(32) for name in ("SECRET_KEY", "ADMIN_TOKEN", "VIEWER_TOKEN", "DEVICE_TOKEN")}
    content = "".join(f"{name} = {value!r}\n" for name, value in keys.items())
    content += f"SESSION_COOKIE_SECURE = {not args.local!r}\n"
    # Exclusive creation prevents a simultaneous setup from replacing another worker's keys.
    with path.open("x", encoding="utf-8") as output:
        output.write(content)
    if os.name != "nt":
        path.chmod(0o600)
    print("Private configuration created. Keep this terminal output and instance/config.py private.")
    for name in ("ADMIN_TOKEN", "VIEWER_TOKEN", "DEVICE_TOKEN"):
        print(f"{name}: {keys[name]}")
    print("Admin/viewer keys sign into the dashboard. The device key authenticates ingestion.")


if __name__ == "__main__":
    main()
