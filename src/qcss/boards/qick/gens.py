"""Signal-generator register models: a pulse's register values, read back as the tones a DAC plays.

A tProc v2 port write hands a generator six registers (``Event.wave``: freq, phase, env, gain, length,
conf, the layout of qick's ``Waveform``). What a generator does with them:

- ``axis_signal_gen_v6`` (full speed): a DDS at ``freq`` and ``phase`` (32-bit fractions of ``f_dds`` and
  of a turn) times ``gain / maxv``; ``conf`` picks the output (TRM ``outsel``): the DDS times the envelope
  memory from fabric cycle ``env`` on (product), the DDS alone (dds), the envelope alone (input), or
  nothing (zero). ``length`` counts fabric cycles of ``samps_per_clk`` samples, 16 bits wide;
- ``axis_sg_mux8_v1`` (multiplexed): ``conf``'s low byte masks which of the tones configured by
  ``config_mux_gen`` sound, each at its own frequency, gain and phase, for ``length`` fabric cycles.

A DDS register names a frequency only modulo the DAC rate; the analog output carries every image of it.
A full-speed generator's Nyquist zone (``set_nyquist``) says which one the user means; a mux tone's
config carries the frequency the client asked for, and the image nearest it is the one returned.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import numpy as np

if TYPE_CHECKING:
    from qcss.boards.qick.soc import GenState

TWO_PI = 2 * np.pi
OUTSEL = ("product", "dds", "input", "zero")


@dataclass(frozen=True)
class Tone:
    freq_hz: float
    phase_rad: float
    amplitude: float                  # fraction of full scale, signed


@dataclass(frozen=True)
class Pulse:
    tones: tuple[Tone, ...]
    n_samples: int                    # DAC samples
    sample_rate_hz: float
    envelope: np.ndarray | None       # complex, one per DAC sample, full scale 1; None: a flat tone
    dds: bool = True                  # False: the envelope plays at baseband (outsel "input")
    periodic: bool = False            # the generator repeats this wave until the next one
    phase_reset: bool = False

    @property
    def duration_s(self) -> float:
        return self.n_samples / self.sample_rate_hz


def _u32(v: int) -> int:
    return int(v) & 0xFFFFFFFF


def _s32(v: int) -> int:
    v = _u32(v)
    return v - (1 << 32) if v >> 31 else v


def images(freq_reg: int, f_dds_hz: float, bits: int = 32, zones: int = 4) -> list[float]:
    """Every output frequency a DDS register produces, from zone 1 up to ``2 * zones``."""
    f = _u32(freq_reg) / 2 ** bits * f_dds_hz
    out = []
    for k in range(zones):
        out += [k * f_dds_hz + f, (k + 1) * f_dds_hz - f]
    return out


def zone_frequency(freq_reg: int, f_dds_hz: float, nqz: int | None, bits: int = 32) -> float:
    """The register's image in Nyquist zone ``nqz`` (1 when the user never set one)."""
    zone = nqz or 1
    lo, hi = (zone - 1) * f_dds_hz / 2, zone * f_dds_hz / 2
    return next(f for f in images(freq_reg, f_dds_hz, bits) if lo <= f <= hi)


def nearest_image(freq_reg: int, f_dds_hz: float, target_hz: float, bits: int = 32) -> float:
    return min(images(freq_reg, f_dds_hz, bits), key=lambda f: abs(f - target_hz))


def _phase(reg: int, bits: int) -> float:
    return _u32(reg) / 2 ** bits * TWO_PI


def pulse_of(gen: GenState, wave: tuple[int, ...] | None) -> Pulse:
    """The pulse generator ``gen`` plays for one port write of registers ``wave``."""
    if wave is None:
        raise ValueError("a pulse needs its wave registers")
    cfg: dict[str, Any] = gen.cfg
    f_dds = float(cfg["f_dds"]) * 1e6
    fs = float(cfg["fs"]) * 1e6
    spc = int(cfg.get("samps_per_clk", 16))
    maxv = float(cfg["maxv"])
    freq, phase, env, gain, length, conf = (int(x) for x in wave[:6])
    if cfg["type"].startswith("axis_sg_mux"):
        mask = _u32(conf) & 0xFF
        tones = []
        for i, t in enumerate(gen.tones or []):
            if not mask >> i & 1:
                continue
            target = t.get("freq_rounded")
            f = (nearest_image(t["freq_int"], f_dds, float(target) * 1e6, cfg["b_dds"]) if target is not None
                 else zone_frequency(t["freq_int"], f_dds, gen.nqz, cfg["b_dds"]))
            tones.append(Tone(f, _phase(t.get("phase_int", 0), cfg["b_phase"]), t.get("gain_int", maxv) / maxv))
        return Pulse(tuple(tones), _u32(length) * spc, fs, None)
    outsel = OUTSEL[conf & 0b11]
    n = (_u32(length) & 0xFFFF) * spc
    amp = _s32(gain) / maxv if outsel != "zero" else 0.0
    tone = Tone(zone_frequency(freq, f_dds, gen.nqz, cfg["b_dds"]) if outsel != "input" else 0.0,
                _phase(phase, cfg["b_phase"]) if outsel != "input" else 0.0, amp)
    envelope = None
    if outsel in ("product", "input"):
        start = (_u32(env) & 0xFFFFFF) * spc
        mem = gen.envelope if gen.envelope is not None else np.zeros((start + n, 2), dtype=np.int16)
        seg = mem[start:start + n].astype(np.float64)
        if seg.shape[0] < n:                                  # past the end of the memory: the address wraps
            seg = np.concatenate([seg, mem[:n - seg.shape[0]].astype(np.float64)])
        envelope = (seg[:, 0] + 1j * seg[:, 1]) / maxv
    return Pulse((tone,), n, fs, envelope, dds=outsel != "input", periodic=bool(conf >> 2 & 1),
                 phase_reset=bool(conf >> 4 & 1))
