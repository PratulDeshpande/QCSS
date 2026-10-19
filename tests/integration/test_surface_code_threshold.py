"""Integration test: Surface Code memory threshold and syndrome decoding on Tier 1a Stim.

Validates:
1. Error suppression below threshold: at p = 0.1%, eps_L(d=5) < eps_L(d=3).
2. Error amplification above threshold: at p = 2.0%, eps_L(d=5) > eps_L(d=3).
3. Threshold crossing occurs between 0.3% and 1.5%.
4. Detector and observable streaming with PyMatching reference decoding.
"""
from __future__ import annotations

import numpy as np

from qcss.physics.stim_t1a import StimT1a


def test_surface_code_detector_streaming():
    """Verify that detector and observable streams match dimensions and PyMatching decodes them."""
    d = 3
    rounds = 3
    eng = StimT1a.generate_surface_code(distance=d, rounds=rounds, physical_error_rate=0.005)
    shots = 200

    dets, obs = eng.sample_detectors(shots=shots, seed=123)
    assert dets.shape[0] == shots
    assert obs.shape == (shots, 1)
    assert dets.dtype == bool
    assert obs.dtype == bool

    # Reference decoding with PyMatching
    preds = eng.decode_syndromes(dets)
    assert preds.shape == (shots, 1)

    # At p=0.005, error rate should be small (< 10%)
    err_rate = np.mean(np.any(preds != obs, axis=1))
    assert err_rate < 0.10


def test_surface_code_threshold_crossing():
    """Verify that rotated surface code memory exhibits threshold crossing between 0.3% and 1.5%."""
    shots = 5000
    seed = 42

    # 1. Below threshold: p = 0.001 (0.1%)
    eng_d3_low = StimT1a.generate_surface_code(distance=3, rounds=3, physical_error_rate=0.001)
    err_d3_low = eng_d3_low.evaluate_logical_error_rate(shots=shots, seed=seed)

    eng_d5_low = StimT1a.generate_surface_code(distance=5, rounds=5, physical_error_rate=0.001)
    err_d5_low = eng_d5_low.evaluate_logical_error_rate(shots=shots, seed=seed)

    # d=5 must have strictly lower logical error rate than d=3
    assert err_d5_low < err_d3_low, f"Below threshold, expected eps_L(d=5) < eps_L(d=3), got {err_d5_low} vs {err_d3_low}"
    lambda_factor = err_d3_low / max(err_d5_low, 1e-6)
    assert lambda_factor > 1.5, f"Expected Lambda > 1.5 below threshold, got {lambda_factor}"

    # 2. Above threshold: p = 0.02 (2.0%)
    eng_d3_high = StimT1a.generate_surface_code(distance=3, rounds=3, physical_error_rate=0.02)
    err_d3_high = eng_d3_high.evaluate_logical_error_rate(shots=shots, seed=seed)

    eng_d5_high = StimT1a.generate_surface_code(distance=5, rounds=5, physical_error_rate=0.02)
    err_d5_high = eng_d5_high.evaluate_logical_error_rate(shots=shots, seed=seed)

    # d=5 must have strictly higher logical error rate than d=3
    assert err_d5_high > err_d3_high, f"Above threshold, expected eps_L(d=5) > eps_L(d=3), got {err_d5_high} vs {err_d3_high}"

    # 3. Crossing check: at p = 0.003 (0.3%), d=5 is still better than d=3
    eng_d3_mid_low = StimT1a.generate_surface_code(distance=3, rounds=3, physical_error_rate=0.003)
    err_d3_mid_low = eng_d3_mid_low.evaluate_logical_error_rate(shots=shots, seed=seed)

    eng_d5_mid_low = StimT1a.generate_surface_code(distance=5, rounds=5, physical_error_rate=0.003)
    err_d5_mid_low = eng_d5_mid_low.evaluate_logical_error_rate(shots=shots, seed=seed)
    assert err_d5_mid_low < err_d3_mid_low

    # at p = 0.015 (1.5%), d=5 is worse than d=3
    eng_d3_mid_high = StimT1a.generate_surface_code(distance=3, rounds=3, physical_error_rate=0.015)
    err_d3_mid_high = eng_d3_mid_high.evaluate_logical_error_rate(shots=shots, seed=seed)

    eng_d5_mid_high = StimT1a.generate_surface_code(distance=5, rounds=5, physical_error_rate=0.015)
    err_d5_mid_high = eng_d5_mid_high.evaluate_logical_error_rate(shots=shots, seed=seed)
    assert err_d5_mid_high > err_d3_mid_high
