"""QcssController: the Qibolab driver of a QCSS instrument.

Like every Qibolab instrument driver it connects to the box at its address, programs it
from the platform's configs and plays sequences; it never decides physics or calibration.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import grpc
from pydantic import PrivateAttr
from qibolab import ExecutionParameters, PulseSequence
from qibolab._core.instruments.abstract import Controller  # Qibolab 0.2.17 keeps the base class here

from qcss.client import QcssClient, QcssRpcError
from qcss.v1 import calibration_pb2, result_pb2
from qcss_qibolab.translate import assemble, translate


class QcssController(Controller):
    token_env: str | None = "QCSS_TOKEN"      # name of the environment variable holding the instrument token
    ca_file: str | None = None                # PEM to trust (enables TLS)
    timeout_s: float = 3600.0

    _client: QcssClient | None = PrivateAttr(default=None)
    _los: dict[str, float] = PrivateAttr(default_factory=dict)
    _tick_per_ns: float = PrivateAttr(default=1.0)
    _sampling_rate: float = PrivateAttr(default=1.0)

    @property
    def sampling_rate(self) -> float:
        return self._sampling_rate

    def connect(self) -> None:
        if self._client is not None:
            return
        token = os.environ.get(self.token_env) if self.token_env else None
        ca = Path(self.ca_file).read_bytes() if self.ca_file else None
        client = QcssClient(self.address, tls_ca=ca, token=token, timeout_s=60.0)
        desc = self._call(client.describe)
        self._client = client
        self._los = {c.channel_id: c.lo_frequency_hz for c in desc.channels}
        self._tick_per_ns = float(desc.tick_hz) / 1e9
        rates = [c.sample_rate_hz for c in desc.channels if c.sample_rate_hz]
        self._sampling_rate = max(rates) / 1e9 if rates else 1.0

    def disconnect(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def play(self, configs: dict[str, Any], sequences: list[PulseSequence], options: ExecutionParameters,
             sweepers: list[Any]) -> dict[Any, Any]:
        client = self._client
        if client is None:
            raise RuntimeError(f"{self.signature}: not connected")
        out: dict[Any, Any] = {}
        for seq in sequences:
            tr = translate(seq, configs, options, sweepers, los=self._los, tick_per_ns=self._tick_per_ns,
                           sampling_rate=self._sampling_rate)
            # pin the job to the settings just uploaded: if another client reprograms the instrument
            # before it runs, it is refused (and resubmitted) rather than run with someone else's settings
            tr.job.expected_calibration_epoch = self._program(client, tr.calibration)
            job_id, _ = self._call(client.submit, tr.job)
            st = self._call(client.wait, job_id, timeout_s=self.timeout_s)
            if st.state != result_pb2.JOB_STATE_COMPLETED:
                raise RuntimeError(f"{self.signature}: job {job_id} ended "
                                   f"{result_pb2.JobState.Name(st.state).removeprefix('JOB_STATE_')}: {st.message}")
            out |= assemble(self._call(_all_chunks, client, job_id), tr, options)
        return out

    def _program(self, client: QcssClient, settings: calibration_pb2.CalibrationSnapshot) -> int:
        """Write the platform's settings into the instrument, keeping what they do not cover."""
        current = self._call(client.get_calibration)
        by_q = {qc.qubit_index: qc for qc in current.qubits}
        upload = calibration_pb2.CalibrationSnapshot()
        for qc in settings.qubits:
            merged = upload.qubits.add()
            if qc.qubit_index in by_q:
                merged.CopyFrom(by_q[qc.qubit_index])
            merged.MergeFrom(qc)
            merged.readout_rotation_rad, merged.readout_threshold = qc.readout_rotation_rad, qc.readout_threshold
        return int(self._call(client.update_calibration, upload, current.calibration_epoch))

    def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except QcssRpcError as err:
            kind = ConnectionError if err.code is grpc.StatusCode.UNAVAILABLE else RuntimeError
            raise kind(f"{self.signature}: {err.code.name}: {err.message}") from err


def _all_chunks(client: QcssClient, job_id: str) -> list[result_pb2.ResultChunk]:
    return list(client.results(job_id))
