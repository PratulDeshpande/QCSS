"""End-to-end smoke test of a QCSS server from another machine.

Run it on the client laptop:

    python scripts/remote_smoke.py --target 192.168.1.20:50051 --ca server.pem --token "$QCSS_TOKEN"

Every step prints PASS or FAIL with its time and the evidence. The exit code is 0 only if every
step passes. --report writes the same results as JSON for the test log in docs/remote-testing.md.
The jobs use qubit 0's xy_q0 and ro_q0 channels, which every shipped profile with a device has.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import platform
import sys
import time
from collections.abc import Callable
from typing import Any

import grpc

from qcss.client import QcssClient, QcssRpcError, counts
from qcss.v1 import job_pb2, result_pb2

PI_AMPLITUDE = 0.5            # a pi pulse at the default Rabi rate for a 20-sample square pulse (see README)
MIN_FRACTION = 0.8            # a pi pulse must read 1, an idle qubit 0, in at least this share of shots


def make_job(shots: int, *, amplitude: float | None = PI_AMPLITUDE, seed: int = 7) -> job_pb2.Job:
    """A square pulse of `amplitude` on q0 (none if None), then a discriminated readout under key 'q0'."""
    job = job_pb2.Job(num_shots=shots, requested_tier=job_pb2.FIDELITY_TIER_T1B_STATEVECTOR, random_seed=seed,
                      waveform_library={"pi": job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE,
                                                               length_samples=20)})
    if amplitude is not None:
        job.main.instructions.add(play=job_pb2.Play(channel_id="xy_q0", waveform_id="pi", amplitude=amplitude))
    job.main.instructions.add(start_tick=24, acquire=job_pb2.Acquire(
        channel_id="ro_q0", integration_ticks=1000, mode=job_pb2.ACQUISITION_MODE_DISCRIMINATED, result_key="q0"))
    return job


class Smoke:
    def __init__(self, client: QcssClient, token: str | None, target: str, ca: bytes | None,
                 insecure: bool = False) -> None:
        self.c, self.token, self.target, self.ca, self.insecure = client, token, target, ca, insecure
        self.steps: list[dict[str, Any]] = []

    def step(self, name: str, fn: Callable[[], str]) -> None:
        t0 = time.perf_counter()
        try:
            evidence, status = fn(), "PASS"
        except AssertionError as err:
            evidence, status = f"check failed: {err}", "FAIL"
        except QcssRpcError as err:
            evidence, status = f"unexpected {err.code.name}: {err.message}", "FAIL"
        except Exception as err:  # noqa: BLE001  (report anything, keep going)
            evidence, status = f"{type(err).__name__}: {err}", "FAIL"
        ms = (time.perf_counter() - t0) * 1e3
        self.steps.append({"step": len(self.steps) + 1, "name": name, "status": status, "ms": round(ms, 1),
                           "evidence": evidence})
        print(f"[{status}] {len(self.steps):>2}. {name:<44} {ms:9.1f} ms  {evidence}", flush=True)

    def _run(self, job: job_pb2.Job) -> tuple[result_pb2.JobStatus, list[result_pb2.ResultChunk]]:
        job_id, _ = self.c.submit(job)
        return self.c.wait(job_id, timeout_s=300), list(self.c.results(job_id))

    # ------------------------------------------------------------------ steps
    def health(self) -> str:
        assert self.c.health(), "server is not SERVING"
        return "SERVING"

    def describe(self) -> str:
        d = self.c.describe()
        ids = {ch.channel_id for ch in d.channels}
        assert {"xy_q0", "ro_q0"} <= ids, f"xy_q0/ro_q0 missing from {sorted(ids)}"
        p = self.c.properties()
        q0 = next(q for q in p.qubits if q.qubit_index == 0)
        return (f"{d.profile_name} ({d.vendor}), {len(ids)} channels; q0 T1={q0.t1_s * 1e6:.1f} us, "
                f"P(0|1)={q0.prob_meas0_prep1:.3f} [{p.source}]")

    def pi_pulse(self) -> str:
        st, chunks = self._run(make_job(500))
        assert st.state == result_pb2.JOB_STATE_COMPLETED, result_pb2.JobState.Name(st.state)
        c = counts(chunks, ["q0"])
        frac = c.get("1", 0) / max(1, sum(c.values()))
        assert sum(c.values()) == 500, f"{sum(c.values())} shots returned"
        assert frac >= MIN_FRACTION, f"P(1) = {frac:.3f} < {MIN_FRACTION}"
        return f"counts {dict(sorted(c.items()))}, P(1) = {frac:.3f}"

    def idle(self) -> str:
        st, chunks = self._run(make_job(500, amplitude=None))
        assert st.state == result_pb2.JOB_STATE_COMPLETED, result_pb2.JobState.Name(st.state)
        c = counts(chunks, ["q0"])
        frac = c.get("0", 0) / max(1, sum(c.values()))
        assert frac >= MIN_FRACTION, f"P(0) = {frac:.3f} < {MIN_FRACTION}"
        return f"counts {dict(sorted(c.items()))}, P(0) = {frac:.3f}"

    def hardware_violation(self) -> str:
        bad = make_job(10)
        bad.main.instructions[0].play.channel_id = "xy_q99"
        try:
            self.c.submit(bad)
        except QcssRpcError as err:
            assert err.code == grpc.StatusCode.INVALID_ARGUMENT, err.code.name
            assert err.field_violations, "no field violations attached"
            return f"INVALID_ARGUMENT at {err.field_violations[0][0]}"
        raise AssertionError("job on an unknown channel was accepted")

    def stale_job_epoch(self) -> str:
        job = make_job(10)
        job.expected_calibration_epoch = self.c.get_calibration().calibration_epoch + 1000
        try:
            self.c.submit(job)
        except QcssRpcError as err:
            assert err.code == grpc.StatusCode.FAILED_PRECONDITION, err.code.name
            kinds = [k for k, _, _ in err.precondition_failures]
            assert kinds == ["CALIBRATION_EPOCH"], kinds
            return "FAILED_PRECONDITION CALIBRATION_EPOCH"
        raise AssertionError("job pinned to a future calibration epoch was accepted")

    def calibration_cas(self) -> str:
        snap = self.c.get_calibration([0])
        epoch = snap.calibration_epoch
        new = self.c.update_calibration(snap, expected_epoch=epoch)       # writes back the same values
        assert new == epoch + 1, f"epoch {epoch} -> {new}"
        try:
            self.c.update_calibration(snap, expected_epoch=epoch)
        except QcssRpcError as err:
            assert err.code == grpc.StatusCode.FAILED_PRECONDITION, err.code.name
            return f"epoch {epoch} -> {new}; stale update refused"
        raise AssertionError("stale calibration update was accepted")

    def chunks_and_resume(self) -> str:
        job_id, _ = self.c.submit(make_job(5000))
        self.c.wait(job_id, timeout_s=300)
        seqs = [ch.sequence_number for ch in self.c.results(job_id)]
        assert seqs == list(range(1, len(seqs) + 1)) and len(seqs) >= 5, f"sequence numbers {seqs}"
        resumed = [ch.sequence_number for ch in self.c.results(job_id, resume_after=2)]
        assert resumed == seqs[2:], f"resume after 2 gave {resumed}"
        return f"{len(seqs)} chunks; resume after 2 -> {resumed[0]}..{resumed[-1]}"

    def cancel(self) -> str:
        job_id, _ = self.c.submit(make_job(200_000))
        self.c.cancel(job_id)
        st = self.c.wait(job_id, timeout_s=120)
        assert st.state == result_pb2.JOB_STATE_CANCELLED, result_pb2.JobState.Name(st.state)
        return "CANCELLED"

    def wrong_token(self) -> str:
        if not self.token:
            return "skipped: server reached without a token (pass --token to test authentication)"
        with QcssClient(self.target, tls_ca=self.ca, token=self.token + "-wrong", insecure=self.insecure) as bad:
            try:
                bad.describe()
            except QcssRpcError as err:
                assert err.code == grpc.StatusCode.UNAUTHENTICATED, err.code.name
                return "UNAUTHENTICATED"
        raise AssertionError("a wrong token was accepted")

    def run_all(self) -> None:
        self.step("health check", self.health)
        self.step("describe device and properties", self.describe)
        self.step("pi pulse on q0 reads 1", self.pi_pulse)
        self.step("idle q0 reads 0", self.idle)
        self.step("hardware violation -> INVALID_ARGUMENT", self.hardware_violation)
        self.step("stale job epoch -> FAILED_PRECONDITION", self.stale_job_epoch)
        self.step("calibration compare-and-swap", self.calibration_cas)
        self.step("5000 shots: chunks and resume", self.chunks_and_resume)
        self.step("cancel a long job", self.cancel)
        self.step("wrong token -> UNAUTHENTICATED", self.wrong_token)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("--target", required=True, help="host:port of the QCSS server")
    ap.add_argument("--ca", type=pathlib.Path, help="PEM certificate to trust (enables TLS)")
    ap.add_argument("--token", help="bearer token the server was started with")
    ap.add_argument("--report", type=pathlib.Path, help="write the results as JSON here")
    ap.add_argument("--insecure", action="store_true",
                    help="send the token without TLS to a non-loopback address (trusted networks only)")
    args = ap.parse_args(argv)
    ca = args.ca.read_bytes() if args.ca else None

    print(f"QCSS remote smoke test -> {args.target} ({'TLS' if ca else 'plaintext'}, "
          f"{'token' if args.token else 'no token'}) from {platform.node()}")
    try:
        client = QcssClient(args.target, tls_ca=ca, token=args.token, timeout_s=60, insecure=args.insecure)
    except ValueError as err:
        print(f"error: {err}")
        return 2
    with client:
        smoke = Smoke(client, args.token, args.target, ca, args.insecure)
        smoke.run_all()
    passed = sum(s["status"] == "PASS" for s in smoke.steps)
    print(f"\n{passed}/{len(smoke.steps)} steps passed")
    if args.report:
        args.report.write_text(json.dumps({
            "target": args.target, "tls": ca is not None, "client_host": platform.node(),
            "client_python": platform.python_version(), "time": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "steps": smoke.steps}, indent=2), encoding="utf-8")
    return 0 if passed == len(smoke.steps) else 1


if __name__ == "__main__":
    sys.exit(main())
