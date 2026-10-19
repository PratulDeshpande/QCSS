"""Transmon device physics in ordinary frequency units (GHz); convert to rad/ns ONCE.

f01(Phi) uses the E_C-corrected asymmetric-SQUID form (Koch / Hutchings / Barrett):
    f(Phi) = (f_max + E_C) * [cos^2(pi Phi) + d^2 sin^2(pi Phi)]^(1/4) - E_C
The draft omitted the E_C terms: +22.5 MHz error at 0.2 Phi0 and +113 MHz at 0.5 Phi0
for f_max = 6 GHz, E_C = 0.25 GHz, d = 0.3 [local check].
"""
from __future__ import annotations

import numpy as np

H_PLANCK = 6.62607015e-34
K_B = 1.380649e-23
TWO_PI = 2.0 * np.pi


def f01_ghz(phi_phi0: np.ndarray | float, f_max_ghz: float | np.ndarray,
            ec_ghz: float | np.ndarray, d_asym: float | np.ndarray) -> np.ndarray | float:
    phi = np.pi * np.asarray(phi_phi0, dtype=np.float64)
    x = (np.cos(phi) ** 2 + np.asarray(d_asym, dtype=np.float64) ** 2 * np.sin(phi) ** 2) ** 0.25
    res = (np.asarray(f_max_ghz, dtype=np.float64) + ec_ghz) * x - ec_ghz
    if np.isscalar(phi_phi0) and np.isscalar(f_max_ghz) and np.isscalar(ec_ghz) and np.isscalar(d_asym):
        return float(res)
    return res


def df01_dphi_ghz(phi_phi0, f_max_ghz, ec_ghz, d_asym, h: float = 1e-6) -> np.ndarray | float:
    """Flux sensitivity (GHz per Phi0), used for flux-noise dephasing."""
    f_plus = f01_ghz(np.asarray(phi_phi0) + h, f_max_ghz, ec_ghz, d_asym)
    f_minus = f01_ghz(np.asarray(phi_phi0) - h, f_max_ghz, ec_ghz, d_asym)
    return (f_plus - f_minus) / (2 * h)


class FluxModel:
    """Phi = Phi_offset + M_dc @ V_dc + M_fast @ V_fast   (rows: SQUIDs incl. couplers; NOT symmetric).

    Typical magnitudes (Barrett et al. 2023): DC off-diagonals ~<1 % of diagonal, fast-flux
    off-diagonals ~100x smaller (~0.01 %). V_fast must already include line distortion and
    the OS's predistortion (signal chain, Phase 5) before it reaches this model.
    """

    def __init__(self, phi_offset, m_dc, m_fast, f_max_ghz, ec_ghz, d_asym) -> None:
        self.phi_offset = np.asarray(phi_offset, dtype=np.float64)
        self.m_dc = np.asarray(m_dc, dtype=np.float64)
        self.m_fast = np.asarray(m_fast, dtype=np.float64)
        self.f_max = np.asarray(f_max_ghz, dtype=np.float64)
        self.ec = np.asarray(ec_ghz, dtype=np.float64)
        self.d = np.asarray(d_asym, dtype=np.float64)

    def phi(self, v_dc: np.ndarray, v_fast: np.ndarray) -> np.ndarray:
        """v_fast may be (n_lines,) or (n_lines, n_samples)."""
        v_dc = np.asarray(v_dc, dtype=np.float64)
        v_fast = np.asarray(v_fast, dtype=np.float64)
        base = self.phi_offset + self.m_dc @ v_dc
        return base[:, None] + self.m_fast @ v_fast if np.ndim(v_fast) == 2 else base + self.m_fast @ v_fast

    def f01(self, v_dc: np.ndarray, v_fast: np.ndarray) -> np.ndarray:
        phi = self.phi(v_dc, v_fast)
        if phi.ndim == 2:
            return f01_ghz(phi, self.f_max[:, None], self.ec[:, None], self.d[:, None])
        return f01_ghz(phi, self.f_max, self.ec, self.d)


def nbar_from_temperature(f_ghz: float, t_eff_mk: float) -> float:
    if t_eff_mk <= 0:
        return 0.0
    x = H_PLANCK * f_ghz * 1e9 / (K_B * t_eff_mk * 1e-3)
    return float(1.0 / np.expm1(x))


def nbar_from_excited_population(p_e: float) -> float:
    """Invert the qutrit ladder P = (1, r, r^2)/Z for the measured P(|1>)+P(|2>) ~ p_e (two-level approx)."""
    r = p_e / (1.0 - p_e)
    return float(r / (1.0 - r))           # r = nbar/(1+nbar)


def thermal_populations(nbar: float, dim: int = 3) -> np.ndarray:
    """Exact steady state of the ladder Lindbladian: P_k proportional to r^k, r = nbar/(1+nbar)."""
    r = nbar / (1.0 + nbar) if nbar > 0 else 0.0
    p = r ** np.arange(dim)
    return p / p.sum()


def bare_decay_rate(t1_measured_ns: float, nbar: float) -> float:
    """Measured 1/T1 = gamma_down + gamma_up = gamma (2 nbar + 1)  [derivation]."""
    return 1.0 / (t1_measured_ns * (1.0 + 2.0 * nbar))


def zz_second_order_ghz(j_ghz: float, f1_ghz: float, f2_ghz: float, a1_ghz: float, a2_ghz: float) -> float:
    """Static ZZ for two transmons with exchange J (valid off resonance; diverges at Delta=-a1 or a2).
    zeta = 2 J^2 (a1 + a2) / ((Delta + a1)(Delta - a2)),  Delta = f1 - f2   [physics notes, local check]."""
    delta = f1_ghz - f2_ghz
    return 2 * j_ghz**2 * (a1_ghz + a2_ghz) / ((delta + a1_ghz) * (delta - a2_ghz))
