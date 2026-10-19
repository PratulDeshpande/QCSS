"""Per-path DAC saturation check on the RENDERED port signal.

The draft summed |envelope| per port: a triangle-inequality upper bound that ignores the
IF modulation of each generator (two tones at different IFs rarely peak together) and
the per-I/Q-path limit. Here each generator's samples are modulated by its NCO, summed
on the port, and I and Q are compared separately against full scale.
"""
from __future__ import annotations

import numpy as np

from qcss.config.profile import SaturationPolicy


def render_port_iq(n_samples: int, fs_hz: float,
                   plays: list[tuple[int, np.ndarray, float, float, float]]) -> np.ndarray:
    """plays: (start_sample, env[complex], amplitude, f_if_hz, phase0_rad) for one port.

    Returns the complex DAC stream x[n] = sum_k A_k env_k[n - s_k] e^{i(2 pi f_k n/fs + phi_k)}.
    phase0 should be the frame's absolute NCO phase at the play start (FrameTracker.phase_at).
    """
    x = np.zeros(n_samples, dtype=np.complex128)
    for s, env, amp, f_if, phi0 in plays:
        n = np.arange(len(env))
        x[s:s + len(env)] += amp * env * np.exp(1j * (2 * np.pi * f_if * n / fs_hz + phi0))
    return x


def check(x: np.ndarray, full_scale: float, policy: SaturationPolicy,
          port_id: str) -> tuple[np.ndarray, list[str], list[str]]:
    """Return (possibly clipped stream, errors, warnings)."""
    peak_i = float(np.max(np.abs(x.real), initial=0.0))
    peak_q = float(np.max(np.abs(x.imag), initial=0.0))
    peak = max(peak_i, peak_q)
    if peak <= full_scale * (1 + 1e-9):
        return x, [], []
    msg = f"port {port_id}: peak |I|={peak_i:.3f}, |Q|={peak_q:.3f} exceeds full scale {full_scale}"
    if policy is SaturationPolicy.REJECT:
        return x, [msg], []
    if policy is SaturationPolicy.WRAP:   # two's-complement-like wrap, normalised
        wrap = lambda v: (v + full_scale) % (2 * full_scale) - full_scale
        return wrap(x.real) + 1j * wrap(x.imag), [], [msg + " (wrapped)"]
    clipped = np.clip(x.real, -full_scale, full_scale) + 1j * np.clip(x.imag, -full_scale, full_scale)
    return clipped, [], [msg + " (clipped)"]
