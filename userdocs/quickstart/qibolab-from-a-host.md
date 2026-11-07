# Quick-start: use the Qibolab face from your laptop

**Audience:** you have never used Qibolab. You want to load a Qibolab platform on your laptop that drives QCSS like a real instrument.
**Time:** about 10 minutes. **Verified:** loopback, 2026-11-05, `qibolab==0.2.17`. TLS between two machines is described but not re-tested here.

## What is Qibolab, in five lines
Qibolab is the Qibo package for quantum hardware control. A *platform* describes a lab setup (qubits, channels, instruments). `create_platform("name")` loads it, `platform.connect()` opens the instruments, and `platform.execute(...)` runs pulse sequences. QCSS provides the instrument side: a driver (`QcssController`) talks gRPC to `qcss serve`. Official docs: https://qibo.science/qibolab/stable/

## Prerequisites
- Python 3.12 or 3.13 and `uv`.
- From the QCSS repo: `uv sync --group lab --extra qibolab` (installs `qibolab==0.2.17` and the `qcss-qibolab` driver).

## Step 1: start the simulated instrument (terminal 1)
```
uv run qcss serve --profile qblox_cluster_5q --device transmon_5q --port 50051
```
Expect `QCSS ControlService listening on 127.0.0.1:50051`. Check it from another terminal: `uv run qcss remote ping -t 127.0.0.1:50051` prints `SERVING`.

## Step 2: load the platform (terminal 2)
PowerShell:
```
$env:QIBOLAB_PLATFORMS = "<repo>\platforms"
$env:QCSS_QBLOX_5Q_ADDRESS = "127.0.0.1:50051"
```
bash: `export QIBOLAB_PLATFORMS=<repo>/platforms QCSS_QBLOX_5Q_ADDRESS=127.0.0.1:50051`
```python
from qibolab import create_platform
platform = create_platform("qcss_qblox_5q")
platform.connect()
print(sorted(platform.qubits))   # [0, 1, 2, 3, 4]
platform.disconnect()
```
Verified output: `connected` and qubits `[0, 1, 2, 3, 4]`.

## Step 3 (optional): a raw job without Qibolab
`uv run qcss remote run examples/jobs/pi_q0.json -t 127.0.0.1:50051` printed `q0: {'0': 32, '1': 968}` (a pi pulse on qubit 0, 1000 shots, seed 1).

## Another machine (TLS + token)
1. On the server machine: `uv run python scripts/make_dev_cert.py <server-ip>`, then
   `uv run qcss serve --host 0.0.0.0 --tls-cert server.pem --tls-key server.key --token $QCSS_TOKEN ...`
2. Copy `server.pem` to the laptop. The shipped `platform.py` sets no `ca_file`, so copy the platform folder and set `ca_file` in your copy; see `docs/remote-testing.md` section 8 (that file is local-only).
3. Set `QCSS_QBLOX_5Q_ADDRESS=<server-ip>:50051` and the token env var the driver reads.
The client refuses to send a token in cleartext to a non-local address, by design.

## Calibration
Qibocal calibration is run by the *technician* on the server side: `uv run qcss technician run ...` (see `qcss technician --help`).

## If it does not work
| Symptom | Likely cause |
|---|---|
| Platform not found | `QIBOLAB_PLATFORMS` not pointing at the repo's `platforms/` |
| Connection refused | server not running, or wrong `QCSS_QBLOX_5Q_ADDRESS` |
| Token refused to send | missing CA (`ca_file`/`--ca`) for a non-local address |
| Server refuses `--host 0.0.0.0` | needs `--tls-cert/--tls-key` and `--token`, or `--insecure` |

Sources: `integrations/qcss_qibolab/README.md`, `platforms/qcss_qblox_5q/`, `src/qcss/adapters/grpc_server.py` (`check_bind_is_safe`).
