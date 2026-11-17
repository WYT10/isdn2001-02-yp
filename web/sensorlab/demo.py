import math
from datetime import datetime, timedelta, timezone

from .data import ingest
from .db import get_db


def seed():
    db = get_db()
    if db.execute("SELECT 1 FROM devices WHERE device_id='demo-xiao'").fetchone():
        return
    now = datetime.now(timezone.utc)
    total = 0
    for seq in range(120):
        hz = 25 + 12 * math.sin(seq / 13) + 3 * math.cos(seq / 4)
        pulses = round(hz * 2)
        total += pulses
        sample = {"seq": seq, "uptime_us": (seq + 1) * 2000000, "dt_us": 2000000,
                  "pulses": pulses, "total_pulses": total, "frequency_hz": round(hz, 4),
                  "flow_lpm": None, "total_l": None, "pulse": None, "source": "simulation"}
        at = (now - timedelta(seconds=(119 - seq) * 2)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        ingest({"device_id": "demo-xiao", "label": "Simulation · ZJ-S201C", "boot_id": "simulation-1", "samples": [sample]},
               demo=True, received_at=at)
