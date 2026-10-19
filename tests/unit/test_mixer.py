"""Unit tests for mixer model, image sideband, and OS IQ correction."""
from __future__ import annotations

import numpy as np

from qcss.signal.mixer import (
    IQCorrection,
    IQImpairment,
    apply_mixer,
)


def test_mixer_ideal_pass_through():
    truth = IQImpairment(gain_i=1.0, gain_q=1.0, phase_rad=0.0, dc_i=0.0, dc_q=0.0)
    corr = IQCorrection()

    m = np.array([1.0 + 0.5j, -0.3 + 0.8j])
    out = apply_mixer(m, truth, corr, lo_enabled=True)
    assert np.allclose(out, m)


def test_mixer_image_and_leakage():
    # Gain imbalance 1.5%, phase skew 12 mrad, DC offsets
    g_i = 1.015
    g_q = 1.0
    phase_skew = 0.012
    dc_i = 0.01
    dc_q = -0.015

    truth = IQImpairment(gain_i=g_i, gain_q=g_q, phase_rad=phase_skew, dc_i=dc_i, dc_q=dc_q)
    corr = IQCorrection()

    # Pure IF tone: e^{i 2 pi f_IF t}
    fs = 1e9
    f_if = 100e6
    n = 1000
    t = np.arange(n) / fs
    m_if = np.exp(1j * 2 * np.pi * f_if * t)

    out = apply_mixer(m_if, truth, corr, lo_enabled=True)

    # FFT to check tone, image, and DC
    spectrum = np.fft.fft(out) / n
    freqs = np.fft.fftfreq(n, 1 / fs)

    # Power in main tone (+100 MHz)
    idx_main = int(np.argmin(np.abs(freqs - 100e6)))
    p_main = abs(spectrum[idx_main]) ** 2

    # Power in image tone (-100 MHz)
    idx_image = int(np.argmin(np.abs(freqs - (-100e6))))
    p_image = abs(spectrum[idx_image]) ** 2

    image_ratio = p_image / p_main
    # Small error formula: ((gamma - 1)^2 + phi^2) / 4 = ((0.015)^2 + (0.012)^2) / 4 = (2.25e-4 + 1.44e-4) / 4 = 9.2e-5
    expected_ratio = ((g_i - 1.0) ** 2 + phase_skew ** 2) / 4.0
    assert np.isclose(image_ratio, expected_ratio, rtol=0.2)

    # Check LO leakage present at DC (0 Hz)
    idx_dc = int(np.argmin(np.abs(freqs - 0.0)))
    assert np.isclose(abs(spectrum[idx_dc]), np.sqrt(dc_i**2 + dc_q**2), atol=1e-3)


def test_mixer_os_correction():
    # Hardware with imbalance
    truth = IQImpairment(gain_i=1.0, gain_q=1.05, phase_rad=0.02, dc_i=0.03, dc_q=-0.04)
    # OS calibrated correction
    corr = IQCorrection(dc_i=-0.03, dc_q=0.04, gain_ratio=1.0 / 1.05, phase_rad=-0.02)

    m = np.array([0.5 + 0.5j])
    out = apply_mixer(m, truth, corr, lo_enabled=True)
    # With first-order correction applied, output is close to un-impaired signal within ~1%
    assert np.isclose(out.real, 0.5, atol=0.01)
    assert np.isclose(out.imag, 0.5, atol=0.01)
