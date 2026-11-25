# Agent instructions

Read this file and `readme.md` first. Keep both short; they are the only authored Markdown files.

## Rules

- Work on `main`; inspect Git status and preserve user changes. Current target is ESP32-S3 dev kit, GPIO10, 4 MB flash, native USB serial.
- Keep four runtime files: main.c, wifi.c, flow_sensor.c, cli.c and their headers. Defaults belong in the typed `app` initializer. Sensor input must never be driven. Optional XIAO is D10/GPIO9; WROOM is D15/GPIO15.
- **User cleanup rule:** do not retain test suites, synthetic pulse generators, benchmark code, validation helpers or placeholder app trees. Perform necessary checks in temporary locations. After each check, remove temporary scripts, binaries, captures and caches. Keep only a short result in this Memory section. Preserve original board backups, private configuration, real databases and the useful deployment ZIP.
- Build firmware after firmware edits. Check changed web behavior temporarily and verify package contents/health before publishing. Keep runtime health endpoints and CI build/package checks. Distinguish a successful build from flashing, real sensor response and water accuracy.
- Before flashing, identify the actual chip/MAC/capacity and save/verify its original flash. Preserve NVS/calibration and `.pio/backup/`; never identify hardware from a COM number alone.
- Calibration stays zero/unset until measured. Keep litres/L/min null. Runtime serial changes are volatile. Main owns sensor settings; the network task owns network changes.
- Keep Wi-Fi, app and provider keys private in ignored configuration. Public firmware uses ABCD/00000000; private enterprise builds retain CA/domain/time validation. A board receives only a device key. Private headers/images/backups never enter Git or deployment packages.
- Preserve 60-second no-IP AP+STA fallback: SensorLab-Local/00000000 at 192.168.4.1 (WROOM uses SensorLab-WROOM). Retry upstream; no NAT. RAM uploads have bounded queues/drop counters.
- Preserve SQLite research data, idempotent ingestion, role boundaries and CSRF. Public dashboard access covers synthetic views only; /sensors and real APIs remain protected. Use PythonAnywhere Files/Reload APIs through the existing updater.
- Keep the approved LiveGreen icon and minimal four-tab dashboard. Activities and the +0.35 green index remain synthetic; do not invent factors, calibration or implemented mobile/account features. Raw reference folders stay local; select and sanitize reusable source before publication.
- Before ending work, replace stale Memory entries with concise changes, actual checks, blockers and the next action. Never expand this into a session transcript.

## Memory

- **25 Nov:** current GPIO10 setup/approved website consolidated on main, preserving both histories. Removed test suites, synthetic/benchmark firmware, benchmark-only ESP-DSP, validation helpers and DB demo seeder. Four runtime C files remain. Docs condensed; LF standardized. Historical diagnostics are private in .local/archive/main-cleanup-20261125/.
- **Validation:** baseline 63 web checks and native sensor/CLI checks passed before removal. Final dev-kit build passed (1,079,785 bytes flash; 41,584 bytes RAM). Temporary web checks passed: health, role boundaries, ingestion/retry/conflict and CSV. Deployment ZIP has 38 files matching Git source. Known private credentials absent from index and 253 history blobs. Temporary check files/caches removed. No flash performed during cleanup; cleaned web package is not deployed.
- **Last physical board, 24 Nov:** COM24, MAC 8c:45:98:0d:fc:bc, 4 MB flash. Backup/restore manifest: .pio/backup/s3-devkit-0dfcbc-20261124/ (verified original SHA256 0dc8e79f4bbd9837d8f17e9e6050eed696530921d1fd215ab24a59458215decc). GPIO10 reader connected to eduroam and uploaded 252 idle samples. Physical stimulus/calibration remain pending. Old XIAO/WROOM tests concern different boards.
- **Website:** greenwithisd.pythonanywhere.com, ~/mysite, SQLite schema 1. Live health/database and authenticated hosting API passed on 25 Nov. Provider configuration is .local/pythonanywhere.json; app role keys are .local/sensorlab.json. Never print them.
- **Product direction:** public Overall Data/Shopping/Transport/Home Sensors dashboard; protected real stream at /sensors. SQLite persists readings/feedback; synthetic corrections use sessionStorage. Future mobile interaction UI and later Kotlin/Flutter client share the backend/API/database. Persistent activities and individual user accounts are future work.
- **References:** React/TypeScript mobile UI is local-only; Android Java provides reviewed OCR/GPS and local SQLite/schemaVersion 1 JSON export, without cloud sync. Spreadsheet layouts, IDs, time zones, g/kg units and allocation need normalization. Shopping.json factors are illustrative. STEP CAD needs mesh conversion for browser use. Raw personal records/photos/APK/browser saves remain local and ignored.
- **Next:** user wants a website TODO list first. First milestone: owned activity storage/API, real sign-in, mobile add/edit flow and the same record on the desktop dashboard. Reuse selected React UI and Android JSON; verify item/factor evidence before estimating carbon. Native Kotlin/Flutter and CAD viewing are later work.
