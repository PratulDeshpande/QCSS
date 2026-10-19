"""Synchronous client for a QCSS (or QCSS-compatible) ControlService, local or across a network.

    with QcssClient("192.168.1.20:50051", tls_ca=ca_pem, token="...") as c:
        job_id, epoch = c.submit(job)
        c.wait(job_id)
        print(counts(list(c.results(job_id)), ["q0"]))

Errors come back as QcssRpcError with the gRPC code and the decoded google.rpc.Status details
(field paths for hardware violations, precondition types such as CALIBRATION_EPOCH).
"""
from __future__ import annotations

import time
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from types import TracebackType
from typing import Any, Self

import grpc
import numpy as np
from google.rpc import error_details_pb2
from grpc_status import rpc_status

from qcss.core.ndarray import from_proto
from qcss.core.net import is_local_address
from qcss.v1 import calibration_pb2, device_pb2, job_pb2, result_pb2
from qcss.v1 import control_service_pb2 as pb
from qcss.v1 import control_service_pb2_grpc as pbg

TERMINAL_STATES = frozenset({result_pb2.JOB_STATE_COMPLETED, result_pb2.JOB_STATE_FAILED,
                             result_pb2.JOB_STATE_CANCELLED, result_pb2.JOB_STATE_REJECTED})
MAX_MESSAGE_BYTES = 16 << 20                       # matches the server's limits


class QcssRpcError(Exception):
    """A failed call, with the server's structured error details decoded."""

    def __init__(self, code: grpc.StatusCode, message: str,
                 field_violations: list[tuple[str, str]] | None = None,
                 precondition_failures: list[tuple[str, str, str]] | None = None) -> None:
        super().__init__(f"{code.name}: {message}")
        self.code = code
        self.message = message
        self.field_violations = field_violations or []                 # (field path, description)
        self.precondition_failures = precondition_failures or []       # (type, subject, description)

    @classmethod
    def from_call(cls, err: grpc.RpcError) -> QcssRpcError:
        call: grpc.Call = err  # type: ignore[assignment]   # every RpcError a stub raises is also a Call
        fields: list[tuple[str, str]] = []
        preconditions: list[tuple[str, str, str]] = []
        status = rpc_status.from_call(call)
        for detail in status.details if status is not None else ():
            br, pf = error_details_pb2.BadRequest(), error_details_pb2.PreconditionFailure()
            if detail.Unpack(br):
                fields += [(v.field, v.description) for v in br.field_violations]
            elif detail.Unpack(pf):
                preconditions += [(v.type, v.subject, v.description) for v in pf.violations]
        return cls(call.code(), call.details() or "", fields, preconditions)


class QcssClient:
    """One channel to a ControlService. Pass tls_ca (PEM) for a TLS server and token for an authenticated one.

    A token is only sent over TLS or to a loopback address, unless insecure=True.
    """

    def __init__(self, target: str, *, tls_ca: bytes | None = None, token: str | None = None,
                 timeout_s: float = 30.0, insecure: bool = False) -> None:
        if token and tls_ca is None and not insecure and not is_local_address(target):
            raise ValueError(f"refusing to send the token in cleartext to {target}; pass tls_ca (the server's "
                             "certificate) or insecure=True on a network you trust")
        options = [("grpc.max_send_message_length", MAX_MESSAGE_BYTES),
                   ("grpc.max_receive_message_length", MAX_MESSAGE_BYTES),
                   ("grpc.keepalive_time_ms", 30_000),               # >= the server's 10 s minimum ping interval
                   ("grpc.keepalive_timeout_ms", 10_000)]
        if tls_ca is not None:
            self._channel = grpc.secure_channel(target, grpc.ssl_channel_credentials(root_certificates=tls_ca),
                                                options=options)
        else:
            self._channel = grpc.insecure_channel(target, options=options)
        self._stub = pbg.ControlServiceStub(self._channel)
        self._metadata: list[tuple[str, str]] = [("authorization", f"Bearer {token}")] if token else []
        self.timeout_s = timeout_s

    # ------------------------------------------------------------------ plumbing
    def close(self) -> None:
        self._channel.close()

    def __enter__(self) -> Self:
        return self

    def __exit__(self, exc_type: type[BaseException] | None, exc: BaseException | None,
                 tb: TracebackType | None) -> None:
        self.close()

    def _md(self, quark_job_id: str | None = None) -> list[tuple[str, str]]:
        return self._metadata + ([("x-quark-job-id", quark_job_id)] if quark_job_id else [])

    def _call(self, method, request, quark_job_id: str | None = None):
        try:
            return method(request, timeout=self.timeout_s, metadata=self._md(quark_job_id))
        except grpc.RpcError as err:
            raise QcssRpcError.from_call(err) from None

    # ------------------------------------------------------------------ service
    def health(self) -> bool:
        """True when the server's gRPC health check reports SERVING (needs no token)."""
        from grpc_health.v1 import health_pb2, health_pb2_grpc
        try:
            stub: Any = health_pb2_grpc.HealthStub(self._channel)     # the generated stub is untyped
            r = stub.Check(health_pb2.HealthCheckRequest(service=""), timeout=self.timeout_s)
        except grpc.RpcError as err:
            raise QcssRpcError.from_call(err) from None
        return r.status == health_pb2.HealthCheckResponse.SERVING

    def describe(self) -> device_pb2.DeviceDescription:
        return self._call(self._stub.DescribeDevice, pb.DescribeDeviceRequest()).device

    def properties(self) -> device_pb2.DeviceProperties:
        return self._call(self._stub.GetDeviceProperties, pb.GetDevicePropertiesRequest()).properties

    def submit(self, job: job_pb2.Job, *, quark_job_id: str | None = None) -> tuple[str, int]:
        """Validate and queue a job; returns (job_id, calibration epoch it will run under)."""
        r = self._call(self._stub.SubmitJob, pb.SubmitJobRequest(job=job), quark_job_id)
        return r.job_id, r.calibration_epoch

    def status(self, job_id: str) -> result_pb2.JobStatus:
        return self._call(self._stub.GetJobStatus, pb.GetJobStatusRequest(job_id=job_id)).status

    def wait(self, job_id: str, *, poll_s: float = 0.2, timeout_s: float | None = None) -> result_pb2.JobStatus:
        """Poll until the job reaches a terminal state (COMPLETED, FAILED, CANCELLED or REJECTED)."""
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while True:
            st = self.status(job_id)
            if st.state in TERMINAL_STATES:
                return st
            if deadline is not None and time.monotonic() > deadline:
                raise TimeoutError(f"job {job_id} still {result_pb2.JobState.Name(st.state)} after {timeout_s} s")
            time.sleep(poll_s)

    def results(self, job_id: str, *, resume_after: int = 0, reconnects: int = 3) -> Iterator[result_pb2.ResultChunk]:
        """Every result chunk after `resume_after`, reconnecting from the last sequence number if the link drops."""
        last = resume_after
        while True:
            try:
                for m in self._stub.StreamResults(pb.StreamResultsRequest(job_id=job_id, resume_after_sequence=last),
                                                  metadata=self._md()):
                    last = m.chunk.sequence_number
                    yield m.chunk
                return
            except grpc.RpcError as err:
                if err.code() != grpc.StatusCode.UNAVAILABLE or reconnects <= 0:  # type: ignore[attr-defined]
                    raise QcssRpcError.from_call(err) from None
                reconnects -= 1
                time.sleep(0.5)

    def cancel(self, job_id: str) -> result_pb2.JobStatus:
        return self._call(self._stub.CancelJob, pb.CancelJobRequest(job_id=job_id)).status

    def get_calibration(self, qubits: Iterable[int] = ()) -> calibration_pb2.CalibrationSnapshot:
        return self._call(self._stub.GetCalibration, pb.GetCalibrationRequest(qubit_indices=list(qubits))).snapshot

    def update_calibration(self, snapshot: calibration_pb2.CalibrationSnapshot, expected_epoch: int) -> int:
        """Compare-and-swap: succeeds only if expected_epoch is current; returns the new epoch."""
        r = self._call(self._stub.UpdateCalibration,
                       pb.UpdateCalibrationRequest(snapshot=snapshot, expected_epoch=expected_epoch))
        return r.new_epoch


def counts(chunks: Iterable[result_pb2.ResultChunk], keys: Sequence[str] | None = None) -> dict[str, int]:
    """Bitstring counts over all shots. keys[0] is the rightmost bit (OpenQASM/Qiskit order); default: sorted keys.

    Each key contributes its discriminated state per shot; a state of 2 (leakage) prints as '2'.
    """
    total: Counter[str] = Counter()
    for c in chunks:
        states = {a.result_key: from_proto(a.states) for a in c.acquisitions if a.HasField("states")}
        ks = list(keys) if keys is not None else sorted(states)
        if not ks or c.num_shots_in_chunk == 0:
            continue
        cols = [np.asarray(states[k]).astype(int).astype(str) for k in reversed(ks)]
        total.update("".join(bits) for bits in zip(*cols, strict=True))
    return dict(total)
