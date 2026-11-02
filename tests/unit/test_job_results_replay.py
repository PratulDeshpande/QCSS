"""JobManager keeps each job's result chunks so a client can reconnect and resume (StreamResults twice)."""
from __future__ import annotations

import asyncio

import pytest

from qcss.runtime.jobs import JobManager, ResultsEvictedError
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


async def test_only_the_newest_finished_jobs_are_retained():
    jobs = JobManager(five_chunks, validator, max_retained_jobs=2)
    try:
        ids = []
        for _ in range(3):
            ids.append(await jobs.submit(job_pb2.Job(num_shots=1)))
            await asyncio.wait_for(_drain(jobs, ids[-1]), 5)
        assert not jobs.has_job(ids[0])
        assert jobs.has_job(ids[1]) and jobs.has_job(ids[2])
    finally:
        await jobs.close()


async def test_replay_window_drops_the_oldest_chunks_beyond_the_byte_cap():
    one = result_pb2.ResultChunk(job_id="x" * 32, sequence_number=1, is_last=False).ByteSize()
    jobs = JobManager(five_chunks, validator, max_retained_bytes_per_job=2 * one + 4)
    try:
        job_id = await jobs.submit(job_pb2.Job(num_shots=1))
        assert await asyncio.wait_for(_drain(jobs, job_id), 5) == [1, 2, 3, 4, 5]
        with pytest.raises(ResultsEvictedError):
            await asyncio.wait_for(_drain(jobs, job_id), 5)
        resumed = [c.sequence_number async for c in jobs.results(job_id, resume_after_sequence=3)]
        assert resumed == [4, 5]
    finally:
        await jobs.close()


async def test_resumed_reader_does_not_count_skipped_chunks_as_delivered():
    jobs = JobManager(five_chunks, validator)
    try:
        job_id = await jobs.submit(job_pb2.Job(num_shots=1))
        assert [c.sequence_number async for c in jobs.results(job_id, resume_after_sequence=2)] == [3, 4, 5]
    finally:
        await jobs.close()


async def slow_one_chunk(job_id: str, job: job_pb2.Job, cancel: asyncio.Event):
    await asyncio.sleep(0.2)
    yield result_pb2.ResultChunk(job_id=job_id, sequence_number=1, is_last=True)


async def test_evicting_a_job_cancelled_while_queued_does_not_kill_the_worker():
    jobs = JobManager(slow_one_chunk, validator, max_concurrent_jobs=1, max_retained_jobs=1)
    try:
        await jobs.submit(job_pb2.Job(num_shots=1))                    # occupies the only worker
        queued = [await jobs.submit(job_pb2.Job(num_shots=1)) for _ in range(2)]
        for job_id in queued:                                          # finished before start; the first is evicted
            jobs.cancel(job_id)
        last = await jobs.submit(job_pb2.Job(num_shots=1))
        assert [c.sequence_number async for c in jobs.results(last)] == [1]
        assert jobs.status(last).state == result_pb2.JOB_STATE_COMPLETED
    finally:
        await jobs.close()


async def test_a_stale_calibration_epoch_at_execution_start_rejects_the_job():
    from qcss.runtime.calibration_store import CalibrationEpochError

    async def stale_at_start(job_id: str, job: job_pb2.Job, cancel: asyncio.Event):
        raise CalibrationEpochError("job expects calibration epoch 3, current is 4")
        yield  # pragma: no cover - makes this an async generator

    jobs = JobManager(stale_at_start, validator)
    try:
        job_id = await jobs.submit(job_pb2.Job(num_shots=1))
        assert await asyncio.wait_for(_drain(jobs, job_id), 5) == []
        st = jobs.status(job_id)
        assert st.state == result_pb2.JOB_STATE_REJECTED
        assert st.message.startswith("CALIBRATION_EPOCH: ")
        assert "current is 4" in st.message
    finally:
        await jobs.close()
