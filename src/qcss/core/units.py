"""Unit conversions and physical constants in ONE place.

Conventions:
- Frequencies at API boundaries and YAML profiles: GHz or Hz
- Angular frequencies inside ODE/Lindblad solvers: rad/ns
- Time in physics solvers: ns
- Time in timing/IR: integer ticks
"""
from __future__ import annotations

import math

import numpy as np

TWO_PI = 2.0 * math.pi
H_PLANCK = 6.62607015e-34    # J*s
K_B = 1.380649e-23           # J/K
PHI0 = 2.067833848e-15       # Wb (h / 2e)


def ghz_to_rad_ns(freq_ghz: float | np.ndarray) -> float | np.ndarray:
    """Convert f in GHz to omega in rad/ns: 2 * pi * f."""
    return TWO_PI * freq_ghz


def rad_ns_to_ghz(omega_rad_ns: float | np.ndarray) -> float | np.ndarray:
    """Convert omega in rad/ns to f in GHz: omega / (2 * pi)."""
    return omega_rad_ns / TWO_PI


def hz_to_rad_ns(freq_hz: float | np.ndarray) -> float | np.ndarray:
    """Convert f in Hz to omega in rad/ns: 2 * pi * f * 1e-9."""
    return TWO_PI * freq_hz * 1e-9


def rad_ns_to_hz(omega_rad_ns: float | np.ndarray) -> float | np.ndarray:
    """Convert omega in rad/ns to f in Hz: omega / (2 * pi) * 1e9."""
    return (omega_rad_ns / TWO_PI) * 1e9
