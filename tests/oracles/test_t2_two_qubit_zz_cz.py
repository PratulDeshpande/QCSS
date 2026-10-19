"""Oracle tests for two-qutrit T2 physics: emergent ZZ from exchange J, and two-qubit relaxation."""
from __future__ import annotations

import numpy as np
import qutip as qt

from qcss.physics.lindblad_t2 import DIM, LindbladT2, QutritParams
from qcss.physics.transmon import zz_second_order_ghz


def test_emergent_zz_from_exchange_coupling():
    """Verify that static ZZ emerges directly from J(a†b + ab†) without hand-crafted zeta*n*n term."""
    j_ghz = 0.005      # J = 5 MHz
    f1_ghz = 5.0       # Qubit 0 at 5.0 GHz
    f2_ghz = 5.1       # Qubit 1 at 5.1 GHz (Delta = -100 MHz)
    a1_ghz = -0.3      # -300 MHz
    a2_ghz = -0.3      # -300 MHz

    # Analytical second-order prediction
    zeta_analytic_ghz = zz_second_order_ghz(j_ghz, f1_ghz, f2_ghz, a1_ghz, a2_ghz)
    zeta_analytic_khz = zeta_analytic_ghz * 1e6

    # Construct two-qutrit Hamiltonian with exchange J
    a0 = qt.tensor(qt.destroy(DIM), qt.qeye(DIM))
    a1 = qt.tensor(qt.qeye(DIM), qt.destroy(DIM))
    n0 = a0.dag() @ a0
    n1 = a1.dag() @ a1

    H0 = (
        2 * np.pi * f1_ghz * n0
        + 0.5 * 2 * np.pi * a1_ghz * (a0.dag() ** 2 @ a0 ** 2)
        + 2 * np.pi * f2_ghz * n1
        + 0.5 * 2 * np.pi * a2_ghz * (a1.dag() ** 2 @ a1 ** 2)
    )
    H_int = 2 * np.pi * j_ghz * (a0.dag() @ a1 + a0 @ a1.dag())
    H_tot = H0 + H_int

    # Diagonalize to find dressed eigenenergies
    eigenenergies, eigenstates = H_tot.eigenstates()

    # Identify dressed eigenstates |00>, |01>, |10>, |11> by maximum overlap
    basis_states = {
        (0, 0): qt.tensor(qt.basis(DIM, 0), qt.basis(DIM, 0)),
        (0, 1): qt.tensor(qt.basis(DIM, 0), qt.basis(DIM, 1)),
        (1, 0): qt.tensor(qt.basis(DIM, 1), qt.basis(DIM, 0)),
        (1, 1): qt.tensor(qt.basis(DIM, 1), qt.basis(DIM, 1)),
    }

    dressed_energies = {}
    for label, bare in basis_states.items():
        overlaps = [abs(bare.overlap(dressed)) ** 2 for dressed in eigenstates]
        best_idx = int(np.argmax(overlaps))
        dressed_energies[label] = eigenenergies[best_idx] / (2 * np.pi)  # in GHz

    # Exact ZZ is defined by: E_11 - E_10 - E_01 + E_00
    e00 = dressed_energies[(0, 0)]
    e01 = dressed_energies[(0, 1)]
    e10 = dressed_energies[(1, 0)]
    e11 = dressed_energies[(1, 1)]

    zeta_exact_ghz = e11 - e10 - e01 + e00
    zeta_exact_khz = zeta_exact_ghz * 1e6

    # From plan: exact ~ 374.4 kHz, analytic ~ 375.0 kHz (agreement within 0.5%)
    assert np.isclose(abs(zeta_exact_khz), abs(zeta_analytic_khz), rtol=0.01)
    assert np.isclose(abs(zeta_exact_khz), 374.4, atol=1.0)


def test_two_qutrit_relaxation():
    """Verify multi-qutrit idle relaxation in LindbladT2."""
    p = QutritParams(
        f01_ghz=[5.0, 5.1],
        alpha_ghz=[-0.3, -0.3],
        t1_ns=[40_000.0, 60_000.0],
        t2_ns=[25_000.0, 35_000.0],
        nbar=[0.0, 0.0],
        frame_ghz=[5.0, 5.1],
        couplings_ghz={},
    )
    sim = LindbladT2(p)
    # Prepare |11>
    s1 = qt.basis(DIM, 1)
    sim.rho = qt.tensor(s1, s1).proj()

    # Evolve idle for 20 us
    sim.evolve_idle(0.0, 20_000.0)

    # Qubit 0 should have decayed to e^{-20/40} = e^{-0.5} ~ 0.6065
    # Qubit 1 should have decayed to e^{-20/60} = e^{-1/3} ~ 0.7165
    p0 = sim.level_probabilities(0)
    p1 = sim.level_probabilities(1)

    assert np.isclose(p0[1], np.exp(-0.5), atol=0.01)
    assert np.isclose(p1[1], np.exp(-1.0 / 3.0), atol=0.01)
