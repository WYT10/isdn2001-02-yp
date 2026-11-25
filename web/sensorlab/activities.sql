BEGIN IMMEDIATE;
CREATE TABLE IF NOT EXISTS activity_accounts (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, is_demo INTEGER NOT NULL CHECK(is_demo IN (0,1)),
    metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity_tokens (
    digest TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES activity_accounts(id), created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity_factors (
    id TEXT PRIMARY KEY, payload_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity_evidence (
    id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES activity_accounts(id),
    source_type TEXT NOT NULL, external_id TEXT NOT NULL, content_hash TEXT NOT NULL,
    payload_json TEXT NOT NULL, created_at TEXT NOT NULL,
    UNIQUE(account_id, source_type, external_id)
);
CREATE TABLE IF NOT EXISTS activity_events (
    id TEXT PRIMARY KEY, account_id TEXT NOT NULL REFERENCES activity_accounts(id),
    occurred_at TEXT, local_date TEXT, kind TEXT NOT NULL CHECK(kind IN ('shopping','transport','household')),
    category TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('confirmed','needs_review','excluded')),
    revision INTEGER NOT NULL CHECK(revision>0), payload_json TEXT NOT NULL,
    evidence_id TEXT REFERENCES activity_evidence(id), created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS activities_account_time ON activity_events(account_id,local_date,occurred_at);
CREATE TABLE IF NOT EXISTS activity_items (
    event_id TEXT NOT NULL REFERENCES activity_events(id), position INTEGER NOT NULL,
    payload_json TEXT NOT NULL, PRIMARY KEY(event_id,position)
);
CREATE TABLE IF NOT EXISTS activity_estimates (
    event_id TEXT NOT NULL REFERENCES activity_events(id), revision INTEGER NOT NULL,
    co2e_kg REAL, formula_version TEXT NOT NULL, details_json TEXT NOT NULL, created_at TEXT NOT NULL,
    PRIMARY KEY(event_id,revision)
);
CREATE TABLE IF NOT EXISTS activity_revisions (
    event_id TEXT NOT NULL REFERENCES activity_events(id), revision INTEGER NOT NULL,
    payload_json TEXT NOT NULL, created_at TEXT NOT NULL, PRIMARY KEY(event_id,revision)
);
PRAGMA user_version=2;
COMMIT;
