"""Simulation runtime: plans jobs at submit time and streams seeded, chunked results.

Plan (at SubmitJob): expand sweeps, compile and validate every point (with real time of flight
and NCO frequencies), lift a dry run of the pulses, route to a tier, check the calibration
epoch. Refusals surface before a job id exists (INVALID_ARGUMENT / FAILED_PRECONDITION).

Run: per sweep point, fixed-size chunks with seed streams keyed by (domain, sweep, chunk)
(plan P10), engine state carried from shot to shot inside a chunk (no hidden reset), device
parameters drawn from the lab-clock device state, compute off the event loop.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import datetime
import multiprocessing
import os
import pickle
import tempfile
import threading
import time
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", tempfile.gettempdir())     # qutip pulls in matplotlib on Windows

import numpy as np

from qcss.config.device import DeviceSpec
from qcss.config.profile import HardwareProfile
from qcss.core.errors import HardwareValidationError, TierRoutingError
from qcss.core.ndarray import to_proto
from qcss.core.seeding import CHUNK_SHOTS, Domain, chunks, job_key, stream
from qcss.core.timebase import TimeBase
from qcss.device.state import DeviceState
from qcss.feedback.executor import ExecContext, QubitModel, ShotExecutor, UnliftableError, shot_duration
from qcss.feedback.latency import FeedbackLatencyResolver, readout_tof_ticks
from qcss.ir.compiler import build_bindings, compile_job, expand_sweeps
from qcss.ir.program import Acquire, Branch, ChannelKind, FrameOp, Play, Program
from qcss.ir.validator import Validator, frame_if_from_bindings
from qcss.ir.waveforms import WaveformLibrary
from qcss.physics.lindblad_t2 import LindbladT2, QutritParams
from qcss.physics.router import route
from qcss.physics.statevector_t1b import StatevectorT1b
from qcss.physics.stim_t1a import StimT1a
from qcss.physics.surrogate_t0 import SurrogateT0
from qcss.physics.transmon import TWO_PI, f01_ghz, nbar_from_excited_population, nbar_from_temperature
from qcss.readout.model import PhysicalReadout, SurrogateReadout, tone_drive
from qcss.runtime.calibration_store import CalibrationEpochError, CalibrationStore

__all__ = ["CalibrationEpochError", "JobInfo", "SimulationContext", "TierRoutingError",
           "create_simulation_runner", "create_simulation_validator"]
from qcss.signal.filters import FluxLineModel
from qcss.signal.mixer import IQCorrection, IQImpairment
from qcss.signal.port_renderer import DriveChain, FluxChain
from qcss.signal.predistortion import QbloxRTP
from qcss.timing.instrument_time import InstrumentPacer
from qcss.v1 import calibration_pb2, device_pb2, job_pb2, result_pb2

REQUESTED = {
    job_pb2.FIDELITY_TIER_UNSPECIFIED: "AUTO",
    job_pb2.FIDELITY_TIER_AUTO: "AUTO",
    job_pb2.FIDELITY_TIER_T0_SURROGATE: "T0",
    job_pb2.FIDELITY_TIER_T1A_STABILIZER: "T1A",
    job_pb2.FIDELITY_TIER_T1B_STATEVECTOR: "T1B",
    job_pb2.FIDELITY_TIER_T2_LINDBLAD: "T2",
    job_pb2.FIDELITY_TIER_T3_TRAJECTORY: "T3",
}
TIER_ENUM = {"T0": job_pb2.FIDELITY_TIER_T0_SURROGATE, "T1A": job_pb2.FIDELITY_TIER_T1A_STABILIZER,
             "T1B": job_pb2.FIDELITY_TIER_T1B_STATEVECTOR, "T2": job_pb2.FIDELITY_TIER_T2_LINDBLAD}
TIER_FIDELITY = {"T0": result_pb2.NOISE_FIDELITY_SURROGATE, "T1A": result_pb2.NOISE_FIDELITY_TWIRLED,
                 "T1B": result_pb2.NOISE_FIDELITY_PHYSICAL, "T2": result_pb2.NOISE_FIDELITY_PHYSICAL}
DEFAULT_FLUX_PHI0_PER_FS = 0.5          # full-scale flux amplitude -> 0.5 Phi0 when the device gives no M_fast
# Gate tiers keep only the qubit subspace, dropping what a pulse leaks. Up to this much per pulse is
# accepted as the gate tiers' approximation (a 20 ns square 2 pi pulse leaks ~2 %, a DRAG gate ~1e-4);
# beyond it the job runs at pulse level (T2): a CZ chevron point 20 MHz from the 11-20 resonance leaks
# ~4 %, at resonance ~25 %.
GATE_TIER_MAX_LEAKAGE = 0.03
NOMINAL_PI_SAMPLES = 20                 # single-qubit gate length when the calibration does not set one
NOMINAL_READOUT_S = 1e-6                # integration window behind the reported readout errors


def _coherence_limited_fidelity(t_s: float, t1_s: float, t2_s: float) -> float:
    """Average gate fidelity of an idle qubit under amplitude and phase damping for t_s."""
    return float((3.0 + np.exp(-t_s / t1_s) + 2.0 * np.exp(-t_s / t2_s)) / 6.0)


ENSEMBLE_RESIDUAL_MAX = 1e-4           # carry-over below this lets T2 evolve once per sweep point (PH-23)


@dataclass
class QubitDefaults:
    f_max_ghz: float
    ec_ghz: float
    d_asym: float
    phi_offset: float
    t1_ns: float
    t2_ns: float
    nbar: float
    rabi_rad_ns: float

    @property
    def f01_ghz(self) -> float:
        return float(f01_ghz(self.phi_offset, self.f_max_ghz, self.ec_ghz, self.d_asym))


@dataclass
class PlannedPoint:
    indices: tuple[int, ...]
    job: job_pb2.Job
    prog: Program
    wf_lib: WaveformLibrary
    probe_hz: dict[int, float] = field(default_factory=dict)    # qubit -> probe frequency set by the program


def _split_probe_frequencies(prog: Program, profile: HardwareProfile) -> tuple[Program, dict[int, float]]:
    """Readout-frame SetFrequency ops set the probe NCO of that point's readout (resonator spectroscopy):
    they leave the program and become a probe frequency, LO + IF, for the readout model."""
    probe: dict[int, float] = {}
    ops = []
    for op in prog.ops:
        b = next((b for b in prog.bindings.values() if b.kind is ChannelKind.READOUT and b.frame_id ==
                  getattr(op, "frame_id", None)), None)
        if isinstance(op, FrameOp) and op.kind == "freq" and b is not None:
            probe[b.qubits[0]] = (profile.port(b.port_id).lo_frequency_hz or 0.0) + op.value
        else:
            ops.append(op)
    if not probe:
        return prog, probe
    return Program(prog.bindings, ops, prog.waveforms, prog.weights, prog.duration, prog.repetition_delay), probe


@dataclass
class JobPlan:
    points: list[PlannedPoint]
    tier: str
    reason: str
    qubits: list[int]                      # device qubits simulated, engine order
    epoch: int
    warnings: list[str] = field(default_factory=list)
    # Calibration pinned at planning: every chunk runs with it, as an instrument keeps what was uploaded.
    snapshot: calibration_pb2.CalibrationSnapshot = field(default_factory=calibration_pb2.CalibrationSnapshot)
    os_set: frozenset[int] = frozenset()

    @property
    def tier_enum(self) -> int:
        return TIER_ENUM[self.tier]

    @property
    def noise_fidelity(self) -> int:
        return TIER_FIDELITY[self.tier]


@dataclass(frozen=True)
class JobInfo:
    tier_used: int
    noise_fidelity: int
    calibration_epoch: int
    warnings: tuple[str, ...] = ()


class _NullEngine:
    """Engine stand-in for the planning dry run (timeline only, no physics)."""
    pulse_level = False

    def advance_to(self, t_ns: float, rng: Any = None) -> None:
        return None

    def measure(self, q: int, t_now: float | None = None, rng: Any = None) -> int:
        return 0


class SimulationContext:
    def __init__(self, profile: HardwareProfile, device: DeviceSpec | None = None, timebase: TimeBase | None = None,
                 calibration: CalibrationStore | None = None, global_seed: int = 0, *,
                 time_scale: float = 0.0, wall_clock: Callable[[], float] = time.monotonic,
                 honour_job_seed: bool = True, tier_policy: str | None = None) -> None:
        """time_scale: lab seconds per wall second while no job runs (0 freezes the chip between jobs).
        honour_job_seed: replay shots from Job.random_seed; a realistic chassis turns it off (hardware can't).
        tier_policy: None honours Job.requested_tier; a tier name ("AUTO", "T2", ...) overrides it, as on a
        lab chassis where the operator, not the client, decides how the physics is computed."""
        self.profile = profile
        self.device = device
        self.tb = timebase if timebase is not None else TimeBase.from_clocks(profile.clock.tick_hz)
        self.global_seed = global_seed
        self.honour_job_seed = honour_job_seed
        self.tier_policy = tier_policy
        self.bindings = build_bindings(profile, device)
        self.gens = {g.generator_id: g for g in profile.generators}
        self.ticks_per_sample = {gid: self.tb.ticks_per(g.sample_rate_hz) for gid, g in self.gens.items()}
        self.tof = {cid: readout_tof_ticks(profile, device, b, self.tb)
                    for cid, b in self.bindings.items() if b.kind is ChannelKind.READOUT}
        self.qdef = self._qubit_defaults()
        self.calibration = calibration if calibration is not None else CalibrationStore(self.default_calibration())
        self._device_state = (DeviceState(device, stream(global_seed, 0, Domain.DRIFT)) if device is not None else None)
        if time_scale < 0:
            raise ValueError("time_scale must be >= 0")
        self.time_scale = time_scale
        self._wall_clock = wall_clock
        self._lab_anchor_s = 0.0
        self._wall_anchor_s = wall_clock()
        self.device_lock = threading.RLock()          # the chip is read and changed from several threads

    def set_time_scale(self, time_scale: float) -> None:
        """Change the pace of lab time from now on (lab time so far is kept)."""
        if time_scale < 0:
            raise ValueError("time_scale must be >= 0")
        now = self.lab_time_s
        self.time_scale = time_scale
        self.lab_time_s = now

    @property
    def device_state(self) -> DeviceState | None:
        """The hidden chip state (drift, defects, scenarios); None without a device file."""
        return self._device_state

    @device_state.setter
    def device_state(self, value: DeviceState | None) -> None:
        self._device_state = value

    @property
    def lab_time_s(self) -> float:
        """Lab time now: the last anchored value plus the scaled wall time spent idle since then."""
        return self._lab_anchor_s + (self._wall_clock() - self._wall_anchor_s) * self.time_scale

    @lab_time_s.setter
    def lab_time_s(self, value: float) -> None:
        self._lab_anchor_s = value
        self._wall_anchor_s = self._wall_clock()

    # ------------------------------------------------------------------ device and calibration
    def _qubit_defaults(self) -> dict[int, QubitDefaults]:
        out = {}
        for q in sorted({q for b in self.bindings.values() for q in b.qubits}):
            spec = None
            if self.device is not None:
                spec = next((s for s in self.device.qubits if s.qubit_index == q), None)
            if spec is None:
                out[q] = QubitDefaults(5.0, 0.3, 0.0, 0.0, 50_000.0, 30_000.0, 0.0, TWO_PI * 0.05)
                continue
            f = float(f01_ghz(spec.phi_offset, spec.f_max_ghz, spec.ec_ghz, spec.d_asym))
            if spec.t_eff_mk is not None:
                nb = nbar_from_temperature(f, spec.t_eff_mk)
            elif spec.p_excited:
                nb = nbar_from_excited_population(spec.p_excited)
            else:
                nb = 0.0
            out[q] = QubitDefaults(spec.f_max_ghz, spec.ec_ghz, spec.d_asym, spec.phi_offset, spec.t1_us * 1e3,
                                   spec.t2_star_us * 1e3, nb, TWO_PI * spec.rabi_max_ghz)
        return out

    def default_calibration(self) -> calibration_pb2.CalibrationSnapshot:
        snap = calibration_pb2.CalibrationSnapshot(calibration_epoch=0)
        for q, d in self.qdef.items():
            qc = snap.qubits.add(qubit_index=q, drive_frequency_hz=d.f01_ghz * 1e9)
            r = self.device.resonator(q) if self.device is not None else None
            if r is not None:
                qc.readout_frequency_hz = r.f_r_ghz * 1e9 + (r.pulls_mhz[0] + r.pulls_mhz[1]) / 2 * 1e6
            ro = self.bindings.get(f"ro_q{q}")
            if ro is not None:
                qc.readout_delay_ticks = self.tof[ro.channel_id]
        return snap

    def _qcal(self, snap: calibration_pb2.CalibrationSnapshot, q: int) -> Any:
        return next((c for c in snap.qubits if c.qubit_index == q), None)

    def device_parameters(self, lab_time_s: float) -> tuple[list[float], list[float]]:
        """(f01 GHz, T1 ns) per device qubit in self.qdef order, at the given lab time."""
        with self.device_lock:
            return self._device_parameters(lab_time_s)

    def _device_parameters(self, lab_time_s: float) -> tuple[list[float], list[float]]:
        qs = list(self.qdef)
        if self._device_state is None:
            return [self.qdef[q].f01_ghz for q in qs], [self.qdef[q].t1_ns for q in qs]
        dt = lab_time_s - self._device_state.clock.t_s
        if dt > 0:
            self._device_state.advance_time(dt)
        f_eff, t1_eff = self._device_state.snapshot()
        idx = {s.qubit_index: i for i, s in enumerate(self.device.qubits)}      # type: ignore[union-attr]
        f_out, t1_out = [], []
        for q in qs:
            d = self.qdef[q]
            if q in idx:   # flux-tuned idle point keeps its offset from f_max
                f_out.append(f_eff[idx[q]] - (d.f_max_ghz - d.f01_ghz))
                t1_out.append(t1_eff[idx[q]])
            else:
                f_out.append(d.f01_ghz)
                t1_out.append(d.t1_ns)
        return f_out, t1_out

    def _physical_readout(self, cid: str, snap: calibration_pb2.CalibrationSnapshot,
                          os_set: frozenset[int]) -> PhysicalReadout | None:
        """The resonator readout of readout channel `cid` under `snap`, or None without resonator data."""
        b = self.bindings[cid]
        q = b.qubits[0]
        r = self.device.resonator(q) if self.device is not None else None
        if r is None:
            return None
        acq = self.profile.acquisition
        qc = self._qcal(snap, q)
        delay = self.tb.ticks_to_ns(qc.readout_delay_ticks) if qc is not None and qc.readout_delay_ticks else None
        return PhysicalReadout(
            r, adc_dt_ns=self.ticks_per_sample[b.generator_id] * 1e9 / float(self.tb.tick_hz),
            tof_ns=self.tb.ticks_to_ns(self.tof[cid]),
            max_states=acq.max_discriminated_states, convention=acq.integration_convention,
            readout_frequency_hz=qc.readout_frequency_hz if qc is not None and qc.readout_frequency_hz else None,
            delay_ns=delay,
            os_rotation_rad=qc.readout_rotation_rad if q in os_set and qc is not None else None,
            os_threshold=qc.readout_threshold if q in os_set and qc is not None else None)

    def device_properties(self) -> device_pb2.DeviceProperties:
        """T1, T2*, readout and coherence-limited gate errors per qubit and coupled pair, now.

        These are modelled, not measured (source "device-model"): QCSS has no randomized
        benchmarking, so gate errors are the coherence limit for the nominal gate duration.
        """
        snap = self.calibration.snapshot([])
        os_set = self.calibration.os_set()
        f_now, t1_now = self.device_parameters(self.lab_time_s)
        props = device_pb2.DeviceProperties(source="device-model", calibration_epoch=snap.calibration_epoch)
        props.measured_at.FromDatetime(datetime.datetime.now(datetime.UTC))
        t2: dict[int, float] = {}
        for i, (q, d) in enumerate(self.qdef.items()):
            t1_s, t2[q] = t1_now[i] * 1e-9, d.t2_ns * 1e-9
            qp = props.qubits.add(qubit_index=q, frequency_hz=f_now[i] * 1e9, t1_s=t1_s, t2_star_s=t2[q],
                                  readout_duration_s=NOMINAL_READOUT_S)
            xy = self.bindings.get(f"xy_q{q}")
            qc = self._qcal(snap, q)
            if xy is not None:
                length = qc.pi_length_samples if qc is not None and qc.pi_length_samples else NOMINAL_PI_SAMPLES
                qp.single_qubit_gate_duration_s = length / float(self.gens[xy.generator_id].sample_rate_hz)
                qp.single_qubit_gate_error = 1.0 - _coherence_limited_fidelity(
                    qp.single_qubit_gate_duration_s, t1_s, t2[q])
            ro = self.bindings.get(f"ro_q{q}")
            phys = self._physical_readout(ro.channel_id, snap, os_set) if ro is not None else None
            if phys is not None:
                n = max(1, round(NOMINAL_READOUT_S * float(self.gens[ro.generator_id].sample_rate_hz)))  # type: ignore[union-attr]
                conf = SurrogateReadout(phys, self.profile.acquisition.max_discriminated_states)._model(
                    n, float(f"{t1_now[i]:.3g}")).c
                qp.prob_meas1_prep0, qp.prob_meas0_prep1 = float(conf[0, 1:].sum()), float(conf[1, 0])
        t1_by_q = {q: p.t1_s for q, p in zip(self.qdef, props.qubits, strict=True)}
        for c in self.device.couplers if self.device is not None else ():
            a, b = c.qubit_pair
            if a not in t1_by_q or b not in t1_by_q or c.j_mhz <= 0:
                continue
            j_hz = c.j_mhz * 1e6
            t = 1.0 / (2.0 * np.sqrt(2.0) * j_hz)       # CZ via the |11>-|02> avoided crossing: t = pi / (sqrt2 * 2 pi J)
            f_proc = ((3 * _coherence_limited_fidelity(t, t1_by_q[a], t2[a]) - 1) / 2
                      * (3 * _coherence_limited_fidelity(t, t1_by_q[b], t2[b]) - 1) / 2)
            props.pairs.add(qubits=[a, b], coupling_hz=j_hz, two_qubit_gate_duration_s=t,
                            two_qubit_gate_error=1.0 - (4 * f_proc + 1) / 5)
        return props

    def drive_frequencies_hz(self, snap: calibration_pb2.CalibrationSnapshot) -> dict[int, float]:
        out = {}
        for q, d in self.qdef.items():
            c = self._qcal(snap, q)
            out[q] = c.drive_frequency_hz if c is not None and c.drive_frequency_hz > 0 else d.f01_ghz * 1e9
        return out

    def frame_if(self, snap: calibration_pb2.CalibrationSnapshot) -> dict[str, float]:
        drive = self.drive_frequencies_hz(snap)
        by_frame = {f"q{q}": f for q, f in drive.items()}
        return frame_if_from_bindings(self.bindings, self.profile, by_frame)

    # ------------------------------------------------------------------ planning
    def plan(self, job: job_pb2.Job) -> JobPlan:
        snap, os_set = self.calibration.pin()
        if job.HasField("expected_calibration_epoch") and job.expected_calibration_epoch != snap.calibration_epoch:
            raise CalibrationEpochError(f"job expects calibration epoch {job.expected_calibration_epoch}, "
                                        f"current is {snap.calibration_epoch}")
        if job.num_shots == 0:
            raise HardwareValidationError([("job.num_shots", "must be > 0")])
        points: list[PlannedPoint] = []
        violations: list[tuple[str, str]] = []
        warnings: list[str] = []
        f_if = self.frame_if(snap)
        validator = Validator(self.profile, self.tb, tof_ticks=self.tof, frame_if_hz=f_if)
        for pt in expand_sweeps(job):
            prefix = "" if not pt.indices else f"sweep{list(pt.indices)}: "
            try:
                prog, wf_lib = compile_job(pt.job, self.profile, self.tb, self.device, bindings=self.bindings)
            except HardwareValidationError as exc:
                violations.extend((prefix + p, d) for p, d in exc.violations)
                continue
            prog, probe = _split_probe_frequencies(prog, self.profile)
            rep = validator.validate(prog, wf_lib)
            violations.extend((prefix + p, d) for p, d in rep.violations)
            warnings.extend(prefix + w for w in rep.warnings)
            points.append(PlannedPoint(pt.indices, pt.job, prog, wf_lib, probe))
        if violations:
            raise HardwareValidationError(violations)

        qubits = self._simulated_qubits(points)
        requested = self.tier_policy or REQUESTED.get(job.requested_tier, "AUTO")
        lifted: list | None = []
        for p in points:
            ev = self.dry_run_lift(p, qubits, snap)
            lifted = None if ev is None or lifted is None else lifted + ev
        leaky = lifted is not None and any(ev.leakage > GATE_TIER_MAX_LEAKAGE for ev in lifted)
        raw_trace = any(isinstance(o, Acquire) and o.mode == "raw_trace" for p in points for o in _all_ops(p.prog.ops))
        decision = route(requested, lifted, len(qubits), needs_leakage=leaky, needs_raw_trace=raw_trace)
        if decision.tier is None:
            raise TierRoutingError(f"Tier routing failed: {decision.reason}")
        return JobPlan(points, decision.tier, decision.reason, qubits, snap.calibration_epoch, warnings,
                       snap, os_set)

    def _simulated_qubits(self, points: list[PlannedPoint]) -> list[int]:
        used: set[int] = set()
        for p in points:
            for op in _all_ops(p.prog.ops):
                cid = getattr(op, "channel_id", None)
                if cid in self.bindings:
                    b = self.bindings[cid]
                    used.update(b.qubits)
                    if b.kind is ChannelKind.FLUX and self.device is not None:
                        for c in self.device.couplers:          # exchange partners take part in flux gates
                            if b.qubits[0] in c.qubit_pair:
                                used.update(c.qubit_pair)
        return sorted(used & set(self.qdef)) or [min(self.qdef)]

    def dry_run_lift(self, p: PlannedPoint, qubits: list[int], snap) -> list | None:
        ex = ShotExecutor(self.exec_context(p, qubits, _NullEngine(), snap, *self.device_parameters(self.lab_time_s),
                                            clifford_required=True))
        ex.lift_log = []
        has_branch = any(isinstance(o, Branch) for o in p.prog.ops)
        rng = np.random.default_rng(0)
        try:
            for force in ((True, False) if has_branch else (None,)):
                ex.run_shot(p.prog, rng, force_branch=force)
        except UnliftableError:
            return None
        return ex.lift_log

    # ------------------------------------------------------------------ execution context
    def exec_context(self, p: PlannedPoint, qubits: list[int], engine: Any, snap, f01_now: list[float],
                     t1_now: list[float], tier: str = "T1B", clifford_required: bool = False,
                     os_set: frozenset[int] | None = None) -> ExecContext:
        prof, dev = self.profile, self.device
        qmap = {q: i for i, q in enumerate(qubits)}
        f_now = dict(zip(self.qdef, f01_now, strict=True))
        t1 = dict(zip(self.qdef, t1_now, strict=True))
        drive_hz = self.drive_frequencies_hz(snap)
        models = []
        for q in qubits:
            d = self.qdef[q]
            phi0 = d.phi_offset

            def flux_det(dphi, d=d, phi0=phi0):
                return TWO_PI * (np.asarray(f01_ghz(phi0 + np.asarray(dphi), d.f_max_ghz, d.ec_ghz, d.d_asym))
                                 - d.f01_ghz)
            models.append(QubitModel(alpha_rad_ns=-TWO_PI * d.ec_ghz,
                                     detuning_rad_ns=TWO_PI * (f_now[q] - d.f01_ghz),
                                     frame_rad_ns=TWO_PI * d.f01_ghz, flux_detuning=flux_det))
        couplings = {}
        if dev is not None:
            for c in dev.couplers:
                a, b = c.qubit_pair
                if a in qmap and b in qmap:
                    couplings[(qmap[a], qmap[b])] = TWO_PI * c.j_mhz * 1e-3
        m_fast = np.zeros((len(qubits), len(qubits)))
        if dev is not None and dev.m_fast is not None:
            full = np.asarray(dev.m_fast, dtype=float)
            for q, i in qmap.items():
                for l_q, j in qmap.items():
                    if q < full.shape[0] and l_q < full.shape[1]:
                        m_fast[i, j] = full[q, l_q]
        else:
            np.fill_diagonal(m_fast, DEFAULT_FLUX_PHI0_PER_FS)

        faults = dev.faults if dev is not None else None
        drive_chains, channel_if, flux_chains = {}, {}, {}
        for cid, b in self.bindings.items():
            fs = float(self.tb.tick_hz / self.ticks_per_sample[b.generator_id])
            port = prof.port(b.port_id)
            if b.kind in (ChannelKind.DRIVE, ChannelKind.CROSS_RESONANCE):
                driven = b.qubits[0]
                target = int(b.frame_id[1:]) if b.frame_id.startswith("q") else driven
                channel_if[cid] = drive_hz.get(target, 0.0) - (port.lo_frequency_hz or 0.0)
                truth = None
                if faults is not None:
                    m = next((x for x in faults.drive_mixers if x.qubit_index == driven), None)
                    if m is not None:
                        truth = IQImpairment(m.gain_i, m.gain_q, m.phase_rad, m.dc_i, m.dc_q)
                corr = None
                qc = self._qcal(snap, driven)
                if qc is not None and qc.HasField("drive_mixer"):
                    mc = qc.drive_mixer
                    corr = IQCorrection(mc.dc_offset_i, mc.dc_offset_q, mc.gain_ratio or 1.0, mc.phase_skew_rad)
                d = self.qdef.get(driven)
                drive_chains[cid] = DriveChain(fs, port.lo_frequency_hz, (d.f01_ghz if d else 5.0) * 1e9,
                                               d.rabi_rad_ns if d else TWO_PI * 0.05, truth, corr)
            elif b.kind is ChannelKind.FLUX and b.port_id not in flux_chains:
                q = b.qubits[0]
                truth = pre = None
                if faults is not None:
                    fl = next((x for x in faults.flux_lines if x.qubit_index == q), None)
                    if fl is not None:
                        truth = FluxLineModel(fs, list(fl.exp_terms), bias_tee_tau_s=fl.bias_tee_tau_s)
                qc = self._qcal(snap, q)
                if qc is not None and qc.HasField("flux_predistortion"):
                    fp = qc.flux_predistortion
                    pre = QbloxRTP(fs)
                    pre.configure([(s.amplitude, s.tau_s) for s in fp.exponential if s.enabled],
                                  fp.inverse_highpass_tau_s if fp.HasField("inverse_highpass_tau_s") else None,
                                  np.asarray(fp.fir_coefficients) if len(fp.fir_coefficients) else None)
                flux_chains[b.port_id] = FluxChain(truth, pre)

        readout, adc = {}, {}
        if os_set is None:
            os_set = self.calibration.os_set()
        acq = prof.acquisition
        for cid, b in self.bindings.items():
            if b.kind is not ChannelKind.READOUT:
                continue
            q = b.qubits[0]
            adc[cid] = self.ticks_per_sample[b.generator_id]
            phys = self._physical_readout(cid, snap, os_set)
            readout[q] = phys if (tier == "T2" and phys is not None) else SurrogateReadout(
                phys, acq.max_discriminated_states)

        first_drive = next((g for g in prof.generators if not g.is_readout), prof.generators[0])
        return ExecContext(
            tb=self.tb, engine=engine, bindings=self.bindings, wf_lib=p.wf_lib, qmap=qmap, qubits=models,
            couplings_rad_ns=couplings, drive_chains=drive_chains, flux_chains=flux_chains, m_fast=m_fast,
            frame_if0=self.frame_if(snap), channel_if0=channel_if, ticks_per_sample=self.ticks_per_sample,
            readout=readout, adc_ticks_per_sample=adc, tof_ticks=self.tof,
            latency=FeedbackLatencyResolver(self.profile).latency_ticks, t1_ns=t1,
            weights={k: np.asarray(_ndarray(w.weights), dtype=np.complex128).reshape(-1)
                     for k, w in p.job.weight_library.items()},
            clifford_required=clifford_required, nco_latched=first_drive.nco_latched,
            nco_phase_steps=first_drive.nco_phase_steps, nco_freq_resolution_hz=first_drive.nco_freq_resolution_hz)

    def make_engine(self, tier: str, qubits: list[int], f01_now: list[float], t1_now: list[float], seed: int) -> Any:
        f = dict(zip(self.qdef, f01_now, strict=True))
        t1 = dict(zip(self.qdef, t1_now, strict=True))
        n = len(qubits)
        t2 = [min(self.qdef[q].t2_ns, 2 * t1[q]) for q in qubits]
        if tier == "T0":
            return SurrogateT0(n, [t1[q] for q in qubits])
        if tier == "T1A":
            return StimT1a(n, [t1[q] for q in qubits], t2, seed=seed)
        if tier == "T1B":
            return StatevectorT1b(n, [t1[q] for q in qubits], t2, nbar=[self.qdef[q].nbar for q in qubits],
                                  seed=seed)
        couplings = {}
        if self.device is not None:
            pos = {q: i for i, q in enumerate(qubits)}
            for c in self.device.couplers:
                a, b = c.qubit_pair
                if a in pos and b in pos:
                    couplings[(pos[a], pos[b])] = c.j_mhz * 1e-3
        return LindbladT2(QutritParams(
            f01_ghz=[f[q] for q in qubits], alpha_ghz=[-self.qdef[q].ec_ghz for q in qubits],
            t1_ns=[t1[q] for q in qubits], t2_ns=t2, nbar=[self.qdef[q].nbar for q in qubits],
            frame_ghz=[self.qdef[q].f01_ghz for q in qubits], couplings_ghz=couplings))

    def default_repetition_delay_ticks(self) -> int:
        """When a job leaves it unset: 10 x the longest T1, so a shot starts near equilibrium."""
        t1_max = max(d.t1_ns for d in self.qdef.values())
        return int(np.ceil(10 * t1_max * float(self.tb.tick_hz) * 1e-9))

    # ------------------------------------------------------------------ one chunk
    def simulate_chunk(self, plan: JobPlan, point: int, chunk_index: int, n_shots: int, key: int,
                       f01_now: list[float], t1_now: list[float], base_tick: int) -> dict:
        p = plan.points[point]
        prog = p.prog
        if prog.repetition_delay is None:
            prog = Program(prog.bindings, prog.ops, prog.waveforms, prog.weights, prog.duration,
                           self.default_repetition_delay_ticks())
        rng = stream(self.global_seed, key, Domain.SHOTS, point, chunk_index)
        ro_rng = stream(self.global_seed, key, Domain.READOUT, point, chunk_index)
        engine = self.make_engine(plan.tier, plan.qubits, f01_now, t1_now,
                                  seed=int(stream(self.global_seed, key, Domain.STIM, point, chunk_index).integers(2**31)))
        snap = plan.snapshot
        if p.probe_hz:
            snap = calibration_pb2.CalibrationSnapshot()
            snap.CopyFrom(plan.snapshot)
            for qc in snap.qubits:
                if qc.qubit_index in p.probe_hz:
                    qc.readout_frequency_hz = p.probe_hz[qc.qubit_index]
        ctx = self.exec_context(PlannedPoint(p.indices, p.job, prog, p.wf_lib), plan.qubits, engine, snap,
                                f01_now, t1_now, tier=plan.tier, clifford_required=plan.tier == "T1A",
                                os_set=plan.os_set)
        ctx.latency = FeedbackLatencyResolver(self.profile, stream(self.global_seed, key, Domain.JITTER, point,
                                                                    chunk_index)).latency_ticks
        ex = ShotExecutor(ctx)
        out: dict[str, dict[str, list]] = {}

        def add(key_: str, label: int, iq: complex, end_tick: int, trace) -> None:
            d = out.setdefault(key_, {"states": [], "iq": [], "end": [], "trace": []})
            d["states"].append(label)
            d["iq"].append(iq)
            d["end"].append(end_tick)
            if trace is not None:
                d["trace"].append(trace)

        if plan.tier == "T2" and _ensemble_eligible(prog):
            dur = shot_duration(prog, ctx.tof_ticks)
            res = ex.run_shot(prog, rng, ro_rng, ensemble=True)
            qs, probs = ex.ensemble_probs                      # type: ignore[misc]
            residual = 0.5 * float((engine.rho - engine.thermal_state()).norm("tr"))
            if residual <= ENSEMBLE_RESIDUAL_MAX:
                joint = rng.choice(len(probs), size=n_shots, p=probs)
                levels = {q: (joint // 3 ** (len(qs) - 1 - i)) % 3 for i, q in enumerate(qs)}
                period = res.end_tick + (prog.repetition_delay or 0)
                ends = base_tick + np.arange(n_shots) * period + dur
                for op in sorted((o for o in prog.ops if isinstance(o, Acquire)), key=lambda o: o.path):
                    q_dev = ctx.bindings[op.channel_id].qubits[0]
                    per = ctx.adc_ticks_per_sample[op.channel_id]
                    n = op.integration // per
                    tone = max((o for o in prog.ops if isinstance(o, Play) and o.channel_id == op.channel_id
                                and o.start <= op.start), key=lambda o: o.start, default=None)
                    drive = None if tone is None else tone_drive(
                        tone.amplitude, (op.start - tone.start) // per,
                        len(ctx.wf_lib.get(ctx.bindings[op.channel_id].generator_id, tone.waveform_id)),
                        tone.phase_offset)
                    r = ctx.readout[q_dev].acquire(levels[ctx.qmap[q_dev]], n, ctx.t1_ns[q_dev], ro_rng,
                                                   ctx.weights.get(op.weights_id), op.mode == "raw_trace",
                                                   drive=drive)
                    for k in range(n_shots):
                        add(op.result_key or op.channel_id, int(r.labels[k]), complex(r.iq[k]), int(ends[k]),
                            None if r.traces is None else r.traces[k])
                return {"acq": out, "end_tick": int(base_tick + n_shots * period)}
            engine.reset_state()                               # carry-over matters: simulate shot by shot
            for ch in ctx.flux_chains.values():
                ch.reset()

        t = 0
        for _ in range(n_shots):
            res = ex.run_shot(prog, rng, ro_rng, shot_start_tick=t)
            for a in res.acquisitions:
                add(a.result_key, a.label, a.iq, base_tick + res.end_tick, a.trace)
            t = res.end_tick + (prog.repetition_delay or 0)
        return {"acq": out, "end_tick": base_tick + t}


def _ndarray(m):
    from qcss.core.ndarray import from_proto
    return from_proto(m)


def _all_ops(ops):
    for op in ops:
        yield op
        if isinstance(op, Branch):
            yield from _all_ops(op.then_ops)
            yield from _all_ops(op.else_ops)


def _ensemble_eligible(prog: Program) -> bool:
    """T2 may evolve once per sweep point when no feedback exists and all qubits are read out
    together at the end (one acquisition tick, each qubit once)."""
    if any(isinstance(o, Branch) for o in prog.ops):
        return False
    acqs = [o for o in prog.ops if isinstance(o, Acquire)]
    if not acqs or len({a.start for a in acqs}) != 1:
        return False
    qs = [prog.bindings[a.channel_id].qubits[0] for a in acqs]
    if len(qs) != len(set(qs)):
        return False
    t_acq = acqs[0].start
    return all(getattr(o, "start", 0) < t_acq for o in prog.ops if not isinstance(o, Acquire))


def _chunk_proto(job_id: str, seq: int, offset: int, point: PlannedPoint, result: dict, epoch: int,
                 is_last: bool, warnings: list[str]) -> result_pb2.ResultChunk:
    acqs = []
    for key_, d in result["acq"].items():
        iq = (np.asarray(d["trace"], dtype=np.complex64) if d["trace"] else np.asarray(d["iq"], dtype=np.complex64))
        acqs.append(result_pb2.AcquisitionResult(
            result_key=key_, iq=to_proto(iq), states=to_proto(np.asarray(d["states"], dtype=np.uint8)),
            shot_end_ticks=to_proto(np.asarray(d["end"], dtype=np.uint64))))
    n = max((len(d["states"]) for d in result["acq"].values()), default=0)
    return result_pb2.ResultChunk(job_id=job_id, sequence_number=seq, sweep_point=list(point.indices),
                                  shot_offset=offset, num_shots_in_chunk=n, acquisitions=acqs,
                                  calibration_epoch=epoch, is_last=is_last, warnings=warnings)


# ---------------------------------------------------------------------- process-pool workers
# Chunks travel to our own spawn workers as pickles: the same trusted parent->child IPC that
# concurrent.futures uses for every call. Nothing from the network is ever unpickled.
_WORKER_CTX: dict[bytes, SimulationContext] = {}


def _worker_init() -> None:
    for var in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS"):
        os.environ[var] = "1"


def _worker_chunk(blob: bytes) -> dict:
    ctx_key, profile, device, snap_bytes, os_set, seed, args = pickle.loads(blob)
    ctx = _WORKER_CTX.get(ctx_key)
    if ctx is None:
        snap = calibration_pb2.CalibrationSnapshot.FromString(snap_bytes)
        store = CalibrationStore(snap)
        store._os_set = set(os_set)
        ctx = SimulationContext(profile, device, calibration=store, global_seed=seed)
        _WORKER_CTX.clear()
        _WORKER_CTX[ctx_key] = ctx
    return ctx.simulate_chunk(*args)


# ---------------------------------------------------------------------- public factories
def create_simulation_validator(profile: HardwareProfile, timebase: TimeBase, device: DeviceSpec | None = None,
                                *, context: SimulationContext | None = None):
    ctx = context if context is not None else SimulationContext(profile, device, timebase)

    async def validate_job(job: job_pb2.Job) -> JobInfo:
        plan = await asyncio.to_thread(ctx.plan, job)
        return JobInfo(plan.tier_enum, plan.noise_fidelity, plan.epoch, tuple(plan.warnings))

    validate_job.context = ctx            # type: ignore[attr-defined]
    return validate_job


def create_simulation_runner(profile: HardwareProfile, device: DeviceSpec | None = None,
                             timebase: TimeBase | None = None, chunk_size: int = CHUNK_SHOTS, *,
                             context: SimulationContext | None = None, workers: int = 0, global_seed: int = 0,
                             pacer: InstrumentPacer | None = None):
    """workers = 0: compute in a thread (keeps the event loop responsive);
    workers > 0: a persistent spawn process pool (Windows-safe, one BLAS thread per worker).
    pacer: make each job take its upload latency plus its lab time in wall time, as on an instrument."""
    ctx = context if context is not None else SimulationContext(profile, device, timebase, global_seed=global_seed)
    pool: concurrent.futures.ProcessPoolExecutor | None = None
    if workers > 0:
        pool = concurrent.futures.ProcessPoolExecutor(max_workers=workers, initializer=_worker_init,
                                                      mp_context=multiprocessing.get_context("spawn"))

    async def run_chunk(plan: JobPlan, args: tuple) -> dict:
        if pool is None:
            return await asyncio.to_thread(ctx.simulate_chunk, plan, *args)
        snap = ctx.calibration.snapshot()
        ctx_key = pickle.dumps((profile.model_dump_json(), device.model_dump_json() if device else "",
                                snap.SerializeToString(), sorted(ctx.calibration.os_set()), ctx.global_seed))
        blob = pickle.dumps((ctx_key, profile, device, snap.SerializeToString(), sorted(ctx.calibration.os_set()),
                             ctx.global_seed, (plan, *args)))
        return await asyncio.get_running_loop().run_in_executor(pool, _worker_chunk, blob)

    async def runner(job_id: str, job: job_pb2.Job, cancel: asyncio.Event) -> AsyncIterator[result_pb2.ResultChunk]:
        plan = await asyncio.to_thread(ctx.plan, job)
        key = job_key(job.random_seed if ctx.honour_job_seed and job.HasField("random_seed") else None, job_id)
        num_shots = int(job.num_shots)
        work = [(pi, ci, n) for pi in range(len(plan.points)) for ci, n in chunks(num_shots, chunk_size)]
        paced = await pacer.begin(cancel) if pacer is not None else None
        seq, tick = 1, 0
        lab0 = ctx.lab_time_s
        tick_s = 1.0 / float(ctx.tb.tick_hz)
        for i, (pi, ci, n) in enumerate(work):
            if cancel.is_set():
                break
            f01, t1 = ctx.device_parameters(lab0 + tick * tick_s)
            result = await run_chunk(plan, (pi, ci, n, key, f01, t1, tick))
            tick = result["end_tick"]
            if paced is not None:
                await paced.pace(tick * tick_s, cancel)
            yield _chunk_proto(job_id, seq, ci * chunk_size, plan.points[pi], result, plan.epoch,
                               i == len(work) - 1, plan.warnings if i == 0 else [])
            seq += 1
        # The chip is at least as old as the job's shots made it, and never younger than the scaled wall clock:
        # a simulation slower than real time does not hand that overrun back (time on an instrument only runs on).
        ctx.lab_time_s = max(lab0 + tick * tick_s, ctx.lab_time_s)

    runner.context = ctx                  # type: ignore[attr-defined]
    runner.pool = pool                    # type: ignore[attr-defined]
    return runner
