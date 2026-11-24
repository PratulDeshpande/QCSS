"""A job must finish whether or not anyone is reading it: submit, wait, then fetch is the documented flow."""
from __future__ import annotations

import asyncio

import pytest

from qcss.adapters.grpc_server import serve
from qcss.client import QcssClient
from qcss.runtime.jobs import JobManager
from qcss.v1 import control_service_pb2 as pb
from qcss.v1 import job_pb2, result_pb2
from tests.integration.test_grpc_end_to_end import _can_connect_loopback, _free_port

pytestmark = pytest.mark.anyio

COMPLETED, FAILED = result_pb2.JOB_STATE_COMPLETED, result_pb2.JOB_STATE_FAILED


async def validator(job: job_pb2.Job) -> None:
    return None


def runner_of(n: int, *, padding: int = 0):
    """A runner yielding n chunks, and the list of the chunks it has produced so far."""
    produced: list[int] = []

    async def run(job_id: str, job: job_pb2.Job, cancel: asyncio.Event):
        for seq in range(1, n + 1):
            produced.append(seq)
            yield result_pb2.ResultChunk(job_id=job_id + "x" * padding, sequence_number=seq, is_last=seq == n)
            await asyncio.sleep(0)
    return run, produced


async def until_finished(jobs: JobManager, job_id: str, timeout_s: float = 5.0) -> result_pb2.JobStatus:
    async def poll() -> result_pb2.JobStatus:
        while jobs.status(job_id).state not in (COMPLETED, FAILED):
            await asyncio.sleep(0.005)
        return jobs.status(job_id)
    return await asyncio.wait_for(poll(), timeout_s)


async def drain(jobs: JobManager, job_id: str, resume_after: int = 0) -> list[int]:
    return [c.sequence_number async for c in jobs.results(job_id, resume_after)]


async def test_a_job_larger_than_the_window_finishes_with_nobody_reading_and_frees_the_queue():
    run, _ = runner_of(70)
    jobs = JobManager(run, validator, max_buffered_chunks=64, max_concurrent_jobs=1)
    try:
        first = await jobs.submit(job_pb2.Job(num_shots=1))
        second = await jobs.submit(job_pb2.Job(num_shots=1))
        assert (await until_finished(jobs, first)).state == COMPLETED
        assert (await until_finished(jobs, second)).state == COMPLETED
        assert await asyncio.wait_for(drain(jobs, first), 5) == list(range(1, 71))
    finally:
        await jobs.close()


async def test_a_connected_reader_still_throttles_the_producer_and_lets_it_resume():
    run, produced = runner_of(10)
    jobs = JobManager(run, validator, max_buffered_chunks=2)
    try:
        job_id = await jobs.submit(job_pb2.Job(num_shots=1))
        reader = jobs.results(job_id)
        assert (await asyncio.wait_for(anext(reader), 5)).sequence_number == 1
        await asyncio.sleep(0.05)
        assert jobs.status(job_id).state == result_pb2.JOB_STATE_RUNNING
        assert len(produced) <= 4                     # 1 read + 2 buffered + the one waiting to be appended
        assert [c.sequence_number async for c in reader] == list(range(2, 11))
        assert (await until_finished(jobs, job_id)).state == COMPLETED
    finally:
        await jobs.close()


async def test_a_connected_reader_is_also_throttled_by_unread_bytes():
    one = result_pb2.ResultChunk(job_id="j" * 32 + "x" * 1000, sequence_number=1).ByteSize()
    run, produced = runner_of(10, padding=1000)
    jobs = JobManager(run, validator, max_buffered_chunks=64, max_retained_bytes_per_job=2 * one + 8)
    try:
        job_id = await jobs.submit(job_pb2.Job(num_shots=1))
        reader = jobs.results(job_id)
        await asyncio.wait_for(anext(reader), 5)
        await asyncio.sleep(0.05)
        assert jobs.status(job_id).state == result_pb2.JOB_STATE_RUNNING
        assert len(produced) <= 4
        assert [c.sequence_number async for c in reader] == list(range(2, 11))
        assert (await until_finished(jobs, job_id)).state == COMPLETED
    finally:
        await jobs.close()


async def test_a_reader_that_goes_away_releases_a_blocked_producer():
    run, _ = runner_of(10)
    jobs = JobManager(run, validator, max_buffered_chunks=1)
    try:
        job_id = await jobs.submit(job_pb2.Job(num_shots=1))
        reader = jobs.results(job_id)
        await asyncio.wait_for(anext(reader), 5)
        await asyncio.sleep(0.02)
        await reader.aclose()
        assert (await until_finished(jobs, job_id)).state == COMPLETED
        assert await asyncio.wait_for(drain(jobs, job_id), 5) == list(range(1, 11))
    finally:
        await jobs.close()


async def test_unread_results_beyond_the_retention_cap_fail_the_job_and_say_why():
    one = result_pb2.ResultChunk(job_id="j" * 32 + "x" * 1000, sequence_number=1).ByteSize()
    run, produced = runner_of(10, padding=1000)
    jobs = JobManager(run, validator, max_retained_bytes_per_job=3 * one)
    try:
        job_id = await jobs.submit(job_pb2.Job(num_shots=1))
        st = await until_finished(jobs, job_id)
        assert st.state == FAILED
        assert "not collected" in st.message and "StreamResults" in st.message
        assert len(produced) < 10
        assert await asyncio.wait_for(drain(jobs, job_id), 5) == [1, 2, 3, 4]    # what was kept stays readable
    finally:
        await jobs.close()


async def test_a_reader_that_stops_reading_fails_the_job_instead_of_holding_the_chassis():
    run, _ = runner_of(10)
    jobs = JobManager(run, validator, max_buffered_chunks=1, reader_stall_timeout_s=0.05)
    try:
        job_id = await jobs.submit(job_pb2.Job(num_shots=1))
        reader = jobs.results(job_id)
        await asyncio.wait_for(anext(reader), 5)
        st = await until_finished(jobs, job_id)
        assert st.state == FAILED and "stalled" in st.message
        await reader.aclose()
    finally:
        await jobs.close()


async def test_a_finished_job_does_not_keep_its_program_in_memory():
    run, _ = runner_of(1)
    jobs = JobManager(run, validator)
    try:
        job_id = await jobs.submit(job_pb2.Job(num_shots=7))
        await until_finished(jobs, job_id)
        assert jobs._jobs[job_id].job.ByteSize() == 0
    finally:
        await jobs.close()


async def test_wait_then_results_over_real_grpc_for_a_job_larger_than_the_window():
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    run, _ = runner_of(70)
    jobs = JobManager(run, validator, max_concurrent_jobs=1)
    addr = f"127.0.0.1:{_free_port()}"
    server = await serve(addr, jobs, pb.DescribeDeviceResponse())

    def wait_then_fetch() -> tuple[int, list[int]]:
        with QcssClient(addr) as c:
            job_id, _ = c.submit(job_pb2.Job(num_shots=1))
            st = c.wait(job_id, poll_s=0.01, timeout_s=10)
            return st.state, [chunk.sequence_number for chunk in c.results(job_id)]
    try:
        state, seqs = await asyncio.to_thread(wait_then_fetch)
        assert state == COMPLETED
        assert seqs == list(range(1, 71))
    finally:
        await server.stop(None)
        await jobs.close()
