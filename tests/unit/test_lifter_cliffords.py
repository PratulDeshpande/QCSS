"""Pulse lifting and Clifford identification from physics, not waveform names (D4)."""
from __future__ import annotations

import numpy as np
import pytest

from qcss.physics.lifter import is_clifford_unitary, lift_1q, lift_multi, nearest_clifford

TWO_PI = 2 * np.pi
X = np.array([[0, 1], [1, 0]], complex)
SX = 0.5 * np.array([[1 + 1j, 1 - 1j], [1 - 1j, 1 + 1j]])
SY = 0.5 * np.array([[1 + 1j, -1 - 1j], [1 + 1j, 1 + 1j]])
CZ = np.diag([1, 1, 1, -1]).astype(complex)


def _same_up_to_phase(a, b):
    return abs(abs(np.trace(a.conj().T @ b)) / a.shape[0] - 1) < 1e-9


def _pulse(area_rad: float, phase: float = 0.0, n: int = 40):
    return np.full(n, area_rad / n * np.exp(1j * phase), complex)   # dt = 1 ns


def test_pi_pulse_lifts_to_x_whatever_its_name():
    u, leak = lift_1q(_pulse(np.pi), 1.0, TWO_PI * -0.3)
    c, fid = nearest_clifford(u)
    assert _same_up_to_phase(c, X)
    assert fid > 0.99 and leak < 0.02


def test_frame_phase_turns_x90_into_y90():
    u, _ = lift_1q(_pulse(np.pi / 2, phase=np.pi / 2), 1.0, TWO_PI * -0.3)
    c, _ = nearest_clifford(u)
    assert _same_up_to_phase(c, SY)
    u0, _ = lift_1q(_pulse(np.pi / 2), 1.0, TWO_PI * -0.3)
    assert _same_up_to_phase(nearest_clifford(u0)[0], SX)


def test_small_rotation_is_not_clifford():
    u, _ = lift_1q(_pulse(0.3), 1.0, TWO_PI * -0.3)
    assert not is_clifford_unitary(u)


@pytest.mark.parametrize("gate", [CZ, np.kron(X, np.eye(2))])
def test_two_qubit_clifford_identified(gate):
    c, fid = nearest_clifford(gate)
    assert _same_up_to_phase(c, gate) and fid > 1 - 1e-12


def test_lift_multi_resonant_exchange_gives_iswap_like_unitary():
    # Two resonant qutrits with exchange J for t = 1/(4J): |01> -> -i|10> (iSWAP)
    j_ghz = 0.01
    t_ns = 1 / (4 * j_ghz)
    n = 100
    u, leak = lift_multi(n_qubits=2, dt_ns=t_ns / n, n_samples=n,
                         detunings_rad_ns=[0.0, 0.0], alphas_rad_ns=[TWO_PI * -0.3] * 2,
                         couplings_rad_ns={(0, 1): TWO_PI * j_ghz})
    assert u.shape == (4, 4)
    assert 0 < leak < 0.01                      # |11> mixes with |20>,|02> via the qutrit level (alpha = -300 MHz)
    assert abs(abs(u[2, 1]) - 1) < 1e-6         # |01> -> |10>
