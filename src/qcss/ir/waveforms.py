"""Waveform synthesis at the GENERATOR sample rate (one sample = one DAC sample)."""
from __future__ import annotations

import numpy as np


def gaussian(n: int, sigma: float | None = None) -> np.ndarray:
    """Pedestal-subtracted, peak-normalised Gaussian sampled at sample centres k = 0..n-1."""
    sigma = sigma if sigma and sigma > 0 else n / 4.0
    k = np.arange(n, dtype=np.float64)
    t0 = 0.5 * (n - 1)
    g = np.exp(-0.5 * ((k - t0) / sigma) ** 2)
    ped = np.exp(-0.5 * ((-0.5 - t0) / sigma) ** 2)     # value half a sample outside the window
    return (g - ped) / (1.0 - ped)


def drag(n: int, sigma: float | None, beta_samples: float) -> np.ndarray:
    """I = Gaussian; Q = beta * dI/dk of the SAME (normalised) envelope.

    beta is in SAMPLES (hardware convention); beta_ns = beta_samples / fs_GHz.
    First-order optimum (Gambetta 2011 / Krantz 2019): beta_ns ~ -lambda/alpha_rad_per_ns,
    lambda ~0.5 (phase) .. 1 (leakage). The SIGN depends on the IQ/sideband convention
    of the impersonated instrument -> enforced by a unit test (leakage must decrease).
    """
    i = gaussian(n, sigma)
    q = beta_samples * np.gradient(i)                   # derivative per sample
    return i + 1j * q


def square(n: int) -> np.ndarray:
    return np.ones(n, dtype=np.complex128)


def cosine_flattop(n: int, rise: int) -> np.ndarray:
    env = np.ones(n, dtype=np.float64)
    rise = max(1, min(rise, n // 2))
    ramp = 0.5 * (1.0 - np.cos(np.pi * (np.arange(rise) + 0.5) / rise))
    env[:rise] = ramp
    env[n - rise:] = ramp[::-1]
    return env.astype(np.complex128)


class WaveformLibrary:
    """Unique waveforms per generator; memory is charged once per stored waveform."""

    def __init__(self) -> None:
        self._store: dict[tuple[str, str], np.ndarray] = {}

    def add(self, generator_id: str, waveform_id: str, samples: np.ndarray) -> None:
        self._store[(generator_id, waveform_id)] = np.asarray(samples, dtype=np.complex128)

    def get(self, generator_id: str, waveform_id: str) -> np.ndarray:
        return self._store[(generator_id, waveform_id)]

    def has(self, generator_id: str, waveform_id: str) -> bool:
        return (generator_id, waveform_id) in self._store

    def samples_used(self, generator_id: str) -> int:
        return sum(len(w) for (g, _), w in self._store.items() if g == generator_id)

    def count(self, generator_id: str) -> int:
        return sum(1 for (g, _) in self._store if g == generator_id)
