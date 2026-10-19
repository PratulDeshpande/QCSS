"""Port renderer: one continuous, stateful stream per port (P8, seam 1)."""
from __future__ import annotations

import numpy as np

from qcss.signal.filters import FluxLineModel
from qcss.signal.mixer import IQCorrection, IQImpairment
from qcss.signal.port_renderer import DriveChain, FluxChain
from qcss.signal.predistortion import QbloxRTP


def test_ideal_drive_chain_returns_envelope_in_qubit_frame():
    ch = DriveChain(fs_hz=1e9, f_lo_hz=4.9e9, f_phys_frame_hz=5.0e9, rabi_rad_ns=0.3)
    t_ns = np.arange(20.0)
    env = np.ones(20)
    omega = ch.render(env * np.exp(1j * 0.7), t_ns, f_if_hz=100e6)
    assert np.allclose(omega, 0.3 * np.exp(1j * 0.7))


def test_os_correction_cancels_hidden_mixer_imbalance_and_lo_leakage():
    truth = IQImpairment(gain_q=1.1, dc_i=0.02)
    raw = DriveChain(1e9, 4.9e9, 5.0e9, 1.0, truth=truth)
    fixed = DriveChain(1e9, 4.9e9, 5.0e9, 1.0, truth=truth, correction=IQCorrection(gain_ratio=1 / 1.1, dc_i=-0.02))
    t_ns = np.arange(200.0)
    env = np.ones(200)
    image = lambda om: abs(np.mean(om * np.exp(2j * np.pi * 0.2 * t_ns)))      # tone at -2 f_IF
    leak = lambda om: abs(np.mean(om * np.exp(2j * np.pi * 0.1 * t_ns)))       # LO tone at -f_IF
    out_raw, out_fixed = raw.render(env, t_ns, 100e6), fixed.render(env, t_ns, 100e6)
    assert image(out_raw) > 1e-2 and leak(out_raw) > 1e-2
    assert image(out_fixed) < 1e-9 and leak(out_fixed) < 1e-9


def test_flux_predistortion_inverts_the_hidden_line_and_keeps_state_across_pulses():
    fs = 1e9
    truth = FluxLineModel(fs, [(0.04, 45e-9), (-0.02, 900e-9)])
    rtp = QbloxRTP(fs)
    rtp.configure([(0.04, 45e-9), (-0.02, 900e-9)])
    chain = FluxChain(truth=truth, predistortion=rtp)
    pulse = np.ones(60)
    first = chain.render(pulse, start_sample=0)
    second = chain.render(pulse, start_sample=200)          # gap of 140 zero samples is fast-forwarded
    assert np.max(np.abs(first - pulse)) < 1e-3
    assert np.max(np.abs(second - pulse)) < 1e-3


def test_uncorrected_flux_line_carries_its_tail_into_the_next_pulse():
    fs = 1e9
    chain = FluxChain(truth=FluxLineModel(fs, [(-0.1, 2e-6)]))
    pulse = np.ones(100)
    a = chain.render(pulse, start_sample=0)
    b = chain.render(pulse, start_sample=200)
    assert not np.allclose(a, b)                             # inter-pulse ISI from the long time constant
