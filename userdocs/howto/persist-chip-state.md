# How to: keep the chip's state across restarts

**Goal:** a server restart should not reset the chip. **Verified:** loopback, 2026-11-05.

## Use `--state-dir`
```
uv run qcss serve --device transmon_5q --state-dir state --admin-listen 127.0.0.1:50052 --admin-token <t>
```
The chip's drift, defects, scenarios, lab clock and random state are saved as plain JSON in `state/chip.state`, every 60 seconds and at a clean shutdown. Downtime counts as lab time.

## Proof
1. Start with `--state-dir`, run `qcss admin kill 2`. Wait more than 60 s (or stop with Ctrl+C, a clean shutdown).
2. `chip.state` exists. Restart with the same command. The log says:
```
Restored the chip from <path>\chip.state.
```
3. `qcss admin truth` still shows qubit 2 at 4.749777 GHz, T1 0.10 us, `DEAD`.

## Pitfalls
- A forced kill (Task Manager, `Stop-Process -Force`) skips the shutdown save, so anything newer than the last 60 s autosave is lost. I saw this: a restart right after `kill` showed qubit 2 `ok`. Stop with Ctrl+C.
- Always pass `--device` as well: without it the chassis "runs without a device file" and admin commands answer `FAILED_PRECONDITION: the chassis runs without a device file`.
- To start fresh, point at a new folder (or delete `chip.state` while the server is stopped).
Sources: `src/qcss/cli.py` (`serve`), README ("The chip persists").
