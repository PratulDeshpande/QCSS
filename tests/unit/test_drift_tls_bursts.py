"""Unit tests for virtual lab clock, OU drift, TLS defect bath, and cosmic bursts."""
from __future__ import annotations

import numpy as np
import pytest

from qcss.device.bursts import BurstModel
from qcss.device.drift import OUProcess
from qcss.device.labclock import LabClock
from qcss.device.tls import TLSBath


def test_lab_clock_monotonic():
    clock = LabClock(t0_s=10.0)
    clock.advance(5.0)
    assert clock.t_s == 15.0

    with pytest.raises(ValueError, match="cannot go backwards"):
        clock.advance(-1.0)


def test_ou_process_variance_and_stationarity():
    rng = np.random.default_rng(12345)
    mu = 0.0
    sigma = 0.1
    tau = 10.0
    ou = OUProcess(mu=mu, sigma=sigma, tau_s=tau, rng=rng)

    samples = [ou.step(1.0) for _ in range(5000)]
    measured_std = float(np.std(samples))
    # Standard deviation should be within 10% of configured sigma=0.1
    assert np.isclose(measured_std, sigma, rtol=0.10)


def test_burst_model_arrivals_and_recovery():
    rng = np.random.default_rng(54321)
    chip_area = 2.25  # cm^2
    # Rate ~ 0.035 * 2.25 = 0.07875 Hz => mean gap ~ 12.7 s
    model = BurstModel(chip_area_cm2=chip_area, rng=rng)

    # Advance through 1000 seconds
    model.advance_to(1000.0)
    assert len(model.arrival_times_s) > 10

    gaps = np.diff(model.arrival_times_s)
    mean_gap = float(np.mean(gaps))
    expected_gap = 1.0 / model.rate_hz
    # Mean gap within 25% for 1000s window
    assert np.isclose(mean_gap, expected_gap, rtol=0.25)

    # Check temporal recovery profile
    qubit_xy = np.array([[5.0, 5.0]])  # center of chip
    # Test decay over 100 ms in steps of 5 ms
    model.events = []  # inject one single burst at t=1000.0 exactly at (5.0, 5.0)
    from qcss.device.bursts import Burst
    model.events.append(Burst(t0_s=1000.0, xy_mm=np.array([5.0, 5.0]), peak_gamma_per_us=1.0))

    t_eval = np.linspace(1000.0 + 1e-4, 1000.0 + 100e-3, 20)
    gammas = [model.extra_gamma1_per_us(t, qubit_xy)[0] for t in t_eval]

    # After initial rise, gamma must decay monotonically
    assert gammas[0] > gammas[-1]
    # At t = 1000.0 + 25 ms (~1 tau_rec), value should be approximately e^-1 of early peak
    val_25ms = model.extra_gamma1_per_us(1000.0 + 25e-3, qubit_xy)[0]
    val_early = model.extra_gamma1_per_us(1000.0 + 1e-3, qubit_xy)[0]
    assert np.isclose(val_25ms / val_early, np.exp(-1.0), atol=0.1)


def test_tls_bath_extra_decay():
    rng = np.random.default_rng(999)
    bath = TLSBath(f_range_ghz=(4.5, 5.5), n_defects=10, rng=rng)

    # At f_q = 5.0 GHz, TLS bath adds positive decay
    gamma_extra = bath.extra_gamma1_per_us(5.0)
    assert gamma_extra >= 0.0

    # Step time advances spectral diffusion
    bath.step(3600.0)  # 1 hour
    gamma_later = bath.extra_gamma1_per_us(5.0)
    assert gamma_later >= 0.0


def test_the_burst_arrival_history_stays_bounded_on_a_long_running_chip():
    from qcss.device.bursts import MAX_ARRIVAL_HISTORY
    model = BurstModel(chip_area_cm2=2.25, rng=np.random.default_rng(1))
    model.advance_to(30 * 86400.0)                          # a month: ~200k arrivals at 0.08 Hz
    assert len(model.arrival_times_s) == MAX_ARRIVAL_HISTORY
    assert model._next_s is not None
    assert model.arrival_times_s[-1] <= 30 * 86400.0 < model._next_s     # the most recent ones are kept
