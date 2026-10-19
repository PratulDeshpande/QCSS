"""Lab translator: physical OpenQASM 3 -> qcss.v1.Job, through the lab's pulse library.

This is the lab-owned step of HLD ADR-0029 (native-op -> pulse library). Quark hands over a physical
native-gate program; the lab side decides the pulses. Rules:

* x / sx  -> one Play on the qubit's drive channel: the live calibration's DRAG pi pulse when
             GetCalibration has one (pi_amplitude, pi_length_samples), else the library default;
             sx is the same waveform at half amplitude.
* rz(t)   -> virtual Z: a frame shift of -t (OpenPulse convention), merged per qubit and emitted
             just before that qubit's next pulse; an rz with no pulse after it emits nothing.
* cz a,b  -> the library's calibrated flux pulse for the pair, then its phase corrections as
             pending frame shifts. Refused for pairs the library does not list.
* measure -> a discriminated Acquire on the readout channel, result_key "<creg>[<i>]".
* barrier -> the listed qubits (all, if none listed) wait for the latest of them.

Scheduling is as-soon-as-possible per qubit; every start tick is on the library's grid.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

from qcss.v1 import calibration_pb2, job_pb2
from quark_qcss.lab.pulse_library import PulseLibrary
from quark_qcss.lab.qasm import Op, QasmError, parse

NATIVE = ("x", "sx", "rz", "cz", "measure", "barrier")
_SHAPES = {"square": job_pb2.WAVEFORM_SHAPE_SQUARE, "gaussian": job_pb2.WAVEFORM_SHAPE_GAUSSIAN,
           "drag": job_pb2.WAVEFORM_SHAPE_DRAG}
_SHAPE_NAMES = {v: k for k, v in _SHAPES.items()}


class UnsupportedProgramError(ValueError):
    """The program uses something this lab's pulse library cannot run (always names the source line)."""


@dataclass
class Translation:
    job: job_pb2.Job
    clbits: list[str]                         # every declared bit, bit 0 first: "c[0]", "c[1]", ...
    schedule: list[dict[str, Any]] = field(default_factory=list)    # preview (HLD ADR-0055)


class Translator:
    def __init__(self, library: PulseLibrary) -> None:
        self.lib = library

    def _align(self, t: int) -> int:
        g = self.lib.grid_ticks
        return -(-t // g) * g

    def translate(self, qasm: str, calibration: calibration_pb2.CalibrationSnapshot | None, *, shots: int,
                  seed: int | None = None, expected_epoch: int | None = None, job_key: str = "",
                  tier: int = job_pb2.FIDELITY_TIER_AUTO) -> Translation:
        try:
            prog = parse(qasm)
        except QasmError as err:
            raise UnsupportedProgramError(str(err)) from err
        job = job_pb2.Job(job_key=job_key, num_shots=shots, requested_tier=tier)   # type: ignore[arg-type]
        if seed is not None:
            job.random_seed = seed
        if expected_epoch is not None:
            job.expected_calibration_epoch = expected_epoch
        cal = {q.qubit_index: q for q in calibration.qubits} if calibration is not None else {}

        cursor: dict[int, int] = {}
        pending: dict[int, float] = {}                         # accumulated virtual-Z per qubit (frame shift)
        acquires: dict[str, list[int]] = {}                  # start ticks per readout sequencer
        written: set[tuple[str, int]] = set()
        entries: list[tuple[int, int, job_pb2.Instruction, dict[str, Any]]] = []

        def emit(t: int, ins: job_pb2.Instruction, preview: dict[str, Any]) -> None:
            ins.start_tick = t
            entries.append((t, len(entries), ins, {"t_ticks": t, **preview}))

        def chan(q: int, op: Op):
            if q not in self.lib.qubits:
                raise UnsupportedProgramError(f"line {op.line}: qubit {q} is not in the pulse library")
            return self.lib.qubits[q]

        def flush_phase(q: int, t: int) -> None:
            delta = pending.pop(q, 0.0)
            if abs(math.remainder(delta, 2 * math.pi)) > 1e-12:
                frame = self.lib.qubits[q].frame
                emit(t, job_pb2.Instruction(shift_phase=job_pb2.ShiftPhase(frame_id=frame, delta_rad=delta)),
                     {"op": "shift_phase", "channel": frame, "delta_rad": delta})

        def waveform(wid: str, shape: str, length: int, beta: float = 0.0) -> None:
            if wid in job.waveform_library:
                return
            wf = job_pb2.Waveform(shape=_SHAPES[shape], length_samples=length)  # type: ignore[arg-type]
            if shape in ("gaussian", "drag"):
                wf.sigma_samples = length / 4
            if shape == "drag":
                wf.drag_beta_samples = beta
            job.waveform_library[wid].CopyFrom(wf)

        def play(t: int, channel: str, wid: str, amplitude: float) -> None:
            wf = job.waveform_library[wid]
            emit(t, job_pb2.Instruction(play=job_pb2.Play(channel_id=channel, waveform_id=wid, amplitude=amplitude)),
                 {"op": "play", "channel": channel, "amplitude": amplitude,
                  "waveform": {"id": wid, "shape": _SHAPE_NAMES[wf.shape], "length_samples": wf.length_samples}})

        for op in prog.ops:
            if op.name not in NATIVE:
                raise UnsupportedProgramError(f"line {op.line}: gate '{op.name}' is not a native operation "
                                              f"(native: {', '.join(NATIVE)})")
            if op.name in ("x", "sx"):
                (q,) = op.qubits
                ch = chan(q, op)
                qc = cal.get(q)
                if qc is not None and qc.pi_amplitude > 0 and qc.pi_length_samples > 0:
                    wid, length, amp = f"pi_q{q}", qc.pi_length_samples, qc.pi_amplitude
                    waveform(wid, "drag", length, qc.drag_beta_samples)
                else:
                    d = self.lib.single_qubit
                    wid, length, amp = f"pi_default_{d.shape}{d.length_samples}", d.length_samples, d.pi_amplitude
                    waveform(wid, d.shape, length, d.drag_beta_samples)
                t = self._align(cursor.get(q, 0))
                flush_phase(q, t)
                play(t, ch.drive, wid, amp if op.name == "x" else amp / 2)
                cursor[q] = t + self._align(length)
            elif op.name == "rz":
                (q,) = op.qubits
                chan(q, op)
                pending[q] = pending.get(q, 0.0) - op.params[0]
            elif op.name == "cz":
                a, b = op.qubits
                chan(a, op)
                chan(b, op)
                spec = self.lib.pair(a, b)
                if spec is None:
                    raise UnsupportedProgramError(f"line {op.line}: cz on qubits {(a, b)} is not calibrated in "
                                                  "the pulse library (two_qubit)")
                t = self._align(max(cursor.get(a, 0), cursor.get(b, 0)))
                wid = f"cz_{min(a, b)}_{max(a, b)}"
                waveform(wid, spec.shape, spec.length_samples)
                play(t, spec.channel, wid, spec.amplitude)
                cursor[a] = cursor[b] = t + self._align(spec.length_samples)
                for q, corr in spec.phase_corrections.items():
                    pending[q] = pending.get(q, 0.0) - corr
            elif op.name == "measure":
                (q,) = op.qubits
                ch = chan(q, op)
                (bit,) = op.clbits
                if bit in written:
                    raise UnsupportedProgramError(f"line {op.line}: bit {bit[0]}[{bit[1]}] is measured twice")
                written.add(bit)
                seq = ch.readout_sequencer or ch.readout
                t = self._align(max(cursor.get(q, 0),
                                    max((s + self.lib.min_acquire_spacing_ticks for s in acquires.get(seq, [])),
                                        default=0)))
                ro = self.lib.readout
                key = f"{bit[0]}[{bit[1]}]"
                mode = (job_pb2.ACQUISITION_MODE_DISCRIMINATED if ro.mode == "discriminated"
                        else job_pb2.ACQUISITION_MODE_INTEGRATED)
                emit(t, job_pb2.Instruction(acquire=job_pb2.Acquire(
                    channel_id=ch.readout, integration_ticks=ro.integration_ticks, mode=mode,
                    register_index=len(written) - 1, result_key=key)),
                    {"op": "acquire", "channel": ch.readout, "integration_ticks": ro.integration_ticks,
                     "result_key": key})
                acquires.setdefault(seq, []).append(t)
                cursor[q] = t + self._align(ro.integration_ticks)
            elif op.name == "barrier":
                qs = op.qubits or tuple(cursor)
                t = max((cursor.get(q, 0) for q in qs), default=0)
                for q in qs:
                    cursor[q] = t

        entries.sort(key=lambda e: (e[0], e[1]))
        job.main.instructions.extend(e[2] for e in entries)
        clbits = [f"{name}[{i}]" for name, size in prog.cregs.items() for i in range(size)]
        return Translation(job, clbits, [e[3] for e in entries])
