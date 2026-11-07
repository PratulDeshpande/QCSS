# How to: seeded and deterministic runs

**Goal:** repeatable results (for CI or debugging). **Verified:** loopback, 2026-11-05.

## Two independent knobs
| Flag | What it fixes |
|---|---|
| `qcss serve --seed N` | the chip itself (its starting parameters and random-stream tree). Default: fresh entropy, as a real lab never repeats. |
| `qcss serve --deterministic` | the shot noise: the server then honours each job's `randomSeed` so a job replays. Without it the job's seed is ignored. |

Switch it live: `qcss admin mode --deterministic` / `--realistic` (prints `time_scale 0  deterministic yes  tier T1B  seed 11`).

## Recipe
```
uv run qcss serve --port 50995 --time-scale 0 --seed 5 --deterministic
uv run qcss remote run examples/jobs/rabi_amplitude_q0.json -t 127.0.0.1:50995 -o a.json
uv run qcss remote run examples/jobs/rabi_amplitude_q0.json -t 127.0.0.1:50995 -o b.json
```
`rabi_amplitude_q0.json` carries `"randomSeed": "7"`. Number of `1` readouts at the first six sweep points, both runs:
```
[0, 53, 164, 318, 448, 499]
[0, 53, 164, 318, 448, 499]
```
Identical. The same server started without `--deterministic` (still `--seed 5`):
```
[0, 42, 198, 331, 446, 500]
[0, 48, 154, 327, 436, 499]
```
Different each time, as a real lab would be.

## Notes
- Both knobs together give reproducible CI. `--seed` alone gives a reproducible chip but fresh shot noise.
- Different `--chunk-size` changes the seed key for local `qcss run -c` (the help says chunk size is part of the seed key).
- Use `--time-scale 0` so the chip does not drift between runs (otherwise lab time changes the chip).
- A deterministic server is not indistinguishable from a real instrument: use it only for testing.

Sources: `src/qcss/cli.py` (`serve`, `admin mode`).
