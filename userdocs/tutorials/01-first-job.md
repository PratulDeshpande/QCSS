# Tutorial 1: your first job

**You will:** start a simulated lab, check it is alive, and run a pi pulse on qubit 0. **Time:** 10 minutes. **Verified:** loopback, 2026-11-05.

## Before you start
From the QCSS repo: `uv sync`. Everything below runs in two terminals.

## 1. Start the lab (terminal 1)
```
uv run qcss serve --profile qblox_cluster_5q --device transmon_5q --port 50991 --time-scale 0
```
You should see:
```
Starting QCSS ControlService on 127.0.0.1:50991 (plaintext, no token) with profile 'qblox_cluster_5q'...
QCSS ControlService listening on 127.0.0.1:50991. Press Ctrl+C to terminate.
```
The *profile* is the control hardware (a Qblox cluster), the *device* is the chip (5 transmons). `--time-scale 0` freezes the chip and skips the real-time pacing, so jobs return fast. Port 50991 is just a free port (default 50051).

## 2. Check it is alive (terminal 2)
```
uv run qcss remote ping -t 127.0.0.1:50991
```
```
127.0.0.1:50991: SERVING (8.3 ms)
```
```
uv run qcss remote describe -t 127.0.0.1:50991
```
prints the channels you may use, such as `xy_q0` (drive) and `ro_q0` (readout) with their ports.

## 3. Run a pi pulse
```
uv run qcss remote run examples/jobs/pi_q0.json -t 127.0.0.1:50991
```
```
Submitted 85ec053dd31e4a7ba3a4f78f51cc3414 (calibration epoch 0)
JOB_STATE_COMPLETED in 1.03 s on tier FIDELITY_TIER_UNSPECIFIED; 1 chunk(s)
  q0: {'0': 39, '1': 961}
```
A pi pulse flips qubit 0 from state 0 to 1, so about 96% of 1000 shots read `1` (the rest is readout and gate error). Your counts will differ: a lab never repeats, so results come from fresh randomness.

Now do nothing (`idle_q0.json`):
```
uv run qcss remote run examples/jobs/idle_q0.json -t 127.0.0.1:50991
```
```
  q0: {'0': 976, '1': 24}
```
Same qubit, no pulse, so it stays in 0. The two jobs differ only by the pulse.

## 4. What you learned
- `qcss serve` is the instrument; `qcss remote ...` is a client talking to it over gRPC.
- A job is a JSON file (pulses, acquisitions, shots). The tier shows as UNSPECIFIED because a real instrument would not tell you how it was simulated (the operator can see it via the admin channel, Tutorial 3).
- The "calibration epoch" is the version of the lab's calibration; jobs are pinned to it.

## Try also
`uv run qcss validate examples/jobs/pi_q0.json --profile qblox_cluster_5q` checks a job against hardware rules without running it. Running the same file against the ZCU216 profile is rejected with real rule violations (for example `integration 1000 not a multiple of 112`), because each profile has its own timing grid.

Stop the server with Ctrl+C in terminal 1. Next: Tutorial 2, a Rabi experiment.

Sources: `src/qcss/cli.py`, `examples/jobs/pi_q0.json`.
