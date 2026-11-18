# LiveGreen

LiveGreen is the website name, with the existing icon retained. The live branding release is `a8f8675b`; public access, research sign-in and desktop/tablet/phone layouts were verified. This project includes XIAO ESP32-S3 and ESP32-WROOM sensor firmware, with a responsive Flask research dashboard for PythonAnywhere. The first supported sensor is the ZJ-S201C water-flow sensor. Read [agent.md](agent.md) for agent instructions and maintained project memory. These are the only authored Markdown files in the repository.

This first website release includes authenticated measurement ingestion, SQLite storage, JSON/CSV exports, descriptive analytics, device freshness, user feedback, health checks and a repeatable source updater. Optional direct ESP32 HTTPS uploading runs in a separate task with bounded buffering and retry-safe batches. Actual pulse reading was confirmed by blowing air through the connected sensor. The site is live at [greenwithisd.pythonanywhere.com](https://greenwithisd.pythonanywhere.com/): public health, database readiness and the login page returned HTTP 200. Direct WROOM-to-cloud ingestion and a physical air test are verified: the database retained 1,005 boot pulses, an 80.99838 Hz peak, 76 exact UART/cloud sample matches and stopped/stale readings. This verifies the electrical/rotor response and delivery, not water-flow accuracy. Calibration remains unknown; raw pulse frequency and timing are the primary measurements.

## Green living UI prototype

`/` and `/living` open publicly without an access key and show **Overall Data**, the leftmost default tab. Navigation is **Overall Data · Shopping · Transport · Home Sensors**; the former Home tab is replaced. A compact green-index/footprint band leads into equal-size treemap and map panels. The treemap uses continuous macro-category regions with smaller named activities; category names filter and item labels open their records. Areas follow known estimates, with small labels hidden when they do not fit. Phones show the diagrams sequentially. Scrolling reveals trends, resource totals, input requests and records. **Filter** holds Period, Activities, Category and Smoothing, with Reset and Done. Estimation details stay closed initially.

All four tabs share the same minimal styling. Shopping groups purchases into expandable rows under clothing, groceries, electronics and other subdivisions; packaging grams and product kg CO₂e stay separate. Transport supports MTR/bus/car confirmation or Skip, retaining skipped journeys as unresolved. Home Sensors shows completed shower and appliance examples with plain-language comparisons. Raw readings, formulas and sources sit behind **How we estimated this**. The real research stream remains at `/sensors`, protected by viewer/admin sign-in at `/login` (also linked as **Research sign in**). It shows pulse counts, frequency, timing and upload history. Home Sensors contains synthetic session examples; electricity metering is not connected. This interface uses a **fixed synthetic Hong Kong scenario**; live uncalibrated pulses are not converted into household activities.

The same `shower-01` record supplies the 48 L / eight-minute session, comparison to 40 L from eight synthetic prior sessions and Overall Data water totals. Correcting its litres/duration updates both views. Trip confirmation updates estimates and coverage once; catalogue confirmation updates packaging without inventing carbon from HK$45 spend. Corrections stay in this browser tab's `sessionStorage` and can be reset. They are previews, not saved research records or device calibration changes. JSON export includes selected records, corrections, sources and comparison.

Overall Data combines the green index, treemap, **Contour / 3D landscape** map, activity records including unknown estimates, coverage and four synthetic weekly totals. The gauge is the **green index**, with **−1 left, 0 up, +1 right**. Its current **+0.35 is a synthetic placeholder** while the scoring formula is undefined; changing activity filters or corrections does not invent a score. Separately, **Over time** shows `(reference − selected) / reference` as a percentage, with no percentage for a zero reference. Both periods use the same length, scope and category; incomplete coverage is disclosed. Category drill-through retains date/scope and restores all categories for the other tabs.

3D loads initially on Overall Data; select Contour for a flat map, or drag in 3D and use rotate/zoom/reset. Height represents the same density in kg CO₂e/km², exaggerated for clarity. Both modes share data, filters, smoothing and legend. The renderer loads only when needed, reuses displayed street tiles and falls back to contours without WebGL 2. Marker/table links open activity records; treemap categories filter records and can open the corresponding activity tab.

The map includes known carbon estimates; water with no factor stays unknown and appears separately in litres and coverage. The current week has 20 example records, 16 known estimates totalling 18.3404 kg CO₂e, and eleven distinct locations with known estimates around Mong Kok, Yau Ma Tei and Jordan. Locations are fictional examples, not collected GPS. Density uses mass-weighted Gaussians in a local metre projection, a 96×96 grid and four-sigma padding, with a tighter **150 m default smoothing radius**. A closer street view, clearer tiles and high-density display support expose more detail. Smoothing changes density, not the input total. This is point attribution, not air pollution or route reconstruction. The rail example uses 23.4 km × 0.041 kg CO₂e/passenger-km, verified in the [MTR Sustainable Finance Report 2025](https://www.mtr.com.hk/sustainability/assets/pdf/en/2025/MTR_Sustainable_Finance_Rpt_2025.pdf), covering railway operational GHG. Distance/stops remain illustrative. Other factors, weights and baselines are unverified demo inputs. Selected shopping names/fields are adapted from the supplied Shopping.json; no payment, Taobao or Octopus integration is implied.

`GET /api/v1/living/activities` returns the fixed scenario. `POST /api/v1/living/activities/preview` recalculates it with `period` (`week`, `fortnight`), `scope`, `category`, `bandwidth_m` and up to ten bounded `corrections`. These two synthetic-scenario endpoints allow anonymous access when `PUBLIC_DASHBOARD=True` (the default). Browser preview POSTs still require the CSRF token supplied by the public page. They never grant a viewer role or write SQLite. Explicit Bearer credentials are still checked. Set `FLOW_PUBLIC_DASHBOARD=false` or `PUBLIC_DASHBOARD=False` in private instance configuration to restore the access-key gate. Real sensor data, raw preview APIs, uploads, feedback writes and admin operations retain their existing authentication. Example:

```json
{"period":"week","scope":"all","corrections":[{"id":"trip-02","mode":"mtr"}]}
```

The earlier `GET /api/v1/living/example` and `POST /api/v1/living/preview` raw-activity APIs remain available separately. Future persistent activity storage should retain source, status, activity/time/unit, factor version, method, location precision and user confirmation. Research datasets and live APIs are not connected yet. GPS inference, session detection, Bayesian baselines, background tracking and opt-in push delivery are future work. Feedback here is in-app, with source assumptions disclosed.

Map/chart scripts are pinned local copies: Leaflet 1.9.4 (BSD-2-Clause), D3 7.9.0 (ISC), and Three.js r170 / OrbitControls (MIT; only its import path changed), with licenses included. Street imagery comes from OpenStreetMap with attribution and normal caching, following its [tile policy](https://operations.osmfoundation.org/policies/tiles/). Only the green-living pages (`/living` and the public `/` dashboard) allow that tile origin and an origin-only cross-site referrer; scripts remain same-origin. No bulk/offline tile downloader is included. Failed tiles produce a visible message.

## First upload to PythonAnywhere

Already created `~/mysite/flask_app.py` using PythonAnywhere's Flask setup? Keep that web app. The ZIP now includes `flask_app.py` and matches its default entry point. This project needs the whole ZIP, including the `sensorlab/` package, templates and static files; uploading only flask_app.py is insufficient.

1. Open PythonAnywhere **Files**, go to `/home/YOUR_USERNAME/mysite/`, and upload **`dist/pythonanywhere-starter.zip`** from this computer. Upload the ZIP itself, without opening it in the online editor. If it already appears beside `flask_app.py`, it is in the correct directory.
2. Open **Consoles > Bash** and run:

```bash
mkdir -p ~/mysite
cd ~/mysite
# Preserve the initial starter file before replacing it.
if [ -f flask_app.py ]; then cp -n flask_app.py ~/flask_app.starter.backup.py; fi
unzip -o pythonanywhere-starter.zip
python3.11 -m venv ~/.virtualenvs/sensorlab
source ~/.virtualenvs/sensorlab/bin/activate
pip install -r requirements.txt
python bootstrap.py
```

If you uploaded the ZIP to your home directory instead, use `unzip -o ~/pythonanywhere-starter.zip -d ~/mysite`. A ZIP listed by `dir` in `~/mysite` is at `~/mysite/pythonanywhere-starter.zip`; the shorter `~/pythonanywhere-starter.zip` points to a different location. Run `bootstrap.py` with the full `.py` extension after extraction and dependency installation succeed.

Use Python **3.11 or newer**, matching the version shown in the **Web** tab. If your newly created app says **3.10**, change its Python version to **3.11** in Web first, then use the commands above. If you choose 3.13, use `python3.13` instead. Setup prints private admin, viewer and device keys. Save them privately: admin/viewer keys sign into the research sensor dashboard; the main synthetic dashboard is public. The device key authenticates sensor uploads. Repeating setup preserves existing keys and data.

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
python tools/deploy_pythonanywhere.py auth
python tools/deploy_pythonanywhere.py deploy
python tools/deploy_pythonanywhere.py check
```

`plan` and `bundle` work offline. `auth` checks the account Files and Webapp APIs using GET only, reporting access and whether the remote release matches local source without returning source or private settings. `deploy` runs web tests, compares the release manifest, snapshots affected remote source to ignored `output/deploy/`, uploads changes, reloads and verifies the running release and database readiness. If the reload response is lost, it still requires the expected running release and healthy database before accepting the deployment, and reports `reload_acknowledged: false`. On upload or health failure it attempts source restoration and requests another reload. It never replaces instance configuration or research databases. API requests are paced for the documented rate limit.

Keep subsequent source updates through the updater so its manifest stays current. Install changed requirements in the remote virtualenv before deploying a dependency update. Initial WSGI/virtualenv setup and database migrations are separate operations; source rollback does not roll back a database migration. The live site passes health/readiness/login checks. Account API access is now verified: a temporary file passed upload, exact readback and deletion, and the official Reload API succeeded with healthy release/database checks afterward. The temporary file was removed; the current dashboard update was subsequently deployed through the same snapshot/reload workflow, preserving instance configuration and the research database. The provider account token remains in the ignored local settings and is separate from SensorLab application role keys. Run `auth` to check access before subsequent API deployments.

The direct-upload release is published on `test/esp32-wroom` at code commit `e632ec6`; [all three CI jobs](https://github.com/WYT10/isdn2001-02-yp/actions/runs/44198904761) passed (40 web/provisioning/deployment tests, native/source checks, and clean WROOM/S3 builds). The connected WROOM is flashed and uploading.

## Direct sensor uploads

Create **ignored** `.local/cloud.json` using the site's **device** key only:

```json
{"url":"https://YOUR_USERNAME.pythonanywhere.com/api/v1/readings","device_token":"YOUR_DEVICE_KEY"}
```

When first adding or removing a private profile, run `pio run -e esp32_wroom -t clean` once, then build and flash normally. CMake generates a private header; no cloud key is committed, and public builds disable uploading. Private firmware images contain credentials and must stay private. Self-test builds disable uploading so synthetic waveforms cannot enter the real dataset. Network and uploader defaults live in `app.wifi` and `app.cloud` in main.c; implementation stays in wifi.c/h.

The board uses CA-verified HTTPS without redirects, an ID derived from its MAC, a random boot ID and increasing sample sequence numbers. Every 250 ms report is enqueued without waiting for the network. Up to 24 reports are sent per request on a three-second schedule; the HTTPS connection is reused after success, and an unsuccessful batch is retained unchanged for deduplicated retries with 5–60 second backoff. Invalid/authentication/conflict responses block further uploads until reboot/configuration correction and are visible in `wifi status` and local `/api/status`.

The default cloud schedule can send at most 24 reports per three-second interval before network overhead; faster CLI reporting may overflow the queue unless the compiled upload schedule is adjusted. The acquisition priority reduces scheduling jitter, but it is not a hard real-time guarantee.

Buffering is **RAM only**: 24 waiting reports plus at most 24 pending reports. A full queue drops new reports and increments `upload_dropped`; sequence gaps remain visible in the chart. Reboot loses unsent reports. This starter does not provide persistent offline logging. Use `wifi status` for acknowledgements, pending/queued reports, failures, clock state and drops; no token is returned. The 2 MiB application partition starts at 0x10000; NVS remains 0x9000/0x6000 and PHY remains 0xf000/0x1000. Do not erase flash when updating.

SNTP adds `observed_at` only after a confirmed time sync. Raw uptime is always retained. Dashboard lines use device elapsed time anchored to the latest server receipt per boot, preserving spacing across batches; breaks mark sequence gaps/restarts. This receipt anchor is an approximate wall-clock position, not an upload-latency measurement. Window summaries and time-bucket analytics use server receipt time. The dashboard shows actual board/GPIO/report settings, boot pulse totals, queue/drop snapshots and database readiness. Unknown calibration keeps litres and L/min null.

SQLite already stores devices, immutable raw readings, unique `(device_id, boot_id, seq)` identities and linked observations, with indexes and atomic transactions. JSON retains raw metadata; CSV and the analytics API support further research. Source updates preserve the private database. Back it up with the existing backup command before independent schema work.

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

Public-access changes additionally passed all 63 tests, including anonymous preview CSRF, data preservation, research/API access boundaries, disabling public mode and research login/logout. Local and hosted Chromium passed public navigation, browser-session corrections, protected API checks and research sensor login at 1440/390/320 widths with no overflow or JS/console errors.

The approved redesign passed 58 Flask/deployment/provisioning tests, including activity correction/coverage/reference invariants, subdivisions reconciling to macro totals, independent green index, KDE mass, access boundaries, CSRF, research-data preservation, extracted-ZIP startup, deployment rollback and lost reload responses. Local and deployed Chromium checks passed all four tabs at 1440, 768, 390 and 320 widths, proportional treemap areas, equal chart sizing, eleven locations, compact filters, record links, trip and shower corrections, catalogue confirmation retaining unknown carbon, session reload, themes, contour/3D, export and empty states without overflow or JavaScript/console errors. Automatic contour fallback without WebGL also passed. A visual review compared the selected mockups with actual captures; gauge readability and a mobile map-label overlap were corrected. These are browser viewport checks, not certification on every physical operating system or iPad model. The updater allows 90 seconds for reload and verifies the expected release after a transport disconnect; file/public requests retain 20 seconds. The public-access release is `500c5f99`, with healthy schema-1 database checks. Its approved-design predecessor was `bc156ce4`; that design source is published on `test/esp32-wroom` at [fbe8fc1](https://github.com/WYT10/isdn2001-02-yp/commit/fbe8fc1). Its reload response disconnected after 60.7 seconds; the updater confirmed the exact running release before accepting it. Earlier WROOM ingestion and air-test evidence remains separate from this synthetic demo.

## Firmware

PlatformIO/ESP-IDF structure is retained: `src/`, `include/`, `components/`, `test/host/`, `platformio.ini` and `sdkconfig.defaults`. Application firmware has four C files: `main.c` wires the application and owns settings; `wifi.c` handles scanning, reconnection and the local fallback dashboard; `flow_sensor.c` contains PCNT/capture, calculations, DSP benchmarks and synthetic tests; `cli.c` handles bounded serial commands over native USB or the board UART bridge. The public interfaces are `wifi.h`, `flow_sensor.h` and `cli.h`.

Edit the typed `app` initializer in `src/main.c`: `.sensor` holds GPIO, pull-up, edge capture, glitch filter, stale timeout, report interval, averaging window and calibration; `.wifi` holds credentials, retry/status intervals and nested `.fallback` settings; `.cli` controls the serial interface and default stream; `.diagnostics` controls benchmarks and the separate test GPIO. Both modules copy their configuration. The current test hotspot is `ABCD` / `00000000`, WPA2-Personal, on the selected ESP32 board's 2.4 GHz radio. Empty passwords select open authentication; a nonempty password selects a minimum WPA2 authentication threshold. Previous account configuration was removed. Application and hosting keys remain private.

The network task retries ABCD continuously, five seconds after each failed attempt. If it has no station IP for 60 seconds, it enables AP+STA fallback:

- Join **SensorLab-Local** on XIAO or **SensorLab-WROOM** on WROOM, password **00000000**, and open **http://192.168.4.1**. If your phone warns that this network has no Internet, choose to remain connected.
- The responsive page shows raw frequency, pulse counts, high/low time, duty cycle and calibrated values when available. It polls `/api/status` once per second; the reader itself still reports every 250 ms. `/healthz` reports local HTTP liveness.
- Station retries continue, spaced 30 seconds after failures once fallback is active. The local AP stays on until reboot, including after station recovery. The HTTP server then also listens on the station IP.
- The trigger is missing IP, rather than an Internet health check. AP+STA shares one radio/channel; scanning or upstream channel changes can briefly interrupt local clients. There is no Internet forwarding/NAT.
- The driver's individual authentication/association timers are unchanged. App retry/wait logs include attempt numbers and elapsed milliseconds. Sensor reporting runs independently.

Earlier XIAO tests used no external antenna. That serial probe confirmed the configured AP is active and not hidden, and all three HTTP loopback routes pass. However, the phone still cannot discover it after a fresh restart, hotspot off and a check 5-10 cm from the board; a 60-second watch recorded zero clients. Nearby networks appeared weak at -85 to -94 dBm, and ABCD was absent. Missing antenna is the leading hypothesis; a known-good compatible antenna is needed to test it against other RF faults. [Seeed warns that Wi-Fi may fail without the antenna](https://wiki.seeedstudio.com/xiao_esp32s3_wifi_usage/#installation-of-antenna). Driver configuration and internal HTTP checks do not establish over-the-air visibility.

ZJ-S201C signal: **D15/GPIO15 on WROOM**, or **D10/GPIO9 on XIAO**, with common ground and a 3.3 V compatible signal interface. Supply the sensor according to its label. A GPIO pull-up does not level-shift a driven 5 V signal.

PCNT continuously counts rising edges with a 1 microsecond glitch filter and extended counter wrap. MCPWM measures rising/falling edge times for frequency, high/low duration and duty. Normal firmware never drives the selected sensor input. Measurements update every 250 ms by default, with approximately a one-second rolling frequency window. Serial streaming starts off for readable command replies; the local dashboard keeps updating independently. `app.sensor.pulses_per_litre=0` until calibrated, so flow and volume remain null. Obtain the exact coefficient from the sensor datasheet or a known-volume collection. The configurable rolling window is bounded to 1-32 report samples.

```bash
pio run -e seeed_xiao_esp32s3
pio run -e seeed_xiao_esp32s3 -t upload --upload-port COM19
pio device monitor --port COM19 --baud 115200
python tools/serial_cli.py --port COM19 stream on
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

## ESP32-WROOM branch

Branch `test/esp32-wroom` defaults to `esp32_wroom`. Both boards use the same four application C files and portable sensor/command logic. Board-specific defaults remain in the typed `app` initializer in `main.c`; target SDK settings are in `sdkconfig.defaults.esp32` and `sdkconfig.defaults.esp32s3`.

| Target | Sensor input | Serial interface | Local AP | Flash setting |
|---|---|---|---|---|
| `esp32_wroom` (`esp32dev`) | D15 / GPIO15 | UART0 via USB bridge, 115200 | SensorLab-WROOM | 4 MB |
| `seeed_xiao_esp32s3` | D10 / GPIO9 | Native USB Serial/JTAG | SensorLab-Local | 8 MB |

The current WROOM sensor signal is on the pin labelled D15, mapped to GPIO15. This supersedes the earlier GPIO27 wiring. Share ground and use a 3.3 V-compatible signal. The pulse reader uses digital PCNT/MCPWM, not an analog ADC reading. GPIO6-11 are reserved for the classic ESP32's module flash; do not copy the XIAO GPIO9 wiring to WROOM. Leave UART0 GPIO1/3 available for the USB bridge. Boot and reading JSON identify the selected board and input GPIO, and the local page displays those actual values.

Use the detected WROOM COM port in place of COM_PORT below. Identify the actual chip/MAC and save its original flash before its first upload; the XIAO backup cannot restore a different board. A power LED only establishes power, not USB data communication.

```bash
pio run -e esp32_wroom
pio run -e esp32_wroom -t upload --upload-port COM_PORT
python tools/serial_cli.py --port COM_PORT help
python tools/serial_cli.py --port COM_PORT wifi ap only
python tools/serial_cli.py --port COM_PORT wifi status
python tools/serial_cli.py --port COM_PORT --watch 15 stream on
python tools/serial_cli.py --port COM_PORT stream off
```

For local Wi-Fi, join **SensorLab-WROOM**, password **00000000**, then open **http://192.168.4.1**. `wifi ap only` activates it immediately after network setup. Automatic fallback still starts after 60 seconds without a station IP. The distinct SSID prevents confusion with a nearby XIAO AP. The upstream test hotspot stays ABCD/00000000.

Optional synthetic firmware is `esp32_wroom_selftest`, using disconnected GPIO4; restore `esp32_wroom` afterwards. Do not run it with anything connected to GPIO4. The generic profile assumes a classic ESP32-WROOM and 4 MB flash; confirm the actual hardware before uploading. PlatformIO's [esp32dev profile](https://docs.platformio.org/en/latest/boards/espressif32/esp32dev.html) and Espressif's [GPIO restrictions](https://docs.espressif.com/projects/esp-idf/en/v6.0.1/esp32/api-reference/peripherals/gpio.html) describe this target.

The replacement WROOM on COM16 (MAC ending 4b:fe:38) passed its first real hardware test on D15/GPIO15. ABCD connected on the first attempt at 10.64.117.36, with -46/-43/-44 dBm across three scans; eduroam was visible too. The user joined SensorLab-WROOM and opened its dashboard, with one client confirmed by the driver. Blowing air through the sensor counted 1236 pulses, peak rolling frequency 57 Hz, captured high/low/duty timing and cleared stopped/stale readings. Flow calibration remains unknown. The local build, all flash-region hashes, three DSP numerical cases and both chip builds/source checks in GitHub CI passed. No WROOM synthetic-output test or water accuracy test is claimed.

### Private enterprise Wi-Fi

An optional ignored `.local/wifi.json` selects a private PEAP profile when configuring the firmware. It has `ssid`, `identity`, `username`, `password` and `server_domain` string fields. Keep real values out of source, command arguments and dashboard routes. The generator writes only into the ignored build directory; firmware containing the profile is private too. Without this file, builds use ABCD/00000000. Force a clean build when first adding or removing the profile so CMake regenerates it.

For HKUST, use PEAP/MSCHAPv2 with server domain `wireless.ust.hk` and the system CA bundle, following [HKUST's instructions](https://itso.hkust.edu.hk/services/general-it-services/wifi/wi-fi-services/configuration-eduroam/Android). The implementation verifies the CA chain and hostname and keeps certificate-time checks enabled. It seeds the board clock from build time before the first authentication; this is a bootstrap clock, not a measured network-time service. The sensor CLI and local HTTP routes never return enterprise identity or password. The private WROOM build connected to eduroam on its first attempt at 10.89.157.94 with validation enabled, retained its IP during the check and kept SensorLab-WROOM active alongside it. Actual host requests to the dashboard, health and status routes returned HTTP 200 with credentials absent. Build/flash/serial logs and authored-source checks also passed the secret audit. Account values, generated headers and the credential-bearing firmware remain excluded from Git and the upload ZIP. Public/default builds retain ABCD; the sensor input remains D15/GPIO15.

## USB serial commands

Commands run at 115200 baud through native USB Serial/JTAG on XIAO or the USB-to-UART bridge on WROOM. Close other serial monitors before using the helper. Install pyserial with the development requirements, then run from this project:

```bash
python tools/serial_cli.py --port COM19 help
python tools/serial_cli.py --port COM19 status
python tools/serial_cli.py --port COM19 get
python tools/serial_cli.py --port COM19 set report_ms 100
python tools/serial_cli.py --port COM19 set window_samples 8
python tools/serial_cli.py --port COM19 --watch 5 stream on
python tools/serial_cli.py --port COM19 stream off
python tools/serial_cli.py --port COM19 wifi status
```

For an interactive terminal, use `python -m serial.tools.miniterm COM19 115200 --eol LF --raw --echo`, then type commands and press Enter. Exit miniterm with Ctrl+]. The helper also accepts commands from Windows Command Prompt or PowerShell without editing firmware.

| Command | Behavior |
|---|---|
| `help` | List commands and ranges |
| `status` | Latest measurement, uptime, free heap, serial stream and revision |
| `get` / `get NAME` | Read the current runtime settings |
| `set report_ms N` | Report interval, integer 50-10000 ms |
| `set window_samples N` | Averaging window, integer 1-32 reports |
| `set pulses_per_litre N` | Calibration, finite 0-1e9 pulses/L; zero means unknown |
| `stream on` / `stream off` | Enable/disable serial measurement output; local HTTP continues |
| `wifi status` | Actual driver mode, AP SSID/hidden flag/channel/MAC, clients and transmit-power limit |
| `wifi scan` | Scan in station/AP+STA mode; temporarily uses the radio off channel |
| `wifi reconnect` | Schedule another upstream connection; unavailable in AP-only mode |
| `wifi ap on` | Open the local AP immediately with station retries |
| `wifi ap only` | Local AP on channel 6, with upstream station/scanning stopped |
| `wifi auto` | Resume station retries and automatic fallback; an already opened AP stays on |
| `benchmark` | Run the DSP microbenchmark; this can delay a report |
| `reboot` | Restart and restore the compiled default settings |

Changes are **volatile until reboot**. Set calibration only from the sensor specification or a known-volume experiment. The acquisition task runs above the uploader/CLI/network-control tasks and owns runtime settings; the network task owns Wi-Fi mutations. Hardware pulse counting continues independently of HTTPS. Queued Wi-Fi requests have a separate completion response, which the helper waits for. There is no command to drive the sensor GPIO, execute a shell or erase NVS.

Changing the report interval changes the telemetry rate; hardware pulse counting and edge capture continue independently. Changing the interval/window clears the rolling calculation window while preserving accumulated pulse counts. Every reading includes report interval, averaging size, calibration and config revision. Inputs are limited to 95 ASCII characters; invalid/overlong lines are discarded completely. LF, CR, CRLF, backspace and Ctrl+C cancellation are supported.

If the AP is missing on a phone, run `wifi ap only`, then `wifi status`, and check for **SensorLab-Local** / **00000000** at **http://192.168.4.1**. This removes reconnect scans during discovery. It does not establish antenna/RF performance: this board currently has no external antenna. After the check, `wifi auto` resumes the normal fallback behavior.

The CLI firmware was built and flashed to the serial-verified board, with all three flash regions hash-verified. On-board tests passed command round trips, invalid/overlong input rejection, 100 ms reporting with eight-report averaging, responsive commands at a ten-second report interval, stream-off cache updates, calibration round trips, numerical DSP checks and reboot restoring defaults. The automatic fallback opened after 60.101 seconds and all three HTTP loopback routes passed. AP-only/AP+STA/auto transitions passed without duplicate connection attempts. The board is left in AP-only mode, with the driver confirming the visible SSID and channel 6. The subsequent phone discovery test failed even after a fresh AP-only restart and disabling the phone hotspot; external dashboard access remains unverified. No new physical pulses arrived during this command test; the earlier air test remains the real sensor-signal evidence.

## Layout and Git hygiene

```text
agent.md                    Agent rules and maintained memory
readme.md                   Setup, API and operations
src/main.c                  Application settings and reporting loop
src/wifi.c                  Wi-Fi, HTTPS uploader, local dashboard and fallback
src/flow_sensor.c           Sensor driver, calculations and diagnostics
src/cli.c                   Serial command parser and USB input task
include/wifi.h              Typed Wi-Fi configuration/API
include/flow_sensor.h       Typed sensor configuration/API
include/cli.h               Typed command/configuration interface
components/esp-dsp/         Minimal upstream acceleration dependency
components/cjson/           Pinned cJSON v1.7.19 with MIT license
partitions.csv              2 MiB application, original NVS/PHY locations
web/                        Flask source, templates, assets and upload example
test/host/ test/web/        Native C and Flask/deployment tests
tools/                      Build, capture, deployment and project checks
```

Git ignores credentials, databases, virtualenvs, PlatformIO output, deployment snapshots, browser artifacts and ZIPs. Additional Markdown files are ignored; the project check enforces the two-document rule in authored source. Dependency licenses are retained.

Public repository: [WYT10/isdn2001-02-yp](https://github.com/WYT10/isdn2001-02-yp). The tested serial CLI and AP-only diagnostics are published on main at code commit `401fcf9`; the [CLI CI run](https://github.com/WYT10/isdn2001-02-yp/actions/runs/43998281707) passed both the source/web/native checks and the clean Linux firmware build. The previous [SensorLab CI run](https://github.com/WYT10/isdn2001-02-yp/actions/runs/43994801212) passed both jobs: web/native tests, publication audit, ZIP packaging and the clean Linux firmware build. The branded firmware built locally and passed the on-board check. Both jobs passed for the earlier code commit `40a4671`. GitHub Actions supplies the PythonAnywhere ZIP as an artifact. The final documentation update records the separate on-board and browser results.

The local checkout is linked to origin/main after the earlier workspace restriction was lifted. Source edits can be committed and pushed using the normal Git workflow. Build output, captures, instance configuration and research databases remain ignored. Firmware version `0.1.0` is explicitly set in the root CMakeLists.txt, so building also works from a source ZIP or an empty local Git history.

