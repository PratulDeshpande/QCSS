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
    results: asyncio.Queue                # bounded -> backpressure on the producer
    cancel: asyncio.Event = field(default_factory=asyncio.Event)
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    info: Any = None


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
        rec = _JobRecord(job_id, job, st, asyncio.Queue(maxsize=self._max_buf), info=info)
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
        return rec.status

    async def results(self, job_id: str) -> AsyncIterator[result_pb2.ResultChunk]:
        rec = self._jobs[job_id]
        while True:
            chunk = await rec.results.get()
            if chunk is None:
                return
            yield chunk

    def _finish(self, rec: _JobRecord, state: int, msg: str = "") -> None:
        if rec.finished.is_set():
            return
        rec.status.state = state
        rec.status.message = msg
        rec.status.finished_at.CopyFrom(_now())
        rec.finished.set()
        try:
            rec.results.put_nowait(None)          # end-of-stream sentinel
        except asyncio.QueueFull:
            asyncio.get_running_loop().create_task(rec.results.put(None))

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
                    await rec.results.put(chunk)  # blocks when client is slow (backpressure)
                    if rec.cancel.is_set():
                        break
                self._finish(rec, result_pb2.JOB_STATE_CANCELLED if rec.cancel.is_set()
                             else result_pb2.JOB_STATE_COMPLETED)
            except Exception as exc:              # noqa: BLE001
                self._finish(rec, result_pb2.JOB_STATE_FAILED, repr(exc))

    async def close(self) -> None:
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
