"""QcssExecutionDriver: Quark's ExecutionDriver for a QCSS-compatible control stack (HLD §5.7).

submit(NativeJob)  live calibration -> lab translator -> qcss.v1.Job pinned to the plan's epoch -> SubmitJob
status(handle)     GetJobStatus mapped to Quark's lifecycle states
result(handle)     waits for a terminal state, streams every chunk (resuming on drops), returns counts
cancel(handle)     CancelJob
preview(job)       the pulse schedule the lab translator would submit (ADR-0055 approval view)

Every gRPC failure becomes a DriverError the Scheduler can act on (see errors.py).
"""
from __future__ import annotations

import datetime
import time
from collections import Counter
from typing import Any

import numpy as np

from qcss.client import QcssClient, QcssRpcError
from qcss.core.ndarray import from_proto
from qcss.v1 import job_pb2, result_pb2
from quark_qcss.contracts import Handle, JobStatus, NativeJob, RawResult
from quark_qcss.errors import PermanentDriverError, StaleCalibrationError, classify
from quark_qcss.lab.translator import Translator, UnsupportedProgramError

_STATUS = {
    result_pb2.JOB_STATE_QUEUED: JobStatus.DISPATCHED, result_pb2.JOB_STATE_VALIDATING: JobStatus.DISPATCHED,
    result_pb2.JOB_STATE_RUNNING: JobStatus.RUNNING, result_pb2.JOB_STATE_COMPLETED: JobStatus.COMPLETED,
    result_pb2.JOB_STATE_FAILED: JobStatus.FAILED, result_pb2.JOB_STATE_REJECTED: JobStatus.FAILED,
    result_pb2.JOB_STATE_CANCELLED: JobStatus.CANCELLED,
}


class QcssExecutionDriver:
    def __init__(self, client: QcssClient, translator: Translator, *,
                 tier: int = job_pb2.FIDELITY_TIER_AUTO, result_timeout_s: float = 3600.0) -> None:
        self.client = client
        self.translator = translator
        self.tier = tier
        self.result_timeout_s = result_timeout_s

    def _translate(self, job: NativeJob):
        try:
            snap = self.client.get_calibration()
        except QcssRpcError as err:
            raise classify(err) from None
        if job.calibration_epoch is not None and job.calibration_epoch != snap.calibration_epoch:
            raise StaleCalibrationError(f"plan used calibration epoch {job.calibration_epoch}, the control stack "
                                        f"is at {snap.calibration_epoch}", code="CALIBRATION_EPOCH")
        try:
            return self.translator.translate(job.program, snap, shots=job.shots, seed=job.seed,
                                             expected_epoch=snap.calibration_epoch, job_key=job.job_id,
                                             tier=self.tier)
        except UnsupportedProgramError as err:
            raise PermanentDriverError(str(err), code="UNSUPPORTED_PROGRAM") from None

    def submit(self, job: NativeJob) -> Handle:
        t = self._translate(job)
        try:
            backend_id, epoch = self.client.submit(t.job, quark_job_id=job.job_id)
        except QcssRpcError as err:
            raise classify(err) from None
        return Handle(job_id=job.job_id, backend_job_id=backend_id, calibration_epoch=epoch, clbits=t.clbits,
                      submitted_at=datetime.datetime.now(datetime.UTC))

    def status(self, handle: Handle) -> JobStatus:
        try:
            return _STATUS[self.client.status(handle.backend_job_id).state]
        except QcssRpcError as err:
            raise classify(err) from None

    def result(self, handle: Handle) -> RawResult:
        t0 = time.monotonic()
        try:
            st = self.client.wait(handle.backend_job_id, timeout_s=self.result_timeout_s)
            if st.state != result_pb2.JOB_STATE_COMPLETED:
                raise PermanentDriverError(f"job {handle.backend_job_id} ended {result_pb2.JobState.Name(st.state)}"
                                           + (f": {st.message}" if st.message else ""), code="JOB_NOT_COMPLETED")
            chunks = list(self.client.results(handle.backend_job_id))
        except QcssRpcError as err:
            raise classify(err) from None
        except TimeoutError as err:
            raise PermanentDriverError(str(err), code="RESULT_TIMEOUT") from None
        counts = _bit_counts(chunks, handle.clbits)
        return RawResult(counts=counts, shots=sum(counts.values()), executed_as_submitted=True,
                         calibration_epoch=handle.calibration_epoch,
                         backend={"backend_job_id": handle.backend_job_id,
                                  "tier_used": job_pb2.FidelityTier.Name(st.tier_used),
                                  "warnings": sorted({w for c in chunks for w in c.warnings})},
                         timings={"result_wait_s": time.monotonic() - t0})

    def cancel(self, handle: Handle) -> None:
        try:
            self.client.cancel(handle.backend_job_id)
        except QcssRpcError as err:
            raise classify(err) from None

    def preview(self, job: NativeJob) -> list[dict[str, Any]]:
        return self._translate(job).schedule

    def health(self) -> bool:
        try:
            return self.client.health()
        except QcssRpcError as err:
            raise classify(err) from None


def _bit_counts(chunks: list[result_pb2.ResultChunk], clbits: list[str]) -> dict[str, int]:
    """Counts over every declared bit, last bit leftmost; a bit the program never measured reads 0."""
    total: Counter[str] = Counter()
    for c in chunks:
        n = c.num_shots_in_chunk
        states = {a.result_key: np.asarray(from_proto(a.states)).astype(int) for a in c.acquisitions}
        cols = [states[b].astype(str) if b in states else np.full(n, "0") for b in reversed(clbits)]
        total.update("".join(bits) for bits in zip(*cols, strict=True))
    return dict(total)
