"""JobManager keeps each job's result chunks so a client can reconnect and resume (StreamResults twice)."""
from __future__ import annotations

import asyncio

import pytest

from qcss.runtime.jobs import JobManager
from qcss.v1 import job_pb2, result_pb2

pytestmark = pytest.mark.anyio
produced: list[int] = []


async def validator(job: job_pb2.Job) -> None:
    return None


async def five_chunks(job_id: str, job: job_pb2.Job, cancel: asyncio.Event):
    for seq in range(1, 6):
        produced.append(seq)
        yield result_pb2.ResultChunk(job_id=job_id, sequence_number=seq, is_last=seq == 5)
        await asyncio.sleep(0)


async def _drain(jobs: JobManager, job_id: str) -> list[int]:
    return [c.sequence_number async for c in jobs.results(job_id)]


async def test_a_second_reader_replays_every_chunk():
    jobs = JobManager(five_chunks, validator)
    try:
        job_id = await jobs.submit(job_pb2.Job(num_shots=1))
        assert await asyncio.wait_for(_drain(jobs, job_id), 5) == [1, 2, 3, 4, 5]
        assert await asyncio.wait_for(_drain(jobs, job_id), 5) == [1, 2, 3, 4, 5]
        assert jobs.status(job_id).state == result_pb2.JOB_STATE_COMPLETED
    finally:
        await jobs.close()


async def test_producer_runs_at_most_max_buffered_chunks_ahead_of_the_furthest_reader():
    produced.clear()
    jobs = JobManager(five_chunks, validator, max_buffered_chunks=2)
    try:
        job_id = await jobs.submit(job_pb2.Job(num_shots=1))
        await asyncio.sleep(0.1)
        assert jobs.status(job_id).state == result_pb2.JOB_STATE_RUNNING
        assert len(produced) <= 3                     # 2 buffered + the one waiting to be appended
        assert await asyncio.wait_for(_drain(jobs, job_id), 5) == [1, 2, 3, 4, 5]
    finally:
        await jobs.close()


async def test_cancel_releases_a_producer_blocked_on_a_full_buffer():
    jobs = JobManager(five_chunks, validator, max_buffered_chunks=1)
    try:
        job_id = await jobs.submit(job_pb2.Job(num_shots=1))
        await asyncio.sleep(0.05)
        jobs.cancel(job_id)
        for _ in range(100):
            if jobs.status(job_id).state == result_pb2.JOB_STATE_CANCELLED:
                break
            await asyncio.sleep(0.01)
        assert jobs.status(job_id).state == result_pb2.JOB_STATE_CANCELLED
        assert len(await asyncio.wait_for(_drain(jobs, job_id), 5)) <= 2
    finally:
        await jobs.close()
