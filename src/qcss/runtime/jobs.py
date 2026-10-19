"""JobManager: state machine, priority dispatch, bounded per-job result queues, cancellation.

The heavy work (compile + simulate) runs in a persistent process pool; this module only
orchestrates. `runner` is injected so tests can use a fake runner or real worker pool.
"""
from __future__ import annotations

import asyncio
import itertools
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from google.protobuf.timestamp_pb2 import Timestamp

from qcss.v1 import job_pb2, result_pb2

# Runner signature: yields ResultChunk objects and checks cancel event between chunks.
Runner = Callable[[str, job_pb2.Job, asyncio.Event], AsyncIterator[result_pb2.ResultChunk]]
# Validator: raises HardwareValidationError / TierRoutingError / CalibrationEpochError, and may return an
# info object with tier_used, noise_fidelity and calibration_epoch for the job status.
Validator = Callable[[job_pb2.Job], Awaitable[Any]]


def _now() -> Timestamp:
    ts = Timestamp()
    ts.FromNanoseconds(time.time_ns())
    return ts


@dataclass
class _JobRecord:
    job_id: str
    job: job_pb2.Job
    status: result_pb2.JobStatus
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    info: Any = None
    # Every chunk is kept, so a client can reconnect and resume (StreamResults any number of times).
    # Backpressure: the producer runs at most max_buffered_chunks ahead of the furthest reader.
    chunks: list[result_pb2.ResultChunk] = field(default_factory=list)
    delivered: int = 0                    # chunks the furthest reader has taken
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)


class JobManager:
    def __init__(self, runner: Runner, validator: Validator, *,
                 max_buffered_chunks: int = 64, max_concurrent_jobs: int = 2) -> None:
        self._runner = runner
        self._validator = validator
        self._jobs: dict[str, _JobRecord] = {}
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._seq = itertools.count()             # tie-breaker: FIFO among equal priorities
        self._max_buf = max_buffered_chunks
        self._workers = [asyncio.create_task(self._dispatch_loop()) for _ in range(max_concurrent_jobs)]

    async def submit(self, job: job_pb2.Job) -> str:
        info = await self._validator(job)         # raises -> INVALID_ARGUMENT / FAILED_PRECONDITION
        job_id = uuid.uuid4().hex
        st = result_pb2.JobStatus(job_id=job_id, state=result_pb2.JOB_STATE_QUEUED, submitted_at=_now())
        if info is not None:
            st.tier_used = info.tier_used
            st.noise_fidelity = info.noise_fidelity
        rec = _JobRecord(job_id, job, st, info=info)
        self._jobs[job_id] = rec
        prio = job.priority if job.HasField("priority") else 0
        # PriorityQueue is min-first: negate so a higher priority runs sooner; seq breaks ties
        await self._queue.put((-prio, next(self._seq), job_id))
        return job_id

    def has_job(self, job_id: str) -> bool:
        return job_id in self._jobs

    def info(self, job_id: str) -> Any:
        """What the submit-time validator reported (tier, fidelity, calibration epoch), if anything."""
        return self._jobs[job_id].info

    def status(self, job_id: str) -> result_pb2.JobStatus:
        return self._jobs[job_id].status

    def cancel(self, job_id: str) -> result_pb2.JobStatus:
        rec = self._jobs[job_id]
        rec.cancel.set()
        if rec.status.state == result_pb2.JOB_STATE_QUEUED:
            self._finish(rec, result_pb2.JOB_STATE_CANCELLED, "cancelled before start")
        else:
            self._wake(rec)                       # a producer blocked on backpressure re-checks cancel
        return rec.status

    async def results(self, job_id: str) -> AsyncIterator[result_pb2.ResultChunk]:
        """All chunks of the job from the first, then live ones until it finishes."""
        rec = self._jobs[job_id]
        i = 0
        while True:
            async with rec.changed:
                await rec.changed.wait_for(lambda i=i: i < len(rec.chunks) or rec.finished.is_set())
                if i >= len(rec.chunks):
                    return
                chunk = rec.chunks[i]
                i += 1
                if i > rec.delivered:
                    rec.delivered = i
                    rec.changed.notify_all()
            yield chunk

    @staticmethod
    def _wake(rec: _JobRecord) -> None:
        async def notify() -> None:
            async with rec.changed:
                rec.changed.notify_all()
        asyncio.get_running_loop().create_task(notify())

    def _finish(self, rec: _JobRecord, state: result_pb2.JobState, msg: str = "") -> None:
        if rec.finished.is_set():
            return
        rec.status.state = state
        rec.status.message = msg
        rec.status.finished_at.CopyFrom(_now())
        rec.finished.set()
        self._wake(rec)                           # readers waiting for more chunks see the end

    async def _dispatch_loop(self) -> None:
        while True:
            try:
                _, _, job_id = await self._queue.get()
            except asyncio.CancelledError:
                break
            rec = self._jobs[job_id]
            if rec.cancel.is_set():
                continue
            rec.status.state = result_pb2.JOB_STATE_RUNNING
            rec.status.started_at.CopyFrom(_now())
            try:
                async for chunk in self._runner(job_id, rec.job, rec.cancel):
                    async with rec.changed:       # blocks when every client is slow (backpressure)
                        await rec.changed.wait_for(
                            lambda rec=rec: len(rec.chunks) - rec.delivered < self._max_buf or rec.cancel.is_set())
                        if rec.cancel.is_set():
                            break
                        rec.chunks.append(chunk)
                        rec.changed.notify_all()
                self._finish(rec, result_pb2.JOB_STATE_CANCELLED if rec.cancel.is_set()
                             else result_pb2.JOB_STATE_COMPLETED)
            except Exception as exc:              # noqa: BLE001
                self._finish(rec, result_pb2.JOB_STATE_FAILED, repr(exc))

    async def close(self) -> None:
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
