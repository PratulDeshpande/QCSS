# Release notes (draft) and compatibility matrix

Status of versions, from the repo: `pyproject.toml` and both integration packages say `0.1.0`. Git tag `v0.1.0` exists (commit d7b16c3, 2026-10-19), and `CHANGELOG.md` already has a released `[0.1.0] - 2026-10-19` section. Everything after it is in `[Unreleased]` and has no version number yet. This draft is for the next release; its number is a maintainer decision (Unverified). The README calls the state "alpha (0.1.0, with the virtual lab unreleased)". Note the CHANGELOG says the deprecated `integrations/quark_qcss` "will be removed in the next release".

## Draft entry: next release (CHANGELOG [Unreleased]; 24 commits after v0.1.0 per `git log v0.1.0..HEAD`)

QCSS becomes a virtual lab: Quark reaches it exactly as it reaches a lab, through Qibolab, and cannot tell it is a simulator.

### Highlights
- Virtual lab: chassis behaves like a lab (entropy seeds, wall-clock pacing with `--time-scale`, persistent chip state with `--state-dir`, one job at a time).
- Qibolab driver `qcss-qibolab` (`QcssController`) and platforms `qcss_qblox_5q`, `qcss_rfsoc_5q`.
- Qibosoq-compatible board face (`--board-listen`).
- Native QICK face (`--qick-ns`, extra `qick`): unmodified `qick` programs, tProc v1 and v2, firmware `zcu216_v2_5q` / `zcu216_v1_5q`, loopback cables; profile `qick_zcu216_5q`.
- Technician (`qcss technician run|request`): real Qibocal on a schedule (`quick`, `full`, `cz` runcards), atomic installs.
- Admin channel (`qcss admin ...`): scenarios, modes, truth, job inspection, instrument faults, on its own address and token.
- QCSS Explorer (`qcss-dashboard`): operator dashboard with embedded lab, sandbox, admin and bench views, field registry.
- Client-resolved sweep points (`Job.program_points`), `ChannelInfo.lo_frequency_hz`.
- Acceptance harness and indistinguishability scan.

### Breaking
- `qcss serve` behaves like a lab chassis by default: entropy seeds (`--seed` optional), `random_seed` honoured only with `--deterministic`, operator-chosen tier (`--tier`, default auto), no tier/fidelity in `JobStatus`, no reflection unless `--debug-reflection`, generic internal-failure messages.
- An admin channel beside a tokened lab link needs its own, different token.
- `qblox_cluster_5q` rewired as a lab wires a cluster (one drive and flux line and sequencer per qubit; five readout sequencers on one feedline).
- AUTO routing prefers exact T1B up to 26 qubits; `transmon_5q` at T_eff 60 mK.

### Deprecated
- `integrations/quark_qcss` (to be removed in the next release).

### Fixed (selection; full list in CHANGELOG.md)
Calibration-epoch pinning against races; one job at a time; locked chip state; Explorer bounds and Host/origin guards; board-face size, stall and sweep limits; technician atomic install with rollback and bad-fit refusal; physics fixes (overlapping drive/flux, leakage routed to T2, T1B temperature); flag validation before the Pyro4 import check; CI runs QICK tests and hang diagnostics.

### Commit log, newest 12
```text
da53e92 Document the Explorer hardening, and dump stacks when a CI test hangs
e36b0c6 Run the QICK face's tests in CI, and report serve's flag errors first
aa86172 Bound the Explorer's GET views and count sandbox sweeps before planning
f2f266e Clean up after the QICK and Explorer merges: CI, docs, and two test fixes
0a97a7a Merge feat/qick-native-face: native QICK face
2668d86 Add a native QICK face: Pyro4 QickSoc with tProc v1 and v2
414c6b8 Fix the final review's findings: calibration writes, origin guards, trajectory, bounds, errors, restart
2b3e2cd Document QCSS Explorer and build its frontend in CI
ab3dd37 QCSS Explorer frontend: an explanatory control panel for every layer
49e92af Bridge: embedded chassis, admin and lab links, sandbox explain runs and physics views
b83a013 Add the QCSS Explorer bridge: parameter registry, config store and guarded API
7cef116 Add virtual-lab layer: admin channel, Qibolab integration, technician and chassis
```
(Only the 12 commits dated 2026-11-03 to 2026-11-05 are listed. The other 12 are dated 2026-10-19, the same day as the tag, and cover TLS/token auth, `QcssClient`, `quark_qcss` and fixes; run `git log --oneline v0.1.0..HEAD` for all 24. Whether they belong in 0.1.0 or the next release is Unverified.)

### Known limitations
No T3 engine; T2 limited to 4 qutrits (a CZ calibration takes hours); Qibolab driver refuses coupler flux, DC flux offsets and `drive12`; Qibosoq face refuses RAW acquisition and nonzero DC bias; no ZI platform folder; Qblox (Q1Simulator) face and QCoDeS mirror not built; profile numbers marked `verified: false` are estimates; one token per channel, no per-user accounts.

## Compatibility matrix

| Component | Version | Source |
|---|---|---|
| Python | 3.12, 3.13 (`>=3.12,<3.14`) | pyproject.toml; CI matrix |
| qibolab | `==0.2.17` (pinned exactly: Controller lives in private `qibolab._core`) | pyproject extras `qibolab`, `qibocal` |
| qibocal | `==0.2.6` | extra `qibocal` |
| qibo | `>=0.3,<0.4` | extras |
| qick (client, manual install) | `0.2.370` (the version qibosoq 0.1.5 pins; surface.json frozen against it) | CI, CONTRIBUTING.md |
| Pyro4 / psutil (extra `qick`) | `>=4.82,<5` / `>=5.9` | pyproject |
| qibosoq (manual, git pin) | commit `2c376278785e6ae8aae1f13d1b0b467e067aaf7d` (no numpy-2 release on PyPI) | CI, CONTRIBUTING.md |
| numpy / scipy / qutip / stim | `>=2.3,<3` / `>=1.16` / `>=5.2,<6` / `>=1.15` | pyproject |
| grpcio, protobuf | `>=1.71.2`, `>=5.29,<6`; grpcio-tools `>=1.71.2,<1.72` (dev) | pyproject |
| pydantic / click / pyyaml | `>=2.10,<3` / `>=8.1` / `>=6.0` | pyproject |
| pyright / ruff (dev) | `==1.1.414` / `>=0.6` | pyproject |
| Node (Explorer frontend CI) | 22 | ci.yml |
| OS in CI | ubuntu-latest and windows-latest for the test job (py3.12 and 3.13); ubuntu for lint, typecheck, proto, virtual-lab (3.13), dashboard-web | ci.yml |
| Wire contracts | `qcss.v1`, `qcss.admin.v1` (protobuf) | proto/ |

Not tested here: macOS is not in CI (classifier says OS Independent; Unverified). Qibolab/Qibocal are not installed on the documenting laptop, and its installed `qick` is 0.2.406, not the pin, so the pinned stack was not exercised in this session.

Sources: CHANGELOG.md, pyproject.toml, .github/workflows/ci.yml, CONTRIBUTING.md, README.md, `git log --oneline`, `git tag`.
