"""Unit tests for waveform synthesis, DRAG derivative, and waveform library."""
from __future__ import annotations

import numpy as np

from qcss.ir.waveforms import (
    WaveformLibrary,
    cosine_flattop,
    drag,
    gaussian,
    square,
)


def test_gaussian_normalized_and_pedestal_subtracted():
    # Odd length has sample exactly at center
    n_odd = 65
    g_odd = gaussian(n_odd, sigma=16.0)
    assert np.isclose(np.max(g_odd), 1.0, atol=1e-9)

    # Even length sample centres are offset by 0.5 sample
    n_even = 64
    g = gaussian(n_even, sigma=16.0)
    assert np.isclose(np.max(g), 1.0, atol=1e-3)
    # Pedestal subtraction ensures ends are close to 0
    assert g[0] >= 0.0
    assert g[-1] >= 0.0
    assert g[0] < 0.05
    # Symmetric
    assert np.allclose(g, g[::-1], atol=1e-12)


def test_drag_waveform_components():
    n = 64
    beta = 2.5
    d = drag(n, sigma=16.0, beta_samples=beta)
    # I component is Gaussian
    assert np.allclose(d.real, gaussian(n, sigma=16.0))
    # Q component is beta * gradient(I)
    expected_q = beta * np.gradient(gaussian(n, sigma=16.0))
    assert np.allclose(d.imag, expected_q)
    # Q must be anti-symmetric around center
    assert np.isclose(d.imag[n // 2], 0.0, atol=0.01)


def test_square_and_flattop():
    sq = square(20)
    assert len(sq) == 20
    assert np.all(sq == 1.0)

    ft = cosine_flattop(40, rise=10)
    assert len(ft) == 40
    # Peak is 1.0
    assert np.isclose(np.max(ft.real), 1.0)
    # Middle is flat 1.0
    assert np.allclose(ft.real[10:30], 1.0)
    # Ends ramp up from 0
    assert ft.real[0] < ft.real[5] < ft.real[10]


def test_waveform_library_unique_memory():
    lib = WaveformLibrary()
    g0 = "gen_0"
    g1 = "gen_1"

    w1 = np.ones(100, dtype=np.complex128)
    w2 = np.ones(250, dtype=np.complex128)

    lib.add(g0, "w1", w1)
    lib.add(g0, "w2", w2)
    lib.add(g1, "w1", w1)

    assert lib.count(g0) == 2
    assert lib.samples_used(g0) == 350

    assert lib.count(g1) == 1
    assert lib.samples_used(g1) == 100
