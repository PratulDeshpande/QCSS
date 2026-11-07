# QCSS User Manual

## Chapter 6: The admin channel and fault injection

The **admin channel** is a second gRPC service (`qcss.admin.v1.AdminService`, `proto/qcss/admin/v1/admin.proto`) on its **own address and own token**. It exists for the operator or a CI job. It can read the hidden truth and break things, so a lab client can never reach it: the instrument link does not serve any admin RPC.

## 6.1 Enabling it

```
export QCSS_ADMIN_TOKEN=change-me
qcss serve --profile qblox_cluster_5q --device transmon_5q \
   --listen 127.0.0.1:50051 --admin-listen 127.0.0.1:50052 --admin-token "$QCSS_ADMIN_TOKEN"
```
Rules (from `cli.py`): `--admin-token` must differ from `--token`; `--admin-listen` must differ from the instrument address; the admin channel is also subject to the bind guard (a network bind needs TLS and a token). Every `qcss admin` command takes `--target` (default `127.0.0.1:50052`), `--token` (or `QCSS_ADMIN_TOKEN`), `--ca` (a PEM to trust; enables TLS), `--insecure` and `--timeout` (default 30 s). The client refuses to send the token in clear text to a non-loopback address unless `--ca` or `--insecure` is given.

## 6.2 RPCs and CLI commands

| RPC | CLI | What it does |
|---|---|---|
| `KillQubit` / `ReviveQubit` | `qcss admin kill Q` / `revive Q` | A lost qubit decays within about 100 ns (T1 100 ns) and sits 200 MHz below where it was calibrated (`device/scenarios.py`: `DEAD_T1_NS`, `DEAD_SHIFT_GHZ`) |
| `DriftStep` | `qcss admin drift Q [--df-hz F] [--t1-factor X]` | Step the qubit's frequency and/or multiply T1 (`--t1-factor` > 0). Steps accumulate |
| `TlsCollision` | `qcss admin tls Q [--coupling-hz] [--linewidth-hz] [--detuning-hz]` | A two-level defect drifts into resonance. Defaults: 0.5 MHz coupling, 1 MHz linewidth |
| `Burst` | `qcss admin burst Q [--peak-gamma-per-s]` | A cosmic-ray hit centred on the qubit now (default peak 2 per us; the proto field name is `peak_gamma_per_s`, as the CLI help states) |
| `FreezeDrift` | `qcss admin freeze` (and resume) | Stop or resume drift of the whole chip |
| `ClearScenarios` | `qcss admin clear` | Remove every scenario (kills, steps, defects, bursts) |
| `GetMode` / `SetMode` | `qcss admin mode [--time-scale F] [--deterministic/--realistic] [--tier requested\|auto\|t0\|t1a\|t1b\|t2]` | Show or change how the chassis runs. `--tier requested` honours each job's own tier |
| `ReadTruth` | `qcss admin truth` | The chip as it really is now |
| `InspectJob` | `qcss admin inspect JOB_ID` | Tier used, noise fidelity, calibration epoch and warnings of a job |
| `InjectInstrumentFault` | `qcss admin fault hang\|drop\|reboot\|slow-upload [--count N] [--duration S]` | Make the instrument misbehave (below) |
| `ClearInstrumentFaults` | `qcss admin clear-faults` | Remove pending faults |

Real output (verified, chassis on 127.0.0.1:50981/50982, `--time-scale 0`):

```
$ qcss admin truth
lab time 0.000 s
  qubit   f01 (GHz)   T1 (us)   state
    0    5.049914     59.12   ok
    ...
$ qcss admin kill 2
qubit 2 killed
    2    4.749878      0.10   DEAD
$ qcss admin clear
scenarios cleared
$ qcss admin mode
time_scale 0  deterministic no  tier AUTO  seed 8822294976808165586
```

Note the frequency of qubit 2 dropped by 0.2 GHz and T1 to 0.10 us when killed, matching the constants above. `qcss admin mode` also prints the chassis's global seed, which is secret from the lab link.

## 6.3 Instrument faults

`InstrumentFault` (proto): faults of the instrument itself, which the client sees as a misbehaving instrument, not as simulator internals.

| Fault | Effect |
|---|---|
| `HANG` | the next `count` calls stall for `duration_s` before being served (`--duration` required) |
| `DROP` | the next `count` calls fail as if the connection dropped |
| `REBOOT` | the instrument reboots: running jobs fail and every call fails for `duration_s` (`--duration` required); boards forget what they were given (`chassis._on_reboot`, which also reboots the QICK board) |
| `SLOW_UPLOAD` | the next `count` submissions take `duration_s` longer to upload (`--duration` required) |

`--count` defaults to 1. A job killed by a fault ends `FAILED` and the client sees only "execution failed: instrument fault"; the admin side sees the reason through `inspect`.

Unverified in this session: the fault commands were not run (only `--help` read), and neither were `tls`, `burst`, `drift` or `inspect`.

## 6.4 What the lab never sees

The README lists what the lab link hides: results use fresh entropy, the tier is the operator's and is not reported in `JobStatus`, there is no gRPC reflection (unless `--debug-reflection`), failures read like an instrument's, and `GetDeviceProperties` (true T1 and f01) is not served. The admin channel is the only door to these. The QCSS Explorer's Admin console (chapter 7) is an admin client and logs every action.

## 6.5 A typical session

1. Run a Ramsey or a calibration. 2. `qcss admin drift 0 --df-hz 3e5` moves the true frequency by 300 kHz while the calibration is unchanged. 3. Repeat the Ramsey: the fringe frequency shows a detuning the lab did not know about. 4. `qcss admin clear` removes scenarios. This is the dashboard's "How does a drifting chip spoil calibration?" tour.

---
Sources: `proto/qcss/admin/v1/admin.proto`, `src/qcss/cli.py` (admin commands, serve checks), `src/qcss/adapters/admin_server.py`, `src/qcss/adapters/instrument_faults.py`, `src/qcss/device/scenarios.py`, `src/qcss/chassis.py`, `README.md`, `SECURITY.md`, `integrations/qcss_dashboard/web/src/views/Learn.tsx`. Run: `qcss admin --help`, `qcss admin {fault,mode,drift,tls,burst} --help`, `qcss admin truth|kill|clear|mode`.
