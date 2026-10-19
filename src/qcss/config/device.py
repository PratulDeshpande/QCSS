"""Device physics specifications (Pydantic v2).

Defines transmon qubits, couplers, readout resonators, flux crosstalk matrices, the
optional slow device dynamics (drift, TLS, bursts) and the hidden fault profile
(mixer and flux-line impairments the OS has to calibrate away).
"""
from __future__ import annotations

import math
import warnings
from typing import Annotated

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from qcss.config.profile import Provenance
from qcss.core.units import H_PLANCK, K_B


class QubitSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    qubit_index: int
    f_max_ghz: float
    ec_ghz: float
    d_asym: float = 0.0                     # junction asymmetry parameter d in [0, 1]
    phi_offset: float = 0.0                 # flux offset in Phi0
    t1_us: Annotated[float, Field(gt=0)]
    t2_star_us: Annotated[float, Field(gt=0)]
    t_eff_mk: float | None = None           # effective temperature in mK
    p_excited: float | None = None          # thermal residual population (e.g. 0.015)
    rabi_max_ghz: float = 0.05              # Rabi frequency at full-scale drive amplitude, GHz
    xy_mm: tuple[float, float] = (0.0, 0.0) # physical position on chip
    provenance: Provenance = Provenance()


class CouplerSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    qubit_pair: tuple[int, int]
    j_mhz: float                            # exchange coupling in MHz
    f_max_ghz: float | None = None          # if tunable coupler
    ec_ghz: float | None = None
    d_asym: float = 0.0
    phi_offset: float = 0.0
    provenance: Provenance = Provenance()


class ResonatorSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    qubit_index: int
    f_r_ghz: float                          # bare/midpoint resonator frequency
    kappa_mhz: float                        # linewidth (decay rate) in MHz
    pulls_mhz: tuple[float, float, float]   # [delta_f(0), delta_f(1), delta_f(2)] in MHz
    cable_delay_ns: float = 120.0           # external cable delay in ns
    eta: float = 0.4                        # measurement quantum efficiency
    readout_photons: float = 5.0            # nominal operating photons
    provenance: Provenance = Provenance()


class DynamicsSpec(BaseModel):
    """Slow device dynamics advanced on the virtual lab clock (plan Phase 5).

    Off unless a device file enables it, so oracle devices stay static.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")
    enabled: bool = True
    t1_sigma_ln: float = 0.08               # log-normal T1 fluctuation (sigma of ln T1)
    t1_tau_s: float = 7200.0                # T1 drift correlation time
    flux_noise_ghz: float = 1e-4            # 1/f frequency noise amplitude
    tls_per_qubit: int = 5
    bursts: bool = True
    provenance: Provenance = Provenance(note="defaults are calibration parameters (UNVERIFIED)")


class MixerImpairmentSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    qubit_index: int
    gain_i: float = 1.0
    gain_q: float = 1.0
    phase_rad: float = 0.0
    dc_i: float = 0.0
    dc_q: float = 0.0


class FluxLineSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    qubit_index: int
    exp_terms: tuple[tuple[float, float], ...] = ()    # (A_k, tau_k in s), Rol form
    bias_tee_tau_s: float | None = None


class FaultSpec(BaseModel):
    """Hidden 'true' impairments; the OS sees only their effect and calibrates against them."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    drive_mixers: tuple[MixerImpairmentSpec, ...] = ()
    flux_lines: tuple[FluxLineSpec, ...] = ()


def thermal_excited_population(f_ghz: float, t_eff_mk: float) -> float:
    """Two-level thermal excited population 1 / (e^{hf/kT} + 1)."""
    x = H_PLANCK * f_ghz * 1e9 / (K_B * t_eff_mk * 1e-3)
    return float(1.0 / (np.exp(x) + 1.0))


class DeviceSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    device_name: str
    qubits: tuple[QubitSpec, ...]
    couplers: tuple[CouplerSpec, ...] = ()
    resonators: tuple[ResonatorSpec, ...] = ()
    m_dc: list[list[float]] | None = None   # SQUIDs x lines DC crosstalk matrix
    m_fast: list[list[float]] | None = None # fast flux crosstalk matrix (Phi0 per full-scale amplitude)
    chip_area_cm2: float = 2.25
    dynamics: DynamicsSpec | None = None
    faults: FaultSpec | None = None

    @property
    def chip_side_mm(self) -> float:
        return math.sqrt(self.chip_area_cm2) * 10.0

    def qubit(self, index: int) -> QubitSpec:
        for q in self.qubits:
            if q.qubit_index == index:
                return q
        raise KeyError(f"no qubit {index} in device {self.device_name}")

    def resonator(self, index: int) -> ResonatorSpec | None:
        return next((r for r in self.resonators if r.qubit_index == index), None)

    @model_validator(mode="after")
    def _validate_physics(self) -> DeviceSpec:
        for q in self.qubits:
            # 1. T2* must be <= 2*T1
            if q.t2_star_us > 2.0 * q.t1_us * (1.0 + 1e-9):
                raise ValueError(
                    f"qubit {q.qubit_index}: T2* ({q.t2_star_us} us) cannot exceed 2*T1 ({2*q.t1_us} us)"
                )

            # 2. Temperature vs P_e consistency: one physical fact, so a mismatch is an error
            if q.t_eff_mk is not None and q.p_excited is not None:
                p_e_expected = thermal_excited_population(q.f_max_ghz, q.t_eff_mk)
                if abs(q.p_excited - p_e_expected) > 0.01:
                    raise ValueError(
                        f"qubit {q.qubit_index}: t_eff_mk={q.t_eff_mk} implies P_e~{p_e_expected:.4f}, "
                        f"inconsistent with declared p_excited={q.p_excited}; give one or the other"
                    )

        # 3. Crosstalk off-diagonal warning
        if self.m_dc is not None:
            m = np.asarray(self.m_dc)
            if m.ndim == 2 and m.shape[0] == m.shape[1]:
                diag = np.diag(m)
                off_diag = m.copy()
                np.fill_diagonal(off_diag, 0.0)
                for i in range(m.shape[0]):
                    if diag[i] != 0 and np.max(np.abs(off_diag[i])) / abs(diag[i]) > 0.10:
                        warnings.warn(
                            f"M_dc row {i}: off-diagonal crosstalk > 10% of diagonal",
                            stacklevel=2,
                        )

        # 4. Resonator pulls check: pulls[1] - pulls[0] = 2*chi
        for r in self.resonators:
            chi_2 = r.pulls_mhz[1] - r.pulls_mhz[0]
            if abs(chi_2) < 1e-6:
                raise ValueError(f"resonator {r.qubit_index}: pulls[1] - pulls[0] (2*chi) cannot be zero")

        return self
