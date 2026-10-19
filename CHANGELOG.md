# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project aims to follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html) once it leaves alpha.

## [Unreleased]

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
