"""Standard characterization experiments, built as ordinary QCSS jobs.

The same job runs two ways:
  * in the sandbox (run_in_sandbox): QCSS's own planner and runner, in process, on any draft profile or device; this is
    how the What-If view compares two configurations;
  * on the live chassis (lab.run_experiment): over the lab link, exactly as Qibolab or Qibocal would submit it.
Every timing is aligned to the profile's grids, so the job is valid on whichever instrument the profile describes.
"""
from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Iterable
from typing import Any

import numpy as np
from google.protobuf import json_format
from scipy.optimize import curve_fit

from qcss.config.device import DeviceSpec
from qcss.config.profile import HardwareProfile
from qcss.core.ndarray import from_proto, to_proto
from qcss.runtime.runner import SimulationContext, create_simulation_runner
from qcss.v1 import job_pb2, result_pb2

TIERS = {"AUTO": job_pb2.FIDELITY_TIER_AUTO, "T0": job_pb2.FIDELITY_TIER_T0_SURROGATE,
         "T1A": job_pb2.FIDELITY_TIER_T1A_STABILIZER, "T1B": job_pb2.FIDELITY_TIER_T1B_STATEVECTOR,
         "T2": job_pb2.FIDELITY_TIER_T2_LINDBLAD}

EXPERIMENTS: dict[str, dict[str, str]] = {
    "rabi": {"name": "Rabi (amplitude)", "measures": "pi-pulse amplitude",
             "summary": "Sweep the drive amplitude of a fixed Gaussian pulse; the excited population oscillates as "
                        "cos(theta), theta proportional to the pulse area. The first maximum is the pi pulse."},
    "t1": {"name": "T1 (energy relaxation)", "measures": "T1",
           "summary": "Excite with a pi pulse, wait, measure. The excited population decays as exp(-t/T1) towards "
                      "the thermal floor."},
    "ramsey": {"name": "Ramsey (T2*)", "measures": "T2* and frequency error",
               "summary": "Two pi/2 pulses separated by a delay, the second phase-advanced to fake a detuning. The "
                          "fringe decays with T2*; its frequency reveals how far the drive is from the qubit."},
    "single_shot": {"name": "Single-shot readout", "measures": "assignment fidelity",
                    "summary": "Prepare |0> and |1> many times and record the integrated IQ point of every shot; "
                               "the overlap of the two clouds is the readout error."},
    "spectroscopy": {"name": "Qubit spectroscopy", "measures": "qubit frequency",
                     "summary": "Sweep the drive NCO frequency around the calibrated value; the qubit responds "
                                "where the drive is resonant with f01."},
}


def _up(x: float, grid: int) -> int:
    grid = max(1, int(grid))
    return int(math.ceil(x / grid) * grid)


def _lcm(*xs: int) -> int:
    out = 1
    for x in xs:
        out = out * max(1, x) // math.gcd(out, max(1, x))
    return out


class _Geometry:
    """Timing of one qubit's drive pulse and readout window on the profile's grids."""

    def __init__(self, ctx: SimulationContext, qubit: int, pulse_ns: float = 40.0, readout_ns: float = 1000.0):
        p = ctx.profile
        xy, ro = ctx.bindings.get(f"xy_q{qubit}"), ctx.bindings.get(f"ro_q{qubit}")
        if xy is None or ro is None:
            raise ValueError(f"qubit {qubit} has no drive or readout channel on profile {p.profile_name}")
        self.xy, self.ro = xy, ro
        g, rg = ctx.gens[xy.generator_id], ctx.gens[ro.generator_id]
        self.tick_hz = float(ctx.tb.tick_hz)
        self.tps = ctx.ticks_per_sample[xy.generator_id]
        fs = self.tick_hz / self.tps
        n = max(g.wave_min_samples, round(pulse_ns * 1e-9 * fs))
        n = _up(n, g.wave_granularity_samples)
        while (n * self.tps) % g.rt_granularity_ticks:            # pulse length must stay on the real-time grid
            n += g.wave_granularity_samples
        self.samples = n
        self.pulse_ticks = n * self.tps
        self.grid = _lcm(g.rt_granularity_ticks, rg.rt_granularity_ticks)
        acq = p.acquisition
        integ = _up(readout_ns * 1e-9 * self.tick_hz, acq.integration_granularity_ticks)
        integ = _up(integ, ctx.ticks_per_sample[ro.generator_id])
        self.integration = min(integ, acq.max_square_integration_ticks - acq.max_square_integration_ticks
                               % acq.integration_granularity_ticks)
        modes = {m.value if hasattr(m, "value") else str(m) for m in acq.modes}
        self.discriminated = "discriminated" in modes

    def at(self, ticks: float) -> int:
        return _up(ticks, self.grid)

    def ns(self, ticks: int) -> float:
        return ticks / self.tick_hz * 1e9


def _pi_amplitude_estimate(ctx: SimulationContext, qubit: int, geo: _Geometry) -> float:
    """Amplitude that rotates by pi with the Gaussian envelope, from the device's Rabi rate (sandbox default)."""
    from qcss.ir.waveforms import gaussian

    rabi_ghz = 0.05
    if ctx.device is not None:
        q = next((s for s in ctx.device.qubits if s.qubit_index == qubit), None)
        if q is not None:
            rabi_ghz = q.rabi_max_ghz
    area_ns = float(np.sum(gaussian(geo.samples))) * geo.tps / geo.tick_hz * 1e9
    return float(min(1.0, 0.5 / (rabi_ghz * area_ns)))


def _acquire(geo: _Geometry, qubit: int, start: int, iq: bool = False) -> job_pb2.Instruction:
    mode = (job_pb2.ACQUISITION_MODE_DISCRIMINATED if geo.discriminated and not iq
            else job_pb2.ACQUISITION_MODE_INTEGRATED)
    return job_pb2.Instruction(start_tick=start, acquire=job_pb2.Acquire(
        channel_id=geo.ro.channel_id, integration_ticks=geo.integration, mode=mode, result_key=f"q{qubit}"))


def _play(geo: _Geometry, start: int, amp: float, phase: float = 0.0) -> job_pb2.Instruction:
    return job_pb2.Instruction(start_tick=start, play=job_pb2.Play(channel_id=geo.xy.channel_id, waveform_id="g",
                                                                     amplitude=amp, phase_offset_rad=phase))


def build_job(kind: str, ctx: SimulationContext, *, qubit: int = 0, points: int = 21, shots: int = 500,
              pi_amplitude: float | None = None, max_delay_us: float | None = None, span_mhz: float = 40.0,
              detuning_mhz: float | None = None, seed: int | None = None,
              tier: str = "AUTO") -> tuple[job_pb2.Job, dict[str, Any]]:
    """(job, axis) for one experiment; axis = {name, unit, values} of the swept quantity."""
    if kind not in EXPERIMENTS:
        raise ValueError(f"unknown experiment '{kind}'")
    geo = _Geometry(ctx, qubit)
    pi_amp = pi_amplitude if pi_amplitude is not None else _pi_amplitude_estimate(ctx, qubit, geo)
    job = job_pb2.Job(job_key=f"dashboard_{kind}_q{qubit}", num_shots=shots, requested_tier=TIERS[tier.upper()])
    job.waveform_library["g"].CopyFrom(job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_GAUSSIAN,
                                                        length_samples=geo.samples))
    if seed is not None:
        job.random_seed = seed
    t_acq = geo.at(geo.pulse_ticks)
    t1_us = 50.0
    if ctx.device is not None:
        q = next((s for s in ctx.device.qubits if s.qubit_index == qubit), None)
        t1_us = q.t1_us if q is not None else t1_us

    if kind == "rabi":
        values = np.linspace(0.0, 1.0, points)
        job.main.instructions.extend([_play(geo, 0, 0.0), _acquire(geo, qubit, t_acq)])
        job.sweeps.add(axis=0, amplitude=job_pb2.AmplitudeTarget(instruction_index=0),
                       values=to_proto(values.astype(np.float64)))
        return job, {"name": "drive amplitude", "unit": "FS", "values": values.tolist()}

    if kind == "spectroscopy":
        snap = ctx.calibration.snapshot([])
        f_if = ctx.frame_if(snap)[geo.xy.frame_id]
        values = f_if + np.linspace(-span_mhz, span_mhz, points) * 1e6
        job.main.instructions.extend([_play(geo, 0, pi_amp), _acquire(geo, qubit, t_acq)])
        job.sweeps.add(axis=0, frequency=job_pb2.FrequencyTarget(frame_id=geo.xy.frame_id),
                       values=to_proto(values.astype(np.float64)))
        lo = ctx.profile.port(geo.xy.port_id).lo_frequency_hz or 0.0
        return job, {"name": "drive frequency", "unit": "GHz", "values": ((values + lo) / 1e9).tolist()}

    if kind == "single_shot":
        for i, amp in enumerate((0.0, pi_amp)):
            p = job.program_points.add(indices=[i])
            p.main.instructions.extend([_play(geo, 0, amp), _acquire(geo, qubit, t_acq, iq=True)])
        return job, {"name": "prepared state", "unit": "", "values": [0, 1]}

    if kind == "t1":
        max_s = (max_delay_us if max_delay_us is not None else 4 * t1_us) * 1e-6
        delays = np.linspace(0.0, max_s, points)
        for i, d in enumerate(delays):
            p = job.program_points.add(indices=[i])
            p.main.instructions.extend([_play(geo, 0, pi_amp),
                                        _acquire(geo, qubit, geo.at(geo.pulse_ticks + d * geo.tick_hz))])
        return job, {"name": "delay", "unit": "µs", "values": (delays * 1e6).tolist()}

    # ramsey
    t2_us = t1_us
    if ctx.device is not None:
        q = next((s for s in ctx.device.qubits if s.qubit_index == qubit), None)
        t2_us = q.t2_star_us if q is not None else t2_us
    max_s = (max_delay_us if max_delay_us is not None else 2 * t2_us) * 1e-6
    det_hz = (detuning_mhz * 1e6) if detuning_mhz is not None else 4.0 / max_s
    delays = np.linspace(0.0, max_s, points)
    for i, d in enumerate(delays):
        t2 = geo.at(geo.pulse_ticks + d * geo.tick_hz)
        tau = (t2 - geo.pulse_ticks) / geo.tick_hz
        p = job.program_points.add(indices=[i])
        p.main.instructions.extend([_play(geo, 0, pi_amp / 2),
                                    _play(geo, t2, pi_amp / 2, phase=2 * math.pi * det_hz * tau),
                                    _acquire(geo, qubit, geo.at(t2 + geo.pulse_ticks))])
    return job, {"name": "delay", "unit": "µs", "values": (delays * 1e6).tolist(), "detuning_hz": det_hz}


# ------------------------------------------------------------------ analysis
def summarize(kind: str, chunks: Iterable[result_pb2.ResultChunk], qubit: int, axis: dict[str, Any]) -> dict[str, Any]:
    """Per-point excited population (or IQ clouds) from result chunks, plus the experiment's fit."""
    key = f"q{qubit}"
    states: dict[tuple[int, ...], list[np.ndarray]] = {}
    iqs: dict[tuple[int, ...], list[np.ndarray]] = {}
    warnings: list[str] = []
    for c in chunks:
        warnings.extend(c.warnings)
        for a in c.acquisitions:
            if a.result_key != key:
                continue
            idx = tuple(c.sweep_point)
            states.setdefault(idx, []).append(np.asarray(from_proto(a.states)).reshape(-1))
            iqs.setdefault(idx, []).append(np.asarray(from_proto(a.iq)).reshape(-1))
    order = sorted(states)
    p1 = [float(np.mean(np.concatenate(states[i]) >= 1)) for i in order]
    mean_iq = []
    for i in order:
        m = complex(np.mean(np.concatenate(iqs[i])))
        mean_iq.append([m.real, m.imag])
    out: dict[str, Any] = {"kind": kind, "qubit": qubit, "axis": axis, "p1": p1, "mean_iq": mean_iq,
                           "warnings": sorted(set(warnings))}
    if kind == "single_shot":
        clouds = {str(i[0]): np.concatenate(iqs[i]) for i in order}
        out["iq"] = {k: [[float(z.real), float(z.imag)] for z in v] for k, v in clouds.items()}
        out["fit"] = _fit_single_shot(clouds.get("0"), clouds.get("1"))
    else:
        out["fit"] = _fit(kind, np.asarray(axis["values"], dtype=float), np.asarray(p1), axis)
    return out


def _fit_single_shot(z0: np.ndarray | None, z1: np.ndarray | None) -> dict[str, Any]:
    if z0 is None or z1 is None or not len(z0) or not len(z1):
        return {}
    m0, m1 = complex(np.mean(z0)), complex(np.mean(z1))
    axis = (m1 - m0) / (abs(m1 - m0) or 1.0)
    proj0, proj1 = ((z0 - m0) * np.conj(axis)).real, ((z1 - m0) * np.conj(axis)).real
    thr = abs(m1 - m0) / 2
    e01, e10 = float(np.mean(proj0 > thr)), float(np.mean(proj1 <= thr))
    sigma = float(np.sqrt((np.var(proj0) + np.var(proj1)) / 2)) or 1e-12
    return {"assignment_fidelity": 1 - (e01 + e10) / 2, "p1_given_0": e01, "p0_given_1": e10,
            "rotation_rad": float(np.angle(m1 - m0)), "threshold": float(((m0 + m1) / 2 * np.conj(axis)).real),
            "snr": float(abs(m1 - m0) / sigma), "centers": [[m0.real, m0.imag], [m1.real, m1.imag]]}


def _fit(kind: str, x: np.ndarray, y: np.ndarray, axis: dict[str, Any]) -> dict[str, Any]:
    try:
        if kind == "rabi":
            def f(a, c, d, api):
                return c + d * (1 - np.cos(np.pi * a / api)) / 2
            best = max(np.linspace(0.05, 1.5, 120), key=lambda api: -np.sum((f(x, y.min(), np.ptp(y), api) - y) ** 2))
            (c, d, api), _ = curve_fit(f, x, y, p0=[y.min(), max(np.ptp(y), 0.1), best], maxfev=5000)
            return {"pi_amplitude": float(abs(api)), "contrast": float(d), "offset": float(c),
                    "curve": f(np.linspace(x.min(), x.max(), 200), c, d, api).tolist()}
        if kind == "t1":
            def g(t, c, a, t1):
                return c + a * np.exp(-t / t1)
            (c, a, t1), _ = curve_fit(g, x, y, p0=[y.min(), max(np.ptp(y), 0.1), max(x.max() / 3, 1e-3)],
                                      maxfev=5000)
            return {"t1_us": float(t1), "amplitude": float(a), "offset": float(c),
                    "curve": g(np.linspace(x.min(), x.max(), 200), c, a, t1).tolist()}
        if kind == "ramsey":
            det = float(axis.get("detuning_hz", 0.0)) * 1e-6          # per µs
            def h(t, c, a, t2, df, ph):
                return c + a * np.exp(-t / t2) * np.cos(2 * np.pi * df * t + ph)
            (c, a, t2, df, ph), _ = curve_fit(h, x, y, p0=[0.5, 0.5, max(x.max() / 2, 1e-3), det, 0.0],
                                              maxfev=20000)
            return {"t2_star_us": float(abs(t2)), "fringe_mhz": float(abs(df)),
                    "frequency_error_mhz": float(abs(df) - det), "curve":
                    h(np.linspace(x.min(), x.max(), 200), c, a, t2, df, ph).tolist()}
        if kind == "spectroscopy":
            i = int(np.argmax(y))
            return {"peak_ghz": float(x[i]), "peak_p1": float(y[i])}
    except (RuntimeError, ValueError, TypeError) as exc:
        return {"error": f"fit failed: {exc}"}
    return {}


# ------------------------------------------------------------------ sandbox execution
def run_in_sandbox(kind: str, profile: HardwareProfile, device: DeviceSpec | None, *, qubit: int = 0,
                   points: int = 21, shots: int = 500, seed: int = 1, tier: str = "AUTO",
                   **params: Any) -> dict[str, Any]:
    """Run an experiment through QCSS's planner and runner in this process (frozen chip, fixed seed)."""
    ctx = SimulationContext(profile, device, global_seed=seed)
    job, axis = build_job(kind, ctx, qubit=qubit, points=points, shots=shots, seed=seed, tier=tier, **params)
    plan = ctx.plan(job)
    runner = create_simulation_runner(profile, device, ctx.tb, context=ctx, global_seed=seed)
    cancel = asyncio.Event()

    async def collect() -> list[result_pb2.ResultChunk]:
        return [c async for c in runner(job.job_key, job, cancel)]

    t0 = time.perf_counter()
    chunks = asyncio.run(collect())
    out = summarize(kind, chunks, qubit, axis)
    out.update({"tier": plan.tier, "reason": plan.reason, "elapsed_s": time.perf_counter() - t0, "shots": shots,
                "source": "sandbox", "job": json_format.MessageToDict(job)})
    return out
