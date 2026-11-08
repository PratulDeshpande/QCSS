# Developer guide

**Author & Lead Maintainer:** [Pratul Deshpande](https://github.com/PratulDeshpande) (see [About the Author](about.md))

Setup, ground rules, style and PR checks are in `CONTRIBUTING.md`; this page does not repeat them. It covers the project-specific mechanics.

## Environments
Python 3.12 or 3.13 (`requires-python >=3.12,<3.14`). Extras: `qibolab`, `qibocal`, `qick` (Pyro4, psutil), `adapters`. Groups: `lab` (qcss-qibolab), `dev`. The `qick==0.2.370` client and the qibosoq git pin are manual installs (commands in CONTRIBUTING.md). Without the lab stack, `virtual_lab`, technician and platform tests skip; without Pyro4 and `qick`, the QICK face tests skip.

## Add a hardware profile
1. Copy a YAML in `src/qcss/config/profiles/` (existing: `qblox_cluster_5q`, `qick_zcu216_4q`, `qick_zcu216_5q`, `test_ideal_1q`, `zi_shfqc_5q`). Schema: `src/qcss/config/profile.py` (`HardwareProfile`: `profile_name`, `vendor`, `clock`, `ports`, `generators`, `acquisition`, `feedback`; frozen, `extra="forbid"`).
2. Every value block carries `provenance` (`source_url`, `firmware_version`, `verified`, `note`). Unsourced numbers must be `verified: false`. No vendor constants in Python.
3. `tick_hz` must make every clock a whole number of ticks (ticks per sample = tick_hz / sample_rate_hz is an integer).
4. Check: `qcss profile list`, `qcss profile show NAME` (lists unverified blocks), `qcss validate job.json -p NAME -d DEVICE`.
5. The Explorer's field descriptions are in `integrations/qcss_dashboard/src/qcss_dashboard/explanations/a_profile.yaml`; add entries for new fields.

## Add a device
YAML in `src/qcss/config/devices/` (schema `device.py`: `DeviceSpec`, `QubitSpec`, `CouplerSpec`, `ResonatorSpec`, `DynamicsSpec`, `MixerImpairmentSpec`, `FluxLineSpec`, `FaultSpec`). The `faults:` block is the hidden truth. Descriptions: `explanations/b_device.yaml`.

## Add a platform (lab path)
A Qibolab platform folder in `platforms/NAME/` (`platform.py` with `create()`, `parameters.json`; `calibration.json` is written later by the technician). Model on `platforms/qcss_qblox_5q/platform.py` (uses `QcssController(address=..., channels=...)`, address from an env var). Starting parameters: `python scripts/make_platform_parameters.py platforms/NAME --profile PROFILE ...` (see its docstring). QCSS never writes calibration.

## Add a face
A face is an adapter on the chassis: it translates an outside protocol into `qcss.v1.Job`s run by the same `JobManager`.
- Existing faces: gRPC (`src/qcss/adapters/grpc_server.py`), Qibosoq (`src/qcss/boards/qibosoq.py`), native QICK (`src/qcss/boards/qick/`).
- Wire it in `src/qcss/chassis.py` (`ChassisConfig` + `Chassis.start/stop`) and add flags in `src/qcss/cli.py` `serve_cmd`. Validate flags before importing optional dependencies (CHANGELOG fix). Apply the bind rule: non-loopback needs `--insecure` for a face without TLS/token.
- Do not leak the simulation: no tier, fidelity, seed, true parameters or simulator class names on a face. Error text and tracebacks should be the instrument's (see `board_traceback` in `pyro_host.py`). `tests/integration/test_indistinguishability.py` enforces.
- Untrusted decoding: JSON or allowlisted pickle only.
- For a QICK-like face with a client library, freeze the remote surface (`python scripts/qick_surface.py [--check]`).
- Tests: `tests/integration/` (see `test_qick_*.py`, board tests), with the face skipped if its optional dependency is absent.

## Tests: layout and markers
Directories: `tests/unit`, `tests/oracles`, `tests/cross_tier`, `tests/integration`, `tests/virtual_lab`, plus `integrations/qcss_qibolab/tests`, `integrations/qcss_dashboard/tests`, `integrations/quark_qcss/tests` (deprecated). `testpaths` and `pythonpath` are set in `pyproject.toml`; `--strict-markers` is on.

Markers (declared): `slow` (long physics oracles, nightly), `stochastic` (statistical assertions), `linux_only`, `virtual_lab` (end to end through Qibolab against a chassis). Frontend: vitest and Playwright under `integrations/qcss_dashboard/web` (`npx tsc -b`, `npx vitest run`, `npx vite build`).

Rules: physics tests need analytic oracles; no fixed ports (port 0 / `_free_port()`); pin the chip with `TEST_CHIP_SEED` where physics is asserted. Laptop limit in this workspace: `pytest -n 2` at most, no concurrent stress loops.

## Protobuf regeneration
Edit `proto/qcss/v1/*.proto` or `proto/qcss/admin/v1/admin.proto`, then `python scripts/gen_proto.py` (runs `grpc_tools.protoc`, dev dependency `grpcio-tools>=1.71.2,<1.72`; keep in step with the protobuf runtime pin `protobuf>=5.29,<6`). It writes `*_pb2.py`, `*_pb2.pyi` and, for files with a service (`control_service.proto`, `admin.proto`), `*_pb2_grpc.py` under `src/qcss/v1` and `src/qcss/admin/v1`; stray `_grpc.py` for message-only files are deleted. Commit generated code with the `.proto` change. CI job `proto` regenerates and runs `git diff --exit-code -- src/qcss/v1`; `src/qcss/admin/v1` is not diffed in CI (CONTRIBUTING.md). Keep `buf lint` clean and the wire format unbroken; every enum keeps `*_UNSPECIFIED = 0`.

## CI jobs (`.github/workflows/ci.yml`; push to main, pull requests)

| Job | Runs on | What |
|---|---|---|
| `lint` | ubuntu, py3.13 | `ruff check src tests scripts integrations` |
| `typecheck` | ubuntu, py3.13 | installs `.[qibocal,qick]`, qcss-qibolab, `qick==0.2.370`; `pyright` |
| `proto` | ubuntu, py3.13 | `python scripts/gen_proto.py`, fail on diff in `src/qcss/v1` |
| `test` | ubuntu + windows x py3.12 + py3.13, 30 min | `.[qick]`, `qick==0.2.370`; `pytest -o faulthandler_timeout=600` |
| `virtual-lab` | ubuntu, py3.13, 45 min | lab stack + qibosoq git pin `2c376278785e6ae8aae1f13d1b0b467e067aaf7d`; `pytest -n auto -rs` |
| `dashboard-web` | ubuntu, node 22 | in `integrations/qcss_dashboard/web`: `npm ci`, `npx tsc -b`, `npx vitest run`, `npx vite build` |

Dependabot config: `.github/dependabot.yml` (watches the Explorer's npm packages per CHANGELOG).

## Local checks before a PR
`python -m pytest -n 2`, `ruff check .`, `pyright` (in the lab venv), `python scripts/gen_proto.py` if a proto changed. Then update `CHANGELOG.md` `[Unreleased]`.

## Maintainership & Governance
QCSS is designed and maintained by **Pratul Deshpande**. Contributions, RFCs, bug reports, and profile additions are welcome via pull requests and issues on [GitHub](https://github.com/PratulDeshpande/QCSS).

Sources: CONTRIBUTING.md, pyproject.toml, .github/workflows/ci.yml, scripts/gen_proto.py, scripts/qick_surface.py, scripts/make_platform_parameters.py, src/qcss/config/{profile,device}.py, platforms/qcss_qblox_5q/platform.py, src/qcss/boards/qick/pyro_host.py, CHANGELOG.md.
