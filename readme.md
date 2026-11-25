# LiveGreen

ESP32 sensor firmware, a Flask API with SQLite, and a web dashboard.

**Current board:** ESP32-S3 dev kit · GPIO10 · 4 MB flash · native USB serial. Default branch: `main`.

## Files

```text
src/          main.c, wifi.c, flow_sensor.c, cli.c
include/      firmware headers
components/   cJSON runtime dependency
web/          Flask backend, database schema and dashboard
tools/        serial commands, private configuration and deployment
.github/      firmware build and website packaging
```

Only this file and `agent.md` are maintained documentation. Keys, databases, backups and generated files are ignored by Git. Original board backups stay in `.pio/backup/`; historical diagnostics are in `.local/archive/`.

User reference folders (`3d_ref/`, `app_ref/`, `database/`) stay local. They contain CAD, mobile prototypes and personal activity records; they are not runtime dependencies.

## Run

Python 3.11+ and PlatformIO are required. PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install platformio==6.2.0 -r requirements-dev.txt
pio run
pio run -t upload --upload-port COM_PORT
python tools/serial_cli.py --port COM_PORT status
```

Identify the board and preserve its flash/NVS backup before uploading. Signal must be 3.3 V-compatible with common ground. Reports default to 250 ms. Calibration is unset, so litres and L/min remain null. Optional XIAO/WROOM profiles remain in `platformio.ini`.

Public Wi-Fi defaults: **ABCD / 00000000**. Private eduroam settings stay in `.local/wifi.json`; cloud URL/device key stay in `.local/cloud.json`. Never commit private configuration or firmware.

After 60 seconds without a station IP, join **SensorLab-Local / 00000000** and open **http://192.168.4.1**. Fallback keeps upstream retries and provides local readings without Internet forwarding.

## Website

[Live website](https://greenwithisd.pythonanywhere.com/) · public synthetic dashboard at `/` · protected real readings at `/sensors` · research sign-in at `/login`.

```powershell
cd web
python bootstrap.py --local
python -m flask --app flask_app run
```

Open http://127.0.0.1:5000. Bootstrap preserves existing keys/data; keep its printed keys private. SQLite schema 2 preserves sensor readings/feedback and adds owned activities, evidence, line items, factor snapshots and revision history. A schema-1 database is backed up under the instance `backups/` directory before migration.

From the repository root:

```powershell
python tools/deploy_pythonanywhere.py bundle
python tools/deploy_pythonanywhere.py check
```

Upload `dist/pythonanywhere-starter.zip` into PythonAnywhere `~/mysite/` and extract the whole package. Configure WSGI using `web/wsgi.py`. For API updates, use the existing private `.local/pythonanywhere.json` with `auth` and `deploy` actions. The updater snapshots source and verifies the running release/database; it does not reset research data.

The website owns the API, database, dashboard and formulas. A separate mobile app will use `app_ref` as its UI reference and connect to this backend; native capture needs platform-specific implementation. Data quality, extraction feasibility and research-backed factors come first. Activity accounts currently use independently scoped keys provisioned by an administrator; self-service sign-up and the native app are future work.

## Activity data

The dashboard now reads 175 saved activities for Alex, a fictional person, over 26 Oct–22 Nov 2026. Demo records use normal storage/calculation/editing workflows and retain their provenance flag. Private source diaries stay local.

Open `/workspace` for date filters, daily water/energy/travel/carbon series, record inspection and edits. Connect an activity key, or sign in as administrator and create an editable demo copy. Changes persist; stale revisions are rejected. Accounts cannot edit each other's records. Green index +0.35 is still manually assigned.

- Public demo: `/api/v1/demo/overview`, `/api/v1/demo/events`, `/api/v1/demo/export?format=csv`.
- Account key: `/api/v1/activity-events`, `/api/v1/activity-overview`, `/api/v1/activity-export`.
- Android import: `POST /api/v1/activity-imports/record-today` with schemaVersion 1 JSON.
- API contract: `/api/v1/activity-spec`. Browser writes require CSRF; apps use a Bearer account key.

With local references present, regenerate using `python tools/prepare_demo.py`. Review exports are in `dist/livegreen-demo.json`, `.csv`, `.sqlite3` and `livegreen-overview.json`; the web ZIP contains source and the sanitized seed, never private databases/keys.

Temporary tests and diagnostics must be removed after use. Runtime health checks and CI build/package checks remain.
