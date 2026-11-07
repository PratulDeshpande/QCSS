# QCSS User Manual

## Chapter 7: The QCSS Explorer dashboard

**QCSS Explorer** is a web dashboard that explains, visualises and configures every layer of the simulator. Every number on screen is computed by QCSS's own code (compiler, validator, signal chain, engines, readout model); nothing is mocked in the browser. It is an **operator surface**: it shows the chip's hidden truth and drives the admin channel. It adds nothing to the lab link, so a lab client sees no difference (the "indistinguishability rule").

Code: `integrations/qcss_dashboard` (bridge in `src/qcss_dashboard`, FastAPI; frontend in `web/`, React 19 + TypeScript + Vite + Tailwind).

## 7.1 Running it

Build the frontend once (Node 20.19+ or 22), then start the bridge:

```bash
cd integrations/qcss_dashboard/web && npm ci && npm run build && cd -
PYTHONPATH=integrations/qcss_dashboard/src uv run python -m qcss_dashboard.cli
```
It opens an **embedded virtual lab** (`qblox_cluster_5q` + `transmon_5q`) and serves on `http://127.0.0.1:8765`. Options (verified with `--help`):

| Option | Meaning |
|---|---|
| `--host` (default 127.0.0.1), `--port` (default 8765) | Where the dashboard listens |
| `--embedded` / `--no-embedded` | Run a chassis inside the bridge, or connect to an existing one |
| `--profile`, `--device`, `--time-scale` | What the embedded chassis runs (defaults `qblox_cluster_5q`, `transmon_5q`, 1.0) |
| `--lab HOST:PORT`, `--admin HOST:PORT`, `--ca PEM` | Existing chassis (defaults 127.0.0.1:50051 and :50052) |
| `--read-only` | Refuse every change: configs, admin actions, calibration, jobs |
| `--workspace DIR` | Your config copies, audit log and embedded chip state (default `~/.qcss-dashboard`) |
| `--static DIR` | Built frontend (default `web/dist`) |
| `--tls-cert`, `--tls-key` | TLS for the dashboard itself |
| `--insecure` | Allow a non-loopback bind without TLS and a login token |
| `--allowed-host NAME` | Host name browsers use to reach a network-bound dashboard (repeatable) |

Port note: pick a free port (`--port`) if 8765 is taken.

### Tokens

Tokens are never taken from the command line. For an external chassis the lab and admin tokens come from `QCSS_TOKEN` and `QCSS_ADMIN_TOKEN`. An embedded chassis gets fresh random tokens on every start that only the bridge knows. A network-bound dashboard needs TLS and a login token in `QCSS_DASHBOARD_TOKEN`; the browser shows a sign-in page ("QCSS Explorer - sign in") and the bridge never sends the lab or admin tokens to the browser.

## 7.2 The window

The left menu groups views as below. The top bar shows two status dots (`lab link`, `admin channel`), a **theme** toggle and an **explain depth** switch (plain / expert / source): plain gives a one-line meaning; expert adds type, default and range; source adds equations and the implementing source file. The choice is remembered in the browser. The "layer" badges mean: *lab* (what a lab client may know) versus *truth* (hidden state).

## 7.3 Every view (routes from `web/src/main.tsx` and `Shell.tsx`)

| Menu group | View | Route | What it shows |
|---|---|---|---|
| Overview | **Atlas** | `/` | The architecture map (adapters outside, one wiring layer, four physics seams inside) and a real job followed through plan, render, evolve, read out and stream with each stage timed. Also "Where every parameter lives": the five configuration layers. |
| Configure | **Config Studio** | `/config` | Every field of five layers: **A** profile, **B** device, **C** calibration, **D** job, **E** chassis. Edit as tree or YAML, validate with QCSS's own Pydantic models, field-level diff with meaning and **apply mode** (when a change takes effect), save a copy, use the draft in the sandbox, restart the chassis with it. Calibration is read and written over the lab link (compare-and-swap); the editor merges your edits over the qubit's full record. A parameter reference lists every field with unit, default, range, equation, source. Fields validated but never used at run time are marked **inert**. |
| Instrument | **Hardware & timing** | `/hardware` | Tick ruler, ports and generators, generator limits, feedback latency matrix, acquisition limits, validator rules and the profile fields they read, channel bindings of the device onto the instrument. |
| | **Program & compiler** | `/program` | The job as protobuf JSON (edit and re-run), program timeline per channel, compiled instructions, waveforms, port streams against full scale, and the validator's verdict with field paths. |
| | **Signal chain** (seam 1) | `/signal` | IQ mixer imbalance versus the lab's correction (image and LO leakage); flux-line step response versus predistortion. |
| | **Chip truth** (seam 2) | `/chip` | Transmon parameters, flux tuning curve, level diagram, couplers (CZ time, ZZ), chip map, frequency and T1 drift over hours, TLS defects. Marked as truth. |
| | **Physics & tiers** (seam 3) | `/physics` | Tier router decision with reason, lifted gates (leakage, nearest Clifford), populations, density matrix, Bloch trajectory, state through the pulses (re-evolved on T2). |
| | **Readout** (seam 4) | `/readout` | Resonator ring-up per level, readout parameters, single-shot I/Q clouds with threshold, confusion matrix, example ADC traces, resonator spectroscopy, SNR versus integration window, matched-filter weights. |
| | **Feedback & timing** (DES) | `/timing` | One shot's discrete-event timeline, "when is a result available" arithmetic (acquisition start + time of flight + integration), and the drive the qubit actually saw. |
| | **Board faces** | `/boards` | How Qibolab, Qibosoq and QICK clients reach QCSS, and what every client sees from `DescribeDevice`. Describes the native QICK face; views of its tProc disassembly and event stream are not built. |
| Operate | **Admin console** | `/admin` | Truth vs belief (calibrated drive versus true f01), live frequency drift and T1 charts, scenarios (kill, drift, TLS, burst, freeze, clear), live mode (SetMode), instrument faults, job inspection, and the audit log. |
| | **Lab bench** | `/lab` | Run experiments **exactly as a lab client** over the lab link, built only from what a client may know: Rabi (amplitude), T1, Ramsey (T2*), single-shot readout, qubit spectroscopy. Lists only jobs this dashboard submitted. |
| | **What-if lab** | `/whatif` | Change one chip factor (A/B compare) or sweep it, and see what a lab would measure. Runs in the sandbox, not on the live chassis. Capped at 201 sweep points. |
| Learn | **Tours & glossary** | `/learn` | Five guided tours and a searchable list of every parameter. Tours: why a pi pulse does not give exactly |1>; how a drifting chip spoils calibration; what decides how a job is simulated; why a branch cannot come sooner; what the lab never sees. |

Any other route shows "No such view."

## 7.4 Sandbox versus live chassis

Deep internals (states, traces, timelines) come from a **sandbox**: QCSS's own `SimulationContext` and `ShotExecutor` run in-process on a copy of the configuration. The live chassis discards them chunk by chunk. QCSS has no push events, so live state (mode, truth, calibration epoch) is polled and streamed to the browser over `/api/events`. A busy sandbox answers 503 instead of queueing.

## 7.5 Guards (what protects the dashboard)

- Mutating calls need the `X-QCSS-Dashboard` header (CSRF guard).
- `--read-only`, the login token, and an **audit log** of every change (`workspace/audit.log`).
- Shipped profiles and devices are never overwritten; drafts are saved under new names in the workspace.
- Unknown `Host` names and cross-origin mutations or WebSocket upgrades are refused (DNS-rebinding and CSRF defence).
- Request sizes are bounded (samples, integration, hours, points, shots, qubit); the GET and POST forms of the chip and readout views share bounds.
- A restart starts the new chassis first and keeps the running one if that fails.

## 7.6 Known limits (dashboard README)

- Hard-coded physics is shown read-only: TLS frequency and coupling ranges, the burst shape, `CHUNK_SHOTS = 1024`, the 4-qutrit T2 limit, the upload-latency distribution.
- No `ListJobs`, progress or event RPCs exist, so the Lab bench lists only jobs it submitted and live state is polled.
- No tProc disassembly or event-stream view for the native QICK face yet.

Unverified in this session: the frontend was not built or opened in a browser; the view list is taken from the router and sidebar source, and the view contents from the view source and the dashboard README. Only `--help` of the bridge CLI was run.

---
Sources: `integrations/qcss_dashboard/README.md`, `web/src/main.tsx`, `web/src/Shell.tsx`, `web/src/views/{Atlas,ConfigStudio,Hardware,Pipeline,Signal,Chip,Readout,Boards,Admin,LabBench,WhatIf,Learn}.tsx`, `src/qcss_dashboard/{experiments,architecture,cli}.py`, `SECURITY.md`. Run: `python -m qcss_dashboard.cli --help`.
