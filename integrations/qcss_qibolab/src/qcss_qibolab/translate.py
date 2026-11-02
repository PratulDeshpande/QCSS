"""Qibolab -> instrument job, and instrument results -> Qibolab.

Pure functions, no network. A Qibolab play() call (configs, one sequence, execution
parameters, sweepers) becomes one job: the instrument is programmed with the configs
(frequencies, discriminator), and every point of the sweep grid becomes its own program,
uploaded together as the job's program points. Envelopes are sampled with Qibolab's own
code, so what plays is exactly what Qibolab defines.

Conventions taken from Qibolab 0.2.17:
- a VirtualZ adds its phase to every later pulse on that drive (emulator: phi = wt + rel + sum vz);
- discrimination rotates IQ by +iq_angle and thresholds the real part (qibosoq driver);
- results are keyed by the acquisition id, shaped by ExecutionParameters.results_shape.
"""
from __future__ import annotations

import hashlib
import itertools
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
from qibolab import (
    Acquisition,
    AcquisitionType,
    AveragingMode,
    Delay,
    ExecutionParameters,
    Parameter,
    Pulse,
    PulseSequence,
    Readout,
    VirtualZ,
)

from qcss.core.ndarray import from_proto, to_proto
from qcss.v1 import calibration_pb2, job_pb2, result_pb2

_CHANNEL = re.compile(r"^(\d+)/(drive|probe|acquisition|flux)$")
_MODES = {AcquisitionType.DISCRIMINATION: job_pb2.ACQUISITION_MODE_DISCRIMINATED,
          AcquisitionType.INTEGRATION: job_pb2.ACQUISITION_MODE_INTEGRATED,
          AcquisitionType.RAW: job_pb2.ACQUISITION_MODE_RAW_TRACE}
_PULSE_FIELDS = {Parameter.amplitude: "amplitude", Parameter.duration: "duration",
                 Parameter.duration_interpolated: "duration", Parameter.relative_phase: "relative_phase",
                 Parameter.phase: "phase"}


@dataclass(frozen=True)
class Translation:
    job: job_pb2.Job
    calibration: calibration_pb2.CalibrationSnapshot      # what the instrument is programmed with
    acquisitions: dict[str, Any]                           # result key -> Qibolab acquisition id
    sweep_shape: tuple[int, ...] = ()


def instrument_channel(channel: str) -> tuple[int, str]:
    """('{q}/drive' etc.) -> (qubit, role). Lines this instrument does not have are refused."""
    m = _CHANNEL.match(channel)
    if m is None:
        raise ValueError(f"channel '{channel}' is not wired to this instrument "
                         "(it serves '<qubit>/drive', '/probe', '/acquisition' and '/flux')")
    return int(m.group(1)), m.group(2)


def _cid(q: int, role: str) -> str:
    return {"drive": f"xy_q{q}", "probe": f"ro_q{q}", "acquisition": f"ro_q{q}", "flux": f"flux_q{q}"}[role]


def _values(sw: Any) -> np.ndarray:
    return np.asarray(sw.values if sw.values is not None else np.arange(*sw.range))


def _grid(sweepers: list[list[Any]]) -> tuple[tuple[int, ...], list[tuple[int, ...]]]:
    shape = []
    for group in sweepers:
        lengths = {len(_values(sw)) for sw in group}
        if len(lengths) != 1:
            raise ValueError(f"parallel sweepers must have equal lengths, got {sorted(lengths)}")
        shape.append(lengths.pop())
    return tuple(shape), list(itertools.product(*(range(n) for n in shape)))


def _point(sequence: PulseSequence, sweepers: list[list[Any]], idx: tuple[int, ...],
           ) -> tuple[list[tuple[str, Any]], dict[str, dict[str, float]]]:
    """The sequence and config overrides at one grid point."""
    pulse_updates: dict[Any, dict[str, float]] = {}
    config_updates: dict[str, dict[str, float]] = {}
    for group, i in zip(sweepers, idx, strict=True):
        for sw in group:
            v = float(_values(sw)[i])
            if sw.parameter in _PULSE_FIELDS:
                for p in sw.pulses or []:
                    pulse_updates.setdefault(p.id, {})[_PULSE_FIELDS[sw.parameter]] = v
            elif sw.parameter in (Parameter.frequency, Parameter.offset):
                for ch in sw.channels or []:
                    config_updates.setdefault(ch, {})[sw.parameter.name] = v
            else:
                raise ValueError(f"sweeping {sw.parameter.name} is not supported by this instrument")

    def upd(p: Any) -> Any:
        if isinstance(p, Readout):
            return p.model_copy(update={"probe": upd(p.probe), "acquisition": upd(p.acquisition)})
        return p.model_copy(update=pulse_updates[p.id]) if p.id in pulse_updates else p
    return [(ch, upd(p)) for ch, p in sequence.align_to_delays()], config_updates


class _Builder:
    def __init__(self, job: job_pb2.Job, tick_per_ns: float, sampling_rate: float) -> None:
        self.job, self.tpn, self.sr = job, tick_per_ns, sampling_rate
        self._wf: dict[bytes, str] = {}

    def tick(self, t_ns: float) -> int:
        return round(t_ns * self.tpn)

    def waveform(self, p: Pulse) -> str:
        samples = np.asarray(p.i(self.sr)) + 1j * np.asarray(p.q(self.sr))
        key = hashlib.blake2b(samples.tobytes(), digest_size=16).digest()
        if key not in self._wf:
            wid = f"w{len(self._wf)}"
            self._wf[key] = wid
            self.job.waveform_library[wid].CopyFrom(job_pb2.Waveform(
                shape=job_pb2.WAVEFORM_SHAPE_ARBITRARY, samples=to_proto(samples.astype(np.complex128)),
                length_samples=len(samples)))
        return self._wf[key]


def translate(sequence: PulseSequence, configs: Mapping[str, Any], options: ExecutionParameters,
              sweepers: list[list[Any]], *, los: Mapping[str, float], tick_per_ns: float = 1.0,
              sampling_rate: float = 1.0) -> Translation:
    """One Qibolab sequence (with its sweepers) as one instrument job."""
    for ch, cfg in configs.items():
        if _CHANNEL.match(ch) and getattr(cfg, "offset", 0.0):
            raise ValueError(f"'{ch}': DC flux offsets are not supported by this instrument")
    job = job_pb2.Job(num_shots=int(options.nshots or 1))
    if options.relaxation_time is not None:
        job.repetition_delay_ticks = round(float(options.relaxation_time) * tick_per_ns)
    mode = _MODES[options.acquisition_type]
    b = _Builder(job, tick_per_ns, sampling_rate)
    shape, grid = _grid(sweepers)
    acquisitions: dict[str, Any] = {}
    used: set[int] = set()

    for idx in grid:
        items, cfg_upd = _point(sequence, sweepers, idx)
        ins = job.program_points.add(indices=list(idx)).main.instructions
        for ch, upd in cfg_upd.items():
            q, role = instrument_channel(ch)
            if "offset" in upd:
                raise ValueError(f"'{ch}': sweeping a DC flux offset is not supported by this instrument")
            frame = {"drive": f"q{q}", "probe": f"ro_q{q}"}.get(role)
            if frame is None:
                raise ValueError(f"'{ch}': frequency sweeps need a drive or probe channel")
            ins.add(start_tick=0, set_frequency=job_pb2.SetFrequency(
                frame_id=frame, frequency_hz=upd["frequency"] - los[_cid(q, role)]))
        cursor: dict[str, float] = {}
        for ch, p in items:
            q, role = instrument_channel(ch)
            used.add(q)
            t = cursor.get(ch, 0.0)
            if isinstance(p, VirtualZ):
                ins.add(start_tick=b.tick(t), shift_phase=job_pb2.ShiftPhase(frame_id=f"q{q}", delta_rad=p.phase))
            elif isinstance(p, Readout | Acquisition):
                acq = p.acquisition if isinstance(p, Readout) else p
                key = str(acq.id)
                acquisitions[key] = acq.id
                ins.add(start_tick=b.tick(t), acquire=job_pb2.Acquire(
                    channel_id=_cid(q, "acquisition"), integration_ticks=max(4, 4 * (b.tick(acq.duration) // 4)),
                    mode=mode, register_index=len(acquisitions) % 15, result_key=key))
            elif isinstance(p, Pulse) and role != "probe":     # a probe tone is part of the readout
                ins.add(start_tick=b.tick(t), play=job_pb2.Play(
                    channel_id=_cid(q, role), waveform_id=b.waveform(p), amplitude=1.0,
                    phase_offset_rad=p.relative_phase))
            elif not isinstance(p, Pulse | Delay):
                raise ValueError(f"{type(p).__name__} on '{ch}' is not supported by this instrument")
            cursor[ch] = t + p.duration

    cal = calibration_pb2.CalibrationSnapshot()
    for q in sorted(used):
        qc = cal.qubits.add(qubit_index=q)
        drive, probe, acq = configs.get(f"{q}/drive"), configs.get(f"{q}/probe"), configs.get(f"{q}/acquisition")
        if drive is not None:
            qc.drive_frequency_hz = drive.frequency
        if probe is not None:
            qc.readout_frequency_hz = probe.frequency
        if acq is not None:
            qc.readout_threshold = acq.threshold or 0.0
            qc.readout_rotation_rad = -(acq.iq_angle or 0.0)
    return Translation(job, cal, acquisitions, shape)


def assemble(chunks: Iterable[result_pb2.ResultChunk], tr: Translation,
             options: ExecutionParameters) -> dict[Any, np.ndarray]:
    """Instrument result chunks -> {acquisition id: array shaped as Qibolab's results_shape}."""
    parts: dict[str, dict[tuple[int, ...], list[tuple[int, np.ndarray]]]] = {}
    integration = options.acquisition_type is not AcquisitionType.DISCRIMINATION
    for c in chunks:
        idx = tuple(c.sweep_point)
        for a in c.acquisitions:
            vals = from_proto(a.iq if integration else a.states)
            parts.setdefault(a.result_key, {}).setdefault(idx, []).append((c.shot_offset, np.asarray(vals)))
    grid = list(itertools.product(*(range(n) for n in tr.sweep_shape)))
    out: dict[Any, np.ndarray] = {}
    for key, acq_id in tr.acquisitions.items():
        per_point = []
        for idx in grid:
            shots = np.concatenate([v for _, v in sorted(parts.get(key, {}).get(idx, []), key=lambda t: t[0])])
            if integration:
                shots = np.stack([np.real(shots), np.imag(shots)], axis=-1)
            per_point.append(shots)
        data = np.stack(per_point, axis=1)                   # (shots, points, *tail)
        data = data.reshape((data.shape[0], *tr.sweep_shape, *data.shape[2:]))
        if options.averaging_mode is not AveragingMode.SINGLESHOT:
            data = data.mean(axis=0)
        out[acq_id] = data
    return out
