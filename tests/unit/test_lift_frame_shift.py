"""A flux pulse lifted at one start time gives the lift at any other by a diagonal frame rotation (exact)."""
from __future__ import annotations

import numpy as np

from qcss.physics.lifter import lift_multi, shift_lift_start


def _lift(t0_ns: float) -> tuple[np.ndarray, float]:
    n = 40
    flux = {1: -2 * np.pi * 0.43 * np.ones(n)}           # q1 tuned 430 MHz down, into the 11-20 resonance
    return lift_multi(n_qubits=2, dt_ns=1.0, n_samples=n, detunings_rad_ns=[0.001, -0.002],
                      alphas_rad_ns=[-2 * np.pi * 0.28, -2 * np.pi * 0.29],
                      couplings_rad_ns={(0, 1): 2 * np.pi * 0.0035}, flux=flux,
                      frame_rad_ns=[2 * np.pi * 5.05, 2 * np.pi * 5.2], t0_ns=t0_ns)


def test_shifting_a_lift_matches_lifting_at_the_later_start():
    u_ref, leak_ref = _lift(100.0)
    u_late, leak_late = _lift(100.0 + 12_345.6)
    frames = [2 * np.pi * 5.05, 2 * np.pi * 5.2]
    shifted = shift_lift_start(u_ref, frames, 12_345.6)
    np.testing.assert_allclose(shifted, u_late, atol=1e-8)
    assert leak_ref == leak_late or abs(leak_ref - leak_late) < 1e-10


def test_a_zero_shift_is_the_identity():
    u, _ = _lift(0.0)
    np.testing.assert_array_equal(shift_lift_start(u, [1.0, 2.0], 0.0), u)
