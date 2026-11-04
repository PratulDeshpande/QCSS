"""Lab Bench: experiments over the lab link, exactly as a lab client sees the instrument.

Jobs are built from what a client may know: the hardware profile and the calibration it reads over the lab link.
The device truth is never consulted here, so the Lab Bench shows what Quark would see, and the Admin view shows the
ground truth next to it.
"""
from __future__ import annotations

import threading
import time
from typing import Any

from google.protobuf import json_format

from qcss.client import QcssRpcError
from qcss.config.profile import HardwareProfile
from qcss.runtime.calibration_store import CalibrationStore
from qcss.runtime.runner import SimulationContext
from qcss.v1 import calibration_pb2, result_pb2
from qcss_dashboard.admin import LinkError, Links, to_dict
from qcss_dashboard.experiments import EXPERIMENTS, build_job, summarize

MAX_JOBS = 200


class LabBench:
    def __init__(self, links: Links) -> None:
        self.links = links
        self.jobs: list[dict[str, Any]] = []
        self._lock = threading.Lock()

    def describe(self) -> dict[str, Any]:
        try:
            with self.links.lab() as c:
                return to_dict(c.describe())
        except QcssRpcError as exc:
            raise LinkError.from_rpc(exc) from exc

    def calibration(self) -> dict[str, Any]:
        try:
            with self.links.lab() as c:
                return to_dict(c.get_calibration())
        except QcssRpcError as exc:
            raise LinkError.from_rpc(exc) from exc

    def update_calibration(self, snapshot: dict[str, Any], expected_epoch: int) -> dict[str, Any]:
        snap = json_format.ParseDict(snapshot, calibration_pb2.CalibrationSnapshot(), ignore_unknown_fields=False)
        try:
            with self.links.lab() as c:
                return {"new_epoch": c.update_calibration(snap, expected_epoch)}
        except QcssRpcError as exc:
            raise LinkError.from_rpc(exc) from exc

    def _record(self, entry: dict[str, Any]) -> None:
        with self._lock:
            self.jobs.append(entry)
            del self.jobs[:-MAX_JOBS]

    def run_experiment(self, profile: HardwareProfile, body: dict[str, Any]) -> dict[str, Any]:
        kind = str(body.get("kind", ""))
        if kind not in EXPERIMENTS:
            raise LinkError(f"unknown experiment '{kind}'", 400)
        qubit = int(body.get("qubit", 0))
        params = {k: body[k] for k in ("pi_amplitude", "max_delay_us", "span_mhz", "detuning_mhz")
                  if body.get(k) is not None}
        try:
            with self.links.lab(timeout_s=60.0) as c:
                snap = c.get_calibration()
                ctx = SimulationContext(profile, None, calibration=CalibrationStore(snap))   # no device: no truth
                job, axis = build_job(kind, ctx, qubit=qubit, points=int(body.get("points", 21)),
                                      shots=int(body.get("shots", 500)), tier=str(body.get("tier", "AUTO")),
                                      **params)
                t0 = time.perf_counter()
                job_id, epoch = c.submit(job)
                entry = {"job_id": job_id, "kind": kind, "qubit": qubit, "submitted": time.time(),
                         "state": "JOB_STATE_QUEUED", "calibration_epoch": epoch}
                self._record(entry)
                status = c.wait(job_id, timeout_s=float(body.get("timeout_s", 900.0)))
                entry["state"] = result_pb2.JobState.Name(status.state)
                entry["message"] = status.message
                entry["elapsed_s"] = time.perf_counter() - t0
                if status.state != result_pb2.JOB_STATE_COMPLETED:
                    raise LinkError(f"job {job_id} {entry['state']}: {status.message}", 409,
                                    {"job_id": job_id, "state": entry["state"]})
                chunks = list(c.results(job_id))
        except QcssRpcError as exc:
            raise LinkError.from_rpc(exc) from exc
        out = summarize(kind, chunks, qubit, axis)
        out.update({"source": "lab", "job_id": job_id, "calibration_epoch": epoch, "elapsed_s": entry["elapsed_s"],
                    "shots": job.num_shots, "job": json_format.MessageToDict(job)})
        return out

    def list_jobs(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self.jobs)
