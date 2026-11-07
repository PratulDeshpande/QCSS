# Quick-start: use the QICK face from your laptop

**Audience:** you have never used QICK. You have a laptop (the *host*) and want to run unmodified QICK code against QCSS as if it were a real RFSoC board.
**Time:** about 10 minutes. **Verified:** run on loopback (server and client on one machine) on 2026-11-05 with `qick==0.2.370`. Not yet tried between two machines, see "Two machines" below.

## What is QICK, in five lines
QICK (Quantum Instrumentation Control Kit) is open-source firmware plus a Python package for AMD RFSoC boards (ZCU216, ZCU111, RFSoC4x2). It generates and reads microwave pulses to control qubits. Your Python talks to a `QickSoc` object that lives on the board. Normally the board runs a Pyro4 server and your PC connects with `qick.pyro.make_proxy(...)`. QCSS plays the board: it serves the same Pyro4 object, backed by a simulated qubit chip. See the official guide for the real hardware: https://docs.qick.dev/latest/quick_start.html

## Prerequisites
- Python 3.12 or 3.13 and `uv` (https://docs.astral.sh/uv/).
- The QCSS repo checked out, then, from its folder: `uv sync --extra qick`
- The QICK client, pinned: `uv pip install qick==0.2.370` (`uv sync` removes manual installs, so run this after any `uv sync`).

## Step 1: start the simulated board (terminal 1)
```
uv run qcss serve --profile qick_zcu216_5q --device transmon_5q \
  --qick-ns 127.0.0.1:8888 --qick-start-ns --qick-loopback 0:0
```
- `--qick-ns` is where the Pyro4 nameserver lives, and `--qick-start-ns` starts it inside this process.
- `--qick-loopback 0:0` wires a test cable from generator 0 to readout 0, as QICK's first tutorials assume.
- Add `--qick-firmware zcu216_v1_5q` for the older tProc v1 firmware (default is `zcu216_v2_5q`).

You should see:
```
Starting QCSS ControlService on 127.0.0.1:50051 (plaintext, no token) with profile 'qick_zcu216_5q'...
Pyro.NameServer PYRO:Pyro.NameServer@127.0.0.1:8888
myqick PYRO:obj_...@127.0.0.1:<port>
```

## Step 2: connect from Python (terminal 2)
```python
from qick.pyro import make_proxy
soc, soccfg = make_proxy(ns_host="127.0.0.1", ns_port=8888, proxy_name="myqick")
print(soccfg)
```
You should see `QICK running on ZCU216, software version 0.2.370` and `11 signal generator channels`. From here, write QICK programs as in the official tutorials (`AveragerProgramV2` for tProc v2).

## Two machines
Run step 1 on the server machine with `--qick-listen <server-ip> --insecure` (the QICK face has no TLS or token, so a non-loopback bind needs `--insecure`; use a trusted network only). On the host laptop use `ns_host="<server-ip>"`. Open the nameserver port and the daughter Pyro4 port in the server firewall. *Unverified between two real machines.*

## If it does not work
| Symptom | Likely cause |
|---|---|
| `ModuleNotFoundError: Pyro4` | missed `--extra qick` |
| `ModuleNotFoundError: qick` or version error | run `uv pip install qick==0.2.370` again after `uv sync` |
| Server refuses to start with a non-loopback `--qick-listen` | add `--insecure` |
| Client cannot find `myqick` | wrong `--qick-name` / `proxy_name`, or wrong nameserver port |

Sources: `src/qcss/cli.py` (`serve` options), `src/qcss/boards/qick/pyro_host.py`, `tests/integration/test_qick_pyro_board.py`.
