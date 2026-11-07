# Quick-start: use the Qibosoq (RFSoC) face from your laptop

**Audience:** you have never used Qibosoq. You want Qibolab's stock RFSoC driver to talk to QCSS as if it were a real RFSoC board.
**Time:** about 10 minutes. **Verified:** loopback, 2026-11-05, `qibolab==0.2.17`, `qibosoq==0.1.5`. Not tried between two machines.

## What is Qibosoq, in five lines
Qibosoq is the Qibo team's server for RFSoC boards (it runs on the board). Qibolab's `RFSoC` driver sends it pulse sequences as JSON over a plain TCP socket (a 4-byte length, then JSON) and gets I/Q results back. QCSS plays the board: `--board-listen` starts a Qibosoq-compatible TCP server backed by the simulated chip. Your platform file differs from a lab's only by the board address. Docs: https://qibo.science/qibolab/stable/

## Prerequisites
- Python 3.12 or 3.13 and `uv`.
- From the QCSS repo: `uv sync --group lab --extra qibolab`.
- The qibosoq client has no numpy-2 release on PyPI, so install it from the commit the README pins (re-run after any `uv sync`, which removes manual installs):
  `uv pip install "qibosoq @ git+https://github.com/qiboteam/qibosoq@2c376278785e6ae8aae1f13d1b0b467e067aaf7d"`
  (*Unverified as a fresh install; the environment used for this guide already had `qibosoq 0.1.5`.*)

## Step 1: start the simulated board (terminal 1)
The platform's wiring (DAC 0-4 drive, DAC 10 readout, DAC 5-9 flux) matches the ZCU216 profile, so use `qick_zcu216_5q`. With the `qblox_cluster_5q` profile the server now refuses to start (`--board-listen needs an RFSoC profile whose ports are dacN`); older builds failed late, on the first job, with `dac 0 is not connected`.
```
uv run qcss serve --profile qick_zcu216_5q --device transmon_5q --port 50971 --board-listen 127.0.0.1:6010 --time-scale 0
```
`--time-scale 0` freezes the chip and runs jobs unpaced (handy for a first try). The usual port for the board is 6000; the unusual ports here avoid clashes.

You should see:
```
Starting QCSS ControlService on 127.0.0.1:50971 (plaintext, no token) with profile 'qick_zcu216_5q'...
QCSS ControlService listening on 127.0.0.1:50971. Press Ctrl+C to terminate.
Qibosoq board face on 127.0.0.1:6010.
```

## Step 2: load the platform (terminal 2)
PowerShell:
```
$env:QIBOLAB_PLATFORMS = "<repo>\platforms"
$env:QCSS_RFSOC_5Q_ADDRESS = "127.0.0.1:6010"
```
bash: `export QIBOLAB_PLATFORMS=<repo>/platforms QCSS_RFSOC_5Q_ADDRESS=127.0.0.1:6010`
```python
from qibolab import AcquisitionType, AveragingMode, create_platform
platform = create_platform("qcss_rfsoc_5q")
platform.connect()
print("qubits:", sorted(platform.qubits))
natives = platform.natives.single_qubit[0]
for name, seq in (("ground", natives.MZ()), ("after RX", natives.RX() | natives.MZ())):
    acq = next(r for _, r in seq.acquisitions)
    p = platform.execute([seq], nshots=400, acquisition_type=AcquisitionType.DISCRIMINATION,
                         averaging_mode=AveragingMode.CYCLIC)[acq.id]
    print(f"P(1) {name}: {float(p):.2f}")
platform.disconnect()
```
You should see (verified; exact P(1) varies by run):
```
qubits: [0, 1, 2, 3, 4]
P(1) ground: 0.03
P(1) after RX: 0.95
```

## What the board face refuses
It is honest about what a real simulated board cannot do. Raw (decimated) acquisition gives:
`QibosoqError NotImplementedError: decimated (raw) acquisition is not supported by this board` (verified with `AcquisitionType.RAW`). A DC bias on a DAC, or a sweep of the DC bias, is refused too (read from `src/qcss/boards/qibosoq.py`; not run).

## Two machines
The Qibosoq protocol has no TLS and no token, so a non-loopback `--board-listen` is refused unless you add `--insecure`:
```
Error: refusing to bind the board face to 0.0.0.0:6011: the qibosoq protocol has no TLS and no token; pass --insecure on a network you trust
```
(verified message). Use a trusted network only; set `QCSS_RFSOC_5Q_ADDRESS=<server-ip>:6000` on the laptop. *Unverified between two real machines.*

## If it does not work
| Symptom | Likely cause |
|---|---|
| `--board-listen needs an RFSoC profile` (or, on older builds, `dac 0 is not connected`) | server started with the wrong profile; use `qick_zcu216_5q` |
| `--board-listen 6011: the board face is TCP host:port` | give `host:port`, not a bare port |
| `refusing to bind the board face to ...` | add `--insecure` (trusted network) or use loopback |
| Platform not found | `QIBOLAB_PLATFORMS` not pointing at the repo's `platforms/` |
| Connection refused / hangs on `connect()` | server not running, or wrong `QCSS_RFSOC_5Q_ADDRESS` (default `192.168.0.81:6000`) |
| `ModuleNotFoundError: qibosoq` | install the pinned commit again after `uv sync` |
| decimated (raw) acquisition not supported | by design; use INTEGRATION or DISCRIMINATION |

See also `../troubleshooting.md`.

Sources: `src/qcss/cli.py` (`serve`), `src/qcss/boards/qibosoq.py`, `platforms/qcss_rfsoc_5q/platform.py`, `tests/integration/test_rfsoc_platform.py`, README (pinned commit).
