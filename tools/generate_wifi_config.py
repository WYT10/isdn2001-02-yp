"""Generate an ignored firmware header from optional private Wi-Fi settings."""
import argparse
import json
import time
from pathlib import Path


def generate(source, destination):
    lines = ["#pragma once", f"#define SENSORLAB_BUILD_EPOCH {int(time.time())}LL"]
    if source.exists():
        config = json.loads(source.read_text(encoding="utf-8"))
        limits = {"ssid": 32, "identity": 127, "username": 127,
                  "password": 127, "server_domain": 253}
        if not isinstance(config, dict) or set(config) != set(limits):
            raise ValueError("Private Wi-Fi configuration has invalid fields")
        for name, limit in limits.items():
            value = config[name]
            if (not isinstance(value, str) or not 1 <= len(value) <= limit or
                    not value.isascii() or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                raise ValueError("Private Wi-Fi configuration contains an invalid value")
        lines.append("#define SENSORLAB_PRIVATE_ENTERPRISE 1")
        for name, value in config.items():
            lines.append(f"#define SENSORLAB_EAP_{name.upper()} {json.dumps(value)}")
    else:
        lines.append("#define SENSORLAB_PRIVATE_ENTERPRISE 0")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    generate(args.source, args.destination)
