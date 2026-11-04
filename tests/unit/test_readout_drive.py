"""A readout driven by an explicit tone: the hardware view of the ADC window.

Without a readout tone in the program the readout model keeps its calibrated view (window aligned to
the signal, matched filter). A board that plays the probe tone itself (QICK) gives the model a
``ReadoutDrive``: the tone's amplitude scales the resonator drive, the window starts where the trigger
is relative to the tone (so the time of flight shows), and the window is summed as captured (boxcar).
"""
from __future__ import annotations

import numpy as np
import pytest

from qcss.config.device import ResonatorSpec
from qcss.readout.model import PhysicalReadout, ReadoutDrive, SurrogateReadout

SPEC = ResonatorSpec(qubit_index=0, f_r_ghz=7.0, kappa_mhz=2.0, pulls_mhz=(-0.5, 0.5, 1.2), eta=0.4)
DT, TOF_NS = 1.0, 100.0
N = 400                                                       # window samples


def _ro():
    return PhysicalReadout(SPEC, adc_dt_ns=DT, tof_ns=TOF_NS, readout_frequency_hz=7.0e9 - 0.5e6)


def _mean_iq(drive, levels=0, shots=4000, seed=1):
    r = _ro().acquire(np.full(shots, levels), N, 1e9, np.random.default_rng(seed), drive=drive)
    return r.iq.mean(), r


def test_a_stronger_tone_gives_a_proportionally_larger_signal_on_the_same_noise():
    full, r1 = _mean_iq(ReadoutDrive(scale=1.0, offset_samples=150, drive_samples=1000))
    half, r2 = _mean_iq(ReadoutDrive(scale=0.5, offset_samples=150, drive_samples=1000))
    assert abs(half) == pytest.approx(abs(full) / 2, rel=0.05)
    assert np.std(np.real(r1.iq)) == pytest.approx(np.std(np.real(r2.iq)), rel=0.1)   # the noise is not the tone's


def test_a_window_before_the_tone_arrives_holds_only_noise():
    early, _ = _mean_iq(ReadoutDrive(scale=1.0, offset_samples=-N, drive_samples=1000))
    late, _ = _mean_iq(ReadoutDrive(scale=1.0, offset_samples=150, drive_samples=1000))
    assert abs(early) < 0.05 * abs(late)


def test_the_raw_window_shows_the_time_of_flight():
    r = _ro().acquire(np.zeros(2000, dtype=int), N, 1e9, np.random.default_rng(2), want_trace=True,
                      drive=ReadoutDrive(scale=4.0, offset_samples=0, drive_samples=1000))
    assert r.traces is not None and r.traces.shape == (2000, N)       # the window, sample by sample
    mean = np.abs(r.traces.mean(axis=0))
    tof = int(TOF_NS / DT)
    assert mean[: tof - 5].mean() < 0.3 * mean[tof + 50:].mean()      # nothing comes back before the ToF


def test_the_window_is_summed_as_captured():
    drive = ReadoutDrive(scale=1.0, offset_samples=150, drive_samples=1000)
    r = _ro().acquire(np.zeros(3, dtype=int), N, 1e9, np.random.default_rng(3), want_trace=True, drive=drive)
    assert r.traces is not None
    np.testing.assert_allclose(r.iq, r.traces.sum(axis=1) * DT)


def test_the_surrogate_readout_hands_a_driven_window_to_the_physical_model():
    s = SurrogateReadout(_ro())
    drive = ReadoutDrive(scale=0.5, offset_samples=150, drive_samples=1000)
    a = s.acquire(np.zeros(50, dtype=int), N, 1e9, np.random.default_rng(4), drive=drive)
    b = _ro().acquire(np.zeros(50, dtype=int), N, 1e9, np.random.default_rng(4), drive=drive)
    np.testing.assert_allclose(a.iq, b.iq)


def test_the_tones_phase_turns_the_signal_but_not_the_noise():
    a, _ = _mean_iq(ReadoutDrive(scale=1.0, offset_samples=150, drive_samples=1000))
    b, _ = _mean_iq(ReadoutDrive(scale=1.0, offset_samples=150, drive_samples=1000, phase_rad=np.pi / 2))
    assert np.angle(b / a) == pytest.approx(np.pi / 2, abs=0.1)
    assert abs(b) == pytest.approx(abs(a), rel=0.05)
