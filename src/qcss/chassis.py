"""The chassis: one simulated instrument as `qcss serve` runs it.

It serves the instrument link (what a lab client uses) and, separately, the admin link
(what the operator and CI use). In lab mode, the default, it behaves like hardware:
entropy seeds, the operator's tier policy, no diagnostics on the instrument link, paced
execution, a chip that keeps drifting between jobs and survives restarts of the process.
"""
from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import grpc

from qcss.adapters.admin_server import AdminService, serve_admin
from qcss.adapters.grpc_server import describe_device, serve
from qcss.adapters.instrument_faults import InstrumentFaults
from qcss.boards.qibosoq import BoardWiring, QibosoqBoard
from qcss.boards.qick.soc import QcssQickSoc  # numpy only: Pyro4 is imported when the face starts
from qcss.config.device import DeviceSpec
from qcss.config.profile import HardwareProfile
from qcss.core.seeding import chassis_seed
from qcss.core.timebase import TimeBase
from qcss.runtime.jobs import JobManager
from qcss.runtime.persistence import load_state, save_state
from qcss.runtime.runner import SimulationContext, create_simulation_runner, create_simulation_validator
from qcss.timing.instrument_time import InstrumentPacer

STATE_FILE = "chip.state"


@dataclass
class ChassisConfig:
    profile: HardwareProfile
    device: DeviceSpec | None
    lab_address: str
    admin_address: str | None = None
    board_address: str | None = None     # host:port of a Qibosoq-compatible board face (TCP/JSON)
    qick_ns: str | None = None           # host:port of the Pyro4 nameserver the native QICK board registers with
    qick_name: str = "myqick"            # the board's proxy name there (qick.pyro's proxy_name)
    qick_listen: str = "127.0.0.1"       # host[:port] the board's Pyro4 daemon binds (port 0: any free one)
    qick_firmware: str = "zcu216_v2_5q"  # the firmware the board runs (qcss.boards.qick.firmware)
    qick_start_ns: bool = False          # also run that nameserver in this process
    qick_loopback: tuple[tuple[int, int], ...] = ()   # bench test cables: (generator, readout) pairs
    tls: tuple[bytes, bytes] | None = None
    token: str | None = None
    admin_token: str | None = None
    state_dir: Path | None = None
    seed: int | None = None              # None: fresh entropy, as a real lab never repeats
    time_scale: float = 1.0              # lab seconds per wall second; 0 = frozen chip, unpaced jobs
    deterministic: bool = False          # honour Job.random_seed (CI replay)
    tier: str = "AUTO"                   # physics tier for every job, the operator's choice
    workers: int = 0
    reflection: bool = False
    save_interval_s: float = 60.0


class Chassis:
    def __init__(self, config: ChassisConfig) -> None:
        self.config = config
        tb = TimeBase.from_clocks(config.profile.clock.tick_hz)
        self.ctx = SimulationContext(config.profile, config.device, tb, global_seed=chassis_seed(config.seed),
                                     time_scale=config.time_scale, honour_job_seed=config.deterministic,
                                     tier_policy=config.tier)
        self.restored = False
        if config.state_dir is not None:
            Path(config.state_dir).mkdir(parents=True, exist_ok=True)
            self.restored = load_state(self.state_path, self.ctx)
        self._runner = create_simulation_runner(config.profile, config.device, tb, context=self.ctx,
                                                workers=config.workers,
                                                pacer=InstrumentPacer(lambda: self.ctx.time_scale))
        self.jobs: JobManager | None = None
        self._lab: grpc.aio.Server | None = None
        self._admin: grpc.aio.Server | None = None
        self._board: QibosoqBoard | None = None
        self.qick_soc: QcssQickSoc | None = None
        self._qick: list[Any] = []                      # the QICK board's Pyro4 host (and nameserver), to stop
        self.faults: InstrumentFaults | None = None
        self._saver: asyncio.Task | None = None

    @property
    def state_path(self) -> Path:
        assert self.config.state_dir is not None
        return Path(self.config.state_dir) / STATE_FILE

    async def start(self) -> None:
        c = self.config
        self.jobs = JobManager(self._runner,
                               create_simulation_validator(c.profile, self.ctx.tb, c.device, context=self.ctx),
                               expose_diagnostics=False, max_concurrent_jobs=1)    # one chip, one program
        faults = self.faults = InstrumentFaults(on_reboot=self._on_reboot)
        self._lab = await serve(c.lab_address, self.jobs, describe_device(c.profile, self.ctx.bindings),
                                self.ctx.calibration, tls=c.tls, token=c.token, reflection=c.reflection,
                                faults=faults)
        if c.admin_address is not None:
            self._admin = await serve_admin(c.admin_address, AdminService(self.ctx, self.jobs, faults),
                                            tls=c.tls, token=c.admin_token)
        if c.board_address is not None:
            self._board = QibosoqBoard(self.jobs, BoardWiring.from_bindings(self.ctx.bindings), c.profile, faults)
            await self._board.start(c.board_address)
        if c.qick_ns is not None:
            # Pyro4 calls block: keep them off the event loop
            await asyncio.to_thread(self._start_qick, asyncio.get_running_loop())
        if c.state_dir is not None and c.save_interval_s > 0:
            self._saver = asyncio.create_task(self._save_periodically())

    def _start_qick(self, loop: asyncio.AbstractEventLoop) -> None:
        # Pyro4 is an optional dependency (the qick extra): import it only when the face is wanted
        from qcss.boards.qick.firmware import description
        from qcss.boards.qick.pyro_host import QickBoardHost, start_nameserver
        from qcss.boards.qick.results import ChassisLink

        c = self.config
        assert c.qick_ns is not None
        if c.qick_start_ns:
            self._qick.append(start_nameserver(c.qick_ns))
        host, _, port = c.qick_listen.partition(":")
        self.qick_soc = QcssQickSoc(description(c.qick_firmware))
        self.qick_soc._attach(ChassisLink(self.jobs, loop, self.ctx.bindings, c.profile, dict(c.qick_loopback)))
        board = QickBoardHost(self.qick_soc, ns_address=c.qick_ns, name=c.qick_name, host=host,
                              port=int(port or 0))
        board.start()
        self._qick.insert(0, board)                     # stopped before its nameserver

    def _on_reboot(self, reason: str) -> None:
        """An electronics reboot: running jobs end, and every board forgets what it was given."""
        assert self.jobs is not None
        self.jobs.abort_all(reason)
        if self.qick_soc is not None:
            self.qick_soc._reboot()

    async def _save_periodically(self) -> None:
        while True:
            await asyncio.sleep(self.config.save_interval_s)
            await asyncio.to_thread(self.save)          # JSON + fsync off the event loop; the snapshot takes device_lock

    def save(self) -> None:
        if self.config.state_dir is not None:
            save_state(self.state_path, self.ctx)

    async def wait(self) -> None:
        assert self._lab is not None
        await self._lab.wait_for_termination()

    async def stop(self, grace_s: float = 1.0) -> None:
        if self._saver is not None:
            self._saver.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._saver
        if self._board is not None:
            await self._board.stop()
        for loop in self._qick:
            await asyncio.to_thread(loop.stop)
        self._qick.clear()
        for server in (self._lab, self._admin):
            if server is not None:
                await server.stop(grace=grace_s)
        if self.jobs is not None:
            await self.jobs.close()
        self.save()
