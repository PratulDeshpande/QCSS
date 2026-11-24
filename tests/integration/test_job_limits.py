"""A client's numbers must not exhaust the host: an absurd job is refused at once, before anything is allocated."""
from __future__ import annotations

import asyncio
import time

import grpc
import numpy as np
import pytest

from qcss.adapters.grpc_server import ControlService
from qcss.config.loader import load_device, load_profile
from qcss.core.errors import HardwareValidationError
from qcss.core.ndarray import to_proto
from qcss.core.timebase import TimeBase
from qcss.readout.resonator import DispersiveReadout, ResonatorParams
from qcss.runtime.jobs import JobManager
from qcss.runtime.runner import SimulationContext
from qcss.v1 import control_service_pb2 as pb
from qcss.v1 import job_pb2, result_pb2
from tests.conftest import PROFILES_DIR, REPO_ROOT
from tests.integration.test_grpc_end_to_end import MockServicerContext

PROFILE = load_profile(PROFILES_DIR / "qblox_cluster_5q.yaml")
DEVICE = load_device(REPO_ROOT / "src" / "qcss" / "config" / "devices" / "transmon_5q.yaml")


@pytest.fixture(scope="module")
def ctx() -> SimulationContext:
    return SimulationContext(PROFILE, DEVICE, TimeBase.from_clocks(PROFILE.clock.tick_hz))


def small_job(integration_ticks: int = 1000, shots: int = 10) -> job_pb2.Job:
    job = job_pb2.Job(num_shots=shots)
    job.waveform_library["pi"].CopyFrom(job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=20))
    job.main.instructions.add(start_tick=0, play=job_pb2.Play(channel_id="xy_q0", waveform_id="pi", amplitude=0.5))
    job.main.instructions.add(start_tick=24, acquire=job_pb2.Acquire(
        channel_id="ro_q0", integration_ticks=integration_ticks, mode=job_pb2.ACQUISITION_MODE_DISCRIMINATED,
        result_key="q0"))
    return job


def refused(ctx: SimulationContext, job: job_pb2.Job) -> str:
    start = time.monotonic()
    with pytest.raises(HardwareValidationError) as err:
        ctx.plan(job)
    assert time.monotonic() - start < 1.0
    return str(err.value)


def test_an_ordinary_job_is_still_planned(ctx):
    assert len(ctx.plan(small_job()).points) == 1


def test_a_waveform_larger_than_any_memory_is_refused_before_it_is_built(ctx):
    job = small_job()
    job.waveform_library["huge"].CopyFrom(job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=2**31))
    assert "waveform memory" in refused(ctx, job)


def test_a_sweep_grid_too_large_is_refused_before_it_is_expanded(ctx):
    job = small_job()
    for axis in (0, 1):
        job.sweeps.add(axis=axis, values=to_proto(np.arange(1000.0)))
    assert "sweep points" in refused(ctx, job)


def test_a_large_job_swept_too_many_times_is_refused(ctx):
    job = small_job()
    job.waveform_library["arb"].CopyFrom(job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_ARBITRARY,
                                                          samples=to_proto(np.ones(2**17, np.complex64))))
    job.sweeps.add(axis=0, values=to_proto(np.arange(4096.0)))
    assert "sweep points" in refused(ctx, job)


def test_too_many_program_points_are_refused(ctx):
    job = small_job()
    for _ in range(65_537):
        job.program_points.add()
    assert "sweep points" in refused(ctx, job)


def test_too_many_shots_are_refused(ctx):
    assert "num_shots" in refused(ctx, small_job(shots=2**31))


def test_a_readout_window_too_long_to_hold_is_refused(ctx):
    assert "capture memory" in refused(ctx, small_job(integration_ticks=16_000_000))


def test_a_record_too_large_to_hold_fails_cleanly():
    readout = DispersiveReadout(ResonatorParams(0.05, (0.0, 0.0, 0.0), 0.0, 0.5, 0))
    with pytest.raises(ValueError, match="capture memory"):
        readout.traces(np.zeros(10**7, dtype=np.intp), np.zeros(10**5, dtype=np.complex128), 1e4,
                       np.random.default_rng(0))


@pytest.mark.anyio
async def test_a_full_queue_refuses_new_jobs_and_recovers():
    release = asyncio.Event()

    async def blocked(job_id: str, job: job_pb2.Job, cancel: asyncio.Event):
        await release.wait()
        yield result_pb2.ResultChunk(job_id=job_id, sequence_number=1, is_last=True)

    async def accept(job: job_pb2.Job) -> None:
        return None

    request = pb.SubmitJobRequest(job=job_pb2.Job(num_shots=1))
    jobs = JobManager(blocked, accept, max_concurrent_jobs=1, max_pending=2)
    svc = ControlService(jobs, pb.DescribeDeviceResponse())
    try:
        await svc.SubmitJob(request, MockServicerContext())
        await asyncio.sleep(0.01)                      # the first job is running, so it does not count as queued
        waiting = [(await svc.SubmitJob(request, MockServicerContext())).job_id for _ in range(2)]
        full = MockServicerContext()
        with pytest.raises(grpc.RpcError):
            await svc.SubmitJob(request, full)
        assert full.code == grpc.StatusCode.RESOURCE_EXHAUSTED
        jobs.cancel(waiting[0])
        assert (await svc.SubmitJob(request, MockServicerContext())).job_id
    finally:
        release.set()
        await jobs.close()
