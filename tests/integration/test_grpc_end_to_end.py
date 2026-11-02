"""Integration tests for ControlService and JobManager end-to-end."""
from __future__ import annotations

import asyncio
import socket
from typing import Any, cast

import grpc
import numpy as np
import pytest

from qcss.adapters.grpc_server import ControlService, serve
from qcss.core.errors import HardwareValidationError
from qcss.core.ndarray import from_proto, to_proto
from qcss.runtime.jobs import JobManager
from qcss.v1 import control_service_pb2 as pb
from qcss.v1 import control_service_pb2_grpc as pbg
from qcss.v1 import job_pb2, result_pb2


def _free_port() -> int:
    """A loopback port the OS has just confirmed is free (fixed ports collide with other software)."""
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _can_connect_loopback() -> bool:
    s = socket.socket()
    try:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        s2 = socket.socket()
        s2.settimeout(0.05)
        try:
            s2.connect(("127.0.0.1", port))
            return True
        except (PermissionError, OSError):
            return False
        finally:
            s2.close()
    finally:
        s.close()


class MockServicerContext:
    def __init__(self):
        self.code = None
        self.details = None
        self.aborted = False
        self.status = None

    async def abort(self, code, details=""):
        self.code = code
        self.details = details
        self.aborted = True
        raise grpc.RpcError(details)

    async def abort_with_status(self, status):
        self.status = status
        self.code = status.code
        self.details = status.details
        self.aborted = True
        raise grpc.RpcError(status.details)


async def fake_validator(job: job_pb2.Job):
    if job.num_shots == 0:
        raise HardwareValidationError([("job.num_shots", "must be > 0")])


async def fake_runner(job_id: str, job: job_pb2.Job, cancel: asyncio.Event):
    for seq in range(3):
        if cancel.is_set():
            break
        iq = (np.arange(4) + 1j * seq).astype(np.complex64)
        yield result_pb2.ResultChunk(
            job_id=job_id,
            sequence_number=seq + 1,
            shot_offset=4 * seq,
            num_shots_in_chunk=4,
            acquisitions=[result_pb2.AcquisitionResult(result_key="q0", iq=to_proto(iq))],
            is_last=(seq == 2),
        )
        await asyncio.sleep(0.01)


@pytest.mark.anyio
async def test_servicer_submit_stream_status():
    jobs = JobManager(fake_runner, fake_validator)
    svc = ControlService(jobs, pb.DescribeDeviceResponse())
    ctx = MockServicerContext()

    try:
        resp = await svc.SubmitJob(pb.SubmitJobRequest(job=job_pb2.Job(num_shots=12)), ctx)
        assert resp.job_id

        chunks = []
        async for m in svc.StreamResults(pb.StreamResultsRequest(job_id=resp.job_id), ctx):
            chunks.append(m.chunk)

        assert [c.sequence_number for c in chunks] == [1, 2, 3]
        last_iq = from_proto(chunks[2].acquisitions[0].iq)
        assert np.allclose(np.imag(last_iq), 2.0)

        st = await svc.GetJobStatus(pb.GetJobStatusRequest(job_id=resp.job_id), ctx)
        assert st.status.state == result_pb2.JOB_STATE_COMPLETED

        # Test validation rejection
        with pytest.raises(grpc.RpcError):
            await svc.SubmitJob(pb.SubmitJobRequest(job=job_pb2.Job(num_shots=0)), ctx)
        assert ctx.aborted
        assert ctx.status is not None
        assert ctx.code == grpc.StatusCode.INVALID_ARGUMENT
    finally:
        await jobs.close()


@pytest.mark.anyio
async def test_servicer_cancel_job():
    jobs = JobManager(fake_runner, fake_validator)
    svc = ControlService(jobs, pb.DescribeDeviceResponse())
    ctx = MockServicerContext()

    try:
        resp = await svc.SubmitJob(pb.SubmitJobRequest(job=job_pb2.Job(num_shots=100)), ctx)
        cancel_resp = await svc.CancelJob(pb.CancelJobRequest(job_id=resp.job_id), ctx)
        assert cancel_resp.status.job_id == resp.job_id
    finally:
        await jobs.close()


@pytest.mark.anyio
async def test_grpc_networked_end_to_end():
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")

    jobs = JobManager(fake_runner, fake_validator)
    addr = f"127.0.0.1:{_free_port()}"
    server = await serve(addr, jobs)

    try:
        async with grpc.aio.insecure_channel(addr) as ch:
            stub = pbg.ControlServiceStub(ch)
            r = await stub.SubmitJob(pb.SubmitJobRequest(job=job_pb2.Job(num_shots=12)))
            assert r.job_id

            chunks = [m.chunk async for m in stub.StreamResults(pb.StreamResultsRequest(job_id=r.job_id))]
            assert len(chunks) > 0
    finally:
        await server.stop(None)
        await jobs.close()


@pytest.mark.anyio
async def test_simulation_runner_with_control_service():
    from qcss.config.loader import load_profile
    from qcss.core.timebase import TimeBase
    from qcss.runtime.runner import create_simulation_runner, create_simulation_validator

    profile = load_profile("src/qcss/config/profiles/qblox_cluster_5q.yaml")
    tb = TimeBase.from_clocks("1e9")
    runner = create_simulation_runner(profile, timebase=tb, chunk_size=10)
    validator = create_simulation_validator(profile, tb)

    jobs = JobManager(runner, validator)
    svc = ControlService(jobs, pb.DescribeDeviceResponse())
    ctx = MockServicerContext()

    job = job_pb2.Job(
        job_key="real_runner_test",
        num_shots=20,
        repetition_delay_ticks=200_000,
        requested_tier=job_pb2.FIDELITY_TIER_T0_SURROGATE,
        waveform_library={
            "g1": job_pb2.Waveform(
                shape=job_pb2.WAVEFORM_SHAPE_GAUSSIAN,
                length_samples=20,
                sigma_samples=5.0,
            ),
        },
    )
    job.main.instructions.add(
        start_tick=0,
        play=job_pb2.Play(channel_id="xy_q0", waveform_id="g1", amplitude=0.8),
    )
    job.main.instructions.add(
        start_tick=40,
        acquire=job_pb2.Acquire(
            channel_id="ro_q0",
            integration_ticks=500,
            mode=job_pb2.ACQUISITION_MODE_DISCRIMINATED,
            register_index=0,
            result_key="q0",
        ),
    )

    try:
        resp = await svc.SubmitJob(pb.SubmitJobRequest(job=job), ctx)
        assert resp.job_id

        chunks = []
        async for m in svc.StreamResults(pb.StreamResultsRequest(job_id=resp.job_id), ctx):
            chunks.append(m.chunk)

        st = await svc.GetJobStatus(pb.GetJobStatusRequest(job_id=resp.job_id), ctx)
        assert len(chunks) == 2, f"st.state={st.status.state}, st.message={st.status.message}"
        assert chunks[0].num_shots_in_chunk == 10
        assert chunks[1].num_shots_in_chunk == 10
        assert chunks[1].is_last

        # Check acquisitions
        labels = from_proto(chunks[0].acquisitions[0].states)
        assert len(labels) == 10

        st = await svc.GetJobStatus(pb.GetJobStatusRequest(job_id=resp.job_id), ctx)
        assert st.status.state == result_pb2.JOB_STATE_COMPLETED

        # Submit T1B job
        job_t1b = job_pb2.Job(
            job_key="t1b_grpc_test",
            num_shots=10,
            requested_tier=job_pb2.FIDELITY_TIER_T1B_STATEVECTOR,
            waveform_library={
                "x": job_pb2.Waveform(
                    shape=job_pb2.WAVEFORM_SHAPE_SQUARE,
                    length_samples=20,
                ),
            },
        )
        job_t1b.main.instructions.add(
            start_tick=0,
            play=job_pb2.Play(channel_id="xy_q0", waveform_id="x", duration_ticks=20, amplitude=1.0),
        )
        job_t1b.main.instructions.add(
            start_tick=30,
            acquire=job_pb2.Acquire(
                channel_id="ro_q0",
                integration_ticks=100,
                mode=job_pb2.ACQUISITION_MODE_DISCRIMINATED,
                register_index=0,
                result_key="q0",
            ),
        )
        resp_t1b = await svc.SubmitJob(pb.SubmitJobRequest(job=job_t1b), ctx)
        chunks_t1b = []
        async for m in svc.StreamResults(pb.StreamResultsRequest(job_id=resp_t1b.job_id), ctx):
            chunks_t1b.append(m.chunk)
        assert len(chunks_t1b) == 1
        assert chunks_t1b[0].num_shots_in_chunk == 10
    finally:
        await jobs.close()


@pytest.mark.anyio
async def test_health_check_reports_serving_and_debug_reflection_lists_service():
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    from grpc_health.v1 import health_pb2, health_pb2_grpc
    from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc

    jobs = JobManager(fake_runner, fake_validator)
    addr = f"127.0.0.1:{_free_port()}"
    server = await serve(addr, jobs, reflection=True)
    try:
        async with grpc.aio.insecure_channel(addr) as ch:
            # typeshed types these generated stubs for sync channels only; the aio channel works at runtime
            hc: Any = health_pb2_grpc.HealthStub(cast(Any, ch))
            for name in ("", "qcss.v1.ControlService"):
                r = await hc.Check(health_pb2.HealthCheckRequest(service=name))
                assert r.status == health_pb2.HealthCheckResponse.SERVING
            refl: Any = reflection_pb2_grpc.ServerReflectionStub(cast(Any, ch))
            names = []
            async for resp in refl.ServerReflectionInfo(iter([reflection_pb2.ServerReflectionRequest(list_services="")])):
                names = [s.name for s in resp.list_services_response.service]
            assert "qcss.v1.ControlService" in names
    finally:
        await server.stop(None)
        await jobs.close()

@pytest.mark.anyio
async def test_reflection_is_off_by_default():
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    from grpc_reflection.v1alpha import reflection_pb2, reflection_pb2_grpc

    jobs = JobManager(fake_runner, fake_validator)
    addr = f"127.0.0.1:{_free_port()}"
    server = await serve(addr, jobs)
    try:
        async with grpc.aio.insecure_channel(addr) as ch:
            refl: Any = reflection_pb2_grpc.ServerReflectionStub(cast(Any, ch))
            with pytest.raises(grpc.aio.AioRpcError) as err:
                async for _ in refl.ServerReflectionInfo(iter([reflection_pb2.ServerReflectionRequest(list_services="")])):
                    pass
            assert err.value.code() == grpc.StatusCode.UNIMPLEMENTED
    finally:
        await server.stop(None)
        await jobs.close()
