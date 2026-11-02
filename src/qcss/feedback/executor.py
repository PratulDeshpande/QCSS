"""Shot executor: one absolute-time event queue per shot, per-sequencer semantics.

Every play is rendered through the port chain (frame phase from the NCO model, OS correction,
hidden mixer/line truth) into the drive the qubit actually sees. Pulse-level engines (T2)
evolve under those samples, with overlapping pulses evolved together; gate-level engines
(T0, T1a, T1b) receive the lifted unitary of the same samples. Virtual Z / set_phase /
set_frequency only change the frame tracker, never the qubit state.

Times: the event queue runs in integer ticks; engines receive nanoseconds (TimeBase).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from qcss.core.timebase import TimeBase
from qcss.ir.frames import TWO_PI, FrameTracker
from qcss.ir.program import Acquire, Branch, ChannelBinding, ChannelKind, FrameOp, Play, Program
from qcss.ir.waveforms import WaveformLibrary
from qcss.physics.lifter import GateEvent, annotate_clifford, lift_1q, lift_multi, shift_lift_start
from qcss.signal.port_renderer import DriveChain, FluxChain
from qcss.timing.des import DES, Prio

MAX_LIFT_QUTRITS = 4          # 3^4 = 81-dimensional closed propagator per lifted flux pulse


class UnliftableError(Exception):
    """A pulse whose action cannot be reduced to a small gate (route the job to T2)."""


@dataclass
class AcqRecord:
    result_key: str
    register: int
    level: int
    label: int
    iq: complex
    end_tick: int                 # absolute virtual time at which the result is available
    trace: np.ndarray | None = None


@dataclass
class ShotResult:
    acquisitions: list[AcqRecord] = field(default_factory=list)
    timeline: list[tuple[int, str]] = field(default_factory=list)   # (tick, description) for tests
    end_tick: int = 0


@dataclass
class Segment:
    kind: str                     # "drive" (complex Omega on a qubit) | "flux" (line voltage)
    index: int                    # local qubit (drive) or local flux line (flux)
    t0_ns: float
    dt_ns: float
    samples: np.ndarray

    @property
    def t1_ns(self) -> float:
        return self.t0_ns + self.dt_ns * len(self.samples)


@dataclass
class QubitModel:
    """What the executor and lifter need to know about one simulated qubit."""
    alpha_rad_ns: float
    detuning_rad_ns: float        # 2 pi (f01 - frame) in the engine's frame
    frame_rad_ns: float           # 2 pi * frame frequency
    flux_detuning: Callable[[np.ndarray], np.ndarray]    # delta Phi (Phi0) -> extra detuning (rad/ns)


@dataclass
class ExecContext:
    tb: TimeBase
    engine: Any
    bindings: dict[str, ChannelBinding]
    wf_lib: WaveformLibrary
    qmap: dict[int, int]                                    # device qubit -> engine qubit
    qubits: list[QubitModel]                                # by engine qubit
    couplings_rad_ns: dict[tuple[int, int], float]          # engine qubits
    drive_chains: dict[str, DriveChain]                     # channel -> chain
    flux_chains: dict[str, FluxChain]                       # port -> chain (continuous)
    m_fast: np.ndarray                                      # engine qubits x flux lines (Phi0 per unit)
    frame_if0: dict[str, float]                             # frame -> base NCO frequency (Hz)
    channel_if0: dict[str, float]                           # channel -> NCO frequency on its own port (Hz)
    ticks_per_sample: dict[str, int]                        # generator -> ticks
    readout: dict[int, Any]                                 # device qubit -> readout model
    adc_ticks_per_sample: dict[str, int]                    # readout channel -> ticks per ADC sample
    tof_ticks: dict[str, int]
    latency: Callable[[str, str], int]
    t1_ns: dict[int, float]                                 # device qubit -> current T1 (for readout jumps)
    weights: dict[str, np.ndarray] = field(default_factory=dict)
    clifford_required: bool = False
    nco_latched: bool = True
    nco_phase_steps: int = 10**9
    nco_freq_resolution_hz: float = 0.25


def shot_duration(prog: Program, tof_ticks: dict[str, int]) -> int:
    """Program end including the time until the last acquisition result is available."""
    end = prog.duration

    def walk(ops) -> None:
        nonlocal end
        for op in ops:
            if isinstance(op, Acquire):
                end = max(end, op.start + tof_ticks.get(op.channel_id, 0) + op.integration)
            elif isinstance(op, Branch):
                walk(op.then_ops)
                walk(op.else_ops)
    walk(prog.ops)
    return end


class ShotExecutor:
    def __init__(self, ctx: ExecContext) -> None:
        self.ctx = ctx
        self.lift_log: list[GateEvent] | None = None      # dry runs collect lifted events here
        # flux lifts by (line, samples, dt): (U at start t_ref, leakage, t_ref); reused at any start (shift_lift_start)
        self._flux_lifts: dict[tuple, tuple[np.ndarray, float, float]] = {}

    # ------------------------------------------------------------------ frames and rendering
    def _tracker(self) -> FrameTracker:
        c = self.ctx
        return FrameTracker(c.tb.tick_hz, dict(c.frame_if0), phase_steps=c.nco_phase_steps,
                            freq_resolution_hz=c.nco_freq_resolution_hz, latched=c.nco_latched)

    def _frame_phase(self, tr: FrameTracker, fid: str, ticks_rel: np.ndarray) -> np.ndarray:
        """NCO phase relative to the base-frequency ramp: explicit phase + (f - f0) accumulation."""
        fr = tr.frames[fid]
        f0 = tr._qf(self.ctx.frame_if0.get(fid, 0.0))
        ts = tr.tick_s
        acc = fr.acc_rad + TWO_PI * fr.freq_hz * (ticks_rel - fr.t_ref_tick) * ts
        return acc - TWO_PI * f0 * ticks_rel * ts + tr.explicit_phase(fid)

    def _render(self, op: Play, b: ChannelBinding, t_abs: int, shot_start: int, tr: FrameTracker) -> Segment | None:
        c = self.ctx
        per = c.ticks_per_sample[b.generator_id]
        wf = c.wf_lib.get(b.generator_id, op.waveform_id)
        n = len(wf)
        dt_ns = per * 1e9 / float(c.tb.tick_hz)
        t0_ns = c.tb.ticks_to_ns(t_abs)
        if b.kind is ChannelKind.FLUX:
            q = c.qmap.get(b.qubits[0])
            if q is None:
                return None
            chain = c.flux_chains[b.port_id]
            v = chain.render(op.amplitude * np.real(wf), start_sample=t_abs // per)
            return Segment("flux", q, t0_ns, dt_ns, v)
        if b.kind is ChannelKind.READOUT:
            return None                                   # the readout drive is part of the acquisition model
        q = c.qmap.get(b.qubits[0])
        if q is None:
            return None
        tr.on_rt_instruction(b.frame_id, t_abs - shot_start)
        ticks_rel = (t_abs - shot_start) + per * np.arange(n)
        phase = self._frame_phase(tr, b.frame_id, ticks_rel) + op.phase_offset
        env = op.amplitude * wf * np.exp(1j * phase)
        omega = c.drive_chains[b.channel_id].render(env, t0_ns + dt_ns * np.arange(n), c.channel_if0.get(b.channel_id, 0.0))
        return Segment("drive", q, t0_ns, dt_ns, omega)

    # ------------------------------------------------------------------ lifting (gate tiers)
    def lift(self, seg: Segment, name: str) -> GateEvent:
        c = self.ctx
        if seg.kind == "drive":
            qm = c.qubits[seg.index]
            u, leak = lift_1q(seg.samples, seg.dt_ns, qm.alpha_rad_ns, qm.detuning_rad_ns)
            ev = GateEvent((seg.index,), u, seg.t0_ns, seg.t1_ns, leak, name)
        else:
            line = seg.index
            hit = [k for k in range(len(c.qubits)) if c.m_fast[k, line] != 0.0]
            sub = sorted(set(hit) | {k for pair in c.couplings_rad_ns for k in pair if set(pair) & set(hit)})
            if len(sub) > MAX_LIFT_QUTRITS:
                raise UnliftableError(f"flux pulse '{name}' couples {len(sub)} qutrits (> {MAX_LIFT_QUTRITS})")
            pos = {k: i for i, k in enumerate(sub)}
            frames = [c.qubits[k].frame_rad_ns for k in sub]
            key = (line, np.asarray(seg.samples).tobytes(), seg.dt_ns)
            cached = self._flux_lifts.get(key)
            if cached is None:
                flux = {pos[k]: c.qubits[k].flux_detuning(c.m_fast[k, line] * seg.samples) for k in hit}
                u, leak = lift_multi(
                    n_qubits=len(sub), dt_ns=seg.dt_ns, n_samples=len(seg.samples),
                    detunings_rad_ns=[c.qubits[k].detuning_rad_ns for k in sub],
                    alphas_rad_ns=[c.qubits[k].alpha_rad_ns for k in sub],
                    couplings_rad_ns={(pos[a], pos[b]): j for (a, b), j in c.couplings_rad_ns.items()
                                      if a in pos and b in pos},
                    flux=flux, frame_rad_ns=frames, t0_ns=seg.t0_ns)
                self._flux_lifts[key] = (u, leak, seg.t0_ns)
            else:
                u_ref, leak, t_ref = cached
                u = shift_lift_start(u_ref, frames, seg.t0_ns - t_ref)
            ev = GateEvent(tuple(sub), u, seg.t0_ns, seg.t1_ns, leak, name, driven=tuple(hit))
        if c.clifford_required:
            annotate_clifford(ev)
        return ev

    # ------------------------------------------------------------------ pulse-level evolution
    def _evolve_to(self, segs: list[Segment], t_ns: float) -> None:
        eng = self.ctx.engine
        while eng.clock < t_ns - 1e-9:
            now = eng.clock
            live = [s for s in segs if s.t1_ns > now + 1e-9 and s.t0_ns < t_ns - 1e-9]
            edges = [t_ns] + [e for s in live for e in (s.t0_ns, s.t1_ns) if e > now + 1e-9]
            nxt = min(edges)
            active = [s for s in live if s.t0_ns <= now + 1e-9]
            if not active:
                eng.advance_to(nxt)
                continue
            dt = min(s.dt_ns for s in active)
            n = max(1, round((nxt - now) / dt))
            dt = (nxt - now) / n
            mid = now + (np.arange(n) + 0.5) * dt
            drives: dict[int, np.ndarray] = {}
            lines: dict[int, np.ndarray] = {}
            for s in active:
                k = np.clip(((mid - s.t0_ns) / s.dt_ns).astype(int), 0, len(s.samples) - 1)
                target = drives if s.kind == "drive" else lines
                target[s.index] = target.get(s.index, 0) + s.samples[k]
            flux: dict[int, np.ndarray] = {}
            for line, v in lines.items():
                for q in range(len(self.ctx.qubits)):
                    m = self.ctx.m_fast[q, line]
                    if m != 0.0:
                        flux[q] = flux.get(q, 0) + m * v
            flux = {q: self.ctx.qubits[q].flux_detuning(dphi) for q, dphi in flux.items()}
            eng.evolve_segment(now, dt, drives=drives or None, flux_detuning=flux or None)

    # ------------------------------------------------------------------ one shot
    def run_shot(self, prog: Program, rng: np.random.Generator, readout_rng: np.random.Generator | None = None,
                 shot_start_tick: int = 0, force_branch: bool | None = None, ensemble: bool = False) -> ShotResult:
        c = self.ctx
        S = shot_start_tick
        des = DES(now=S)
        res = ShotResult()
        regs: dict[int, int] = {}
        ready_at: dict[int, tuple[int, str]] = {}
        segs: list[Segment] = []
        # When each qubit's last lifted gate ends, to refuse concurrent gates on a shared qubit. Plays arrive in
        # time order (the DES), so one end time per qubit suffices. Only the planning dry run checks: it runs
        # every branch, so an overlapping job never reaches execution (it is routed to T2 or refused).
        busy_until: dict[int, tuple[float, str]] = {}
        tr = self._tracker()
        ro_rng = readout_rng if readout_rng is not None else rng
        pulse_level = bool(getattr(c.engine, "pulse_level", False))
        self.ensemble_probs: tuple[list[int], np.ndarray] | None = None

        def advance(t_abs: int) -> None:
            t_ns = c.tb.ticks_to_ns(t_abs)
            if pulse_level:
                self._evolve_to(segs, t_ns)
                segs[:] = [s for s in segs if s.t1_ns > t_ns + 1e-9]
            else:
                c.engine.advance_to(t_ns, rng)

        def do_play(op: Play, t: int) -> None:
            b = c.bindings[op.channel_id]
            advance(t)
            seg = self._render(op, b, t, S, tr)
            res.timeline.append((t, f"play {op.channel_id}:{op.waveform_id}"))
            if seg is None:
                return
            if pulse_level:
                segs.append(seg)
            else:
                ev = self.lift(seg, op.waveform_id)
                if self.lift_log is not None:
                    qs = ev.driven or ev.qubits      # gates apply one after another; overlapping pulses do not
                    for q in qs:
                        end, prev = busy_until.get(q, (-np.inf, ""))
                        if ev.t_start < end - 1e-9 and ev.t_end - 1e-9 > ev.t_start:
                            raise UnliftableError(f"pulse '{ev.name}' overlaps '{prev}' on a shared qubit; "
                                                  "concurrent pulses need pulse-level physics (T2)")
                    for q in qs:
                        busy_until[q] = max(busy_until.get(q, (-np.inf, "")), (ev.t_end, ev.name))
                    self.lift_log.append(ev)
                else:
                    c.engine.apply_event(ev, rng)

        def do_frame(op: FrameOp, t: int) -> None:
            rel = t - S
            if op.kind == "shift":
                tr.shift_phase(op.frame_id, op.value, rel)
            elif op.kind == "set":
                tr.set_phase(op.frame_id, op.value, rel)
            elif op.kind == "reset":
                tr.reset_phase(op.frame_id, rel)
            elif op.kind == "freq":
                tr.set_frequency(op.frame_id, op.value, rel)
            res.timeline.append((t, f"frame {op.frame_id}:{op.kind}"))

        def do_acq_start(op: Acquire, t: int) -> None:
            b = c.bindings[op.channel_id]
            q_dev = b.qubits[0]
            q = c.qmap.get(q_dev)
            advance(t)
            t_ready = t + c.tof_ticks.get(op.channel_id, 0) + op.integration
            ready_at[op.register] = (t_ready, b.generator_id)
            if ensemble:
                if self.ensemble_probs is None:
                    qs = sorted({c.qmap[c.bindings[o.channel_id].qubits[0]] for o in prog.ops
                                 if isinstance(o, Acquire) and o.start == op.start})
                    self.ensemble_probs = (qs, c.engine.joint_probabilities(qs))
                    c.engine.dephase_measured(qs)
                return
            if self.lift_log is not None:            # a planning dry run: timing only, no readout physics
                des.schedule_at(t_ready, Prio.ACQ_COMPLETE, do_acq_end, op, 0, 0, 0j, None, t_ready)
                return
            level = c.engine.measure(q, rng=rng) if q is not None else 0
            n = op.integration // c.adc_ticks_per_sample[op.channel_id]
            ro = c.readout[q_dev]
            out = ro.acquire(np.array([level]), n, c.t1_ns.get(q_dev, np.inf), ro_rng,
                             c.weights.get(op.weights_id), want_trace=op.mode == "raw_trace")
            des.schedule_at(t_ready, Prio.ACQ_COMPLETE, do_acq_end, op, level, int(out.labels[0]),
                            complex(out.iq[0]), None if out.traces is None else out.traces[0], t_ready)

        def do_acq_end(op: Acquire, level: int, label: int, iq: complex, trace, t: int) -> None:
            regs[op.register] = label
            res.acquisitions.append(AcqRecord(op.result_key or op.channel_id, op.register, level, label, iq, t, trace))
            res.timeline.append((t, f"acq_done {op.channel_id} -> r{op.register}={label}"))

        def do_branch(op: Branch, t_decl: int) -> None:
            t_dec = t_decl
            for r in op.condition.registers:
                t_ready, src_gen = ready_at.get(r, (des.now, op.sequencer_id))
                t_dec = max(t_dec, t_ready + c.latency(src_gen, op.sequencer_id))
            if t_dec > des.now:                            # result not yet available: re-arm
                des.schedule_at(t_dec, Prio.BRANCH_DECISION, do_branch, op, t_dec)
                return
            taken = force_branch if force_branch is not None else op.condition.evaluate(regs)
            res.timeline.append((t_dec, f"branch {op.path} -> {'then' if taken else 'else'}"))
            shift = t_dec - (S + op.start)
            for sub in (op.then_ops if taken else op.else_ops):
                schedule(sub, shift)

        def schedule(op, shift: int = 0) -> None:
            t = S + op.start + shift
            if isinstance(op, Play):
                des.schedule_at(t, Prio.PLAYBACK, do_play, op, t)
            elif isinstance(op, FrameOp):
                des.schedule_at(t, Prio.FRAME_UPDATE, do_frame, op, t)
            elif isinstance(op, Acquire):
                des.schedule_at(t, Prio.PLAYBACK, do_acq_start, op, t)
            elif isinstance(op, Branch):
                des.schedule_at(t, Prio.BRANCH_DECISION, do_branch, op, t)

        for op in prog.ops:
            schedule(op)
        des.run_until()
        end = max(des.now, S + shot_duration(prog, c.tof_ticks))
        advance(end)                                       # tail evolution (FB-08)
        t_next = end + (prog.repetition_delay or 0)        # inter-shot relaxation, no hidden reset
        relax = getattr(c.engine, "relax", None)
        if relax is not None and self.lift_log is None:
            relax(c.tb.ticks_to_ns(t_next), rng)            # tiers whose idle noise is unital (T1a)
        else:
            advance(t_next)
        res.end_tick = end
        return res
