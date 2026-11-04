# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it leaves alpha.

## [Unreleased]

QCSS becomes a virtual lab: Quark reaches it exactly as it reaches a lab, through Qibolab, and
cannot tell it is a simulator.

### Added

* QCSS Explorer (`integrations/qcss_dashboard`): an operator dashboard that explains, visualizes and configures
  every layer (profile, device, calibration, job, chassis), with an embedded virtual lab, a sandbox that runs jobs
  through QCSS's own pipeline, admin and lab-bench views, and a registry that documents every config field.
  See `integrations/qcss_dashboard/README.md`.
* `qcss-qibolab`: a Qibolab `Controller` for QCSS instruments, and the platform `qcss_qblox_5q`.
* A Qibosoq-compatible board face (`qcss serve --board-listen`) and the platform `qcss_rfsoc_5q`,
  which uses Qibolab's own unmodified RFSoC driver. Only the board address differs from a lab's platform.
* The virtual technician, `qcss technician run|request`. It runs the real Qibocal on a schedule and on
  request, and installs each calibration atomically. The runcards are `quick`, `full` and `cz`.
* The admin channel, `qcss admin ...`, on its own address and token. It covers:
  * scenarios: kill or revive a qubit, drift step, TLS collision, burst, freeze;
  * modes: time scale, deterministic, physics tier;
  * the chip's true state, and job inspection;
  * instrument faults: hang, drop, reboot, slow upload.
* The chip's state persists across chassis restarts (`--state-dir`, plain JSON), and downtime
  counts as lab time.
* Wall-clock pacing (`--time-scale`): the chip drifts while idle, and jobs take instrument time.
* Client-resolved sweep points (`Job.program_points`). `ChannelInfo.lo_frequency_hz`. Readout-frame
  frequencies set each point's probe frequency.
* `qick_zcu216_5q` profile.
* Acceptance harness standing in for Quark's Qibolab adapter, and an indistinguishability scan.
* Acceptance checks through Qibolab, ported from the `quark_qcss` conformance run: x reads 1, idle
  reads 0, sx·sx reads 1 and sx·rz(π)·sx reads 0, simultaneous x on two qubits, non-native gates
  refused, a stable calibration set, a killed qubit collapsing its outcomes, and a reboot failing one
  call before the next job runs.

### Changed

* **Breaking:** `qcss serve` now behaves like a lab chassis by default:
  * entropy seeds (`--seed` is optional), and `random_seed` is honoured only with `--deterministic`;
  * the operator picks the tier (`--tier`, default auto);
  * no tier or fidelity in `JobStatus`, and no reflection unless `--debug-reflection`;
  * a generic message for internal failures (the details are on the admin channel).
* `qblox_cluster_5q` is wired as a lab wires a cluster: one drive and flux line and sequencer per
  qubit, and five readout sequencers on one feedline.
* AUTO routing prefers exact T1B up to 26 qubits. T1A (Pauli-twirled) is used only for scale, or
  on request.
* `transmon_5q` sits at a realistic T_eff of 60 mK (1.7 % residual excitation).

### Fixed

* The board face could be made to buffer an unbounded request or to build an unbounded sweep, and
  a client that stalled mid-request held its connection forever. It now refuses requests over 16 MiB
  unread, drops a client that takes more than 30 s to send, and refuses sweeps beyond 2^18
  points x elements, answering with the board's own resource error.
* Two clients could race a calibration upload against a job. The Qibolab driver now pins each job
  to the settings its own `play` uploaded (`expected_calibration_epoch`).
* A chassis now runs one job at a time, as one chip does.
* The chip state is guarded by a lock: concurrent readers advance it once, and admin scenarios first
  bring the chip to the current lab time, so an injected burst hits now.
* Overlapping pulses are judged only on qubits that are driven or flux-tuned, so parallel circuits on
  five qubits are no longer refused.
* Routing refusals on the lab link name no tier or engine class (`INSTRUMENT_RESOURCES`).
* The technician's shift no longer blocks on a malformed or failing request (it moves to `failed/`),
  runs every requested scope, and backs off a failing runcard.
* An admin channel beside a tokened lab link must have its own, different token.
* The acceptance harness evaluates OpenQASM angle expressions (`pi`, `tau`, `-pi/2`, ...).
* Gate tiers lifted overlapping pulses separately, so a flux shift under a drive was ignored. Such
  jobs now run at pulse level, or are refused.
* Gate tiers dropped leakage, so CZ chevrons were invisible. Leaky jobs now run at T2.
* T1B ignored temperature. It now uses generalized amplitude damping and a thermal start.
* A stale calibration epoch at execution start now ends the job `REJECTED` (`CALIBRATION_EPOCH`).
* Every chunk of a job now uses the calibration uploaded at its start.
* The lab clock now advances between jobs.
* The planning dry run no longer simulates readout.
* Repeated flux pulses are lifted once per chunk, with an exact frame shift.
* The technician installs a calibration set whole: if a file cannot be replaced (on Windows, a reader
  holding it open is enough), the files already replaced are rolled back. It also refuses fits that no
  instrument could play (amplitude beyond full scale, non-positive duration or frequency).
* A dropped board connection is now a TCP reset (`ConnectionResetError` in the qibosoq client), as a
  rebooting board gives, not an empty reply.
* `qcss serve --board-listen` refuses anything but TCP `host:port` before starting, since the qibosoq
  client connects over TCP only.
* A job whose simulation runs slower than real time no longer winds the lab clock back: the chip ages
  by the wall time that passed.
* T1B thermalises a warm qubit exactly once it has idled 20 T1, so a killed qubit (very short T1) no
  longer costs a step per T1/10 of idle.
* CI type-checks against the lab stack (Qibolab, Qibocal) and runs the virtual-lab tests in their own
  job; `cryptography` is a dev dependency, so the TLS tests run and pyright is clean.

### Deprecated

* `integrations/quark_qcss`, the Quark-side gRPC driver. Quark reaches QCSS through Qibolab now. It
  will be removed in the next release.

## [0.1.0] - 2026-10-19

First public release.

### Added

* `qcss.v1` gRPC contract (`SubmitJob`, `GetJobStatus`, `CancelJob`, `StreamResults`,
  `GetCalibration`, `UpdateCalibration`, `DescribeDevice`) with rich error details, health checking
  and server reflection.
* Compiler and hardware-rule validator driven by sourced vendor profiles (Qblox, Zurich Instruments,
  QICK, and a noise-free test profile); every violation is reported with its proto field path.
* Integer-tick discrete-event shot executor with feedback latency, time of flight and equal-duration
  branch rules.
* Four physics tiers behind one engine protocol: T0 surrogate, T1a Stim (Pauli-twirled), T1b exact
  amplitude-damping statevector, T2 multi-qutrit Lindblad. Automatic routing that refuses rather than
  downgrades.
* Stateful signal chain (IQ mixer impairments, LO leakage, flux-line response and predistortion) and
  physical dispersive readout with discriminators.
* Slow device dynamics on a virtual lab clock: T1 drift, TLS defects, 1/f flux noise, cosmic-ray bursts.
* Epoch-versioned calibration store with compare-and-swap updates.
* Seeded, worker-count-independent reproducibility (fixed 1024-shot chunks, keyed random streams).
* `qcss` command line: `validate`, `run`, `serve`, `profile`, `device`.
* Test suite of 172 tests: unit, analytic physics oracles, cross-tier agreement and gRPC integration.
* Continuous integration for Linux and Windows on Python 3.12 and 3.13.

### Known limitations

* No T3 (quantum trajectories) engine; T2 is limited to 4 qutrits.
* Vendor adapters (Qibolab, Qblox face, QCoDeS) are not built.
* The gRPC server has no authentication or TLS.

[Unreleased]: https://github.com/PratulDeshpande/qcss/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/PratulDeshpande/qcss/releases/tag/v0.1.0
