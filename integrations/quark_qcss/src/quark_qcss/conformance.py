"""Driver/HAL conformance checks per maturity level (HLD §5.7; week 5-6 checkpoint of Appendix C).

The same checks run against QCSS now and against a lab's control-stack gateway later:

    python -m quark_qcss.conformance --target 192.168.1.20:50051 --ca server.pem --token "$QCSS_TOKEN" \
        --profile lab_examples/qcss_transmon_5q/device_profile.yaml \
        --pulse-library lab_examples/qcss_transmon_5q/pulse_library.yaml

L1  describe() is well formed; calibration events cover every site; a second poll only reports changes
L3  submit -> status -> result round trip; x reads 1, idle reads 0, sx.sx = x, sx.rz(pi).sx = identity;
    gates and readout on two qubits at once; unsupported programs are refused before submission; cancel
L4  health; a stale calibration epoch is classified for re-planning; request_calibration answers
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from quark_qcss.contracts import JobStatus, NativeJob
from quark_qcss.driver import QcssExecutionDriver
from quark_qcss.errors import PermanentDriverError, StaleCalibrationError
from quark_qcss.provider import QcssDeviceProvider

MIN_FRACTION = 0.8
REQUIRED_QUBIT_PARAMETERS = ("t1", "t2_star", "readout_p0_given_1", "readout_p1_given_0", "1q_error")


@dataclass
class Check:
    level: str
    name: str
    passed: bool
    detail: str
    ms: float = 0.0


def run_conformance(provider: QcssDeviceProvider, driver: QcssExecutionDriver, *, shots: int = 200,
                    levels: tuple[str, ...] = ("L1", "L3", "L4")) -> list[Check]:
    checks: list[Check] = []

    def check(level: str, name: str, fn: Callable[[], str]) -> None:
        if level not in levels:
            return
        t0 = time.perf_counter()
        try:
            detail, ok = fn(), True
        except AssertionError as err:
            detail, ok = str(err), False
        except Exception as err:  # noqa: BLE001  (a conformance run reports every failure)
            detail, ok = f"{type(err).__name__}: {err}", False
        checks.append(Check(level, name, ok, detail, (time.perf_counter() - t0) * 1e3))

    desc = provider.describe()
    site_ids = [s["id"] for s in desc.sites]

    def run(program: str, n: int = shots) -> dict[str, int]:
        return driver.result(driver.submit(NativeJob(job_id="conformance", program=program, shots=n, seed=1))).counts

    def frac(counts: dict[str, int], key: str) -> float:
        return counts.get(key, 0) / max(1, sum(counts.values()))

    # ------------------------------------------------------------------ L1
    def l1_describe() -> str:
        assert site_ids, "no sites offered by the control stack"
        assert desc.native_ops, "profile declares no native operations"
        if desc.coupling != "all_to_all":
            bad = [p for p in desc.coupling if not set(p) <= set(site_ids)]
            assert not bad, f"coupling refers to unknown sites {bad}"
        assert "submission_level" in desc.capabilities, "capabilities.submission_level missing (ADR-0054)"
        return f"{desc.device_id}: {len(site_ids)} sites, {len(desc.native_ops)} native ops, {desc.maturity_level}"

    def l1_calibration() -> str:
        events = provider.poll_once()
        have = {(e.resource, e.parameter) for e in events}
        missing = [(f"q{q}", p) for q in site_ids for p in REQUIRED_QUBIT_PARAMETERS if (f"q{q}", p) not in have]
        assert not missing, f"missing calibration events {missing[:5]}"
        assert all(e.measured_at.tzinfo is not None for e in events), "measured_at must be timezone-aware"
        flagged = [(e.resource, e.parameter) for e in events if e.quality_flags]
        return f"{len(events)} events" + (f", {len(flagged)} flagged" if flagged else "")

    def l1_changes_only() -> str:
        before = dict(provider._last)
        events = provider.poll_once()
        repeats = [(e.resource, e.parameter) for e in events if before.get((e.resource, e.parameter)) == e.value]
        assert not repeats, f"unchanged values re-reported {repeats[:5]}"
        return f"{len(events)} changed values on the second poll"

    check("L1", "describe", l1_describe)
    check("L1", "calibration events cover every site", l1_calibration)
    check("L1", "second poll reports changes only", l1_changes_only)

    # ------------------------------------------------------------------ L3
    q = site_ids[0] if site_ids else 0
    header = "OPENQASM 3.0;\nbit[1] c;\n"

    def l3_x() -> str:
        c = run(header + f"x ${q};\nc[0] = measure ${q};")
        assert frac(c, "1") >= MIN_FRACTION, f"x then measure: {c}"
        return f"x: {c}"

    def l3_idle() -> str:
        c = run(header + f"c[0] = measure ${q};")
        assert frac(c, "0") >= MIN_FRACTION, f"idle measure: {c}"
        return f"idle: {c}"

    def l3_virtual_z() -> str:
        c1 = run(header + f"sx ${q};\nsx ${q};\nc[0] = measure ${q};")
        c2 = run(header + f"sx ${q};\nrz(pi) ${q};\nsx ${q};\nc[0] = measure ${q};")
        assert frac(c1, "1") >= MIN_FRACTION, f"sx.sx should read 1: {c1}"
        assert frac(c2, "0") >= MIN_FRACTION, f"sx.rz(pi).sx should read 0: {c2}"
        return f"sx.sx {c1}; sx.rz(pi).sx {c2}"

    def l3_two_qubits() -> str:
        if len(site_ids) < 2:
            return "skipped: fewer than two sites"
        a, b = site_ids[0], site_ids[1]
        c = run(f"OPENQASM 3.0;\nbit[2] c;\nrz(0.3) ${a};\nrz(0.3) ${b};\nx ${a};\nx ${b};\n"
                f"c[0] = measure ${a};\nc[1] = measure ${b};")
        assert frac(c, "11") >= MIN_FRACTION * MIN_FRACTION, f"x on two qubits should read 11: {c}"
        return f"x on q{a}, q{b}: {c}"

    def l3_refuse() -> str:
        try:
            driver.submit(NativeJob(job_id="conformance", program="h $0;", shots=1))
        except PermanentDriverError as err:
            assert not err.counts_toward_breaker, "a bad program must not count toward the circuit breaker"
            return f"refused: {err}"
        raise AssertionError("a non-native gate was accepted")

    def l3_cancel() -> str:
        h = driver.submit(NativeJob(job_id="conformance", program=header + f"c[0] = measure ${q};", shots=200_000))
        driver.cancel(h)
        st = driver.status(h)
        for _ in range(600):
            st = driver.status(h)
            if st in (JobStatus.CANCELLED, JobStatus.COMPLETED, JobStatus.FAILED):
                break
            time.sleep(0.1)
        assert st is JobStatus.CANCELLED, f"status after cancel: {st}"
        return "CANCELLED"

    check("L3", "x reads 1", l3_x)
    check("L3", "idle reads 0", l3_idle)
    check("L3", "virtual Z (sx.rz(pi).sx)", l3_virtual_z)
    check("L3", "simultaneous gates and readout on two qubits", l3_two_qubits)
    check("L3", "non-native program refused", l3_refuse)
    check("L3", "cancel", l3_cancel)

    # ------------------------------------------------------------------ L4
    def l4_health() -> str:
        assert driver.health(), "control stack is not SERVING"
        return "SERVING"

    def l4_stale() -> str:
        live = driver.client.get_calibration().calibration_epoch
        try:
            driver.submit(NativeJob(job_id="conformance", program=header + f"x ${q};", shots=1,
                                    calibration_epoch=live + 1000))
        except StaleCalibrationError:
            return "stale plan -> StaleCalibrationError (re-plan)"
        raise AssertionError("a plan made against a different calibration epoch was accepted")

    def l4_request_calibration() -> str:
        ack = provider.request_calibration(f"q{q}")
        return f"accepted={ack.accepted}: {ack.reason}"

    check("L4", "health", l4_health)
    check("L4", "stale calibration epoch", l4_stale)
    check("L4", "request_calibration answers", l4_request_calibration)
    return checks


def main(argv: list[str] | None = None) -> int:
    from qcss.client import QcssClient
    from quark_qcss.lab.pulse_library import load_pulse_library
    from quark_qcss.lab.translator import Translator

    ap = argparse.ArgumentParser(description="Run the Quark driver/HAL conformance checks against a control stack.")
    ap.add_argument("--target", required=True)
    ap.add_argument("--ca", type=pathlib.Path)
    ap.add_argument("--token")
    ap.add_argument("--insecure", action="store_true")
    ap.add_argument("--profile", type=pathlib.Path, required=True, help="Quark device profile YAML")
    ap.add_argument("--pulse-library", type=pathlib.Path, required=True, help="lab pulse library YAML")
    ap.add_argument("--shots", type=int, default=200)
    args = ap.parse_args(argv)
    with QcssClient(args.target, tls_ca=args.ca.read_bytes() if args.ca else None, token=args.token,
                    insecure=args.insecure, timeout_s=60) as client:
        checks = run_conformance(QcssDeviceProvider(client, args.profile),
                                 QcssExecutionDriver(client, Translator(load_pulse_library(args.pulse_library))),
                                 shots=args.shots)
    for c in checks:
        print(f"[{'PASS' if c.passed else 'FAIL'}] {c.level} {c.name:<46} {c.ms:8.1f} ms  {c.detail}")
    passed = sum(c.passed for c in checks)
    print(f"\n{passed}/{len(checks)} checks passed")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
