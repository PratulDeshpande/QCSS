# Architecture overview

Explanation. Current as of main at commit da53e92 (2026-11-05). Condensed from README.md, docs/HLD_QCSS.md (section 19, the virtual lab) and docs/control-stack-protocol.md.

## What QCSS is
A virtual superconducting-qubit lab. It stands in for control electronics (Qblox Cluster, Zurich Instruments SHFQC+, QICK on an RFSoC) and the chip behind them, so a quantum OS (Quark) can be developed against it. The OS reaches it as it reaches a real lab: through Qibolab, and cannot tell it is a simulator. Three design rules: hardware rules come from sourced YAML profiles; the chip's true state is hidden; behaviour is lab-like (entropy seeds, jobs take instrument time, chip ages while idle and survives restarts, simulator controls on a separate admin channel).

## The virtual lab (what runs where)

| Part | Role | Where |
|---|---|---|
| Chassis | The long-lived instrument process: physics, drift, persistence, pacing, one job at a time. A restart acts as an electronics reboot (uploaded settings lost, chip continues). | `qcss serve`, `src/qcss/chassis.py` |
| Instrument link | gRPC `qcss.v1.ControlService`, port 50051 by default | `src/qcss/adapters/grpc_server.py`, `proto/qcss/v1` |
| Qibolab driver | `QcssController`, thin gRPC client subclassing Qibolab's `Controller`; holds no physics; never writes calibration | `integrations/qcss_qibolab` |
| Platforms | Ordinary Qibolab folders `qcss_qblox_5q`, `qcss_rfsoc_5q` | `platforms/` |
| Qibosoq board face | Qibosoq-compatible TCP/JSON server on the chassis; `qcss_rfsoc_5q` uses Qibolab's unmodified RFSoC driver | `--board-listen`, `src/qcss/boards/qibosoq.py` |
| Native QICK face | `QickSoc` stand-in over Pyro4 (tProc v1 and v2) | `--qick-ns`, `src/qcss/boards/qick/` (see reference/qick-surface.md) |
| Technician | Runs the real Qibocal on a schedule and on request; installs calibration files atomically. Its files are the only calibration the OS sees. | `qcss technician`, `src/qcss/technician/` |
| Admin channel | Scenarios, modes, truth, job inspection, instrument faults, on its own address and token; never on the lab link | `qcss admin`, `proto/qcss/admin/v1` |
| QCSS Explorer | Operator dashboard (FastAPI bridge + React frontend) with an embedded chassis; adds nothing to the lab link | `integrations/qcss_dashboard` |

```text
Quark -> Qibolab -> platform qcss_qblox_5q (QcssController) --gRPC--> chassis
                 -> platform qcss_rfsoc_5q (RFSoC driver)   --Qibosoq TCP/JSON--> chassis
QICK client programs                                        --Pyro4--> chassis
technician (Qibocal) --writes parameters.json / calibration.json--> platforms
operator / CI --admin gRPC (own port + token)--> chassis
```

## Inside the chassis: layers and seams
Hexagonal (ports and adapters) around a per-shot timeline.
1. Interfaces: gRPC, board faces, offline tool; translation and error mapping only.
2. Runtime: job lifecycle, bounded result buffers, calibration store (epoch-versioned, compare-and-swap).
3. Compiler: job to internal program; hardware-rule validation against the profile (field paths reported).
4. Shot executor: discrete-event integer-tick timeline with feedback latency and time of flight.
5. Foundation: profiles, devices, time base, seeding. Depends on nothing.

Impairments enter at exactly four seams, so each error enters once: Render (frame phase, client IQ correction, hidden mixer truth, LO leakage, flux-line response), Parameters (drifting T1 and frequency, TLS defects, bursts on the lab clock), Evolve (state evolution), Readout (state to signal to label).

Job flow: Plan at `SubmitJob` (expand sweeps or take `program_points`, compile, validate, lift pulses, route a tier; refusals come before a job id exists) -> Render -> Evolve -> Read out -> Stream in fixed 1024-shot chunks whose random streams are keyed by (domain, sweep point, chunk).

## Fidelity tiers
T0 surrogate (classical bits), T1a Stim stabiliser (Pauli-twirled), T1b exact amplitude-damping statevector (up to 26 qubits), T2 multi-qutrit Lindblad (4 qutrits), T3 trajectories (not built, refused). AUTO prefers T1b; jobs leaking over 3 % or overlapping drive and flux on one qubit go to T2. QCSS refuses rather than silently downgrading. On a lab chassis the operator picks the tier (`--tier`); a client's `requested_tier` is ignored.

## Time and determinism
Time is an integer tick count (one tick rate per profile, exact LCM of the instrument's clocks). The lab clock runs on wall time scaled by `--time-scale`. With `--state-dir` the chip state persists as plain JSON and downtime counts as lab time. Seeds: chassis uses fresh entropy by default; `random_seed` is honoured only with `--deterministic` (and in `qcss run`).

## What a lab client cannot see
No tier or noise fidelity in `JobStatus`, no reflection (unless `--debug-reflection`), instrument-style error text, no true chip parameters, no `GetDeviceProperties`. Enforced by `tests/integration/test_indistinguishability.py` (CONTRIBUTING.md).

## Source layout
`src/qcss/`: `core` (time base, seeding, errors, net), `config` (profile/device schemas, YAML), `ir` (compiler, validator), `signal`, `device`, `physics`, `readout`, `feedback`, `timing`, `runtime`, `adapters`, `boards`, `technician`, `admin`, `v1` (generated), `chassis.py`, `client.py`, `cli.py`.

## Which docs are current and which are historical

| Document | Status |
|---|---|
| README.md, SECURITY.md, CONTRIBUTING.md, CHANGELOG.md | current |
| docs/HLD.md (v1.1, section 21 virtual lab), docs/HLD_QCSS.md (v1.1, section 19) | current baseline; describe ideas and as-built |
| docs/control-stack-protocol.md | current for the instrument link and admin channel (proto is the source of truth) |
| docs/remote-testing.md, docs/two-pc-setup-guide.md | two-machine guides; the header of remote-testing.md still describes the OS-driver flow; Qibolab path is section 8 (partly Qibolab-only, otherwise unverified current) |
| docs/hal-driver-design.md | Superseded (2026-11) per its own banner; kept for history; the QCSS-specific Quark driver `integrations/quark_qcss` is deprecated and to be removed next release |
| docs/layer-7-hld.md, docs/layer-7-lld.md | Quark-side Layer 7 design (draft dated 2026-10-26), written before the virtual-lab shift; treat as historical for QCSS integration (hal-driver-design's banner points to the README and HLD sections instead). Quark's own docs are in another repo. |

Note `docs/` and `reports/` are gitignored in this repo (CHANGELOG, commit 4656e98).

Sources: README.md, docs/HLD_QCSS.md (sections 5, 19), docs/HLD.md, docs/control-stack-protocol.md, docs/hal-driver-design.md (banner), docs/layer-7-hld.md (header), CHANGELOG.md, CONTRIBUTING.md.
