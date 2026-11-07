# QCSS User Manual

## Chapter 9: Known limits

An honest list of what QCSS does not do, or does only approximately. Read it before trusting a result. Sources are the README "Limits" section plus facts from the code and the CLI output.

## 9.1 Not built

- **T3 (quantum trajectories).** The router refuses T3 with "T3 (quantum trajectories) is not implemented; request T2 for pulse-level physics". It is never silently replaced by another tier.
- **Qblox Q1Simulator face** and **QCoDeS mirror**. The `adapters` extra exists for the mirror only.
- **ZI platform folder.** A `zi_shfqc_5q` profile exists, but it has no flux lines and one sequencer per role, and no Qibolab platform uses it.
- **Dashboard views** of the native QICK face's tProc disassembly and event stream; the dashboard also has no job list, progress or event RPCs to show (chapter 7).
- **Per-user accounts and mutual TLS.** One bearer token per channel.

## 9.2 Refused by design (never silently downgraded)

| What | Where it is refused | Why |
|---|---|---|
| T3 request | tier router | not built |
| T2 above 4 qutrits | router (`T2_MAX_QUTRITS = 4`) | Lindblad state grows steeply |
| T1b above 26 qubits | router (`T1B_MAX_QUBITS = 26`) | statevector size |
| T1a with a pulse more than 1% from a Clifford, or non-Pauli feedback | router | stabiliser tier needs Cliffords |
| T1b with more than 3% leakage, or overlapping pulses on a qubit | router | gate tiers cannot represent leakage or overlap |
| Raw ADC trace on a tier other than T2 | router | only the physical readout makes traces |
| Qibolab driver: coupler flux, DC flux offsets and sweeps, `drive12`, unsupported sweep parameters | `QcssController` translation | outside the Qibocal routines the virtual lab targets |
| Qibosoq face: RAW (decimated) acquisition, nonzero DC bias | board face | same reason |

Consequence: time-of-flight and flux-spectroscopy routines are unavailable through these faces.

## 9.3 Approximations

- **LO leakage** is applied while a pulse plays, not as a continuous tone between pulses.
- **Long idles** (populations module): for delays of many T2, coherences are set to zero and, with exchange coupling present, the closed population equation is an approximation for long delays only.
- **T1a** uses Pauli-twirled noise (`noise_fidelity` "twirled"); only T1b, T2 are "physical" (`result.proto`).
- **T2 is slow for coupled gates.** A flux pulse on one qubit pulls its neighbours into a 4-qutrit run of about 17 s per sweep point (README), so a full CZ calibration (`cz.yml`) takes hours.
- **Initial chip is not the YAML.** Drift and TLS draws at start change T1 (observed 59, 38, 38, 12.5 and 29.5 us on a fresh chassis against 65, 58, 70, 52, 60 in `transmon_5q.yaml`), so do not compare directly with the file.
- **The shipped chip has no hidden mixer or flux faults** (no `faults:` block in `transmon_5q.yaml`), so a calibration against it will not meet mixer imbalance unless you add one.

## 9.4 Unverified numbers

- Profile values marked `verified: false` are calibration parameters, not facts. All QICK profile fields are unverified (`qick_zcu216_5q` lists 30, `qick_zcu216_4q` lists 8 via `qcss profile show`) and "follow one example firmware build". Qblox has five unverified RF-port entries; ZI and the ideal test profile are fully verified.
- The QICK firmware description is "one plausible build, not a verified bitstream" (`firmware.py`).
- The platforms' initial `parameters.json` are generated "last cooldown" values, not real measurements.
- Several literature-derived device defaults (`DynamicsSpec`) carry the note "defaults are calibration parameters (UNVERIFIED)".

## 9.5 Operational limits

- **One job at a time**; others queue.
- Results retention: 256 MiB per job, 256 finished jobs; resuming a dropped chunk returns `OUT_OF_RANGE`, an evicted job `NOT_FOUND`.
- A restart loses uploaded settings (like rebooting electronics) unless the client reprograms; without `--state-dir` the chip itself restarts from fresh entropy.
- `--deterministic` replays seeds only when set; the chassis never repeats by default.
- Board faces have no TLS or token; Qibosoq `reps` is not capped.
- Pyro4 firmware: the native QICK face does not serve every `QickSoc` method (`NOT_YET_SERVED` in `soc.py`: for example `tproc`, `streamer`, `load_mem`/`read_mem`, DDR4/MR buffer, time taggers, clock control, attenuator control, unit helpers like `freq2reg`). Programs relying on them may fail. Unverified per program.
- Qibolab is pinned to 0.2.17 and qibocal to 0.2.6; qick client to 0.2.370. Other versions are untested.
- Python 3.12 or 3.13 only.
- The Quark gRPC driver is deprecated and will be removed.

## 9.6 Things this manual did not verify

Run in this session: `--help` of the CLI, `profile list|show`, `device show`, `validate`, `run`, a short live chassis with `remote ping|describe|calibration|run` and `admin truth|mode|kill|clear` (ports 50981-50982, stopped afterward).

Read only (not run): the QICK face from a client, the Qibosoq face, the technician, TLS between machines, fault injection commands, the dashboard, the oracle and cross-tier physics tests, and the claims on literature references in source comments.

---
Sources: `README.md` (Limits), `SECURITY.md`, `src/qcss/physics/router.py`, `src/qcss/physics/populations.py`, `src/qcss/boards/qick/{soc,firmware}.py`, `src/qcss/config/device.py`, `src/qcss/config/profiles/*.yaml`, `src/qcss/runtime/jobs.py`, `integrations/qcss_dashboard/README.md`, `integrations/qcss_qibolab/src/qcss_qibolab/translate.py`, `integrations/quark_qcss/README.md`.
