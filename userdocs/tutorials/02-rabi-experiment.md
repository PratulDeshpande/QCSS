# Tutorial 2: a Rabi experiment

**You will:** sweep a drive pulse's amplitude, watch the qubit oscillate between 0 and 1, and read off the pi-pulse amplitude. **Time:** 10 minutes. **Prerequisite:** Tutorial 1's server running (port 50991). **Verified:** loopback, 2026-11-05.

## The idea
A longer or stronger drive rotates the qubit further around the Bloch sphere. At small amplitude it barely moves, at the "pi amplitude" it is fully in state 1, past that it rotates back. Plotting P(1) against amplitude gives a Rabi oscillation; its first maximum is your pi pulse.

## 1. Look at the job
`examples/jobs/rabi_amplitude_q0.json` plays a 20-sample square pulse on `xy_q0`, then reads out `ro_q0`. A `sweeps` entry varies the pulse amplitude over 11 values (0.0, 0.1 ... 1.0) with 500 shots each, and `requestedTier` asks for T1B (statevector). The lab ignores a client's tier request (the operator chooses), which is fine here.

Check it first:
```
uv run qcss validate examples/jobs/rabi_amplitude_q0.json --profile qblox_cluster_5q
```
```
Job 'rabi_amplitude_q0' is VALID against profile 'qblox_cluster_5q' (tier T1B: lifts to gates).
```

## 2. Run it and save the results
```
uv run qcss remote run examples/jobs/rabi_amplitude_q0.json -t 127.0.0.1:50991 -o rabi.json
```
```
Submitted 658d6bb3fc52453c9156c4ddefa57a7d (calibration epoch 0)
JOB_STATE_COMPLETED in 8.85 s on tier FIDELITY_TIER_UNSPECIFIED; 11 chunk(s)
  q0: {'0': 2997, '1': 2503}
  per sweep point (q0):
    point [0]: {'0': 490, '1': 10}
    point [1]: {'0': 448, '1': 52}
    ...
    point [5]: {'0': 19, '1': 481}
    ...
    point [10]: {'0': 486, '1': 14}
Saved results to: ...\rabi.json
```

## 3. Plot it in the terminal
Save as `an.py` next to `rabi.json` and run `python an.py`:
```python
import json
r = json.load(open("rabi.json"))
for pt in r["counts_per_point"]:
    c = pt["counts"]; p1 = c.get("1", 0) / (c.get("0", 0) + c.get("1", 0))
    i = pt["sweep_point"][0]
    print(f"amp {i/10:.1f}  P(1) {p1:.2f}  " + "#" * round(p1 * 40))
```
```
amp 0.0  P(1) 0.02  #
amp 0.1  P(1) 0.10  ####
amp 0.2  P(1) 0.36  ##############
amp 0.3  P(1) 0.68  ###########################
amp 0.4  P(1) 0.89  ####################################
amp 0.5  P(1) 0.96  ######################################
amp 0.6  P(1) 0.87  ###################################
amp 0.7  P(1) 0.65  ##########################
amp 0.8  P(1) 0.34  ##############
amp 0.9  P(1) 0.10  ####
amp 1.0  P(1) 0.03  #
```
One full oscillation: up to a peak near amplitude 0.5 (the pi pulse), back down at 1.0 (a 2*pi rotation). The sweep list in the JSON is base64-packed (`values.data`); to sweep other amplitudes, regenerate it with numpy (`np.linspace(...).astype("<f8").tobytes()`, base64-encoded) and keep `shape` equal to the point count (read from the file layout; *regeneration not run*).

## 4. What you learned
A sweep is one job with many points, results come back per point, and the peak of P(1) locates the pi amplitude. In Tutorial 3 you will break the qubit and see the curve change.

Sources: `examples/jobs/rabi_amplitude_q0.json`, `src/qcss/cli.py` (`remote run`).
