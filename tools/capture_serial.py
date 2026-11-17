"""Capture JSON telemetry without network access or resetting the board."""
import argparse
import json
from pathlib import Path
import time

import serial


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", required=True)
    parser.add_argument("--seconds", type=float, default=20)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    records = []
    with serial.Serial(args.port, 115200, timeout=0.25) as port, args.output.open(
        "w", encoding="utf-8"
    ) as output:
        deadline = time.monotonic() + args.seconds
        while time.monotonic() < deadline:
            line = port.readline().decode("utf-8", errors="replace").strip()
            if not line:
                continue
            output.write(line + "\n")
            output.flush()
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            records.append(item)
            if item.get("type") != "flow":
                print(json.dumps(item), flush=True)
    flow = [r for r in records if r.get("type") == "flow"]
    result = {"records": len(records), "flow_records": len(flow), "output": str(args.output)}
    if flow:
        result.update(
            total_pulses_first=flow[0]["total_pulses"],
            total_pulses_last=flow[-1]["total_pulses"],
            max_frequency_hz=max(r["frequency_hz"] for r in flow),
            valid_timing_records=sum(r["pulse"] is not None for r in flow),
            max_read_calc_format_us=max(r["read_calc_format_us"] for r in flow),
        )
    print(json.dumps(result, indent=2))
    if not flow:
        raise SystemExit("No flow telemetry received; inspect raw log and port.")


if __name__ == "__main__":
    main()
