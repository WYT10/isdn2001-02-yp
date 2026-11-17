# SensorLab

XIAO ESP32-S3 sensor firmware and a responsive Flask research dashboard for PythonAnywhere. The first supported sensor is the ZJ-S201C water-flow sensor. Read [agent.md](agent.md) for agent instructions and maintained project memory. These are the only authored Markdown files in the repository.

This first website release includes authenticated measurement ingestion, SQLite storage, JSON/CSV exports, descriptive analytics, device freshness, user feedback, health checks and a repeatable source updater. ESP32 HTTP uploading is the next integration step. Actual pulse reading was confirmed by blowing air through the connected sensor. Water-flow calibration and online deployment remain to be verified.

## First upload to PythonAnywhere

Already created `~/mysite/flask_app.py` using PythonAnywhere's Flask setup? Keep that web app. The ZIP now includes `flask_app.py` and matches its default entry point. This project needs the whole ZIP, including the `sensorlab/` package, templates and static files; uploading only flask_app.py is insufficient.

1. Open PythonAnywhere **Files**, go to your home directory `/home/YOUR_USERNAME/`, and upload **`dist/pythonanywhere-starter.zip`** from this computer. Upload the ZIP itself, without opening it in the online editor.
2. Open **Consoles > Bash** and run:

```bash
mkdir -p ~/mysite
# Preserve the initial starter file before replacing it.
if [ -f ~/mysite/flask_app.py ]; then cp -n ~/mysite/flask_app.py ~/flask_app.starter.backup.py; fi
unzip -o ~/pythonanywhere-starter.zip -d ~/mysite
cd ~/mysite
python3.11 -m venv ~/.virtualenvs/sensorlab
source ~/.virtualenvs/sensorlab/bin/activate
pip install -r requirements.txt
python bootstrap.py
```

Use Python **3.11 or newer**, matching the version shown in the **Web** tab. If your newly created app says **3.10**, change its Python version to **3.11** in Web first, then use the commands above. If you choose 3.13, use `python3.13` instead. Setup prints private admin, viewer and device keys. Save them privately: the admin/viewer keys sign into the site; the device key authenticates sensor uploads. Repeating setup preserves existing keys and data.

3. Open **Web**, select your existing site and set **Virtualenv** to `/home/YOUR_USERNAME/.virtualenvs/sensorlab`. Set **Source code** and **Working directory** to `/home/YOUR_USERNAME/mysite`.
4. Open the **WSGI configuration file** linked in Web. The default Flask configuration should already import `from flask_app import app as application` with your mysite path. You can replace its contents with the supplied `~/mysite/wsgi.py` contents, which discovers your username automatically:

```python
import sys
from pathlib import Path

project = str(Path.home() / "mysite")
if project not in sys.path:
    sys.path.insert(0, project)

from flask_app import app as application
```

5. Enable **Force HTTPS**, press the green **Reload** button, and visit `https://YOUR_DOMAIN/healthz`, `/readyz`, then `/`. Sign in with the admin key printed by bootstrap.

After extraction, the layout is:

```text
/home/YOUR_USERNAME/mysite/
    flask_app.py
    app.py
    wsgi.py
    bootstrap.py
    requirements.txt
    release.json
    sensorlab/             Python package, templates and static assets
    instance/            Private keys and database, created by setup/app
```

The ZIP contains web source at its root, without credentials or databases. It does not contain an extra mysite folder. Generate it from a fresh checkout with `python tools/deploy_pythonanywhere.py bundle`.

The first dashboard is empty. For a labelled demonstration, run `python -m flask --app flask_app seed-demo` in the activated Bash console. This preserves real samples and does not establish live sensor connectivity. See [PythonAnywhere's Flask/WSGI setup](https://help.pythonanywhere.com/pages/Flask/). Optional static mapping: `/static/` to `/home/YOUR_USERNAME/mysite/sensorlab/static`.

## Future updates without copy/paste

The updater uses [PythonAnywhere's official Files and Webapp Reload APIs](https://help.pythonanywhere.com/pages/API/). There is no arbitrary file-write or shell-execution endpoint on the public dashboard.

After first deployment, obtain the account API token from PythonAnywhere's **Account / API token** tab. Save your values in ignored `.local/pythonanywhere.json`:

```json
{
  "username": "YOUR_USERNAME",
  "api_token": "YOUR_PYTHONANYWHERE_API_TOKEN",
  "api_host": "www.pythonanywhere.com",
  "domain": "YOUR_USERNAME.pythonanywhere.com",
  "remote_dir": "/home/YOUR_USERNAME/mysite"
}
```

EU accounts use `eu.pythonanywhere.com` and the actual site domain. Environment alternatives are `PA_USERNAME`, `PA_API_TOKEN`, `PA_API_HOST` and `PA_DOMAIN`. The account token is separate from app access keys and is never sent to Flask.

From the project root, in the development environment:

```bash
python tools/deploy_pythonanywhere.py plan
python tools/deploy_pythonanywhere.py bundle
python tools/deploy_pythonanywhere.py deploy
python tools/deploy_pythonanywhere.py check
```

`plan` and `bundle` work offline. `deploy` runs web tests, compares the release manifest, snapshots affected remote source to ignored `output/deploy/`, uploads changes, reloads and verifies the running release and database readiness. On upload or health failure it attempts source restoration and requests another reload. It never replaces instance configuration or research databases. API requests are paced for the documented rate limit.

Keep subsequent source updates through the updater so its manifest stays current. Install changed requirements in the remote virtualenv before deploying a dependency update. Initial WSGI/virtualenv setup and database migrations are separate operations; source rollback does not roll back a database migration. Real account-token access and remote reload remain to be tested after your upload.

## Data API

External clients use `Authorization: Bearer <APPLICATION_ROLE_KEY>`. Browser sessions use an HttpOnly cookie and require CSRF for writes. Device keys cannot read research data or administration endpoints.

| Endpoint | Role | Purpose |
|---|---|---|
| `GET /healthz` | Public | Liveness and running release |
| `GET /readyz` | Public | Database/schema readiness |
| `POST /api/v1/readings` | Device/admin | Atomic batch ingestion, max 200 samples |
| `GET /api/v1/readings` | Viewer/admin | Paginated JSON including raw fields |
| `GET /api/v1/readings.csv` | Viewer/admin | CSV pages, max 10,000 rows |
| `GET /api/v1/devices` | Viewer/admin | Device metadata and last new data time |
| `GET /api/v1/dashboard` | Viewer/admin | Latest 240 samples and window summary |
| `GET /api/v1/analytics` | Viewer/admin | Per-device time-bucket statistics |
| `POST /api/v1/feedback` | Viewer/admin | Notes/ratings linked to a device/reading |
| `GET /api/v1/feedback` | Admin | Paginated feedback |
| `GET /api/v1/system` | Admin | Counts, schema and release |
| `POST /api/v1/system/check` | Admin | Read/write probe, rolled back without research records |
| `GET /api/v1/spec` | Viewer/admin | OpenAPI 3.1 contract |

Example body: `web/sample_payload.json`.

```bash
curl -X POST https://YOUR_DOMAIN/api/v1/readings \
  -H "Authorization: Bearer YOUR_DEVICE_KEY" \
  -H "Content-Type: application/json" \
  --data-binary @web/sample_payload.json
```

The measurement ID is `(device_id, boot_id, seq)`. Exact retries deduplicate; conflicting content for an existing ID returns 409 and rolls back the batch. Use a new `boot_id` after resets. The sender should retain pending samples across outages; this release does not yet implement an ESP32 upload queue.

Server `received_at`, optional device `observed_at` and raw `uptime_us` are separate fields. All stored timestamps are UTC. Unknown calibration stays null; zero is a valid value. Pulse duty/high/low times and extra finite JSON fields are retained. Cumulative pulse/volume counters are per boot, not lifetime totals.

JSON/CSV accepts `device_id`, `since`, `until`, `after_id` and bounded `limit`. Continue JSON pages with `next_after_id`; CSV reports `X-Has-More` and `X-Next-After-Id`. Analytics accepts `bucket_minutes`, defaults to seven days, and caps output at 1,000 per-device buckets with `truncated` explicitly reported. Means are arithmetic sample means, with null calibration excluded. These are descriptive statistics, not time-weighted averages, accuracy estimates or a trained mining model. The chart shows up to 240 latest samples by server receipt time.

## Database and operation

SQLite is private at `instance/flowlab.sqlite3` on the server. This existing database filename is retained after the SensorLab rename so collected data remains available. The app uses transactions, indexes, unique sample IDs and per-request connections. This is a starter for modest collection volume; larger studies should revisit database choice, retention and asynchronous processing before increasing load. Heavy analysis should run outside web requests.

Create a consistent backup in the activated console:

```bash
python -m flask --app app backup-db /home/YOUR_USERNAME/sensorlab-backup.sqlite3
```

Choose a new destination and download backups separately. Setup creates schema version 1 only when absent; unknown versions are rejected. Future migrations must preserve collected data. Browser polling is every three seconds, pauses in hidden tabs and avoids holding a hosted worker in a persistent stream.

Private keys live in `instance/config.py`. Environment overrides use `FLOW_SECRET_KEY`, `FLOW_ADMIN_TOKEN`, `FLOW_VIEWER_TOKEN`, `FLOW_DEVICE_TOKEN`, `FLOW_DATABASE`, `FLOW_INSTANCE` and `FLOW_SESSION_COOKIE_SECURE`. Keys must be distinct ASCII strings of at least 24 characters. HTTPS cookies are the default.

## Local development and checks

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements-dev.txt
python web/bootstrap.py --local
python -m flask --app web/app.py run
```

Local runtime files are ignored under `web/instance/` and excluded from the upload. Use `--local` for local HTTP development only; run normal bootstrap on the server. Production imports the app through WSGI and never starts Flask's development server.

```bash
python -m unittest discover -s test/web -v
python tools/run_host_tests.py
python tools/check_project.py
python tools/deploy_pythonanywhere.py bundle
```

The current package passed 33 Flask/deployment tests, including starting the extracted ZIP through PythonAnywhere's default flask_app entry point. The original 32 tests cover roles/CSRF, input bounds, atomic ingestion and retries, persistence, exports, analytics, feedback, setup/backup preservation, file API formatting, release validation and source rollback. Chromium checks passed at widths 1440, 768, 390 and 320, including login, chart switching, feedback, CSV and logout. These are viewport checks, not tests on every physical operating system or iPad model. Remote deployment remains unverified.

## Firmware

PlatformIO/ESP-IDF structure is retained: `src/`, `include/`, `components/`, `test/host/`, `platformio.ini` and `sdkconfig.defaults`. Application firmware has exactly three C files: `main.c` wires the application and owns settings; `wifi.c` handles scanning, reconnection and the local fallback dashboard; `flow_sensor.c` contains PCNT/capture, calculations, DSP benchmarks and synthetic tests. The public interfaces are `wifi.h` and `flow_sensor.h`.

Edit the typed `app` initializer in `src/main.c`: `.sensor` holds GPIO, pull-up, edge capture, glitch filter, stale timeout, report interval, averaging window and calibration; `.wifi` holds credentials, retry/status intervals and nested `.fallback` settings; `.diagnostics` controls benchmarks and the separate test GPIO. Both modules copy their configuration. The current test hotspot is `ABCD` / `00000000`, WPA2-Personal, on the ESP32-S3's 2.4 GHz radio. Empty passwords select open authentication; a nonempty password selects a minimum WPA2 authentication threshold. Previous account configuration was removed. Application and hosting keys remain private.

The network task retries ABCD continuously, five seconds after each failed attempt. If it has no station IP for 60 seconds, it enables AP+STA fallback:

- Join **SensorLab-Local**, password **00000000**, and open **http://192.168.4.1**. If your phone warns that this network has no Internet, choose to remain connected.
- The responsive page shows raw frequency, pulse counts, high/low time, duty cycle and calibrated values when available. It polls `/api/status` once per second; the reader itself still reports every 250 ms. `/healthz` reports local HTTP liveness.
- Station retries continue, spaced 30 seconds after failures once fallback is active. The local AP stays on until reboot, including after station recovery. The HTTP server then also listens on the station IP.
- The trigger is missing IP, rather than an Internet health check. AP+STA shares one radio/channel; scanning or upstream channel changes can briefly interrupt local clients. There is no Internet forwarding/NAT.
- The driver's individual authentication/association timers are unchanged. App retry/wait logs include attempt numbers and elapsed milliseconds. Sensor reporting runs independently.

The user currently has no external antenna. Both station and AP use the same antenna path, so fallback availability over the air must still be checked from a phone/computer.

ZJ-S201C signal: **D10/GPIO9**, with common ground and a 3.3 V compatible signal interface. Supply the sensor according to its label. A GPIO pull-up does not level-shift a driven 5 V signal.

PCNT continuously counts rising edges with a 1 microsecond glitch filter and extended counter wrap. MCPWM measures rising/falling edge times for frequency, high/low duration and duty. Normal firmware never drives D10. Reports arrive every 250 ms, with approximately a one-second rolling frequency window. `app.sensor.pulses_per_litre=0` until calibrated, so flow and volume remain null. Obtain the exact coefficient from the sensor datasheet or a known-volume collection. The configurable rolling window is bounded to 1-32 report samples.

```bash
pio run -e seeed_xiao_esp32s3
pio run -e seeed_xiao_esp32s3 -t upload --upload-port COM19
pio device monitor --port COM19 --baud 115200
python tools/capture_serial.py --port COM19 --seconds 30 --output output/hardware/reader.jsonl
```

Verify the USB device before flashing; COM19 may change. The last verified unit's serial ends `FB6FC8`. Its original pre-reader flash backup and restore instructions remain locally in ignored `.pio/backup/`.

The `selftest` environment uses **D3/GPIO4**, disconnected from external wiring, for 5/75/150/1000 Hz synthetic pulses, a 20 kHz count-only wrap test and stopped-signal checks. Restore the normal reader after testing:

```bash
pio run -e selftest -t upload --upload-port COM19
pio run -e seeed_xiao_esp32s3 -t upload --upload-port COM19
```

The minimal official ESP-DSP v1.8.2 multiplication sources, license and attribution remain in `components/esp-dsp`. The Xtensa FPU/hardware-loop microbenchmark is not an end-to-end sampling speedup. `read_calc_format_us` excludes final USB output, can include preemption and does not measure aggregate CPU/ISR use.

Before adding local HTTP, the three-file refactor passed native calculation/timing tests and both reader/selftest firmware builds. Five synthetic on-board cases passed, including 20 kHz counting across the hardware limit and stopped/stale timing checks; DSP numerical checks passed. The normal reader was restored with flash hash verification. The subsequent air test on the connected sensor counted 1900 pulses with peak rolling frequency 154 Hz, captured duty/high/low timing, and returned to zero with stale timing cleared after stopping. Hydraulic calibration remains unverified. Its latest WPA2 capture observed 95 seconds, 368 sensor reports and 12 connection attempts without an IP; continuous retries remained active. The prior open-network test also failed before obtaining an IP. No firmware HTTP upload exists yet. Before the branding change, the final 140-second local-fallback hardware run passed: AP+STA started after 60.060 seconds without an IP, all three HTTP loopback routes passed without socket errors, 547 reports continued over 136.50 seconds, and upstream retries continued beyond two minutes. The maximum observed report interval was 262.236 ms; these reports are not a hard real-time guarantee. Browser checks passed at 320/390/768/1440 px with simulated API responses. Wireless client association and calibrated water-flow accuracy remain unverified. After the rename, an 85-second on-board check confirmed SensorLab-Local starting at 60.172 seconds, all three local HTTP routes and continued reporting; the maximum observed report interval was 250.114 ms. Previous detailed captures are archived under ignored `.local/`; current evidence and limits are in `agent.md`.

## Layout and Git hygiene

```text
agent.md                    Agent rules and maintained memory
readme.md                   Setup, API and operations
src/main.c                  Application settings and reporting loop
src/wifi.c                  Wi-Fi, local HTTP dashboard and AP fallback
src/flow_sensor.c           Sensor driver, calculations and diagnostics
include/wifi.h              Typed Wi-Fi configuration/API
include/flow_sensor.h       Typed sensor configuration/API
components/esp-dsp/         Minimal upstream acceleration dependency
web/                        Flask source, templates, assets and upload example
test/host/ test/web/        Native C and Flask/deployment tests
tools/                      Build, capture, deployment and project checks
```

Git ignores credentials, databases, virtualenvs, PlatformIO output, deployment snapshots, browser artifacts and ZIPs. Additional Markdown files are ignored; the project check enforces the two-document rule in authored source. Dependency licenses are retained.

Public repository: [WYT10/isdn2001-02-yp](https://github.com/WYT10/isdn2001-02-yp). SensorLab source is published on main at code commit `77fb43c`. The [SensorLab CI run](https://github.com/WYT10/isdn2001-02-yp/actions/runs/43994801212) passed both jobs: web/native tests, publication audit, ZIP packaging and the clean Linux firmware build. The branded firmware built locally and passed the on-board check. Both jobs passed for the earlier code commit `40a4671`. GitHub Actions supplies the PythonAnywhere ZIP as an artifact. The final documentation update records the separate on-board and browser results.

Local Git initialization succeeded, but this session has read-only access to Git metadata, so it could not configure the local remote or commit locally. To link this already initialized folder, which currently has no local commits or remote, run once in your own terminal from the project root:

```bash
git remote add origin https://github.com/WYT10/isdn2001-02-yp.git
git fetch origin
git reset --mixed origin/main
git branch --set-upstream-to=origin/main main
git status
```

The mixed reset updates the index and branch while preserving working files. Inspect git status before future commits. Firmware version `0.1.0` is explicitly set in the root CMakeLists.txt, so building also works from a source ZIP or an empty local Git history.

