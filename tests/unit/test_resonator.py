"""Unit tests for physical dispersive readout cavity model."""
from __future__ import annotations

import numpy as np
import pytest

from qcss.readout.resonator import (
    DispersiveReadout,
    ResonatorParams,
    drive_amplitude_for_photons,
)


def test_resonator_steady_state_and_ringup():
    tp = 2.0 * np.pi
    kappa = tp * 5e-3  # kappa/2pi = 5 MHz => 0.0314 rad/ns
    chi = tp * 1.5e-3  # chi/2pi = 1.5 MHz => 0.0094 rad/ns

    p = ResonatorParams(
        kappa_rad_ns=kappa,
        pulls_rad_ns=(-chi, +chi, +chi * 1.5),
        drive_detuning_rad_ns=0.0,
        eta=0.4,
        tof_samples=150,
    )
    ro = DispersiveReadout(p)

    n_target = 5.0
    A = drive_amplitude_for_photons(n_target, kappa, chi)
    drive = np.full(1000, A, dtype=np.complex128)

    a0 = ro.mean_field(0, drive)
    a1 = ro.mean_field(1, drive)

    # Steady state for level 0 and level 1
    ss0 = np.sqrt(kappa) * A / (1j * (-chi) + kappa / 2.0)
    ss1 = np.sqrt(kappa) * A / (1j * chi + kappa / 2.0)
    assert np.isclose(a0[-1], ss0, rtol=1e-5)
    assert np.isclose(a1[-1], ss1, rtol=1e-5)
    # Photon number at steady state ~ 5.0
    assert np.isclose(abs(a0[-1]) ** 2, n_target, rtol=1e-5)


def test_resonator_traces_and_tof():
    tp = 2.0 * np.pi
    kappa = tp * 5e-3
    chi = tp * 1.5e-3
    tof = 100

    p = ResonatorParams(
        kappa_rad_ns=kappa,
        pulls_rad_ns=(-chi, +chi, +chi * 1.5),
        drive_detuning_rad_ns=0.0,
        eta=0.4,
        tof_samples=tof,
    )
    ro = DispersiveReadout(p)

    A = drive_amplitude_for_photons(5.0, kappa, chi)
    drive = np.full(500, A, dtype=np.complex128)

    rng = np.random.default_rng(42)
    n_shots = 2000
    tr0 = ro.traces(np.zeros(n_shots, dtype=int), drive, t1_ns=1e12, rng=rng)

    # Before ToF, mean signal should be zero (white noise only)
    pre_tof_mean = np.mean(tr0[:, :tof])
    # Standard error of mean: sigma / sqrt(n_shots * tof)
    sigma = np.sqrt(1.0 / (4.0 * p.eta * p.dt_ns))
    sem = sigma / np.sqrt(n_shots * tof)
    assert abs(pre_tof_mean) < 5 * sem


def test_resonator_t1_asymmetry():
    tp = 2.0 * np.pi
    kappa = tp * 5e-3
    chi = tp * 1.5e-3
    tof = 50

    p = ResonatorParams(
        kappa_rad_ns=kappa,
        pulls_rad_ns=(-chi, +chi, +chi * 1.5),
        drive_detuning_rad_ns=0.0,
        eta=0.4,
        tof_samples=tof,
    )
    ro = DispersiveReadout(p)

    A = drive_amplitude_for_photons(5.0, kappa, chi)
    dur = 500
    drive = np.full(dur, A, dtype=np.complex128)

    rng = np.random.default_rng(101)
    n_shots = 5000

    # Traces with infinite T1
    tr0 = ro.traces(np.zeros(n_shots, dtype=int), drive, t1_ns=1e12, rng=rng)
    tr1 = ro.traces(np.ones(n_shots, dtype=int), drive, t1_ns=1e12, rng=rng)

    # Optimal matched weights
    w = (tr1.mean(0) - tr0.mean(0))[tof:]
    z0 = ro.integrate(tr0, w, tof, 1.0)
    z1 = ro.integrate(tr1, w, tof, 1.0)

    # Separation axis
    diff = z1.mean() - z0.mean()
    u = diff / abs(diff)
    x0 = (z0 * np.conj(u)).real
    x1 = (z1 * np.conj(u)).real

    thr = 0.5 * (x0.mean() + x1.mean())

    # Traces with finite T1 = 20 us (20,000 ns)
    t1_finite = 20_000.0
    tr1_decay = ro.traces(np.ones(n_shots, dtype=int), drive, t1_ns=t1_finite, rng=rng)
    x1_decay = (ro.integrate(tr1_decay, w, tof, 1.0) * np.conj(u)).real

    # Assignment error P(0|1) increases due to decay during readout
    p_0_given_1 = float(np.mean(x1_decay < thr))
    # First-order estimate: (dur / 2) / T1 = 250 / 20000 = 0.0125
    assert p_0_given_1 > 0.005


def test_weighted_integrator_and_discriminators():
    from qcss.readout.discriminator import (
        fit_binary_discriminator,
        fit_multistate_discriminator,
    )
    from qcss.readout.integrator import WeightedIntegrator

    integrator = WeightedIntegrator(convention="sum")
    weights = np.ones(100, dtype=complex)
    traces = np.ones((10, 150), dtype=complex)

    # Valid integration
    z = integrator.integrate(traces, weights, start_sample=10, integration_length=100)
    assert z.shape == (10,)
    assert np.allclose(z, 100.0)

    # Length mismatch raises ValueError (RO-09)
    with pytest.raises(ValueError, match="Weight length mismatch"):
        integrator.integrate(traces, weights, start_sample=10, integration_length=80)

    # Test mean convention
    mean_integrator = WeightedIntegrator(convention="mean")
    z_mean = mean_integrator.integrate(traces, weights, start_sample=10)
    assert np.allclose(z_mean, 1.0)

    # Test BinaryDiscriminator fitting and classification
    rng = np.random.default_rng(123)
    z0 = rng.normal(loc=-2.0, scale=0.5, size=500) + 1j * rng.normal(scale=0.5, size=500)
    z1 = rng.normal(loc=2.0, scale=0.5, size=500) + 1j * rng.normal(scale=0.5, size=500)

    bin_disc = fit_binary_discriminator(z0, z1)
    c0 = bin_disc.classify(z0)
    c1 = bin_disc.classify(z1)
    assert np.mean(c0 == 0) > 0.99
    assert np.mean(c1 == 1) > 0.99

    # Test MultistateDiscriminator fitting and classification (0, 1, 2)
    z2 = rng.normal(loc=6.0, scale=0.5, size=500) + 1j * rng.normal(scale=0.5, size=500)
    multi_disc = fit_multistate_discriminator({0: z0, 1: z1, 2: z2})
    assert len(multi_disc.centroids) == 3
    assert np.mean(multi_disc.classify(z2) == 2) > 0.99
