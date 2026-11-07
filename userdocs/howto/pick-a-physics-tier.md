# How to: pick a physics tier

**Goal:** choose how faithfully the chip is simulated, trading accuracy for speed. **Verified:** loopback and local `qcss run`, 2026-11-05.

## The tiers
| Tier | What it is |
|---|---|
| `t0` | classical surrogate: fastest, rough |
| `t1a` | Stim: Clifford gates with twirled noise |
| `t1b` | statevector: lifts pulses to gates |
| `t2` | Lindblad (open-system) master equation |
| `auto` | the router picks per job (default) |

## Set it on the server (the operator decides)
```
uv run qcss serve --device transmon_5q --tier t0
```
A client's own tier request is ignored. The operator can change it live (`requested` honours each job's own):
```
uv run qcss admin mode --tier t1b          # choices: requested, auto, t0, t1a, t1b, t2
```

## See which tier ran
A client never learns it (`on tier FIDELITY_TIER_UNSPECIFIED`). The operator does:
```
uv run qcss admin inspect <job-id>
tier FIDELITY_TIER_T0_SURROGATE  noise NOISE_FIDELITY_SURROGATE  epoch 0
```
(for a server started with `--tier t0`; `auto` on `pi_q0.json` was reported as `FIDELITY_TIER_T1B_STATEVECTOR` with physical noise.)

## Try tiers locally without a server
`qcss run` takes `-t/--tier` (it also lists `t3`):
```
uv run qcss run examples/jobs/pi_q0.json -t t1a --profile qblox_cluster_5q --device transmon_5q -s 200
```
Verified outputs for the same pi job, 200 shots:
| Tier | Reported | Counts |
|---|---|---|
| t0 | `Tier: T0 (requested)` | {0: 1, 1: 199} |
| t1a | `Tier: T1A (Clifford gates, twirled noise)` | {1: 200} |
| t1b | `Tier: T1B (lifts to gates)` | {0: 2, 1: 198} |
| t2 | `Tier: T2 (requested)` | {0: 12, 1: 188} |
Counts are random, so compare tiers over several runs, not from one. `-t t3` was not run.

## Rule of thumb
Use `auto` unless you are teaching or debugging a tier. The router explains its choice: `qcss validate` printed `tier T1B: lifts to gates` for the Rabi job, and `qcss run` prints `Tier: ... (reason)`.

Sources: `src/qcss/cli.py` (`serve`, `run`, `admin mode`, `admin inspect`).
