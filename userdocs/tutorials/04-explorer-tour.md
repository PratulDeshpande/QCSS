# Tutorial 4: tour the QCSS Explorer

**You will:** start the Explorer dashboard with its own embedded virtual lab and visit its main views. **Time:** 15 minutes. **Verified:** the server start and its API (`/api/health`, `/api/settings`, `/api/experiments`) were run on loopback, 2026-11-05. *Unverified:* clicking through the browser views; the view descriptions come from `integrations/qcss_dashboard/README.md`.

## The idea
The Explorer is an operator surface: it shows the chip's hidden truth and explains every layer (compiler, signal chain, physics, readout). It adds nothing to the lab link, so clients still cannot tell they are on a simulator.

## 1. Build the frontend once
Needs Node 20.19+ or 22 (`node --version`):
```
cd integrations/qcss_dashboard/web
npm ci
npm run build
cd ../../..
```
This makes `integrations/qcss_dashboard/web/dist`. Skip it if `dist/` already exists (it did here).

## 2. Start the dashboard
`uv sync` first so the dashboard's dependencies exist (this repo's environment already had them). bash:
```
PYTHONPATH=integrations/qcss_dashboard/src uv run python -m qcss_dashboard.cli --port 8901 --time-scale 0
```
PowerShell:
```
$env:PYTHONPATH = "integrations/qcss_dashboard/src"
uv run python -m qcss_dashboard.cli --port 8901 --time-scale 0
```
You should see:
```
QCSS Explorer on http://127.0.0.1:8901  (workspace ...)
INFO:     Uvicorn running on http://127.0.0.1:8901 (Press CTRL+C to quit)
```
The `qcss-dashboard` command (defined in `integrations/qcss_dashboard/pyproject.toml`) is the same entry point if that package is installed; `python -m qcss_dashboard.cli` always works. Default port is 8765. `--time-scale 0` freezes the embedded chip.

Check the API is up from another terminal:
```
curl http://127.0.0.1:8901/api/health
```
```
{"ok":true,"version":"0.1.0","lab":{"target":"127.0.0.1:53963","ok":true,"error":null},"admin":{"target":"127.0.0.1:53964","ok":true,"error":null}}
```
(The embedded lab and admin use random ports and fresh random tokens; only the bridge knows them.)

## 3. Open the views
Browse to http://127.0.0.1:8901. Suggested path (names from the README):
1. **Atlas**: the layers and a real job followed from plan to stream.
2. **Chip truth**: transmon parameters, flux curve, drift, defects. This is what `qcss admin truth` prints, with pictures.
3. **Physics & tiers**: why the router chose T1B for a job, populations and Bloch trajectory.
4. **Readout**: IQ clouds, threshold, confusion matrix.
5. **Admin console**: kill a qubit, drift, inject faults (Tutorial 3, with buttons).
6. **Lab bench**: Rabi, T1, Ramsey, single-shot over the lab link (`/api/experiments` lists them: Rabi, T1, Ramsey and more). Run Rabi and compare with Tutorial 2.
7. **What-if lab**: change one chip factor and see what a lab would measure.
8. **Config Studio**: edit profile, device, calibration, job, chassis; shipped files are never overwritten, drafts are saved as copies in the workspace.

The **explain depth** switch (plain / expert / source) sets how much detail each explanation shows.

## 4. Use it on an existing server
Point it at a server you started yourself (for example Tutorial 3's), no embedded chassis:
```
PYTHONPATH=integrations/qcss_dashboard/src uv run python -m qcss_dashboard.cli --no-embedded --lab 127.0.0.1:50991 --admin 127.0.0.1:50992 --port 8901
```
Tokens are never on the command line: set `QCSS_TOKEN` and `QCSS_ADMIN_TOKEN` first. (*Unverified as a command; flags checked against `--help`.*) `--read-only` refuses every change.

## 5. Stop it
Ctrl+C in its terminal. A non-loopback bind needs `--tls-cert/--tls-key` plus a login token in `QCSS_DASHBOARD_TOKEN`, or `--insecure`.

Sources: `integrations/qcss_dashboard/README.md`, `integrations/qcss_dashboard/src/qcss_dashboard/cli.py`, `app.py`.
