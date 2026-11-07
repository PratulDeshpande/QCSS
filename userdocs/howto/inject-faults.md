# How to: inject faults (qubits and instrument)

**Goal:** make the virtual lab misbehave on purpose. **Verified:** loopback, 2026-11-05. All commands take `-t host:port` (admin channel, default `127.0.0.1:50052`) and read the admin token from `QCSS_ADMIN_TOKEN` or `--token`; add `--ca server.pem` for TLS. Start the server with `--admin-listen` and `--admin-token` (see Tutorial 3).

## Chip faults (change the physics)
| Command | Effect | Output |
|---|---|---|
| `qcss admin kill Q` | qubit lost: T1 about 0.1 us, 200 MHz off | `qubit 0 killed` |
| `qcss admin revive Q` | undo kill | `qubit 0 revived` |
| `qcss admin drift Q --df-hz 2e6 --t1-factor 0.5` | step frequency and/or T1; accumulates | `qubit 0: df 2e+06 Hz, T1 x1` |
| `qcss admin tls Q [--coupling-hz --linewidth-hz --detuning-hz]` | a TLS defect drifts into resonance | *not run* |
| `qcss admin burst Q [--peak-gamma-per-s]` | cosmic-ray hit now | `qubit 1: burst` |
| `qcss admin freeze` / `freeze --off` | stop / resume all drift | `drift frozen` / `drift resumed` |
| `qcss admin clear` | remove kills, drift steps, defects, bursts | `scenarios cleared` |

## Instrument faults (the box misbehaves)
`qcss admin fault KIND [--count N] [--duration S]`, KIND one of `hang`, `drop`, `reboot`, `slow-upload`. `--count` is how many calls are affected (default 1). `--duration` (seconds) is required for `hang`, `reboot` and `slow-upload`:
```
uv run qcss admin fault hang
Error: --duration (seconds, > 0) is required for a hang fault
uv run qcss admin fault drop --count 1
instrument fault: drop x1
uv run qcss admin fault slow-upload --duration 2
instrument fault: slow-upload x1 for 2 s
uv run qcss admin clear-faults
instrument faults cleared
```
After `drop`, the next client call fails: `Error UNAVAILABLE: Connection reset by peer`. `hang` and `reboot` were not run.

## Check it worked
`qcss admin truth` shows each qubit's `state` (`ok` or `DEAD`), f01 and T1. `qcss admin inspect JOB_ID` shows tier, noise fidelity and epoch of a job.

## Notes
- Scenarios are kept across restarts only with `--state-dir` (see `persist-chip-state.md`).
- `qcss admin ...` against an unreachable address prints the gRPC connection error; with the wrong token, `Error UNAUTHENTICATED: missing or invalid bearer token`.
- For a faulty qubit, a client sees only bad results, never the word "killed".

Sources: `src/qcss/cli.py` (`admin_*`).
