"""Send one SensorLab serial command, optionally watching subsequent telemetry."""
import argparse
import json
import math
import time

import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument("--watch", type=float, default=0, help="Seconds to print records after the reply")
    parser.add_argument("command", nargs="+")
    args = parser.parse_args()
    command = " ".join(args.command)
    if not command.isascii() or len(command) > 95 or any(ord(c) < 32 for c in command):
        parser.error("Command must be one ASCII line, at most 95 characters")
    command = " ".join(command.split())
    if not command:
        parser.error("Command must not be empty")
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 60:
        parser.error("timeout must be in (0, 60] seconds")
    if not math.isfinite(args.watch) or not 0 <= args.watch <= 3600:
        parser.error("watch must be in [0, 3600] seconds")
    action = {"wifi scan": "scan", "wifi reconnect": "reconnect", "wifi ap on": "ap_on",
              "wifi ap only": "ap_only", "wifi auto": "auto", "wifi status": "status"}.get(command)
    ack = completion = None
    expected_command = command if command.startswith("wifi ") else command.split()[0]
    success = False
    # Set control lines before opening; this helper never deliberately resets the board.
    with serial.Serial(port=None, baudrate=115200, timeout=0.1, write_timeout=2) as port:
        port.dtr = False
        port.rts = False
        port.port = args.port
        port.open()
        port.reset_input_buffer()
        port.write((command + "\n").encode("ascii"))
        port.flush()
        deadline = time.monotonic() + args.timeout
        watching = False
        pending = bytearray()
        discard = False
        while time.monotonic() < deadline:
            chunk = port.readline()
            pending.extend(chunk)
            if len(pending) > 8192:
                discard = True
                pending.clear()
            if not chunk.endswith(b"\n"):
                continue
            line = pending.decode("utf-8", errors="replace").strip()
            pending.clear()
            if discard:
                discard = False
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("type") != "flow" or watching:
                print(json.dumps(record), flush=True)
            if watching:
                continue
            if (record.get("type") == "cli" and record.get("status") != "ready" and
                    record.get("command") in (None, expected_command)):
                ack = record
            if record.get("type") == "wifi_command" and record.get("action") == action:
                completion = record
            done = ack and (ack.get("status") != "queued" or completion)
            if done:
                success = ack.get("status") in ("ok", "queued") and (
                    not completion or completion.get("status") == "ok")
                if not args.watch:
                    break
                watching = True
                deadline = time.monotonic() + args.watch
    if ack is None or (ack.get("status") == "queued" and completion is None):
        raise SystemExit("No completed command reply. Check the port, close other monitors, and send help.")
    if not success:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
