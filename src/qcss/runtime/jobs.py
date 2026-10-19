"""JobManager: state machine, priority dispatch, replayable bounded per-job results, cancellation.

The heavy work (compile + simulate) runs in a persistent process pool; this module only
orchestrates. `runner` is injected so tests can use a fake runner or real worker pool.
"""
from __future__ import annotations

import asyncio
import collections
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


class ResultsEvictedError(LookupError):
    """The chunks a reader asked for were dropped from the job's replay window (resume from later)."""


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
    # Chunks are kept so a client can reconnect and resume (StreamResults any number of times).
    # Backpressure: the producer runs at most max_buffered_chunks ahead of the furthest reader.
    # Memory: once the retained bytes exceed the per-job cap, chunks every reader has passed are
    # dropped from the front; `first` is the absolute index of chunks[0] (sequence number - 1).
    chunks: collections.deque[result_pb2.ResultChunk] = field(default_factory=collections.deque)
    first: int = 0
    retained_bytes: int = 0
    delivered: int = 0                    # absolute count of chunks the furthest reader has taken
    changed: asyncio.Condition = field(default_factory=asyncio.Condition)


class JobManager:
    def __init__(self, runner: Runner, validator: Validator, *,
                 max_buffered_chunks: int = 64, max_concurrent_jobs: int = 2,
                 max_retained_jobs: int = 256, max_retained_bytes_per_job: int = 256 << 20) -> None:
        self._runner = runner
        self._validator = validator
        self._jobs: dict[str, _JobRecord] = {}
        self._queue: asyncio.PriorityQueue = asyncio.PriorityQueue()
        self._seq = itertools.count()             # tie-breaker: FIFO among equal priorities
        self._max_buf = max_buffered_chunks
        self._max_jobs = max_retained_jobs
        self._max_bytes = max_retained_bytes_per_job
        self._finished_order: collections.deque[str] = collections.deque()   # oldest finished job first
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

    async def results(self, job_id: str, resume_after_sequence: int = 0) -> AsyncIterator[result_pb2.ResultChunk]:
        """The job's chunks with sequence number > resume_after_sequence, then live ones until it finishes.

        Raises ResultsEvictedError if some of those chunks were already dropped from the replay window.
        """
        rec = self._jobs[job_id]
        i = resume_after_sequence                 # absolute index of the next chunk (sequence numbers are 1, 2, ...)
        while True:
            async with rec.changed:
                await rec.changed.wait_for(
                    lambda i=i: i < rec.first + len(rec.chunks) or rec.finished.is_set())
                if i < rec.first:
                    raise ResultsEvictedError(f"job {job_id}: chunks up to sequence {rec.first} are no longer "
                                              f"retained; resume after sequence {rec.first} or later")
                if i >= rec.first + len(rec.chunks):
                    return
                chunk = rec.chunks[i - rec.first]
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
        self._finished_order.append(rec.job_id)
        while len(self._finished_order) > self._max_jobs:
            self._jobs.pop(self._finished_order.popleft(), None)

    async def _dispatch_loop(self) -> None:
        while True:
            try:
                _, _, job_id = await self._queue.get()
            except asyncio.CancelledError:
                break
            rec = self._jobs.get(job_id)          # a job cancelled while queued may already be evicted
            if rec is None or rec.cancel.is_set() or rec.finished.is_set():
                continue
            rec.status.state = result_pb2.JOB_STATE_RUNNING
            rec.status.started_at.CopyFrom(_now())
            try:
                async for chunk in self._runner(job_id, rec.job, rec.cancel):
                    async with rec.changed:       # blocks when every client is slow (backpressure)
                        await rec.changed.wait_for(
                            lambda rec=rec: rec.first + len(rec.chunks) - rec.delivered < self._max_buf
                            or rec.cancel.is_set())
                        if rec.cancel.is_set():
                            break
                        rec.chunks.append(chunk)
                        rec.retained_bytes += chunk.ByteSize()
                        while rec.retained_bytes > self._max_bytes and rec.first < rec.delivered:
                            rec.retained_bytes -= rec.chunks.popleft().ByteSize()
                            rec.first += 1
                        rec.changed.notify_all()
                self._finish(rec, result_pb2.JOB_STATE_CANCELLED if rec.cancel.is_set()
                             else result_pb2.JOB_STATE_COMPLETED)
            except Exception as exc:              # noqa: BLE001
                self._finish(rec, result_pb2.JOB_STATE_FAILED, repr(exc))

    async def close(self) -> None:
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
