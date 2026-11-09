"""Chassis state on disk: the chip's hidden state survives a restart of the simulator process.

A restart behaves like rebooting the control electronics: whatever was programmed into them
is gone, but the chip in the fridge kept drifting meanwhile, so the downtime counts as lab
time. The file is written atomically (temp file, fsync, rename) as plain JSON, so loading
a state file never executes anything, whoever wrote it.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
import time
from pathlib import Path

from qcss.runtime.runner import SimulationContext

FORMAT = 2


def _device_digest(ctx: SimulationContext) -> str:
    return hashlib.sha256(ctx.device.model_dump_json().encode() if ctx.device else b"").hexdigest()


def save_state(path: Path, ctx: SimulationContext, *, wall_now: float | None = None) -> None:
    state = ctx.device_state
    with ctx.device_lock:
        device = state.to_dict() if state is not None else None
    blob = json.dumps({
        "format": FORMAT,
        "device_sha256": _device_digest(ctx),
        "lab_time_s": ctx.lab_time_s,
        "saved_at_unix_s": time.time() if wall_now is None else wall_now,
        "device_state": device,
    }).encode("utf-8")
    path = Path(path)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(blob)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def load_state(path: Path, ctx: SimulationContext, *, wall_now: float | None = None) -> bool:
    """Restore the chip into ctx; False if there is no saved state (a fresh chip)."""
    path = Path(path)
    if not path.exists():
        return False
    try:
        data = json.loads(path.read_bytes().decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as err:
        raise ValueError(f"{path}: not a chip state (expected JSON); move it away to start a fresh chip") from err
    if not isinstance(data, dict):
        raise ValueError(f"{path}: not a chip state")      # noqa: TRY004 - bad file content, as for bad JSON
    if data.get("format") != FORMAT:
        raise ValueError(f"{path}: unsupported state format {data.get('format')!r}")
    for key in ("device_sha256", "lab_time_s", "saved_at_unix_s", "device_state"):
        if key not in data:
            raise ValueError(f"{path}: not a chip state (no {key!r}); move it away to start a fresh chip")
    lab_t, saved_at = data["lab_time_s"], data["saved_at_unix_s"]
    if not all(isinstance(x, (int, float)) and not isinstance(x, bool) for x in (lab_t, saved_at))             or not math.isfinite(lab_t) or lab_t < 0 or not math.isfinite(saved_at):
        raise ValueError(f"{path}: bad lab_time_s or saved_at_unix_s; move it away to start a fresh chip")
    if data["device_sha256"] != _device_digest(ctx):
        raise ValueError(f"{path}: saved for a different device; move it away to start a fresh chip")
    now = time.time() if wall_now is None else wall_now
    if data["device_state"] is not None and ctx.device_state is not None:
        ctx.device_state.load_dict(data["device_state"])
    ctx.lab_time_s = lab_t + max(0.0, now - saved_at) * ctx.time_scale
    return True
