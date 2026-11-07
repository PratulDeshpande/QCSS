# QCSS User Manual

## Chapter 5: Runtime, jobs and calibration

This chapter covers `src/qcss/runtime/`: how jobs are queued and run, how the calibration store works, how the chip's state survives restarts, and how the technician keeps the lab calibrated.

## 5.1 Jobs

A **job** is a `qcss.v1.Job` protobuf message (`proto/qcss/v1/job.proto`). Key fields: `job_key`, `waveform_library`, `weight_library`, `main` (a block of instructions such as `play` and `acquire`), `sweeps`, `num_shots`, `repetition_delay_ticks` (optional), `priority`, `requested_tier`, `random_seed`, `expected_calibration_epoch` and `program_points` (sweep points that the Qibolab driver fills in itself). Acquisition modes: raw trace, integrated, discriminated. JSON or YAML in the protobuf JSON mapping, or binary `.pb`.

You can check and run a job without a server:

```
qcss validate job.json -p qblox_cluster_5q -d transmon_5q
   -> Job '...' is VALID against profile 'qblox_cluster_5q' (tier T1B: lifts to gates).   (verified)
qcss run job.json -p qblox_cluster_5q -d transmon_5q
   -> Tier: T1B ... Key 'q0': 200 measurements, state counts: {0: 2, 1: 198}              (verified)
```

(The job is the README's half-amplitude 20-sample square pulse then a measurement.) Against a running chassis: `qcss remote run job.json --target host:port`. Verified on a live chassis: `Submitted <id> (calibration epoch 0)`, `JOB_STATE_COMPLETED ... on tier FIDELITY_TIER_UNSPECIFIED` (the tier is hidden on the lab link), `q0: {'0': 5, '1': 195}`.

### Plan, refusal and states

At `SubmitJob` the planner compiles and validates the job and routes a tier. Refusals come back before a job id exists: `INVALID_ARGUMENT` with field paths for hardware violations (`adapters/errors.py`), and `FAILED_PRECONDITION` (with a `PreconditionFailure` detail) for a job the instrument cannot run or for a stale calibration epoch. After acceptance a job moves through `JobState` (`proto/qcss/v1/result.proto`):

| State | Meaning |
|---|---|
| `QUEUED` | accepted, waiting |
| `VALIDATING` | being checked |
| `RUNNING` | simulating |
| `COMPLETED` | finished, results available |
| `FAILED` | execution failed. The client sees only "execution failed: instrument fault"; the real cause is visible to the admin channel (`qcss admin inspect`) |
| `CANCELLED` | cancelled by `CancelJob` |
| `REJECTED` | the job's pinned calibration epoch went stale while it waited; message begins `CALIBRATION_EPOCH:` |

### One job at a time

The chassis builds its job manager with `max_concurrent_jobs=1` ("one chip, one program", `chassis.py`); others queue. Higher `priority` runs sooner, FIFO among equals (`jobs.py`).

### Streaming and retention

Results stream in fixed **1024-shot chunks** (`CHUNK_SHOTS`). The server keeps results so clients can reconnect and call `StreamResults` again: at most 256 MiB per job (older chunks all readers have passed are dropped; resuming before them returns `OUT_OF_RANGE`) and the 256 most recent finished jobs (older return `NOT_FOUND`). The producer runs at most 64 chunks ahead of the furthest reader.

### Pacing

A job takes instrument time: upload latency plus shots x (sequence + relaxation) lab seconds, converted to wall time by `--time-scale` (default 1). `--time-scale 0` runs unpaced and freezes the chip (used for tests). `qcss admin mode` shows and changes it live.

## 5.2 Calibration and the epoch

**Calibration** here is what the control system programmes into the instrument: per qubit, drive and readout frequency, pi-pulse amplitude and length, DRAG beta, readout delay, readout rotation and threshold, drive and readout mixer correction, and flux predistortion (`proto/qcss/v1/calibration.proto`, `QubitCalibration`). The simulator applies it **on top of** the hidden truth, so a wrong calibration gives wrong physics results.

`CalibrationStore` (`runtime/calibration_store.py`) keeps immutable snapshots, each with a `calibration_epoch` number:

- `GetCalibration` returns the snapshot and its epoch.
- `UpdateCalibration(snapshot, expected_epoch)` is **compare-and-swap**: it succeeds only if `expected_epoch` equals the current epoch; otherwise it raises `CalibrationEpochError` and the RPC returns `FAILED_PRECONDITION` with type `CALIBRATION_EPOCH` ("expected_epoch N is stale (current M)"). On success the listed qubits are replaced wholesale and the epoch increases by one. Writing a qubit replaces its whole record, so send the full record.
- A job may carry `expected_calibration_epoch`. If the calibration changes while it waits, it ends `REJECTED` with `CALIBRATION_EPOCH` rather than running with mixed settings. `QcssController` does exactly this: each `play` uploads the platform's settings, takes the new epoch and pins the job to it.

Observed on a fresh chassis (verified): epoch 0, with default readout frequencies a little below each resonator (for example 7149.2 MHz for a 7.15 GHz resonator) and `readoutDelayTicks 273`; `qcss remote calibration` prints the JSON. The initial qubit drive values are the nominal frequencies, not the (drifted) truth.

The calibration set seen by Quark through Qibolab is the technician's files, `parameters.json` and `calibration.json`; its identity is the sha256 of those two files (README). The chassis never writes those files.

## 5.3 Persistence and restarts

`qcss serve --state-dir DIR` saves the chip's hidden state to `DIR/chip.state` as plain JSON, atomically (temp file, fsync, rename), every 60 s (`save_interval_s`) and at shutdown (`runtime/persistence.py`, `chassis.py`). It holds drift processes, TLS defects, scenarios, the lab clock and random state, plus a digest of the device file. Loading never executes anything; a pickle in its place is refused.

A restart behaves like **rebooting the control electronics**: whatever was uploaded (programmed settings, QICK program memory) is lost, but the chip kept ageing, so **downtime counts as lab time**. Without `--state-dir` the chip is rebuilt from fresh entropy on each start. `qcss admin fault reboot` simulates the same thing without restarting the process (chapter 6).

## 5.4 The technician

The **technician** is the lab's calibration staff: it runs the real **Qibocal** (the Qibo calibration package, `qq run`) against the platform on a schedule and installs the result atomically. Needs `--extra qibocal` (chapter 1).

```
qcss technician run --platforms-dir platforms --platform qcss_qblox_5q \
    --reports reports --requests-dir requests --env QCSS_QBLOX_5Q_ADDRESS=127.0.0.1:50051
```
(options verified with `--help`: `--quick-every` 14400 s, `--full-every` 86400 s, `--cz-every` 604800 s, `--poll` 30 s.) The schedule runs on wall time. On the first boot every runcard is due.

| Runcard (`src/qcss/technician/runcards/`) | Routines | Default period |
|---|---|---|
| `quick.yml` | single-shot classification, Ramsey, T1, readout check | 4 h |
| `full.yml` | resonator and qubit spectroscopy, Rabi, Ramsey, T1, T2, single shot, standard RB | 24 h |
| `cz.yml` | CZ chevron, `correct_virtual_z_phases`, `optimize_two_qubit_gate` | 7 days |

Every result is checked before install: NaN or infinite values, amplitudes beyond full scale and non-positive durations or frequencies are refused. A failing runcard backs off and leaves the platform as it was; `last_ok` times are kept in a state file so a restart does not redo fresh work.

### Requests

Quark's `request_calibration` maps to a **request spool**: JSON files in a folder. Ask for one with:

```
qcss technician request --requests-dir requests --scope device     # scopes: quick, device, cz
```
It prints an acknowledgement (accepted, expected completion time). Unknown or empty scope is not accepted. Requests are served before routine calibrations. Unverified here: a full technician run (it needs Qibocal and hours of simulated work for CZ).

## 5.5 Related commands

| Command | Purpose |
|---|---|
| `qcss remote ping\|describe\|calibration\|properties\|run` | talk to the instrument link |
| `qcss admin mode` | see or set time scale, determinism, tier policy |
| `qcss admin inspect <job>` | see tier, noise fidelity, calibration epoch and warnings for a job |

---
Sources: `src/qcss/runtime/{jobs,calibration_store,persistence,runner}.py`, `src/qcss/chassis.py`, `src/qcss/adapters/{errors,grpc_server}.py`, `src/qcss/technician/schedule.py`, `src/qcss/technician/runcards/`, `proto/qcss/v1/{job,result,calibration,control_service}.proto`, `SECURITY.md`, `README.md`, `integrations/qcss_qibolab/src/qcss_qibolab/controller.py`. Run: `qcss validate`, `qcss run`, `qcss remote run|calibration`, `qcss technician run|request --help`.
