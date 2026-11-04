"""Live state for the browser: one snapshot per poll interval over a WebSocket.

QCSS has no push events (no job list, no progress, no change notifications), so the bridge polls the admin channel
(mode, truth) and the lab link (calibration epoch) and fans the result out. Nothing here adds an RPC to the chassis.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from qcss_dashboard.admin import LinkError, Links, admin_state


def snapshot(links: Links, jobs: list[dict[str, Any]]) -> dict[str, Any]:
    links.probe()
    out: dict[str, Any] = {"ts": time.time(), "lab": links.lab_status(), "admin": links.admin_status(),
                           "jobs": jobs[-20:], "chassis": links.embedded.describe() if links.embedded else None}
    try:
        out.update(admin_state(links))
    except LinkError as exc:
        out["truth"] = None
        out["admin_error"] = str(exc)
    try:
        with links.lab(timeout_s=3.0) as c:
            out["calibration_epoch"] = c.get_calibration().calibration_epoch
    except Exception as exc:                    # noqa: BLE001 - shown in the UI, never fatal for the stream
        out["calibration_epoch"] = None
        out["lab_error"] = str(exc)
    return out


async def stream(websocket: Any, links: Links, jobs: Any, interval_s: float) -> None:
    from starlette.websockets import WebSocketDisconnect

    await websocket.accept()
    try:
        while True:
            data = await asyncio.to_thread(snapshot, links, jobs())
            await websocket.send_json(data)
            await asyncio.sleep(interval_s)
    except (WebSocketDisconnect, RuntimeError):
        return
