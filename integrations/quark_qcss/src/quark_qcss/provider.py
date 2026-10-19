"""QcssDeviceProvider: Quark's HAL for a QCSS-compatible control stack (HLD §5.7, DeviceProvider).

describe()            device profile YAML (static) + DescribeDevice (dynamic)          -> DeviceDescription
calibration_stream()  GetDeviceProperties + GetCalibration, polled; changed values only -> CalibrationEvent
request_calibration() not offered: QCSS calibrates only through UpdateCalibration       -> Ack(accepted=False)
"""
from __future__ import annotations

import datetime
import hashlib
import pathlib
import threading
from collections.abc import Iterator
from typing import Any

import yaml

from qcss.client import QcssClient, QcssRpcError
from quark_qcss.contracts import Ack, CalibrationEvent, DeviceDescription, NativeOp
from quark_qcss.errors import classify

ADAPTER = "qcss@v1"

# (parameter, unit, proto field, physical bounds) for each QubitProperties value Quark's predictor uses.
QUBIT_PARAMETERS = (
    ("frequency", "Hz", "frequency_hz", (1e9, 20e9)),
    ("t1", "s", "t1_s", (1e-7, 1.0)),
    ("t2_star", "s", "t2_star_s", (1e-8, 1.0)),
    ("readout_p1_given_0", "", "prob_meas1_prep0", (0.0, 0.5)),
    ("readout_p0_given_1", "", "prob_meas0_prep1", (0.0, 0.5)),
    ("1q_error", "", "single_qubit_gate_error", (0.0, 0.5)),
    ("1q_duration", "s", "single_qubit_gate_duration_s", (0.0, 1e-5)),
    ("readout_duration", "s", "readout_duration_s", (0.0, 1e-3)),
)
PAIR_PARAMETERS = (
    ("2q_error", "", "two_qubit_gate_error", (0.0, 0.5)),
    ("2q_duration", "s", "two_qubit_gate_duration_s", (0.0, 1e-5)),
    ("coupling", "Hz", "coupling_hz", (0.0, 1e9)),
)
# Pulse-level calibration the lab owns; kept as custom.* so nothing is lost (HLD §12).
CUSTOM_QUBIT_FIELDS = ("drive_frequency_hz", "readout_frequency_hz", "pi_amplitude", "pi_length_samples",
                       "drag_beta_samples", "readout_delay_ticks", "readout_rotation_rad", "readout_threshold")


class QcssDeviceProvider:
    def __init__(self, client: QcssClient, profile_path: str | pathlib.Path) -> None:
        self.client = client
        path = pathlib.Path(profile_path)
        raw = path.read_bytes()
        self.profile: dict[str, Any] = yaml.safe_load(raw)
        self.profile_source = f"{path.name}@sha256:{hashlib.sha256(raw).hexdigest()}"
        self.device_id: str = self.profile["device_id"]
        self._last: dict[tuple[str, str], float] = {}

    def describe(self) -> DeviceDescription:
        try:
            live = self.client.describe()
        except QcssRpcError as err:
            raise classify(err) from None
        offered = {q for ch in live.channels for q in ch.qubits}
        sites = [{"id": q} for q in self.profile["sites"] if q in offered]
        p = self.profile
        return DeviceDescription(
            device_id=self.device_id, modality=p["modality"], maturity_level=p["maturity_level"],
            profile_source=self.profile_source, sites=sites, coupling=p["coupling"],
            native_ops=[NativeOp(**op) for op in p["native_ops"]], program_types=p["program_types"],
            capabilities=p["capabilities"], requires_approval=p.get("requires_approval", False),
            control_stack={"profile_name": live.profile_name, "vendor": live.vendor, "tick_hz": live.tick_hz,
                           "channels": len(live.channels),
                           "max_discriminated_states": live.max_discriminated_states})

    def poll_once(self) -> list[CalibrationEvent]:
        """One poll: an event for every parameter whose value changed since the previous poll (all, the first time)."""
        try:
            props = self.client.properties()
            snap = self.client.get_calibration()
        except QcssRpcError as err:
            raise classify(err) from None
        measured = props.measured_at.ToDatetime(tzinfo=datetime.UTC)
        observed = datetime.datetime.now(datetime.UTC)        # the snapshot itself carries no timestamp
        out: list[CalibrationEvent] = []

        def add(resource: str, parameter: str, value: float, unit: str, raw: str, at: datetime.datetime,
                bounds: tuple[float, float] | None = None) -> None:
            if self._last.get((resource, parameter)) == value:
                return
            self._last[(resource, parameter)] = value
            flags = [] if bounds is None or bounds[0] <= value <= bounds[1] else ["out_of_physical_bounds"]
            out.append(CalibrationEvent(device_id=self.device_id, resource=resource, parameter=parameter,
                                        value=value, unit=unit, measured_at=at, adapter=ADAPTER, raw_name=raw,
                                        quality_flags=flags))

        for q in props.qubits:
            for name, unit, fld, bounds in QUBIT_PARAMETERS:
                add(f"q{q.qubit_index}", name, float(getattr(q, fld)), unit, f"QubitProperties.{fld}", measured,
                    bounds)
        for pr in props.pairs:
            a, b = sorted(pr.qubits)
            for name, unit, fld, bounds in PAIR_PARAMETERS:
                add(f"q{a}-q{b}", name, float(getattr(pr, fld)), unit, f"PairProperties.{fld}", measured, bounds)
        add("device", "custom.calibration_epoch", float(snap.calibration_epoch), "",
            "CalibrationSnapshot.calibration_epoch", observed)
        for qc in snap.qubits:
            for fld in CUSTOM_QUBIT_FIELDS:
                v = float(getattr(qc, fld))
                if v:
                    add(f"q{qc.qubit_index}", f"custom.{fld}", v, "", f"QubitCalibration.{fld}", observed)
        return out

    def calibration_stream(self, poll_s: float = 60.0,
                           stop: threading.Event | None = None) -> Iterator[CalibrationEvent]:
        """Events as values change, polling every poll_s seconds until `stop` is set."""
        stop = stop or threading.Event()
        while not stop.is_set():
            yield from self.poll_once()
            stop.wait(poll_s)

    def request_calibration(self, scope: str) -> Ack:
        return Ack(accepted=False, reason=f"QCSS has no calibration routines to run for {scope!r}; the lab "
                                          "calibrates and writes results with UpdateCalibration")
