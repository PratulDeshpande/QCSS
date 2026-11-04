"""The sandbox: run one job through QCSS's real pipeline in this process, keeping what the chassis throws away.

Inside a chassis the rendered drive, the shot timeline, the lifted gates and the quantum state are computed and
discarded chunk by chunk. Here the same objects (SimulationContext, ShotExecutor, the engines) run on a copy of the
configuration with nothing hidden, so every stage of Plan -> Render -> Evolve -> Read out -> Stream can be shown.
The live chassis and the lab link are never touched.
"""
from __future__ import annotations

import asyncio
import itertools
import time
from typing import Any

import numpy as np
from google.protobuf import json_format

from qcss.config.device import DeviceSpec
from qcss.config.profile import HardwareProfile
from qcss.core.errors import HardwareValidationError, TierRoutingError
from qcss.core.ndarray import from_proto
from qcss.feedback.executor import ShotExecutor
from qcss.feedback.latency import FeedbackLatencyResolver
from qcss.ir.program import Acquire, Branch, FrameOp, Play, Program
from qcss.ir.saturation import render_port_iq
from qcss.runtime.calibration_store import CalibrationEpochError
from qcss.runtime.runner import PlannedPoint, SimulationContext, create_simulation_runner
from qcss.v1 import job_pb2, result_pb2
from qcss_dashboard.experiments import TIERS

MAX_SHOTS = 2000


def _ds(n: int, max_pts: int = 300) -> np.ndarray:
    if n <= max_pts:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, max_pts).round().astype(int))


def _op_dict(op: Any, arm: str = "") -> list[dict[str, Any]]:
    base = {"path": op.path, "start": getattr(op, "start", 0), "arm": arm}
    if isinstance(op, Play):
        return [{**base, "kind": "play", "channel_id": op.channel_id, "duration": op.duration,
                 "waveform_id": op.waveform_id, "amplitude": op.amplitude, "phase_offset": op.phase_offset}]
    if isinstance(op, FrameOp):
        return [{**base, "kind": f"frame:{op.kind}", "frame_id": op.frame_id, "value": op.value, "duration": 0}]
    if isinstance(op, Acquire):
        return [{**base, "kind": "acquire", "channel_id": op.channel_id, "duration": op.integration,
                 "mode": op.mode, "register": op.register, "result_key": op.result_key}]
    if isinstance(op, Branch):
        out = [{**base, "kind": "branch", "sequencer_id": op.sequencer_id, "duration": op.duration,
                "condition": {"op": op.condition.op, "registers": list(op.condition.registers),
                              "value": op.condition.value}}]
        for sub in op.then_ops:
            out += _op_dict(sub, "then")
        for sub in op.else_ops:
            out += _op_dict(sub, "else")
        return out
    return [{**base, "kind": type(op).__name__.lower(), "duration": 0}]


class _Recorder(ShotExecutor):
    """A ShotExecutor that also keeps every rendered segment (what the qubit actually saw)."""

    def __init__(self, ctx: Any) -> None:
        super().__init__(ctx)
        self.segments: list[tuple[str, Any]] = []

    def _render(self, op, b, t_abs, shot_start, tr):          # type: ignore[override]
        seg = super()._render(op, b, t_abs, shot_start, tr)
        if seg is not None:
            self.segments.append((op.channel_id, seg))
        return seg


def _without_acquisitions(prog: Program) -> Program:
    ops = tuple(o for o in prog.ops if not isinstance(o, Acquire | Branch))
    return Program(prog.bindings, list(ops), prog.waveforms, prog.weights, prog.duration, 0)


def _bloch(rho2: np.ndarray) -> list[float]:
    """Bloch vector of the qubit (0-1) subspace of a qutrit density matrix."""
    return [float(2 * np.real(rho2[0, 1])), float(-2 * np.imag(rho2[0, 1])), float(np.real(rho2[0, 0] - rho2[1, 1]))]


def explain(profile: HardwareProfile, device: DeviceSpec | None, job_json: dict[str, Any], *, tier: str = "AUTO",
            seed: int = 1, shots: int = 200, point: int = 0) -> dict[str, Any]:
    stages: list[dict[str, Any]] = []
    t0 = time.perf_counter()
    job = json_format.ParseDict(job_json, job_pb2.Job(), ignore_unknown_fields=False)
    job.num_shots = max(1, min(int(shots), MAX_SHOTS))
    job.requested_tier = TIERS.get(tier.upper(), job_pb2.FIDELITY_TIER_AUTO)
    job.random_seed = seed
    ctx = SimulationContext(profile, device, global_seed=seed)
    try:
        plan = ctx.plan(job)
    except HardwareValidationError as exc:
        return {"valid": False, "stage": "plan", "violations": [{"path": p, "description": d}
                                                                for p, d in exc.violations]}
    except (TierRoutingError, CalibrationEpochError) as exc:
        return {"valid": False, "stage": "route", "violations": [{"path": "job.requested_tier",
                                                                  "description": str(exc)}]}
    stages.append({"id": "plan", "ms": (time.perf_counter() - t0) * 1e3,
                   "summary": f"{len(plan.points)} point(s), tier {plan.tier}: {plan.reason}"})
    k = max(0, min(point, len(plan.points) - 1))
    p = plan.points[k]
    snap = plan.snapshot
    f_now, t1_now = ctx.device_parameters(ctx.lab_time_s)
    tick_ns = 1e9 / float(ctx.tb.tick_hz)

    # -------- program and waveforms (compiler output)
    ops: list[dict[str, Any]] = []
    for op in p.prog.ops:
        ops += _op_dict(op)
    for o in ops:
        if "channel_id" in o and o["channel_id"] in p.prog.bindings:
            b = p.prog.bindings[o["channel_id"]]
            o["generator_id"], o["port_id"], o["frame_id"] = b.generator_id, b.port_id, b.frame_id
        o["start_ns"], o["duration_ns"] = o["start"] * tick_ns, o.get("duration", 0) * tick_ns
    waveforms: dict[str, Any] = {}
    plays = [o for o in p.prog.ops if isinstance(o, Play)]
    for wid in p.prog.waveforms:
        user = next((o for o in plays if o.waveform_id == wid), None)
        if user is None:
            continue
        gen = p.prog.bindings[user.channel_id].generator_id
        env = np.asarray(p.wf_lib.get(gen, wid))
        dt = ctx.ticks_per_sample[gen] * tick_ns
        waveforms[wid] = {"generator_id": gen, "dt_ns": dt, "i": np.real(env).tolist(), "q": np.imag(env).tolist(),
                          "spec": json_format.MessageToDict(p.job.waveform_library[wid])
                          if wid in p.job.waveform_library else {}}
    # Port streams: the summed NCO-modulated I/Q the validator checks against full scale.
    f_if = ctx.frame_if(snap)
    ports: dict[str, Any] = {}
    by_port: dict[str, list[Play]] = {}
    for o in plays:
        by_port.setdefault(p.prog.bindings[o.channel_id].port_id, []).append(o)
    for port_id, pl in by_port.items():
        gen = p.prog.bindings[pl[0].channel_id].generator_id
        per = ctx.ticks_per_sample[gen]
        fs = float(ctx.tb.tick_hz) / per
        spec = []
        for o in pl:
            b = p.prog.bindings[o.channel_id]
            env = np.asarray(p.wf_lib.get(b.generator_id, o.waveform_id))
            fi = f_if.get(b.frame_id, 0.0)
            s0 = o.start // per
            spec.append((s0, env, o.amplitude, fi, o.phase_offset + 2 * np.pi * fi * s0 / fs))
        n_total = max(s + len(e) for s, e, *_ in spec)
        x = render_port_iq(n_total, fs, spec)
        i = _ds(n_total, 600)
        port = profile.port(port_id)
        ports[port_id] = {"t_ns": (i * per * tick_ns).tolist(), "i": np.real(x[i]).tolist(), "q": np.imag(x[i]).tolist(),
                          "full_scale": port.full_scale_per_path, "policy": port.saturation_policy.value,
                          "peak": float(max(np.max(np.abs(np.real(x))), np.max(np.abs(np.imag(x)))))}

    # -------- lift (what each pulse does as a gate; decides the tier)
    t1 = time.perf_counter()
    lifted = ctx.dry_run_lift(p, plan.qubits, snap) or []
    lift = []
    for ev in lifted:
        u = np.asarray(ev.unitary)
        lift.append({"name": ev.name, "qubits": [plan.qubits[q] for q in ev.qubits], "t_start_ns": ev.t_start,
                     "t_end_ns": ev.t_end, "leakage": float(ev.leakage), "clifford_fidelity": float(ev.clifford_fidelity),
                     "is_clifford": ev.is_clifford,
                     "unitary": [[[float(np.real(z)), float(np.imag(z))] for z in row] for row in u]})
    stages.append({"id": "lift", "ms": (time.perf_counter() - t1) * 1e3,
                   "summary": f"{len(lift)} pulse(s) lifted; max leakage "
                              f"{max((e['leakage'] for e in lift), default=0):.2e}"})

    # -------- one shot, recorded (render + evolve + read out)
    t2 = time.perf_counter()
    prog = Program(p.prog.bindings, p.prog.ops, p.prog.waveforms, p.prog.weights, p.prog.duration, 0)
    engine = ctx.make_engine(plan.tier, plan.qubits, f_now, t1_now, seed=seed)
    ectx = ctx.exec_context(PlannedPoint(p.indices, p.job, prog, p.wf_lib), plan.qubits, engine, snap, f_now,
                            t1_now, tier=plan.tier, clifford_required=plan.tier == "T1A", os_set=plan.os_set)
    ectx.latency = FeedbackLatencyResolver(profile, np.random.default_rng(seed)).latency_ticks
    rec = _Recorder(ectx)
    rng = np.random.default_rng(seed)
    res = rec.run_shot(prog, rng, np.random.default_rng(seed + 1))
    segments = []
    for cid, s in rec.segments:
        i = _ds(len(s.samples))
        segments.append({"channel_id": cid, "kind": s.kind, "qubit": plan.qubits[s.index] if s.kind == "drive"
                         else s.index, "t0_ns": s.t0_ns, "dt_ns": s.dt_ns,
                         "t_ns": (s.t0_ns + i * s.dt_ns).tolist(),
                         "re": np.real(s.samples[i]).tolist(), "im": np.imag(s.samples[i]).tolist()})
    shot = {"timeline": [{"tick": t, "ns": t * tick_ns, "event": e} for t, e in res.timeline],
            "acquisitions": [{"result_key": a.result_key, "register": a.register, "level": a.level, "label": a.label,
                              "iq": [a.iq.real, a.iq.imag], "end_ns": a.end_tick * tick_ns} for a in res.acquisitions],
            "segments": segments, "end_ns": res.end_tick * tick_ns}
    stages.append({"id": "render", "ms": (time.perf_counter() - t2) * 1e3,
                   "summary": f"{len(segments)} segment(s) rendered through NCO, mixers and lines"})

    # -------- the quantum state just before measurement, and its trajectory through the pulses (T2 engine)
    t3 = time.perf_counter()
    pre = _without_acquisitions(prog)
    eng2 = ctx.make_engine(plan.tier, plan.qubits, f_now, t1_now, seed=seed)
    ectx2 = ctx.exec_context(PlannedPoint(p.indices, p.job, pre, p.wf_lib), plan.qubits, eng2, snap, f_now, t1_now,
                             tier=plan.tier, clifford_required=plan.tier == "T1A", os_set=plan.os_set)
    ShotExecutor(ectx2).run_shot(pre, np.random.default_rng(seed))
    state: dict[str, Any] = {"tier": plan.tier, "qubits": plan.qubits,
                             "populations": [np.asarray(eng2.level_probabilities(i)).tolist()
                                             for i in range(len(plan.qubits))]}
    if hasattr(eng2, "rho"):
        rho = eng2.rho
        state["bloch"] = [_bloch(np.asarray((rho.ptrace(i) if len(plan.qubits) > 1 else rho).full()))
                          for i in range(len(plan.qubits))]
        state["rho_abs"] = np.abs(np.asarray(rho.full())).tolist() if rho.shape[0] <= 9 else None
    state["trajectory"] = _trajectory(ctx, plan.qubits, f_now, t1_now, segments=rec.segments,
                                      end_ns=res.end_tick * tick_ns)
    stages.append({"id": "evolve", "ms": (time.perf_counter() - t3) * 1e3,
                   "summary": f"engine {type(eng2).__name__}; populations before readout"})

    # -------- the full job, chunked and streamed like the chassis does
    t4 = time.perf_counter()
    runner = create_simulation_runner(profile, device, ctx.tb, context=ctx, global_seed=seed)

    async def collect() -> list[result_pb2.ResultChunk]:
        return [c async for c in runner(job.job_key or "explain", job, asyncio.Event())]

    chunks = asyncio.run(collect())
    pts: dict[tuple[int, ...], dict[str, Any]] = {}
    for c in chunks:
        d = pts.setdefault(tuple(c.sweep_point), {"indices": list(c.sweep_point), "p1": {}, "mean_iq": {},
                                                   "_s": {}, "_z": {}})
        for a in c.acquisitions:
            d["_s"].setdefault(a.result_key, []).append(np.asarray(from_proto(a.states)).reshape(-1))
            d["_z"].setdefault(a.result_key, []).append(np.asarray(from_proto(a.iq)).reshape(-1))
    points = []
    for idx in sorted(pts):
        d = pts[idx]
        for key, s in d.pop("_s").items():
            d["p1"][key] = float(np.mean(np.concatenate(s) >= 1))
        for key, z in d.pop("_z").items():
            m = complex(np.mean(np.concatenate(z)))
            d["mean_iq"][key] = [m.real, m.imag]
        points.append(d)
    stages.append({"id": "stream", "ms": (time.perf_counter() - t4) * 1e3,
                   "summary": f"{len(chunks)} chunk(s) of up to 1024 shots"})
    return {
        "valid": True, "warnings": plan.warnings,
        "plan": {"tier": plan.tier, "reason": plan.reason, "qubits": plan.qubits, "epoch": plan.epoch,
                 "n_points": len(plan.points), "point": k, "indices": list(p.indices)},
        "program": {"ops": ops, "duration_ns": p.prog.duration * tick_ns, "tick_ns": tick_ns,
                    "bindings": {c: {"generator_id": b.generator_id, "port_id": b.port_id, "frame_id": b.frame_id,
                                     "kind": b.kind.name.lower(), "qubits": list(b.qubits)}
                                 for c, b in p.prog.bindings.items()
                                 if any(o.get("channel_id") == c for o in ops)}},
        "waveforms": waveforms, "ports": ports, "lift": lift, "shot": shot, "state": state,
        "results": {"points": points, "shots": job.num_shots}, "stages": stages,
        "chip_now": {"f01_ghz": dict(zip(map(str, ctx.qdef), f_now, strict=True)),
                     "t1_us": {str(q): t / 1e3 for q, t in zip(ctx.qdef, t1_now, strict=True)}},
    }


def _trajectory(ctx: SimulationContext, qubits: list[int], f_now: list[float], t1_now: list[float], *,
                segments: list[tuple[str, Any]], end_ns: float, slices: int = 60) -> dict[str, Any]:
    """Populations and Bloch vectors through the drive pulses, re-evolved slice by slice on the T2 engine."""
    drive = [s for _, s in segments if s.kind == "drive"]
    if not drive or len(qubits) > 2:
        return {"t_ns": [], "populations": [], "bloch": [], "note": "trajectory needs 1-2 driven qubits"}
    eng = ctx.make_engine("T2", qubits, f_now, t1_now, seed=0)
    t_end = max(s.t1_ns for s in drive)
    times, pops, blochs = [0.0], [[eng.level_probabilities(i).tolist() for i in range(len(qubits))]], []

    def bloch_now() -> list[list[float]]:
        rho = eng.rho
        return [_bloch(np.asarray((rho.ptrace(i) if len(qubits) > 1 else rho).full())) for i in range(len(qubits))]

    blochs.append(bloch_now())
    edges = np.linspace(min(s.t0_ns for s in drive), t_end, slices + 1)
    for a, b in itertools.pairwise(edges):
        drives: dict[int, np.ndarray] = {}
        dt = None
        for s in drive:
            k0 = int(np.clip(np.floor((a - s.t0_ns) / s.dt_ns), 0, len(s.samples)))
            k1 = int(np.clip(np.ceil((b - s.t0_ns) / s.dt_ns), 0, len(s.samples)))
            if k1 > k0:
                drives[s.index] = drives.get(s.index, 0) + s.samples[k0:k1]
                dt = s.dt_ns
        if drives and dt is not None:
            n = min(len(v) for v in drives.values())
            eng.evolve_segment(max(a, eng.clock), dt, drives={q: v[:n] for q, v in drives.items()})
        else:
            eng.advance_to(b)
        times.append(float(eng.clock))
        pops.append([eng.level_probabilities(i).tolist() for i in range(len(qubits))])
        blochs.append(bloch_now())
    return {"t_ns": times, "populations": pops, "bloch": blochs, "qubits": qubits, "end_ns": end_ns}
