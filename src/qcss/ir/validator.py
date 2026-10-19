"""Hardware-rule validator. Every rule reads its numbers from the HardwareProfile.

Collects ALL violations (with proto field paths) instead of stopping at the first one,
so the OS sees a complete, machine-readable report. The then/else arms of a branch are
mutually exclusive, so per-generator rules (overlap, acquisition spacing) are checked
along each possible execution path, never across two arms.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import numpy as np

from qcss.config.profile import AcqMode, HardwareProfile, OverlapPolicy, SaturationPolicy
from qcss.core.timebase import TimeBase
from qcss.feedback.latency import LatencyRouteError, lookup_latency
from qcss.ir.program import Acquire, Branch, ChannelKind, FrameOp, Play, Program
from qcss.ir.saturation import check as check_saturation
from qcss.ir.saturation import render_port_iq
from qcss.ir.waveforms import WaveformLibrary


@dataclass
class ValidationReport:
    violations: list[tuple[str, str]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def error(self, path: str, msg: str) -> None:
        self.violations.append((path, msg))

    @property
    def ok(self) -> bool:
        return not self.violations


def _flat_arm(ops) -> list:
    out = []
    for op in ops:
        out.append(op)
        if isinstance(op, Branch):
            out.extend(_flat_arm(op.then_ops))
            out.extend(_flat_arm(op.else_ops))
    return out


def _paths(ops) -> list[list]:
    """Execution scenarios, linear in the number of branches: the unconditional ops alone, then
    the unconditional ops plus ONE arm of one top-level branch (anything nested in it included).
    Two arms of the same branch never meet in a scenario."""
    main = [op for op in ops if not isinstance(op, Branch)]
    scenarios = [main + [op for op in ops if isinstance(op, Branch)]]
    for op in ops:
        if isinstance(op, Branch):
            for arm in (op.then_ops, op.else_ops):
                if arm:
                    scenarios.append(main + [op] + _flat_arm(arm))
    return scenarios


class Validator:
    def __init__(self, profile: HardwareProfile, timebase: TimeBase, *,
                 tof_ticks: dict[str, int] | None = None,
                 frame_if_hz: dict[str, float] | None = None) -> None:
        self.p = profile
        self.tb = timebase
        self.gen = {g.generator_id: g for g in profile.generators}
        self.ports = {p.port_id: p for p in profile.ports}
        self.tof = tof_ticks or {}            # readout channel -> total ToF (internal + cable + filters)
        self.frame_if = frame_if_hz or {}     # frame -> NCO (IF) frequency used to render the port signal

    # ------------------------------------------------------------------------------
    def validate(self, prog: Program, wf_lib: WaveformLibrary | None = None) -> ValidationReport:
        rep = ValidationReport()
        flat = list(self._flatten(prog.ops))
        paths = _paths(prog.ops)
        self._plays(prog, flat, rep)
        self._overlaps(prog, paths, rep)
        self._memory(prog, flat, rep)
        self._frame_ops(prog, flat, rep)
        self._acquisitions(prog, flat, paths, rep)
        self._branches(prog, prog.ops, {}, rep)
        self._instruction_budget(prog, flat, rep)
        self._saturation(prog, paths, wf_lib, rep)
        rep.violations = list(dict.fromkeys(rep.violations))      # a rule seen on several paths reports once
        rep.warnings = list(dict.fromkeys(rep.warnings))
        return rep

    @staticmethod
    def _flatten(ops):
        for op in ops:
            yield op
            if isinstance(op, Branch):
                yield from Validator._flatten(op.then_ops)
                yield from Validator._flatten(op.else_ops)

    # ------------------------------------------------------------------------------
    def _plays(self, prog: Program, ops, rep: ValidationReport) -> None:
        for op in ops:
            if not isinstance(op, Play):
                continue
            b = prog.bindings.get(op.channel_id)
            if b is None:
                rep.error(op.path + ".channel_id", f"unknown channel '{op.channel_id}'")
                continue
            if b.generator_id not in self.gen:
                rep.error(op.path + ".generator_id", f"unknown generator '{b.generator_id}'")
                continue
            g = self.gen[b.generator_id]
            if op.start % g.rt_granularity_ticks:
                rep.error(op.path + ".start_tick",
                          f"start {op.start} not on {g.rt_granularity_ticks}-tick grid of {g.generator_id}")
            if op.duration < g.rt_min_duration_ticks:
                rep.error(op.path, f"duration {op.duration} < minimum {g.rt_min_duration_ticks} ticks")
            if op.duration % g.rt_granularity_ticks:
                rep.error(op.path, f"duration {op.duration} not a multiple of {g.rt_granularity_ticks} ticks")
            # waveform length must equal the played duration in SAMPLES (no silent resampling)
            n = prog.waveforms.get(op.waveform_id)
            if n is None:
                rep.error(op.path + ".waveform_id", f"unknown waveform '{op.waveform_id}'")
            else:
                per = self.tb.ticks_per(g.sample_rate_hz)
                if n * per != op.duration:
                    rep.error(op.path, f"waveform '{op.waveform_id}' has {n} samples = {n * per} ticks, "
                                       f"but play duration is {op.duration} ticks")
                if n < g.wave_min_samples or n % g.wave_granularity_samples:
                    rep.error(op.path + ".waveform_id",
                              f"{n} samples violates min {g.wave_min_samples} / "
                              f"granularity {g.wave_granularity_samples} samples")
            if abs(op.amplitude) > 1.0:
                rep.error(op.path + ".amplitude", f"|amplitude| {op.amplitude} > 1 (normalised full scale)")

    def _overlaps(self, prog: Program, paths, rep: ValidationReport) -> None:
        """Same-generator overlap along each execution path (playback is sequential on a sequencer)."""
        for path in paths:
            last_end: dict[str, int] = defaultdict(int)
            for op in sorted((o for o in path if isinstance(o, Play) and o.channel_id in prog.bindings),
                             key=lambda o: o.start):
                gid = prog.bindings[op.channel_id].generator_id
                g = self.gen.get(gid)
                if g is None:
                    continue
                if op.start < last_end[gid]:
                    if g.overlap_policy is OverlapPolicy.REJECT:
                        rep.error(op.path, f"overlaps previous play on {gid} (ends at {last_end[gid]})")
                    else:
                        rep.warnings.append(f"{op.path}: truncates previous play on {gid}")
                last_end[gid] = max(last_end[gid], op.start + op.duration)

    def _memory(self, prog: Program, ops, rep: ValidationReport) -> None:
        used: dict[str, set[str]] = defaultdict(set)          # UNIQUE waveforms per generator
        for op in ops:
            if isinstance(op, Play) and op.channel_id in prog.bindings:
                used[prog.bindings[op.channel_id].generator_id].add(op.waveform_id)
        for gid, wids in used.items():
            if gid not in self.gen:
                rep.error(f"generator[{gid}]", f"unknown generator '{gid}'")
                continue
            g = self.gen[gid]
            samples = sum(prog.waveforms.get(w, 0) for w in wids)
            if samples > g.wave_mem_samples:
                rep.error(f"generator[{gid}]", f"waveform memory {samples} > {g.wave_mem_samples} samples")
            if len(wids) > g.max_waveforms:
                rep.error(f"generator[{gid}]", f"{len(wids)} waveforms > max {g.max_waveforms}")

    def _frame_ops(self, prog: Program, ops, rep: ValidationReport) -> None:
        # a frame op executes on every generator that has a channel bound to the frame
        gens_of_frame: dict[str, set[str]] = defaultdict(set)
        for b in prog.bindings.values():
            gens_of_frame[b.frame_id].add(b.generator_id)
        last: dict[str, int] = {}
        for op in sorted((o for o in ops if isinstance(o, FrameOp)), key=lambda o: o.start):
            if op.frame_id not in gens_of_frame:
                rep.error(op.path + ".frame_id", f"unknown frame '{op.frame_id}'")
                continue
            for gid in sorted(gens_of_frame[op.frame_id]):
                if gid not in self.gen:
                    rep.error(op.path + ".generator_id", f"unknown generator '{gid}'")
                    continue
                g = self.gen[gid]
                if op.start % g.nco_grid_ticks:
                    rep.error(op.path + ".start_tick",
                              f"NCO op at {op.start} not on {g.nco_grid_ticks}-tick NCO grid of {gid}")
                if gid in last and op.start - last[gid] < g.nco_min_spacing_ticks:
                    rep.error(op.path, f"NCO ops on {gid} closer than {g.nco_min_spacing_ticks} ticks")
                if op.kind == "freq" and not (g.nco_freq_range_hz[0] <= op.value <= g.nco_freq_range_hz[1]):
                    rep.error(op.path + ".frequency_hz", f"{op.value} Hz outside NCO range {g.nco_freq_range_hz}")
                last[gid] = op.start

    def _acquisitions(self, prog: Program, ops, paths, rep: ValidationReport) -> None:
        a = self.p.acquisition
        for op in ops:
            if not isinstance(op, Acquire):
                continue
            b = prog.bindings.get(op.channel_id)
            if b is None or b.kind is not ChannelKind.READOUT:
                rep.error(op.path + ".channel_id", f"'{op.channel_id}' is not a readout channel")
                continue
            if AcqMode(op.mode) not in a.modes:
                rep.error(op.path + ".mode", f"mode {op.mode} not supported by {self.p.vendor}")
            if op.integration <= 0:
                rep.error(op.path + ".integration_ticks", "integration must be > 0")
            if op.integration % a.integration_granularity_ticks:
                rep.error(op.path + ".integration_ticks",
                          f"integration {op.integration} not a multiple of {a.integration_granularity_ticks}")
            limit = a.max_weighted_integration_ticks if op.weights_id else a.max_square_integration_ticks
            if op.integration > limit:
                rep.error(op.path + ".integration_ticks", f"integration {op.integration} > limit {limit}")
            if op.weights_id:
                n = prog.weights.get(op.weights_id)
                g = self.gen[b.generator_id]
                if n is None or n * self.tb.ticks_per(g.sample_rate_hz) != op.integration:
                    rep.error(op.path + ".weights_id", "weights length must equal integration length")
        for path in paths:
            last_start: dict[str, int] = {}
            for op in sorted((o for o in path if isinstance(o, Acquire) and o.channel_id in prog.bindings),
                             key=lambda o: o.start):
                gid = prog.bindings[op.channel_id].generator_id
                if gid in last_start and op.start - last_start[gid] < a.min_acq_spacing_ticks:
                    rep.error(op.path, f"acquisitions on {gid} closer than {a.min_acq_spacing_ticks} ticks")
                last_start[gid] = op.start
        n_weights = len({op.weights_id for op in ops if isinstance(op, Acquire) and op.weights_id})
        if n_weights > a.max_weight_sets:
            rep.error("job.weight_library", f"{n_weights} weight sets > max {a.max_weight_sets}")

    def _branches(self, prog: Program, ops, acq_by_reg: dict[int, Acquire], rep: ValidationReport) -> None:
        f = self.p.feedback
        acq_by_reg = dict(acq_by_reg)              # registers written earlier on this path stay visible
        for op in ops:
            if isinstance(op, Acquire):
                acq_by_reg[op.register] = op
            if not isinstance(op, Branch):
                continue
            if op.sequencer_id not in self.gen:
                rep.error(op.path + ".sequencer_id", f"unknown sequencer '{op.sequencer_id}'")
                continue
            if len(op.condition.registers) > f.max_condition_addresses:
                rep.error(op.path + ".condition", f"more than {f.max_condition_addresses} condition registers")
            for r in op.condition.registers:
                src = acq_by_reg.get(r)
                if src is None:
                    rep.error(op.path + ".condition", f"register {r} not written by an earlier acquisition")
                    continue
                if src.channel_id not in prog.bindings:
                    continue                       # reported by _acquisitions
                src_gen = prog.bindings[src.channel_id].generator_id
                try:
                    lat, _ = lookup_latency(self.p, src_gen, op.sequencer_id)
                except LatencyRouteError as exc:
                    rep.error(op.path + ".condition", str(exc.args[0]))
                    continue
                ready = src.start + self.tof.get(src.channel_id, 0) + src.integration + lat
                if op.start < ready:
                    rep.error(op.path + ".start_tick",
                              f"branch at {op.start} before result is available at {ready} "
                              f"(acq start + ToF + integration + latency {lat})")
            for arm, arm_ops in (("then_block", op.then_ops), ("else_block", op.else_ops)):
                end = max((getattr(x, "start", 0) + getattr(x, "duration", getattr(x, "integration", 0))
                           for x in arm_ops), default=op.start)
                if end - op.start > op.duration:
                    msg = f"{arm} lasts {end - op.start} > declared branch duration {op.duration}"
                    if f.branch_equal_duration_required:
                        rep.error(op.path + "." + arm, msg)
                    else:
                        rep.warnings.append(msg)
                self._branches(prog, list(arm_ops), acq_by_reg, rep)

    def latency(self, src_gen: str, dst_gen: str) -> int:
        """Most specific latency entry for the route; raises LatencyRouteError if the profile has none."""
        return lookup_latency(self.p, src_gen, dst_gen)[0]

    def _instruction_budget(self, prog: Program, ops, rep: ValidationReport) -> None:
        count: dict[str, int] = defaultdict(int)
        for op in ops:
            if isinstance(op, (Play, Acquire)):
                gid = prog.bindings[op.channel_id].generator_id if op.channel_id in prog.bindings else None
                if gid:
                    count[gid] += 2                          # op + following wait
        delay = prog.repetition_delay or 0
        for g in self.p.generators:
            # long repetition delays need ceil(delay / max_wait) wait instructions (or a loop)
            count[g.generator_id] += -(-delay // g.max_wait_ticks_per_instr)
            if count[g.generator_id] > g.instr_mem:
                rep.error(f"generator[{g.generator_id}]",
                          f"~{count[g.generator_id]} instructions > instruction memory {g.instr_mem}")

    # ------------------------------------------------------------------------------
    def _saturation(self, prog: Program, paths, wf_lib: WaveformLibrary | None, rep: ValidationReport) -> None:
        """Render each port's summed, NCO-modulated I/Q stream per execution path and check full scale.

        Without a waveform library the envelopes are taken as square (|env| = 1), a worst case.
        """
        for path in paths:
            phases: dict[str, float] = defaultdict(float)
            plays_by_port: dict[str, list] = defaultdict(list)
            for op in sorted(path, key=lambda o: getattr(o, "start", 0)):
                if isinstance(op, FrameOp):
                    if op.kind == "shift":
                        phases[op.frame_id] += op.value
                    elif op.kind in ("set", "reset"):
                        phases[op.frame_id] = op.value if op.kind == "set" else 0.0
                elif isinstance(op, Play) and op.channel_id in prog.bindings and op.waveform_id in prog.waveforms:
                    b = prog.bindings[op.channel_id]
                    plays_by_port[b.port_id].append((op, b, phases[b.frame_id]))
            for port_id, plays in plays_by_port.items():
                port = self.ports.get(port_id)
                if port is None or len(plays) == 0:
                    continue
                per = self.tb.ticks_per(self.gen[plays[0][1].generator_id].sample_rate_hz)
                fs = float(self.tb.tick_hz / per)
                spec = []
                for op, b, ph in plays:
                    n = prog.waveforms[op.waveform_id]
                    env = (wf_lib.get(b.generator_id, op.waveform_id) if wf_lib is not None
                           and wf_lib.has(b.generator_id, op.waveform_id) else np.ones(n, complex))
                    f_if = self.frame_if.get(b.frame_id, 0.0)
                    s0 = op.start // per
                    spec.append((s0, env, op.amplitude, f_if, ph + op.phase_offset + 2 * np.pi * f_if * s0 / fs))
                n_total = max(s + len(env) for s, env, *_ in spec)
                x = render_port_iq(n_total, fs, spec)
                _, errs, warns = check_saturation(x, port.full_scale_per_path, port.saturation_policy, port_id)
                for e in errs:
                    rep.error(f"port[{port_id}]", e)
                if port.saturation_policy is not SaturationPolicy.REJECT:
                    rep.warnings.extend(warns)


def frame_if_from_bindings(bindings, profile: HardwareProfile, drive_freq_hz: dict[str, float]) -> dict[str, float]:
    """IF (NCO) frequency per frame = drive frequency - LO of the port the frame's channels use."""
    out: dict[str, float] = {}
    for b in bindings.values():
        if b.frame_id in drive_freq_hz:
            lo = profile.port(b.port_id).lo_frequency_hz or 0.0
            out.setdefault(b.frame_id, drive_freq_hz[b.frame_id] - lo)
    return out
