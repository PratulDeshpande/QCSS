"""Unit tests for stateful filters, Rol-form exponential step response, and predistortion."""
from __future__ import annotations

import numpy as np
import pytest

from qcss.signal.filters import (
    FluxLineModel,
    StatefulSOS,
    exp_term_sos,
)
from qcss.signal.predistortion import PredistortionError, QbloxRTP


def test_rol_term_endpoints():
    """Verify s[0] = 1 + A and s[inf] = 1.0000000 (DC gain 1, no 4% error)."""
    fs = 1e9  # 1 GS/s
    A = 0.04  # 4% overshoot
    tau = 45e-9  # 45 ns
    sos = exp_term_sos(A, tau, fs)
    filter_sos = StatefulSOS(sos)

    # Step input of length 2000
    n = 2000
    u = np.ones(n, dtype=np.float64)
    s = filter_sos(u)

    # s[0] must equal 1 + A = 1.04 exactly
    assert np.isclose(s[0], 1.0 + A, atol=1e-12)
    # s[inf] must equal 1.0000000 (settles to 1.0, unlike draft's 1.04)
    assert np.isclose(s[-1], 1.0, atol=1e-7)


def test_chunked_equals_oneshot_filtering():
    """Verify that filtering in chunks matches filtering in one call."""
    fs = 1e9
    model_oneshot = FluxLineModel(fs, exp_terms=[(0.04, 50e-9), (-0.02, 200e-9)], bias_tee_tau_s=1e-4)
    model_chunked = FluxLineModel(fs, exp_terms=[(0.04, 50e-9), (-0.02, 200e-9)], bias_tee_tau_s=1e-4)

    rng = np.random.default_rng(42)
    x = rng.standard_normal(5000)

    # One shot
    y_oneshot = model_oneshot(x)

    # In 3 irregular chunks
    c1, c2, c3 = x[:1200], x[1200:3700], x[3700:]
    y1 = model_chunked(c1)
    y2 = model_chunked(c2)
    y3 = model_chunked(c3)
    y_chunked = np.concatenate([y1, y2, y3])

    assert np.allclose(y_oneshot, y_chunked, atol=1e-12)


def test_predistortion_inverts_physical_filter():
    """Predistortion composed with physical distortion reproduces unit step within 0.1%."""
    fs = 1e9
    A1, tau1 = 0.05, 40e-9
    A2, tau2 = -0.02, 150e-9

    rtp = QbloxRTP(fs)
    rtp.configure([(A1, tau1), (A2, tau2)])

    phys = FluxLineModel(fs, exp_terms=[(A1, tau1), (A2, tau2)])

    # Input step
    x = np.ones(1000, dtype=np.float64)
    predistorted = rtp(x)
    actual_signal = phys(predistorted)

    # After initial sample, output must be within 0.1% (1e-3) of 1.0
    assert np.allclose(actual_signal, 1.0, atol=1e-3)


def test_rtp_range_validation():
    rtp = QbloxRTP(1e9)
    # Tau too small (< 6 ns)
    with pytest.raises(PredistortionError, match="outside"):
        rtp.configure([(0.05, 3e-9)])

    # Amplitude out of range [-1, 1)
    with pytest.raises(PredistortionError, match="amplitude"):
        rtp.configure([(1.0, 50e-9)])

    # More than 4 exponential stages
    with pytest.raises(PredistortionError, match="at most 4"):
        rtp.configure([(0.01, 50e-9)] * 5)
