"""Starting, stopping and losing parts of a chassis must leave nothing half-alive."""
from __future__ import annotations

import asyncio
import dataclasses
import os
import signal
import socket
import subprocess
import sys
import time
from concurrent.futures.process import BrokenProcessPool
from typing import Any, cast

import grpc
import pytest
from click.testing import CliRunner
from grpc_health.v1 import health_pb2, health_pb2_grpc

from qcss.adapters.grpc_server import serve
from qcss.chassis import STATE_FILE, Chassis
from qcss.cli import app
from qcss.runtime.jobs import JobManager
from qcss.runtime.runner import create_simulation_runner
from qcss.v1 import job_pb2, result_pb2
from tests.conftest import REPO_ROOT
from tests.integration.test_chassis import config
from tests.integration.test_grpc_calibration import DEV1, IDEAL, _pi_job
from tests.integration.test_grpc_end_to_end import _can_connect_loopback, _free_port

pytestmark = pytest.mark.anyio


async def accept(job: job_pb2.Job) -> None:
    return None


async def eventually(condition, timeout_s: float = 5.0) -> None:
    async def poll() -> None:
        while not condition():
            await asyncio.sleep(0.005)
    await asyncio.wait_for(poll(), timeout_s)


async def test_a_dead_worker_fails_one_job_and_the_next_one_runs():
    runner = cast(Any, create_simulation_runner(IDEAL, DEV1, workers=1))
    job = _pi_job(shots=10)
    try:
        with pytest.raises(BrokenProcessPool):
            await asyncio.wait_for(asyncio.wrap_future(runner.pool.submit(os._exit, 1)), 120)
        with pytest.raises(BrokenProcessPool):
            [c async for c in runner("a", job, asyncio.Event())]
        assert [c async for c in runner("b", job, asyncio.Event())]
    finally:
        runner.pool.shutdown(cancel_futures=True)


async def test_stop_shuts_the_worker_pool_down(tmp_path):
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    chassis = Chassis(config(tmp_path, time_scale=0.0, workers=1))
    await chassis.start()
    await chassis.stop()
    with pytest.raises(RuntimeError):
        cast(Any, chassis._runner).pool.submit(int)


async def test_a_failed_periodic_save_does_not_stop_the_saving(tmp_path, monkeypatch):
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    chassis = Chassis(config(tmp_path, time_scale=0.0, save_interval_s=0.01))
    real, calls = chassis.save, []

    def flaky() -> None:
        calls.append(1)
        if len(calls) == 1:
            raise OSError("disk full")
        real()
    monkeypatch.setattr(chassis, "save", flaky)
    await chassis.start()
    try:
        await eventually(lambda: len(calls) >= 3)
    finally:
        await chassis.stop()


async def test_a_failed_start_releases_what_it_had_already_bound(tmp_path):
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    cfg = dataclasses.replace(config(tmp_path, time_scale=0.0), admin_address="256.0.0.1:1")
    chassis = Chassis(cfg)
    with pytest.raises(Exception, match="(?i)bind"):
        await chassis.start()
    host, port = cfg.lab_address.rsplit(":", 1)
    with socket.socket() as s:
        s.bind((host, int(port)))


async def test_mark_not_serving_flips_the_health_check():
    from qcss.adapters.grpc_server import mark_not_serving
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")

    async def nothing(job_id: str, job: job_pb2.Job, cancel: asyncio.Event):
        return
        yield
    jobs = JobManager(nothing, accept)
    addr = f"127.0.0.1:{_free_port()}"
    server = await serve(addr, jobs)
    try:
        async with grpc.aio.insecure_channel(addr) as ch:
            stub: Any = health_pb2_grpc.HealthStub(ch)
            assert (await stub.Check(health_pb2.HealthCheckRequest())).status == health_pb2.HealthCheckResponse.SERVING
            await mark_not_serving(server)
            assert (await stub.Check(health_pb2.HealthCheckRequest())).status != health_pb2.HealthCheckResponse.SERVING
    finally:
        await server.stop(None)
        await jobs.close()


async def test_stop_reports_not_serving_before_the_lab_link_closes(tmp_path, monkeypatch):
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    chassis = Chassis(config(tmp_path, time_scale=0.0))
    seen: list[Any] = []

    async def spy(server: Any) -> None:
        seen.append(server)
    monkeypatch.setattr("qcss.chassis.mark_not_serving", spy, raising=False)
    await chassis.start()
    await chassis.stop()
    assert seen == [chassis._lab]


async def test_closing_the_manager_ends_a_running_job_and_its_readers():
    async def stuck(job_id: str, job: job_pb2.Job, cancel: asyncio.Event):
        yield result_pb2.ResultChunk(job_id=job_id, sequence_number=1)
        await asyncio.Event().wait()

    jobs = JobManager(stuck, accept)
    job_id = await jobs.submit(job_pb2.Job(num_shots=1))

    async def read() -> int:
        return len([c async for c in jobs.results(job_id)])
    reader = asyncio.create_task(read())
    await asyncio.sleep(0.02)
    await jobs.close()
    assert await asyncio.wait_for(reader, 5) == 1
    assert jobs.status(job_id).state == result_pb2.JOB_STATE_FAILED


async def test_a_cancelled_job_closes_its_runner():
    closed: list[str] = []

    async def endless(job_id: str, job: job_pb2.Job, cancel: asyncio.Event):
        try:
            seq = 0
            while True:
                seq += 1
                yield result_pb2.ResultChunk(job_id=job_id, sequence_number=seq)
                await asyncio.sleep(0)
        finally:
            closed.append(job_id)

    jobs = JobManager(endless, accept)
    try:
        job_id = await jobs.submit(job_pb2.Job(num_shots=1))
        await asyncio.sleep(0.01)
        jobs.cancel(job_id)
        await eventually(lambda: closed == [job_id])
    finally:
        await jobs.close()


def test_a_corrupt_state_file_is_a_clear_error_not_a_traceback(tmp_path):
    (tmp_path / STATE_FILE).write_text("this is not json", encoding="utf-8")
    result = CliRunner().invoke(app, ["serve", "--listen", f"127.0.0.1:{_free_port()}", "--state-dir", str(tmp_path)])
    assert isinstance(result.exception, SystemExit) and result.exit_code == 1
    assert "move it away" in result.output


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no catchable SIGTERM")
def test_sigterm_stops_the_server_cleanly_and_saves_the_chip(tmp_path):
    port = _free_port()
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    proc = subprocess.Popen([sys.executable, "-c", "from qcss.cli import app; app()", "serve", "--listen",
                             f"127.0.0.1:{port}", "--state-dir", str(tmp_path)], env=env, cwd=REPO_ROOT)
    try:
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            with socket.socket() as s:
                s.settimeout(0.2)
                if s.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.1)
        else:
            pytest.fail("the server did not start")
        proc.send_signal(signal.SIGTERM)
        assert proc.wait(30) == 0
        assert (tmp_path / STATE_FILE).exists()
    finally:
        proc.kill()
