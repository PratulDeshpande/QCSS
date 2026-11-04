"""A real QCSS chassis running inside the bridge: the zero-setup virtual lab.

It is the same Chassis `qcss serve` runs (lab link, admin channel, persistence, pacing), on free loopback ports with
fresh random tokens that only the bridge knows. The chip state lives in the dashboard workspace, so the chip keeps
its drift history across restarts, as a real lab would.
"""
from __future__ import annotations

import asyncio
import pathlib
import secrets
import socket
import threading

from qcss.chassis import Chassis, ChassisConfig
from qcss.config.device import DeviceSpec
from qcss.config.profile import HardwareProfile


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class EmbeddedChassis:
    def __init__(self, profile: HardwareProfile, device: DeviceSpec | None, *, profile_name: str,
                 device_name: str | None, time_scale: float, state_dir: pathlib.Path | None,
                 seed: int | None = None) -> None:
        self.profile_name, self.device_name = profile_name, device_name
        self.lab_address = f"127.0.0.1:{_free_port()}"
        self.admin_address = f"127.0.0.1:{_free_port()}"
        self.lab_token = secrets.token_urlsafe(24)
        self.admin_token = secrets.token_urlsafe(24)
        self.chassis = Chassis(ChassisConfig(
            profile=profile, device=device, lab_address=self.lab_address, admin_address=self.admin_address,
            token=self.lab_token, admin_token=self.admin_token, state_dir=state_dir, seed=seed,
            time_scale=time_scale))
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name="qcss-embedded-chassis", daemon=True)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self.chassis.start())
        except BaseException as exc:          # noqa: BLE001 - reported to the starting thread
            self._error = exc
            self._ready.set()
            return
        self._ready.set()
        self._loop.run_forever()

    def start(self, timeout_s: float = 20.0) -> None:
        self._thread.start()
        if not self._ready.wait(timeout_s):
            raise RuntimeError("embedded chassis did not start in time")
        if self._error is not None:
            raise RuntimeError(f"embedded chassis failed to start: {self._error}") from self._error

    def stop(self, timeout_s: float = 20.0) -> None:
        if not self._thread.is_alive():
            return
        asyncio.run_coroutine_threadsafe(self.chassis.stop(), self._loop).result(timeout_s)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(timeout_s)

    def describe(self) -> dict[str, object]:
        return {"profile": self.profile_name, "device": self.device_name, "lab_address": self.lab_address,
                "admin_address": self.admin_address, "time_scale": self.chassis.ctx.time_scale,
                "restored_state": self.chassis.restored}
