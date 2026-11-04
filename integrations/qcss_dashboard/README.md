# QCSS Explorer

An operator dashboard for QCSS that explains, visualizes and configures every layer of the simulator. Every number on
screen is computed by QCSS's own code: the compiler, the validator, the signal chain, the engines and the readout model.
None of it is mocked or re-derived in the browser.

QCSS Explorer is an **operator surface**: it shows the chip's hidden truth and drives the admin channel. It adds nothing
to the lab link, so what a lab client can see is unchanged. That is the indistinguishability rule: the lab link must
never reveal that it is a simulator.

## Run it

```bash
# once: build the frontend (Node 20.19+ or 22)
cd integrations/qcss_dashboard/web && npm ci && npm run build && cd -

# start the bridge with an embedded virtual lab (qblox_cluster_5q + transmon_5q) on http://127.0.0.1:8765
PYTHONPATH=integrations/qcss_dashboard/src uv run python -m qcss_dashboard.cli
```

Useful options (`--help` lists all of them):

| option | meaning |
|---|---|
| `--profile`, `--device`, `--time-scale` | what the embedded chassis runs; `--time-scale 0` freezes the chip and runs jobs unpaced |
| `--no-embedded --lab HOST:PORT --admin HOST:PORT [--ca server.pem]` | connect to an existing `qcss serve` instead |
| `--read-only` | refuse every change (configs, admin actions, calibration writes, jobs) |
| `--workspace DIR` | where your config copies, the audit log and the embedded chip state live (default `~/.qcss-dashboard`) |

Tokens are never taken from the command line. An external chassis's lab and admin tokens come from `QCSS_TOKEN` and
`QCSS_ADMIN_TOKEN`. An embedded chassis gets fresh random tokens on every start, and only the bridge knows them.

### Remote access

The bridge binds to loopback by default. Any other bind needs TLS (`--tls-cert`, `--tls-key`) **and** a login token in
`QCSS_DASHBOARD_TOKEN`; this is the same rule `qcss serve` applies. `--insecure` overrides it, and should only be used
on a network you trust. Browsers sign in with that token. Lab and admin tokens never reach the browser.

### Development

```bash
PYTHONPATH=integrations/qcss_dashboard/src uv run python -m qcss_dashboard.cli --time-scale 0   # API on :8765
cd integrations/qcss_dashboard/web && npm run dev                                                # UI on :5173, proxies /api
```

## What is where

| view | what it explains | computed by |
|---|---|---|
| Atlas | the layers, what flows between them, a real job followed through plan → render → evolve → read out → stream | `architecture.py`, `sandbox.explain` |
| Config Studio | every field of the five layers (profile, device, calibration, job, chassis): edit as a tree or YAML, validate, field-level diff with meaning and apply mode, save a copy, use the draft in the sandbox, restart the chassis with it | `registry.py`, `configs.py` |
| Hardware & timing | tick ruler, generator grids and memories, ports, feedback latency matrix, acquisition limits, validator rules | `hardware.py` |
| Program & compiler | compiled IR, timeline, waveforms, port streams against full scale, validator verdict with field paths | `sandbox.explain` |
| Signal chain | IQ mixer imbalance vs correction (image and LO leakage), flux-line tails vs predistortion | `physics_views.signal_view` |
| Chip truth | transmon parameters, flux tuning curve, level diagram, couplers (CZ time, ZZ), chip map, drift, TLS defects | `physics_views.chip_view` |
| Physics & tiers | tier router decision, lifted gates (leakage, nearest Clifford), populations, density matrix, Bloch trajectory | `sandbox.explain` |
| Readout | resonator ring-up, ADC traces, IQ clouds and threshold, confusion matrix, resonator spectroscopy, SNR vs window | `physics_views.readout_view` |
| Feedback & timing | one shot's discrete-event timeline, result-ready arithmetic, the drive the qubit actually saw | `sandbox.explain` |
| Board faces | how Qibolab, Qibosoq and QICK clients reach QCSS; DescribeDevice | lab link |
| Admin console | truth vs calibration, scenarios, live mode, instrument faults, job inspection, audit log | admin channel |
| Lab bench | Rabi, T1, Ramsey, single-shot, spectroscopy over the lab link, built only from what a client may know | `lab.py`, `experiments.py` |
| What-if lab | change one chip factor (A/B) or sweep it, and see what a lab would measure | `experiments.run_in_sandbox` |
| Tours & glossary | guided questions and every parameter, searchable | registry |

A global **explain depth** switch (plain / expert / source) sets how much each explanation shows: a one-line meaning;
then detail, type, default and range; then equations and the source file that implements the field.

## How it is built

* **Bridge** (`src/qcss_dashboard`, FastAPI). Lab-link calls go through `QcssClient` and admin-channel calls through the
  generated stubs, with both tokens held server-side. Deep internals come from a **sandbox**: QCSS's own
  `SimulationContext` and `ShotExecutor`, run in-process on a copy of the configuration. The live chassis discards these
  internals chunk by chunk. QCSS has no push events, so live state (mode, truth, calibration epoch) is polled and
  streamed to the browser over `/api/events`.
* **Registry** (`registry.py` + `explanations/*.yaml`). Fields are discovered from the Pydantic models, the proto
  descriptors and `ChassisConfig`. A test fails if any field has no explanation, or if an explanation names a field that
  no longer exists. Fields that are validated but never used at runtime are marked **inert**.
* **Frontend** (`web/`, React 19 + TypeScript + Vite + Tailwind). Charts follow the dataviz method; the categorical
  palette passes the six-check validator on the dark surface.
* **Guards.** Mutating calls need the `X-QCSS-Dashboard` header (a CSRF guard). Read-only mode, the login token, an audit
  log of every change, and shipped profiles and devices are never overwritten: drafts are saved under new names in the
  workspace.

## Tests

```bash
uv run pytest integrations/qcss_dashboard/tests -n 2             # bridge: registry, configs, views, sandbox, live chassis, CLI
cd integrations/qcss_dashboard/web
npx tsc -b && npx vitest run && npm run build                    # frontend unit tests and build
npx playwright install chromium && npx playwright test           # 15 journeys against the real bridge + embedded chassis
```

## Known limits

* Hardcoded physics is shown read-only and cannot be changed from the dashboard without a source change. This covers the
  TLS frequency and coupling ranges, the burst shape, `CHUNK_SHOTS = 1024`, the 4-qutrit T2 limit, and the upload-latency
  distribution.
* QCSS has no `ListJobs`, progress or event RPCs. The Lab bench lists only jobs the dashboard submitted, and live state
  is polled. Adding admin-only hooks for these is a separate, proto-changing step.
* The native QICK face is not on this branch yet. The Board faces view describes it; its tProc disassembly and event
  views will follow it.
