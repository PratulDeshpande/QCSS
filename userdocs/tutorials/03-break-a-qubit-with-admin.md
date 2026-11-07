# Tutorial 3: break a qubit with the admin channel

**You will:** play the lab's operator. You will kill a qubit, watch a client's job fail to see it, bring it back, and inject drift and an instrument fault. **Time:** 15 minutes. **Verified:** loopback, 2026-11-05.

## The idea
A lab client (Tutorials 1-2) only sees what a real instrument would show. The *admin channel* is a second, separate door for the operator: it shows the chip's hidden truth and lets you cause trouble. It has its own address and its own token.

## 1. Start the lab with an admin channel (terminal 1)
```
export QCSS_ADMIN_TOKEN=docs-admin        # PowerShell: $env:QCSS_ADMIN_TOKEN = "docs-admin"
uv run qcss serve --profile qblox_cluster_5q --device transmon_5q --port 50991 --time-scale 0 --admin-listen 127.0.0.1:50992 --admin-token docs-admin
```
Among the lines: `Admin channel on 127.0.0.1:50992 (token required).` (The `--admin-token` flag can be replaced by the env var `QCSS_ADMIN_TOKEN`; the client commands read the same variable.) If you already run the server from Tutorial 1, stop it and restart with these flags.

In terminal 2 set the same token, so every `qcss admin` command can use it: `export QCSS_ADMIN_TOKEN=docs-admin`. The admin default target is `127.0.0.1:50052`, so here pass `-t 127.0.0.1:50992`.

## 2. See the truth
```
uv run qcss admin truth -t 127.0.0.1:50992
```
```
lab time 7.364 s
  qubit   f01 (GHz)   T1 (us)   state
    0    5.052180     19.89   ok
    1    5.199950     51.49   ok
    ...
```
A client cannot read this (`qcss remote properties` answers `UNIMPLEMENTED`, on purpose). `qcss admin mode -t ...` shows how the chassis runs: `time_scale 0  deterministic no  tier AUTO  seed 11`.

## 3. Kill qubit 0
```
uv run qcss admin kill 0 -t 127.0.0.1:50992
```
```
qubit 0 killed
```
`admin truth` now shows qubit 0 at `4.852180` GHz (200 MHz lower), T1 `0.10` us and state `DEAD`. Now run the pi pulse as a client:
```
uv run qcss remote run examples/jobs/pi_q0.json -t 127.0.0.1:50991
```
```
  q0: {'0': 999, '1': 1}
```
Compare with ~960 ones before. The client sees only a qubit that stopped answering; nothing says "killed".

## 4. Revive it
```
uv run qcss admin revive 0 -t 127.0.0.1:50992
uv run qcss remote run examples/jobs/pi_q0.json -t 127.0.0.1:50991
```
```
qubit 0 revived
  q0: {'0': 62, '1': 938}
```

## 5. Drift, and undo everything
```
uv run qcss admin drift 0 --df-hz 2e6 -t 127.0.0.1:50992      # qubit 0 moves 2 MHz (accumulates; also --t1-factor)
```
```
qubit 0: df 2e+06 Hz, T1 x1
```
The pi pulse gets a little worse (`{'0': 93, '1': 907}`). `uv run qcss admin clear -t ...` prints `scenarios cleared` and removes kills, drift steps, defects and bursts. Two more actors: `admin burst 1` (a cosmic-ray hit, prints `qubit 1: burst`) and `admin tls 1` (a TLS defect drifts into resonance). `admin freeze` stops all drift (`drift frozen`), `admin freeze --off` resumes it. (`admin tls` was not run here.)

## 6. An instrument fault
```
uv run qcss admin fault drop --count 1 -t 127.0.0.1:50992
uv run qcss remote run examples/jobs/pi_q0.json -t 127.0.0.1:50991
```
```
instrument fault: drop x1
Error UNAVAILABLE: Connection reset by peer
```
The next client call dies like a flaky instrument. Clear leftovers with `uv run qcss admin clear-faults -t ...` (`instrument faults cleared`). The other kinds are `hang`, `reboot` and `slow-upload`, which need `--duration` seconds (see the how-to `../howto/inject-faults.md`).

## 7. See how a job was really run
Pass a job id (printed by `remote run` on `Submitted ...`) to `admin inspect`:
```
uv run qcss admin inspect 215038d85ba148d18c1cc01fff24f26d -t 127.0.0.1:50992
```
```
tier FIDELITY_TIER_T1B_STATEVECTOR  noise NOISE_FIDELITY_PHYSICAL  epoch 0
```
The client saw `tier FIDELITY_TIER_UNSPECIFIED`; only the admin sees the real tier.

## Remember
Admin and lab tokens must differ, and the admin channel requires a token whenever the lab link has one. Real jobs may be slower than in Tutorial 1 when the machine is busy (seconds, not milliseconds).

Sources: `src/qcss/cli.py` (`admin_*` commands, `serve` rules).
