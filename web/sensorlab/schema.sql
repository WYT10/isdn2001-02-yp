BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY,
    label TEXT NOT NULL,
    is_demo INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    last_seen TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS readings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT NOT NULL REFERENCES devices(device_id),
    boot_id TEXT NOT NULL,
    seq INTEGER NOT NULL,
    received_at TEXT NOT NULL,
    observed_at TEXT,
    uptime_us INTEGER NOT NULL,
    dt_us INTEGER NOT NULL,
    pulses INTEGER NOT NULL,
    total_pulses INTEGER NOT NULL,
    frequency_hz REAL NOT NULL,
    flow_lpm REAL,
    total_l REAL,
    pulse_json TEXT,
    raw_json TEXT NOT NULL,
    UNIQUE(device_id, boot_id, seq)
);
CREATE INDEX IF NOT EXISTS readings_device_time ON readings(device_id, received_at);
CREATE INDEX IF NOT EXISTS readings_device_id ON readings(device_id, id);
CREATE INDEX IF NOT EXISTS readings_time ON readings(received_at);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    device_id TEXT REFERENCES devices(device_id),
    reading_id INTEGER REFERENCES readings(id),
    category TEXT NOT NULL,
    rating INTEGER,
    message TEXT NOT NULL,
    created_at TEXT NOT NULL
);
PRAGMA user_version=1;
COMMIT;
