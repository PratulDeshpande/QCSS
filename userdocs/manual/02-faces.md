# QCSS User Manual

## Chapter 2: Faces (how clients reach the simulated lab)

A **face** is one way to plug a client into the same simulated chip. All faces share one chassis, one chip and one clock. Which face you choose depends on what software you want to test.

| Face | Wire protocol | Client software | Switch on with |
|---|---|---|---|
| Qibolab / instrument link | gRPC (`qcss.v1.ControlService`) | Qibolab platform using `QcssController` | `qcss serve` (always on) |
| Qibosoq board | TCP, 4-byte length + JSON | Qibolab's own RFSoC driver | `--board-listen host:port` |
| Native QICK board | Pyro4 (pickle) | unmodified `qick` programs | `--qick-ns host:port` |
| Quark gRPC driver | gRPC | Quark-side driver | deprecated |

Not built: Qblox Q1Simulator face, QCoDeS mirror (end of chapter).

## 2.1 Qibolab face (instrument link)

**Qibolab** is the Qibo package for controlling quantum hardware: a *platform* describes qubits, channels and instruments, and `create_platform(...)` / `platform.connect()` / `platform.execute(...)` run pulse sequences. Official docs: https://qibo.science/qibolab/stable/.

QCSS ships the instrument side. `QcssController` (`integrations/qcss_qibolab/src/qcss_qibolab/controller.py`, package `qcss-qibolab`) subclasses Qibolab's `Controller`. It holds no physics and never writes calibration. On `connect()` it calls `DescribeDevice`; on each `play()` it translates the pulse sequence, uploads the platform's settings through `GetCalibration`/`UpdateCalibration`, pins the job to the resulting epoch (`expected_calibration_epoch`), submits, waits, and assembles results.

The shipped platform is `platforms/qcss_qblox_5q`: five qubits, each with a drive, flux and probe/acquisition channel, address from `QCSS_QBLOX_5Q_ADDRESS` (default `192.168.0.20:50051` in the file). The driver reads its token from the variable named by `token_env` (default `QCSS_TOKEN`) and trusts a CA file for TLS via `ca_file`.

Start the chassis and check it (verified in this session on port 50981):

```
uv run qcss serve --profile qblox_cluster_5q --device transmon_5q --listen 127.0.0.1:50981
uv run qcss remote ping --target 127.0.0.1:50981
   -> 127.0.0.1:50981: SERVING (14.5 ms)
```

Driver refusals (README Limits; translate.py): coupler flux, DC flux offsets and offset sweeps, `drive12`, and sweeping parameters the instrument lacks.

Quick-start: `userdocs/quickstart/qibolab-from-a-host.md`.

## 2.2 The raw instrument link (gRPC)

The same gRPC service is what `QcssController` talks to. Its RPCs (`proto/qcss/v1/control_service.proto`): `SubmitJob`, `GetJobStatus`, `CancelJob`, `StreamResults`, `GetCalibration`, `UpdateCalibration`, `DescribeDevice`, `GetDeviceProperties` (the last is not served on the lab link; the README says the true T1/f01 is not exposed). Use `qcss remote ping|describe|calibration|properties|run`. A job is a `qcss.v1.Job` message (JSON, YAML or binary). Chapter 5 covers jobs.

## 2.3 Qibosoq board face

**Qibosoq** is a server that runs on a QICK-based RFSoC board and accepts a program over TCP. **RFSoC** (Radio-Frequency System on Chip) is the AMD chip family combining FPGA fabric with fast DACs and ADCs. Qibolab's *own* RFSoC driver talks to Qibosoq. QCSS implements the server side, so the lab platform differs from a real one only by the board address.

Enable: `qcss serve ... --board-listen 127.0.0.1:6000`, and set `QCSS_RFSOC_5Q_ADDRESS=127.0.0.1:6000`. Platform: `platforms/qcss_rfsoc_5q` (uses `qibolab.instruments.qibosoq.RFSoC`; the platform file's comment describes it as a ZCU216 running qibosoq, one drive and one flux DAC per qubit, one readout DAC).

Protocol (docstring of `src/qcss/boards/qibosoq.py`): a 4-byte big-endian length and a JSON request; JSON reply, then the connection closes; failures are answered with a traceback string. Times in microseconds, frequencies in MHz, amplitudes as fractions of full scale, phases in degrees. It follows qibosoq at commit `2c37627`.

Limits (README): refuses RAW (decimated) acquisition and nonzero DC bias. Resource bounds (SECURITY.md): requests over 16 MiB refused; a client slower than 30 s to send is dropped; sweeps beyond 2^18 points x sequence elements refused; `reps` is not capped.

No TLS or token (the Qibosoq protocol has neither), so a non-loopback bind needs `--insecure` (chapter 8). Install the pinned qibosoq client as in chapter 1. Unverified in this session: running a Qibolab RFSoC job end to end.

## 2.4 Native QICK face

**QICK** (Quantum Instrumentation Control Kit) is open-source firmware plus the `qick` Python package for RFSoC boards; docs https://docs.qick.dev/. On a real board a `QickSoc` object runs on the board's ARM CPU and a **Pyro4** server exposes it; **Pyro4** is a Python remote-object library. Your PC finds the board via a *nameserver* and gets a proxy with `qick.pyro.make_proxy(ns_host, ns_port, proxy_name)`.

QCSS plays the board. `QcssQickSoc` (`src/qcss/boards/qick/soc.py`) has the same method names and signatures as the real `QickSoc` (frozen from the pinned qick into `surface.json`) and fails the way the real one does. `pyro_host.py` serves it with the same Pyro4 settings as QICK (pickle serializer, protocol 4). Unmodified `qick` programs (tProc v1 averager programs and tProc v2 assembly) therefore run against the simulated chip, with feedback and decimated readout.

### Switches (`qcss serve --help`, verified)

| Option | Meaning |
|---|---|
| `--qick-ns host:port` | Enable the face; register with the Pyro4 nameserver here |
| `--qick-name` | Proxy name (default `myqick`) |
| `--qick-listen host[:port]` | Where the board's Pyro4 daemon binds (default `127.0.0.1`) |
| `--qick-firmware zcu216_v2_5q\|zcu216_v1_5q` | Firmware (default `zcu216_v2_5q`) |
| `--qick-start-ns` | Run the nameserver inside this process |
| `--qick-loopback GEN:RO` | Test cable from generator GEN to readout RO (repeatable) |

### Firmware names

A QICK *firmware* is the FPGA bitstream. It fixes how many generators and readouts exist and which **tProc** (timed processor) is present. `src/qcss/boards/qick/firmware.py` describes both:

- `zcu216_v2_5q` (default): tProc v2, block type `qick_processor`.
- `zcu216_v1_5q`: tProc v1, block type `axis_tproc64x32_x8`.

Both share one layout for the 5-qubit chip: generators 0-4 drive lines, 5-9 flux lines, generator 10 a multiplexed readout tone generator on one feedline; readouts 0-4 are the outputs of one polyphase-filter-bank (PFB) readout on one ADC. DACs run at 6881.28 Msps, the ADC at 2457.6 Msps decimated to 76.8 MHz. The description is for the pinned `qick==0.2.370` and, in the file's own words, "describes one plausible build, not a verified bitstream" (see chapter 3).

### Loopback

On a bench, a cable from a DAC to an ADC makes the readout hear the generator instead of the chip (QICK's first tutorials use this to test the signal path). `--qick-loopback 0:0` wires generator 0 to readout 0: that generator "leaves the chip and the readout hears only the cable" (CLI help). It requires `--qick-ns`, and the value must be `GEN:RO` indices.

### Running it (verified earlier in `userdocs/quickstart/qick-from-a-host.md`)

```
uv run qcss serve --profile qick_zcu216_5q --device transmon_5q \
  --qick-ns 127.0.0.1:8888 --qick-start-ns --qick-loopback 0:0
```
```python
from qick.pyro import make_proxy
soc, soccfg = make_proxy(ns_host="127.0.0.1", ns_port=8888, proxy_name="myqick")
```
Use `uv pip install qick==0.2.370` first (chapter 1). Not-yet-served real-QickSoc methods are listed in `NOT_YET_SERVED` in `soc.py` (for example `tproc`, `streamer`, `load_mem`/`read_mem`, DDR4/MR buffer, time tagger, clock, and attenuator methods, and the unit helpers such as `freq2reg`, `us2cycles`). Unverified: whether a given real-world program touches one of these.

Security: no TLS, no token, but the pickle decoder only resolves an allowlist of globals (chapter 8). Dashboard views of the tProc disassembly and event stream are not built.

## 2.5 Quark gRPC driver (deprecated)

`integrations/quark_qcss` is a reference driver for Quark-QOS that talks to `qcss.v1.ControlService` directly. Its README says it is **deprecated** and "will be removed in the next release": Quark should reach QCSS the way it reaches a lab, through Qibolab (or a Qibosoq board). Its conformance checks live on in `tests/virtual_lab/`. Do not build new work on it.

## 2.6 Not built

- **Qblox Q1Simulator face**: Qblox's own sequencer simulator as a client-visible face. Not built (README Limits).
- **QCoDeS mirror**: the `adapters` extra (`qcodes`, `pyvisa`, `pyvisa-sim`) is installed for it, but the mirror is planned, not built.
- **ZI platform folder**: a profile `zi_shfqc_5q` exists but there is no Qibolab platform folder for it.

---
Sources: `README.md`, `SECURITY.md`, `src/qcss/cli.py` (serve options, `_check_qick_options`), `src/qcss/boards/qibosoq.py`, `src/qcss/boards/qick/{soc,pyro_host,firmware,serializer}.py`, `integrations/qcss_qibolab/src/qcss_qibolab/{controller,translate}.py`, `platforms/*/platform.py`, `proto/qcss/v1/control_service.proto`, `integrations/quark_qcss/README.md`, `userdocs/quickstart/qick-from-a-host.md`. Run: `qcss serve --help`, `qcss remote ping`.
