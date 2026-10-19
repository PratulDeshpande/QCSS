"""Compiler: transforms proto Job into internal Program IR.

UNSPECIFIED enum values are rejected with field paths (proto contract, SW-02); nothing is
silently defaulted. Sweeps are expanded into one concrete Job per sweep point, and every
point is compiled and validated on its own (SW-10).
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any

import numpy as np

from qcss.config.device import DeviceSpec
from qcss.config.profile import GeneratorSpec, HardwareProfile
from qcss.core.errors import HardwareValidationError
from qcss.core.ndarray import from_proto
from qcss.core.timebase import TimeBase
from qcss.ir.program import (
    Acquire,
    Branch,
    ChannelBinding,
    ChannelKind,
    Condition,
    FrameOp,
    Play,
    Program,
)
from qcss.ir.waveforms import (
    WaveformLibrary,
    cosine_flattop,
    drag,
    gaussian,
    square,
)
from qcss.v1 import job_pb2

DEFAULT_QUBITS = 5          # channels offered when no device file is given

_MODES = {
    job_pb2.ACQUISITION_MODE_RAW_TRACE: "raw_trace",
    job_pb2.ACQUISITION_MODE_INTEGRATED: "integrated",
    job_pb2.ACQUISITION_MODE_DISCRIMINATED: "discriminated",
}
_CONDITIONS = {
    job_pb2.CONDITION_OP_EQUAL: "eq",
    job_pb2.CONDITION_OP_NOT_EQUAL: "ne",
    job_pb2.CONDITION_OP_MASK_AND: "and",
    job_pb2.CONDITION_OP_MASK_OR: "or",
    job_pb2.CONDITION_OP_MASK_XOR: "xor",
}


def _waveform_samples(w_id: str, w: Any, errors: list[tuple[str, str]]) -> np.ndarray | None:
    path = f"job.waveform_library[{w_id}]"
    n = w.length_samples
    shape = w.shape
    if shape == job_pb2.WAVEFORM_SHAPE_UNSPECIFIED:
        errors.append((path + ".shape", "WAVEFORM_SHAPE_UNSPECIFIED is not allowed"))
        return None
    if shape == job_pb2.WAVEFORM_SHAPE_ARBITRARY:
        if not w.HasField("samples"):
            errors.append((path + ".samples", "ARBITRARY waveform needs samples"))
            return None
        samples = np.asarray(from_proto(w.samples), dtype=np.complex128).reshape(-1)
        if n and len(samples) != n:
            errors.append((path + ".samples", f"{len(samples)} samples but length_samples is {n}"))
            return None
        return samples
    if n == 0:
        errors.append((path + ".length_samples", "must be > 0"))
        return None
    sigma = w.sigma_samples if w.HasField("sigma_samples") else None
    if shape == job_pb2.WAVEFORM_SHAPE_GAUSSIAN:
        return gaussian(n, sigma).astype(np.complex128)
    if shape == job_pb2.WAVEFORM_SHAPE_DRAG:
        return drag(n, sigma, w.drag_beta_samples if w.HasField("drag_beta_samples") else 0.0)
    if shape == job_pb2.WAVEFORM_SHAPE_SQUARE:
        return square(n)
    if shape == job_pb2.WAVEFORM_SHAPE_COSINE_FLATTOP:
        return cosine_flattop(n, w.rise_fall_samples if w.HasField("rise_fall_samples") else n // 4)
    errors.append((path + ".shape", f"unknown waveform shape {shape}"))
    return None


def compile_job(
    job: job_pb2.Job,
    profile: HardwareProfile,
    timebase: TimeBase,
    device: DeviceSpec | None = None,
    bindings: dict[str, ChannelBinding] | None = None,
) -> tuple[Program, WaveformLibrary]:
    """Compile a proto Job into an executable/validatable Program and WaveformLibrary.

    Raises HardwareValidationError listing every contract violation found.
    """
    if bindings is None:
        bindings = build_bindings(profile, device)
    errors: list[tuple[str, str]] = []

    wf_lib = WaveformLibrary()
    wf_lengths: dict[str, int] = {}
    for w_id, w_proto in job.waveform_library.items():
        samples = _waveform_samples(w_id, w_proto, errors)
        if samples is None:
            continue
        wf_lengths[w_id] = len(samples)
        for gen in profile.generators:
            wf_lib.add(gen.generator_id, w_id, samples)

    weights_lengths: dict[str, int] = {}
    for w_id, w_proto in job.weight_library.items():
        weights_lengths[w_id] = len(np.asarray(from_proto(w_proto.weights)).reshape(-1))

    gen_by_id = {g.generator_id: g for g in profile.generators}

    def compile_instructions(instructions: Any, path_prefix: str) -> list[Any]:
        ops: list[Any] = []
        for idx, inst in enumerate(instructions):
            path = f"{path_prefix}[{idx}]"
            which = inst.WhichOneof("op")
            start = inst.start_tick

            if which == "play":
                p = inst.play
                duration = p.duration_ticks if p.HasField("duration_ticks") else 0
                if duration == 0 and p.waveform_id in wf_lengths:
                    b = bindings.get(p.channel_id)
                    if b and b.generator_id in gen_by_id:
                        per = timebase.ticks_per(gen_by_id[b.generator_id].sample_rate_hz)
                        duration = wf_lengths[p.waveform_id] * per
                ops.append(Play(path=path, channel_id=p.channel_id, start=start, duration=duration,
                                waveform_id=p.waveform_id, amplitude=p.amplitude, phase_offset=p.phase_offset_rad))
            elif which == "shift_phase":
                ops.append(FrameOp(path=path, frame_id=inst.shift_phase.frame_id, start=start, kind="shift",
                                   value=inst.shift_phase.delta_rad))
            elif which == "set_phase":
                ops.append(FrameOp(path=path, frame_id=inst.set_phase.frame_id, start=start, kind="set",
                                   value=inst.set_phase.phase_rad))
            elif which == "reset_phase":
                ops.append(FrameOp(path=path, frame_id=inst.reset_phase.frame_id, start=start, kind="reset"))
            elif which == "set_frequency":
                ops.append(FrameOp(path=path, frame_id=inst.set_frequency.frame_id, start=start, kind="freq",
                                   value=inst.set_frequency.frequency_hz))
            elif which == "acquire":
                acq = inst.acquire
                mode = _MODES.get(acq.mode)
                if mode is None:
                    errors.append((path + ".acquire.mode", "ACQUISITION_MODE_UNSPECIFIED is not allowed"))
                    continue
                ops.append(Acquire(path=path, channel_id=acq.channel_id, start=start,
                                   integration=acq.integration_ticks, mode=mode, weights_id=acq.weights_id,
                                   register=acq.register_index, result_key=acq.result_key))
            elif which == "branch":
                br = inst.branch
                cond_op = _CONDITIONS.get(br.condition.op)
                if cond_op is None:
                    errors.append((path + ".branch.condition.op", "CONDITION_OP_UNSPECIFIED is not allowed"))
                    continue
                cond = Condition(op=cond_op, registers=tuple(br.condition.register_indices),
                                 value=br.condition.value, mask=br.condition.mask)
                then_ops = compile_instructions(br.then_block.instructions, f"{path}.then_block.instructions")
                else_ops = compile_instructions(br.else_block.instructions, f"{path}.else_block.instructions")
                ops.append(Branch(path=path, sequencer_id=br.sequencer_id, start=start, duration=br.duration_ticks,
                                  condition=cond, then_ops=tuple(then_ops), else_ops=tuple(else_ops)))
            elif which == "wait":
                continue        # absolute start ticks already place every op; a wait carries no action
            else:
                errors.append((path, "instruction has no op set"))
        return ops

    main_ops = compile_instructions(job.main.instructions, "job.main.instructions")
    if errors:
        raise HardwareValidationError(errors)

    def max_tick(ops) -> int:
        m = 0
        for op in ops:
            if isinstance(op, Play):
                m = max(m, op.start + op.duration)
            elif isinstance(op, Acquire):
                m = max(m, op.start + op.integration)
            elif isinstance(op, Branch):
                m = max(m, op.start + op.duration, max_tick(op.then_ops), max_tick(op.else_ops))
            elif isinstance(op, FrameOp):
                m = max(m, op.start)
        return m

    prog = Program(
        bindings=bindings,
        ops=main_ops,
        waveforms=wf_lengths,
        weights=weights_lengths,
        duration=max_tick(main_ops),
        repetition_delay=job.repetition_delay_ticks if job.HasField("repetition_delay_ticks") else None,
    )
    return prog, wf_lib


# -------------------------------------------------------------------------------- sweeps
@dataclass(frozen=True)
class SweepPoint:
    indices: tuple[int, ...]          # one index per sweep axis, in ascending axis order
    job: job_pb2.Job                  # the concrete job for this point (no sweeps left)


def expand_sweeps(job: job_pb2.Job) -> list[SweepPoint]:
    """Sweeps sharing an axis are zipped; different axes form a grid (last axis fastest)."""
    axes: dict[int, list[Any]] = {}
    for s in job.sweeps:
        axes.setdefault(s.axis, []).append(s)
    errors: list[tuple[str, str]] = []
    axis_values: list[list[tuple[Any, np.ndarray]]] = []
    lengths: list[int] = []
    for axis in sorted(axes):
        entries = []
        n = None
        for k, s in enumerate(axes[axis]):
            vals = np.asarray(from_proto(s.values)).reshape(-1)
            if n is None:
                n = len(vals)
            elif len(vals) != n:
                errors.append((f"job.sweeps[axis={axis}][{k}].values",
                               f"{len(vals)} values but axis {axis} has {n} (sweeps on one axis are zipped)"))
            entries.append((s, vals))
        if not n:
            errors.append((f"job.sweeps[axis={axis}]", "empty values"))
        axis_values.append(entries)
        lengths.append(n or 0)
    if errors:
        raise HardwareValidationError(errors)

    points = []
    for idx in itertools.product(*(range(n) for n in lengths)):
        j = job_pb2.Job()
        j.CopyFrom(job)
        del j.sweeps[:]
        for entries, i in zip(axis_values, idx, strict=True):
            for s, vals in entries:
                _apply_sweep_value(j, s, vals[i], errors)
        points.append(SweepPoint(tuple(idx), j))
    if errors:
        raise HardwareValidationError(errors)
    return points


def _apply_sweep_value(j: job_pb2.Job, s: Any, value: Any, errors: list[tuple[str, str]]) -> None:
    target = s.WhichOneof("target")
    if target == "amplitude":
        i = s.amplitude.instruction_index
        if i >= len(j.main.instructions) or j.main.instructions[i].WhichOneof("op") != "play":
            errors.append((f"job.sweeps[axis={s.axis}].amplitude.instruction_index",
                           f"instruction {i} is not a play in job.main"))
            return
        j.main.instructions[i].play.amplitude = float(np.real(value))
    elif target == "duration":
        wid = s.duration.waveform_id
        if wid not in j.waveform_library:
            errors.append((f"job.sweeps[axis={s.axis}].duration.waveform_id", f"unknown waveform '{wid}'"))
            return
        j.waveform_library[wid].length_samples = round(float(np.real(value)))
        for inst in j.main.instructions:
            if inst.WhichOneof("op") == "play" and inst.play.waveform_id == wid:
                inst.play.ClearField("duration_ticks")
    elif target == "frequency":
        fid = s.frequency.frame_id
        hit = False
        for inst in j.main.instructions:
            if inst.WhichOneof("op") == "set_frequency" and inst.set_frequency.frame_id == fid:
                inst.set_frequency.frequency_hz = float(np.real(value))
                hit = True
        if not hit:
            new = job_pb2.Instruction(start_tick=0, set_frequency=job_pb2.SetFrequency(
                frame_id=fid, frequency_hz=float(np.real(value))))
            j.main.instructions.insert(0, new)
    else:
        errors.append((f"job.sweeps[axis={s.axis}]", "sweep has no target"))


# -------------------------------------------------------------------------------- bindings
def _classify(profile: HardwareProfile) -> tuple[list[GeneratorSpec], list[GeneratorSpec], list[GeneratorSpec]]:
    """(drive, flux, readout) generators. Flux lines live on baseband ports."""
    kinds = {p.port_id: p.kind for p in profile.ports}
    readout = [g for g in profile.generators if g.is_readout]
    flux = [g for g in profile.generators if not g.is_readout and kinds[g.port_id] == "baseband"]
    drive = [g for g in profile.generators if not g.is_readout and kinds[g.port_id] != "baseband"]
    return drive, flux, readout


def build_bindings(profile: HardwareProfile, device: DeviceSpec | None = None) -> dict[str, ChannelBinding]:
    """Default channels per qubit: xy_q{i} -> a drive generator, ro_q{i} -> a readout generator,
    flux_q{i} -> a baseband generator, cr_q{c}_q{t} on the control's drive generator but bound to
    the TARGET frame. Generators of each role are shared round-robin."""
    drive, flux, readout = _classify(profile)
    qubits = [q.qubit_index for q in device.qubits] if device is not None else list(range(DEFAULT_QUBITS))
    bindings: dict[str, ChannelBinding] = {}

    def bind(cid: str, kind: ChannelKind, g: GeneratorSpec, frame: str, qs: tuple[int, ...]) -> None:
        bindings[cid] = ChannelBinding(channel_id=cid, kind=kind, generator_id=g.generator_id,
                                       port_id=g.port_id, frame_id=frame, qubits=qs)

    for k, q in enumerate(qubits):
        if drive:
            bind(f"xy_q{q}", ChannelKind.DRIVE, drive[k % len(drive)], f"q{q}", (q,))
        if readout:
            bind(f"ro_q{q}", ChannelKind.READOUT, readout[k % len(readout)], f"ro_q{q}", (q,))
        if flux:
            bind(f"flux_q{q}", ChannelKind.FLUX, flux[k % len(flux)], f"flux_q{q}", (q,))
    if device is not None and drive:
        pos = {q: k for k, q in enumerate(qubits)}
        for c in device.couplers:
            a, b = c.qubit_pair
            for ctrl, tgt in ((a, b), (b, a)):
                bind(f"cr_q{ctrl}_q{tgt}", ChannelKind.CROSS_RESONANCE, drive[pos[ctrl] % len(drive)],
                     f"q{tgt}", (ctrl, tgt))
    return bindings
