"""Shot timelines to chassis jobs: what the board plays, shot by shot, as QCSS program points.

The interpreter turns a round into timed port writes, cut into shots where the program counts one. For
each shot this module

- resolves generator queueing first, as the hardware does: a generator still playing holds the next
  pulse until it is free (the validator's overlap rule then holds by construction, never by weakening);
- turns pulses into ``Play``s (with a ``SetFrequency`` on the drive frame), and each readout trigger into
  an ``Acquire`` over the configured window (with the readout frame set to the PFB's frequency);
- measures times from the shot's first output, in chassis ticks.

Identical shots fold into one program point. The chassis runs every point of a job the same number of
times, so points repeated a different number of times go to separate jobs. ``shots`` keeps the true
order, so each result goes back to the place the board would have written it. The gap from one shot's
last output to the next shot's first becomes the repetition delay (the smallest one seen).

A bench test cable (``loopback``: generator -> readout) takes both ends off the chip: the generator's pulses
reach no qubit line, and the readout captures them instead of the resonator, ``CABLE_DELAY_S`` later
(the DAC -> ADC pipelines and the cable), downconverted at the readout's frequency, plus ADC noise. Those windows are
computed here, per shot (``Translation.cabled``), and never reach the chassis.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import TYPE_CHECKING, Any

import numpy as np

from qcss.boards.qick.gens import pulse_of
from qcss.boards.qick.readouts import readout_of
from qcss.config.profile import HardwareProfile
from qcss.core.ndarray import to_proto
from qcss.ir.program import ChannelBinding, ChannelKind
from qcss.v1 import job_pb2

if TYPE_CHECKING:
    from qcss.boards.qick.soc import BoardState
    from qcss.boards.qick.tproc_v2_run import Event, Trace


# A cabled readout, as QICK's demo 00 recorded one on hardware (its saved loopback trace, ZCU111, qick
# 0.2.181): the pulse arrives ~331 ns after it was played (DAC and ADC pipelines plus the cable), at ~125
# counts per decimated sample for gain 3000/32766, i.e. ~1365 counts at full scale. The signal is kept in
# model units here: x ADC_COUNTS_PER_UNIT (100) gives counts. A ZCU216 PFB build may differ; verified: false.
CABLE_UNITS_FULL_SCALE = 13.65
CABLE_DELAY_S = 331e-9
CABLE_NOISE_UNITS = 0.02               # ADC noise per decimated I/Q sample: 2 counts
_SUBSAMPLES = 8                        # points averaged per decimated sample (the decimator's low-pass)


@dataclass(frozen=True)
class Read:
    ro_ch: int                         # the board's readout channel
    key: str                           # the result key of this read in its point
    cabled: bool = False               # captured off a test cable: Translation.cabled holds it per shot


@dataclass
class Translation:
    jobs: list[job_pb2.Job]
    shots: list[tuple[int, int, int]]             # true shot order -> (job, point, occurrence)
    reads: list[list[list[Read]]] = field(default_factory=list)   # [job][point] -> reads, in shot order
    shot_ticks: list[int] = field(default_factory=list)            # each shot's first output, chassis ticks
    cabled: dict[int, dict[str, np.ndarray]] = field(default_factory=dict)  # shot -> key -> decimated window
    chassis_reads: list[list[bool]] = field(default_factory=list)  # [job][point]: does the chassis read anything


def _ticks_per(tick_hz: Fraction, rate_mhz: float) -> int:
    per = Fraction(tick_hz) / Fraction(str(rate_mhz)) / 10 ** 6
    if per.denominator != 1:
        raise ValueError(f"{rate_mhz} MHz is not a whole number of chassis ticks")
    return int(per)


class _Wiring:
    def __init__(self, bindings: Mapping[str, ChannelBinding]) -> None:
        self.dac: dict[int, ChannelBinding] = {}
        self.ro: dict[int, ChannelBinding] = {}
        for b in bindings.values():
            if b.kind in (ChannelKind.DRIVE, ChannelKind.FLUX) and b.port_id.startswith("dac"):
                self.dac[int(b.port_id.removeprefix("dac"))] = b
            elif b.kind is ChannelKind.READOUT:
                self.ro[b.qubits[0]] = b


def _cable_window(t0: int, n_dec: int, dec_ticks: int, f_ro: float, tick_hz: float, delay: int,
                  pulses: list[tuple[int, Any, int]], rng: np.random.Generator) -> np.ndarray:
    """A readout window (decimated samples from tick ``t0``) of what a cabled generator sent."""
    tau = t0 + (np.arange(n_dec)[:, None] + (np.arange(_SUBSAMPLES) + 0.5) / _SUBSAMPLES) * dec_ticks
    sig = np.zeros(tau.shape, dtype=np.complex128)
    for start, p, fine in pulses:
        rel = tau - delay - start
        idx = np.floor(rel / fine).astype(np.int64)
        on = (idx >= 0) & (idx < p.n_samples)
        env = np.ones(p.n_samples, dtype=np.complex128) if p.envelope is None else p.envelope
        for tone in p.tones:
            amp = env[np.clip(idx, 0, p.n_samples - 1)] * tone.amplitude
            if p.dds:
                amp = amp * np.exp(1j * (2 * np.pi * tone.freq_hz * (tau - delay) / tick_hz + tone.phase_rad))
            sig += np.where(on, amp, 0)
    sig = sig * np.exp(-2j * np.pi * f_ro * tau / tick_hz)          # the readout's downconversion
    out = sig.mean(axis=1) * CABLE_UNITS_FULL_SCALE
    return out + CABLE_NOISE_UNITS * (rng.standard_normal(n_dec) + 1j * rng.standard_normal(n_dec))


def translate(trace: Trace, state: BoardState, bindings: Mapping[str, ChannelBinding],
              profile: HardwareProfile, loopback: Mapping[int, int] | None = None,
              rng: np.random.Generator | None = None) -> Translation:
    tick_hz = Fraction(profile.clock.tick_hz)
    cable_of_gen = dict(loopback or {})
    cabled_ros = set(cable_of_gen.values())
    rng = rng if rng is not None else np.random.default_rng()
    cable_delay = round(CABLE_DELAY_S * float(tick_hz))
    wiring = _Wiring(bindings)
    # v2 pulses name the tProc port, v1 pulses (behind a tProc mux) the generator itself
    gen_of_port = ({i: i for i in range(len(state.gens))} if trace.by_gen
                   else {g.cfg["tproc_ch"]: i for i, g in enumerate(state.gens)})
    ro_of_trig: dict[tuple[str, int], list[int]] = {}       # v2: ("trig_set", port); v1: ("bit_set", bit)
    for i, r in enumerate(state.readouts):
        if r.cfg.get("trigger_type") == "tport":
            ro_of_trig.setdefault(("trig_set", int(r.cfg["trigger_port"])), []).append(i)
        elif r.cfg.get("trigger_type") == "output":
            ro_of_trig.setdefault(("bit_set", int(r.cfg["trigger_bit"])), []).append(i)
    f_time = state.tproc_cfg["f_time"]
    per_cycle = _ticks_per(tick_hz, f_time)
    waveforms: dict[bytes, tuple[str, job_pb2.Waveform]] = {}
    pfb: dict[int, float] = {}
    for i, r in enumerate(state.readouts):
        f = readout_of(r).freq_hz
        if f is not None and i in wiring.ro:
            pfb[i] = f

    def tuned_readout(freq_hz: float) -> int | None:
        """The readout a tone is heard on: the one tuned within half a PFB channel of it."""
        best = min(pfb, key=lambda i: abs(pfb[i] - freq_hz), default=None)
        if best is None:
            return None
        half = state.readouts[best].cfg["f_dds"] * 1e6 / 4          # PFB channels are f_dds / 2 apart
        return best if abs(pfb[best] - freq_hz) <= half else None

    def waveform(samples: np.ndarray) -> str:
        key = samples.tobytes()
        if key not in waveforms:
            waveforms[key] = (f"w{len(waveforms)}", job_pb2.Waveform(
                shape=job_pb2.WAVEFORM_SHAPE_ARBITRARY, samples=to_proto(samples), length_samples=len(samples)))
        return waveforms[key][0]

    def shot_block(events: list[Event]) -> tuple[job_pb2.Block, list[Read], int, int, dict[str, np.ndarray]]:
        origin = min(e.t for e in events)
        cable_pulses: dict[int, list[tuple[int, Any, int]]] = {}    # readout -> (tick, pulse, ticks/sample)
        cable_reads: list[tuple[int, str, int, Any]] = []            # (readout, key, tick, Readout)
        busy: dict[int, int] = {}                 # generator -> tick it is free again
        ins: list[job_pb2.Instruction] = []
        reads: list[Read] = []
        end = 0
        n_reads: dict[int, int] = {}
        toned: set[int] = set()                   # readouts a tone has set the probe frequency of
        for e in sorted(events, key=lambda e: e.t):
            t = (e.t - origin) * per_cycle
            if e.kind == "pulse" and e.port in gen_of_port:
                g = gen_of_port[e.port]
                gen = state.gens[g]
                p = pulse_of(gen, e.wave)
                t = max(t, busy.get(g, 0))
                dur = p.n_samples * _ticks_per(tick_hz, gen.cfg["fs"])
                busy[g] = t + dur
                end = max(end, t + dur)
                if g in cable_of_gen:                 # into the test cable, not the chip
                    cable_pulses.setdefault(cable_of_gen[g], []).append(
                        (t, p, _ticks_per(tick_hz, gen.cfg["fs"])))
                    continue
                b = wiring.dac.get(g)
                if b is None:                     # the readout tones: each probes the readout tuned to it
                    for tone in p.tones:
                        ch = tuned_readout(tone.freq_hz)
                        if ch is None:
                            continue              # no readout listens there: the tone reaches no resonator model
                        rb = wiring.ro[ch]
                        toned.add(ch)
                        ins.append(job_pb2.Instruction(start_tick=t, set_frequency=job_pb2.SetFrequency(
                            frame_id=rb.frame_id, frequency_hz=tone.freq_hz)))
                        ins.append(job_pb2.Instruction(start_tick=t, play=job_pb2.Play(
                            channel_id=rb.channel_id, waveform_id=waveform(np.ones(p.n_samples, dtype=np.complex128)),
                            amplitude=tone.amplitude, phase_offset_rad=tone.phase_rad)))
                    continue
                if not p.tones:
                    continue
                tone = p.tones[0]
                env = p.envelope if p.envelope is not None else np.ones(p.n_samples, dtype=np.complex128)
                if b.kind is ChannelKind.FLUX:
                    env = np.real(env * np.exp(1j * tone.phase_rad)).astype(np.complex128)
                    ins.append(job_pb2.Instruction(start_tick=t, play=job_pb2.Play(
                        channel_id=b.channel_id, waveform_id=waveform(env), amplitude=tone.amplitude)))
                    continue
                ins.append(job_pb2.Instruction(start_tick=t, set_frequency=job_pb2.SetFrequency(
                    frame_id=b.frame_id, frequency_hz=tone.freq_hz)))
                ins.append(job_pb2.Instruction(start_tick=t, play=job_pb2.Play(
                    channel_id=b.channel_id, waveform_id=waveform(env), amplitude=tone.amplitude,
                    phase_offset_rad=tone.phase_rad)))
            elif e.kind in ("trig_set", "bit_set"):
                for ch in ro_of_trig.get((e.kind, e.port), []):
                    ro = readout_of(state.readouts[ch])
                    b = wiring.ro.get(ch)
                    if ro.length <= 0 or (b is None and ch not in cabled_ros):
                        continue
                    k = n_reads.get(ch, 0)
                    n_reads[ch] = k + 1
                    key = f"ro{ch}.{k}"
                    if ch in cabled_ros:              # the ADC hears the cable, not the resonator
                        cable_reads.append((ch, key, t, ro))
                        reads.append(Read(ch, key, cabled=True))
                        end = max(end, t + ro.length * _ticks_per(tick_hz, ro.sample_rate_hz / 1e6))
                        continue
                    assert b is not None
                    if ro.freq_hz is not None and ch not in toned:
                        ins.append(job_pb2.Instruction(start_tick=t, set_frequency=job_pb2.SetFrequency(
                            frame_id=b.frame_id, frequency_hz=ro.freq_hz)))
                    span = ro.length * _ticks_per(tick_hz, ro.sample_rate_hz / 1e6)
                    mode = (job_pb2.ACQUISITION_MODE_RAW_TRACE if state.readouts[ch].enabled[1]
                            else job_pb2.ACQUISITION_MODE_INTEGRATED)
                    ins.append(job_pb2.Instruction(start_tick=t, acquire=job_pb2.Acquire(
                        channel_id=b.channel_id, integration_ticks=span, mode=mode,
                        register_index=len(reads) % 8, result_key=key)))
                    reads.append(Read(ch, key))
                    end = max(end, t + span)
            else:
                end = max(end, t)
        ins.sort(key=lambda i: i.start_tick)      # stable: a SetFrequency stays before its Play
        windows = {}
        for ch, key, t, ro in cable_reads:
            windows[key] = _cable_window(t, ro.length, _ticks_per(tick_hz, ro.sample_rate_hz / 1e6),
                                         ro.freq_hz or 0.0, float(tick_hz), cable_delay,
                                         cable_pulses.get(ch, []), rng)
        return job_pb2.Block(instructions=ins), reads, origin, end, windows

    points: dict[bytes, int] = {}
    blocks: list[job_pb2.Block] = []
    point_reads: list[list[Read]] = []
    order: list[tuple[int, int]] = []             # per shot: (unique point, occurrence)
    counts: list[int] = []
    origins: list[int] = []
    gaps: list[int] = []
    prev_end: int | None = None
    cabled: dict[int, dict[str, np.ndarray]] = {}
    for events in trace.shots:
        if not events:
            continue
        block, reads, origin, end, windows = shot_block(events)
        if windows:
            cabled[len(order)] = windows
        key = block.SerializeToString(deterministic=True)
        if key not in points:
            points[key] = len(blocks)
            blocks.append(block)
            point_reads.append(reads)
            counts.append(0)
        u = points[key]
        order.append((u, counts[u]))
        counts[u] += 1
        if prev_end is not None:
            gaps.append(origin * per_cycle - prev_end)
        prev_end = origin * per_cycle + end
        origins.append(origin * per_cycle)

    delay = max(0, min(gaps)) if gaps else None
    by_count: dict[int, list[int]] = {}
    for u, c in enumerate(counts):
        by_count.setdefault(c, []).append(u)
    jobs: list[job_pb2.Job] = []
    reads_out: list[list[list[Read]]] = []
    chassis_reads: list[list[bool]] = []
    where: dict[int, tuple[int, int]] = {}
    for c, us in by_count.items():
        job = job_pb2.Job(num_shots=c)
        if delay is not None:
            job.repetition_delay_ticks = delay
        for idx, u in enumerate(us):
            job.program_points.add(indices=[idx]).main.CopyFrom(blocks[u])
            where[u] = (len(jobs), idx)
        used = {i.play.waveform_id for b in (blocks[u] for u in us) for i in b.instructions
                if i.WhichOneof("op") == "play"}
        for wid, wf in waveforms.values():
            if wid in used:
                job.waveform_library[wid].CopyFrom(wf)
        jobs.append(job)
        reads_out.append([point_reads[u] for u in us])
        chassis_reads.append([any(not r.cabled for r in point_reads[u]) for u in us])
    shots = [(*where[u], occ) for u, occ in order]
    return Translation(jobs, shots, reads_out, origins, cabled, chassis_reads)
