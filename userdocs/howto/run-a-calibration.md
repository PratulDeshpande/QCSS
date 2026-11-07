# How to: run a calibration (the technician)

**Goal:** keep a Qibolab platform calibrated by Qibocal against a running server. **Verified:** `qcss technician request` and its spool file, and `qcss remote calibration`. **Unverified:** a full `qcss technician run` (a long Qibocal job; not run on this laptop). Commands and flags checked against `--help`.

## The idea
Calibration is measured, never handed over. A *technician* process runs Qibocal against the platform, then writes `parameters.json` and `calibration.json` in the platform folder. The calibration identity (epoch) is the sha256 of those files. The chassis never writes calibration. A job pinned to an old epoch ends `REJECTED` (`CALIBRATION_EPOCH`) if a recalibration lands meanwhile (see `../troubleshooting.md`).

## Prerequisites
`uv sync --extra qibocal --group lab --group dev` (Qibolab, Qibocal, the QCSS driver), and a running server on the Qibolab face, with the state kept: 
```
export QCSS_ADMIN_TOKEN=change-me
uv run qcss serve --profile qblox_cluster_5q --device transmon_5q --listen 127.0.0.1:50051 --state-dir state --admin-listen 127.0.0.1:50052 --admin-token "$QCSS_ADMIN_TOKEN"
```

## Run the technician (another terminal)
```
export QIBOLAB_PLATFORMS=$PWD/platforms QCSS_QBLOX_5Q_ADDRESS=127.0.0.1:50051
uv run qcss technician run --platforms-dir platforms --platform qcss_qblox_5q --reports reports \
     --requests-dir requests --env QCSS_QBLOX_5Q_ADDRESS=127.0.0.1:50051
```
All four of `--platforms-dir`, `--platform`, `--reports`, `--requests-dir` are required. On first boot every runcard is due; afterwards it follows a schedule:
| Flag | Default | Meaning |
|---|---|---|
| `--quick-every` | 14400 s | quick checks |
| `--full-every` | 86400 s | full bring-up |
| `--cz-every` | 604800 s | CZ calibration |
| `--poll` | 30 s | idle poll period |
| `--env NAME=VALUE` | none | environment for Qibocal (the instrument address) |

Requests are served first, then whatever is due.

## Ask for a calibration now
From any terminal that shares the `requests` folder:
```
uv run qcss technician request --requests-dir requests --scope quick
```
```
{"accepted": true, "expected_complete_at": 1793823903.2147903, "reason": null}
```
It drops one JSON file into the spool (named like `1793823003.214790-99448839.json`). Scopes: `quick`, `device` (default), `cz`. A bad scope is answered, not crashed: `{"accepted": false, ..., "reason": "unknown calibration scope ['bad']"}`.

## Look at the result
```
uv run qcss remote calibration -t 127.0.0.1:50051 -q 0
```
prints the current snapshot and its epoch as JSON (for example `driveFrequencyHz`, `readoutFrequencyHz`, `readoutDelayTicks` per qubit). `qcss remote run` prints `(calibration epoch N)` for each job.

Sources: `src/qcss/cli.py` (`technician`), README (virtual-lab walkthrough).
