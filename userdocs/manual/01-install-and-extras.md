# QCSS User Manual

## Chapter 1: Installation and optional extras

**Goal:** a working `qcss` command, and the right optional pieces for the face you want to use.

## 1.1 Prerequisites

- **Python 3.12 or 3.13.** `pyproject.toml` pins `requires-python >=3.12,<3.14`.
- **uv**, the Python package manager used by this repo (https://docs.astral.sh/uv/). Plain `pip` works if it is version 25.1 or newer, because the repo uses *dependency groups*.
- **Node 20.19 or 22**, only if you build the Explorer dashboard frontend (chapter 7).
- No compiler needed: all core dependencies (numpy 2.x, scipy, qutip 5, stim, pymatching, grpcio, protobuf 5, pydantic 2, pyyaml, click) install from wheels (listed in `pyproject.toml`).

## 1.2 Core install

```bash
git clone https://github.com/PratulDeshpande/qcss.git
cd qcss
uv sync --group dev
```

`--group dev` adds the test, lint and protobuf tooling, plus `fastapi`, `uvicorn` and `httpx` that the Explorer bridge needs. Check:

```bash
uv run qcss --version      # prints: qcss, version 0.1.0   (verified)
uv run qcss --help
```

The `--help` output lists the top-level commands (verified): `admin`, `device`, `profile`, `remote`, `run`, `serve`, `technician`, `validate`.

## 1.3 Extras and dependency groups

*Extras* are optional features (`--extra NAME`). *Groups* are developer or environment sets (`--group NAME`). The table is from `pyproject.toml` and the README's auto-generated table.

| Name | Kind | Installs | You need it for |
|---|---|---|---|
| `qibolab` | extra | `qibolab==0.2.17`, `qibo` | Loading the QCSS Qibolab platforms |
| `qibocal` | extra | `qibocal==0.2.6`, `qibolab==0.2.17`, `qibo` | The technician (real Qibocal calibration) |
| `qick` | extra | `Pyro4`, `psutil` | The native QICK face (`--qick-ns`) |
| `adapters` | extra | `qcodes`, `pyvisa`, `pyvisa-sim` | The *planned* QCoDeS mirror (not built, chapter 9) |
| `lab` | group | `qcss-qibolab` (editable, from `integrations/qcss_qibolab`) | The Qibolab driver `QcssController` |
| `dev` | group | grpcio-tools, pytest, pytest-xdist, hypothesis, anyio, cryptography, ruff, pyright, fastapi, uvicorn, httpx | Developing, tests, the Explorer bridge |

Qibolab is pinned exactly (`0.2.17`) because its `Controller` base class lives in a private module (`qibolab._core`); a different version may break the driver.

### Recipes

| You want | Command |
|---|---|
| Just the simulator and CLI (`qcss run`, `qcss serve`, profiles) | `uv sync --group dev` |
| The full virtual lab (Qibolab, Qibocal, driver) | `uv sync --extra qibocal --group lab --group dev` |
| Only the Qibolab platform, no Qibocal | `uv sync --extra qibolab --group lab` |
| The native QICK face | `uv sync --extra qick` (then see 1.4) |
| pip instead of uv | `python -m pip install -e ".[qibocal]" -e integrations/qcss_qibolab --group dev` |

## 1.4 Manual installs (not in the lock file)

Two clients are deliberately **not** in the lock file, because their dependencies cannot be resolved by `uv`'s universal lock. After every `uv sync`, reinstall them, because `uv sync` removes manually installed packages.

**The QICK client** (`pyproject.toml` comment: pinned to the version qibosoq 0.1.5 pins and the firmware description is written for):

```bash
uv pip install qick==0.2.370
```

This is what a *user* of the QICK face runs. The QCSS server never imports `qick` (`src/qcss/boards/qick/firmware.py`: "This module never imports qick: the face is a board, not a client"). QICK documentation: https://docs.qick.dev/.

**The Qibosoq client** (only if you use the RFSoC platform `qcss_rfsoc_5q`). The README states it has no numpy-2 release on PyPI, so install from a pinned commit:

```bash
uv pip install "qibosoq @ git+https://github.com/qiboteam/qibosoq@2c376278785e6ae8aae1f13d1b0b467e067aaf7d"
```

Unverified: this manual did not re-run these two installs.

## 1.5 The Explorer dashboard bridge

The dashboard has its own package (`integrations/qcss_dashboard`, project `qcss-dashboard`, script `qcss-dashboard = qcss_dashboard.cli:main`). The README runs it without installing, by path:

```bash
PYTHONPATH=integrations/qcss_dashboard/src uv run python -m qcss_dashboard.cli
```

Build the frontend once: `cd integrations/qcss_dashboard/web && npm ci && npm run build`. Chapter 7 has details. (Verified: `python -m qcss_dashboard.cli --help` runs from the repo with that `PYTHONPATH`.)

## 1.6 Development commands

From the README "Development" section:

```bash
python -m pytest -n 2        # the full suite; virtual-lab tests skip without the lab stack
ruff check .                 # lint
pyright                      # type check
python scripts/gen_proto.py  # regenerate protobuf code after editing a .proto file
```

**Laptop warning (from this project's own notes):** run pytest with at most `-n 2`, and do not run several heavy test loops at once. A heavier load previously shut a laptop down.

## 1.7 Platforms and environment variables

The Qibolab platforms ship in `platforms/` (`qcss_qblox_5q`, `qcss_rfsoc_5q`). Qibolab finds them through `QIBOLAB_PLATFORMS`.

| Variable | Read by | Meaning |
|---|---|---|
| `QCSS_TOKEN` | `qcss serve`, `qcss remote`, `QcssController` | Bearer token of the instrument link |
| `QCSS_ADMIN_TOKEN` | `qcss serve`, `qcss admin` | Token of the admin channel |
| `QIBOLAB_PLATFORMS` | Qibolab, Qibocal | Folder containing the platform folders |
| `QCSS_QBLOX_5Q_ADDRESS` | `platforms/qcss_qblox_5q/platform.py` | `host:port` of the instrument link |
| `QCSS_RFSOC_5Q_ADDRESS` | `platforms/qcss_rfsoc_5q/platform.py` | `host:port` of the Qibosoq board face |
| `QCSS_DASHBOARD_TOKEN` | the Explorer bridge | Login token for a network-bound dashboard |

## 1.8 Troubleshooting installs

| Symptom | Likely cause |
|---|---|
| `ModuleNotFoundError: Pyro4` | `--extra qick` missed |
| `ModuleNotFoundError: qick` or a version error in a client | run `uv pip install qick==0.2.370` again after `uv sync` |
| `qibolab` import errors about `_core` | wrong Qibolab version; use exactly 0.2.17 |
| `qcss` not found | use `uv run qcss ...` or activate the virtual environment |

---
Sources: `pyproject.toml`, `README.md` (Install, Environment variables, Development), `integrations/qcss_dashboard/README.md`, `integrations/qcss_dashboard/pyproject.toml`, `src/qcss/boards/qick/firmware.py`, `userdocs/quickstart/qick-from-a-host.md`, memory note on laptop test load. Run: `uv run qcss --version`, `uv run qcss --help`, `python -m qcss_dashboard.cli --help`.
