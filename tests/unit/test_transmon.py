"""Unit tests for transmon formulas, E_C correction, SQUID asymmetry, and thermal states."""
from __future__ import annotations

import numpy as np

from qcss.physics.transmon import (
    FluxModel,
    bare_decay_rate,
    df01_dphi_ghz,
    f01_ghz,
    thermal_populations,
    zz_second_order_ghz,
)


def test_f01_ec_corrected_squid_formula():
    f_max = 6.0
    ec = 0.25
    d = 0.3

    # At Phi = 0 (sweet spot), f01 must equal f_max exactly
    f_zero = f01_ghz(0.0, f_max, ec, d)
    assert np.isclose(f_zero, f_max, atol=1e-12)

    # At Phi = 0.5 (half flux quantum), f01 = (f_max + ec) * sqrt(d) - ec
    f_half = f01_ghz(0.5, f_max, ec, d)
    expected_half = (f_max + ec) * np.sqrt(d) - ec
    assert np.isclose(f_half, expected_half, atol=1e-12)

    # Check the draft's error: uncorrected formula omitted ec terms
    uncorrected_half = f_max * np.sqrt(d)
    diff_mhz = (uncorrected_half - f_half) * 1e3
    # Barrett / report note: uncorrected was ~113 MHz higher by omitting -EC*(1 - sqrt(d))
    assert np.isclose(diff_mhz, 113.1, atol=1.0)


def test_df01_dphi_sweet_spot():
    f_max = 5.0
    ec = 0.2
    d = 0.2
    # At Phi = 0, first derivative is 0 (first-order insensitive)
    deriv = df01_dphi_ghz(0.0, f_max, ec, d)
    assert np.isclose(deriv, 0.0, atol=1e-6)

    # Away from sweet spot, derivative is nonzero
    deriv_off = df01_dphi_ghz(0.1, f_max, ec, d)
    assert abs(deriv_off) > 0.1


def test_flux_model_crosstalk():
    phi_off = [0.0, 0.0]
    # M_dc with 1% crosstalk
    m_dc = [[1.0, 0.01], [0.02, 1.0]]
    m_fast = [[1.0, 0.0], [0.0, 1.0]]
    f_max = [5.0, 5.2]
    ec = [0.22, 0.22]
    d = [0.2, 0.2]

    model = FluxModel(phi_off, m_dc, m_fast, f_max, ec, d)

    v_dc = np.array([0.1, 0.0])
    v_fast = np.array([0.0, 0.0])
    phi = model.phi(v_dc, v_fast)

    # Qubit 0 gets 0.1 Phi0, Qubit 1 gets 0.002 Phi0 from crosstalk
    assert np.isclose(phi[0], 0.1)
    assert np.isclose(phi[1], 0.002)


def test_thermal_populations_and_bare_decay():
    # nbar = 0.01
    nbar = 0.01
    pops = thermal_populations(nbar, dim=3)
    assert len(pops) == 3
    assert np.isclose(np.sum(pops), 1.0)
    # Ratio P1 / P0 = r = nbar / (1 + nbar)
    r = nbar / (1.0 + nbar)
    assert np.isclose(pops[1] / pops[0], r, atol=1e-9)
    assert np.isclose(pops[2] / pops[1], r, atol=1e-9)

    # Bare decay rate: 1/T1 = gamma * (1 + 2*nbar)
    t1 = 50_000.0  # 50 us
    gamma = bare_decay_rate(t1, nbar)
    assert np.isclose(gamma * (1.0 + 2.0 * nbar), 1.0 / t1)


def test_zz_second_order():
    j = 0.005      # 5 MHz
    f1 = 5.0       # 5.0 GHz
    f2 = 5.1       # 5.1 GHz (Delta = -100 MHz)
    a1 = -0.3      # -300 MHz
    a2 = -0.3      # -300 MHz

    zeta_ghz = zz_second_order_ghz(j, f1, f2, a1, a2)
    zeta_khz = zeta_ghz * 1e6
    # From plan: ~375.0 kHz
    assert np.isclose(abs(zeta_khz), 375.0, atol=1.0)
