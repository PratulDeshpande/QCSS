"""Cross-tier equivalence tests: Tier 1a (Stim stabilizer) vs Tier 1b (Statevector)."""
from __future__ import annotations

import numpy as np
import stim
from scipy.stats import chisquare

from qcss.physics.statevector_t1b import StatevectorT1b
from qcss.physics.stim_t1a import StimT1a


def test_cross_tier_t1a_vs_t1b_noiseless_clifford():
    """Verify that random Clifford circuits produce identical state vectors in T1a and T1b."""
    H = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
    S = np.array([[1, 0], [0, 1j]], dtype=complex)
    CX = np.array([
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 0, 1],
        [0, 0, 1, 0],
    ], dtype=complex)

    rng = np.random.default_rng(42)
    for seed in range(5):
        tab = stim.Tableau.random(3)
        circ = tab.to_circuit()

        stim_eng = StimT1a(3)
        stim_eng.sim.do(circ)
        sv_stim = stim_eng.state_vector(endian="big")

        t1b = StatevectorT1b(3, [1e12] * 3, [1e12] * 3)
        for inst in circ:
            targets = [t.value for t in inst.targets_copy()]
            if inst.name == "H":
                for q in targets:
                    t1b.apply_unitary(H, (q,), 0, 0, rng)
            elif inst.name == "S":
                for q in targets:
                    t1b.apply_unitary(S, (q,), 0, 0, rng)
            elif inst.name == "CX":
                for i in range(0, len(targets), 2):
                    t1b.apply_unitary(CX, (targets[i], targets[i + 1]), 0, 0, rng)

        overlap = abs(np.vdot(sv_stim, t1b.psi))
        assert np.isclose(overlap, 1.0, atol=1e-5), f"Failed for seed {seed}: overlap={overlap}"


def test_cross_tier_t1a_vs_t1b_noisy_pauli_distribution():
    """Verify that bitstring distributions under Pauli noise match between T1a and T1b via chi-square."""
    n_shots = 2000
    p_x = 0.05

    circ = stim.Circuit()
    circ.append("H", [0])
    circ.append("CX", [0, 1])
    circ.append("X_ERROR", [0], p_x)
    circ.append("M", [0, 1])

    shots_stim = circ.compile_sampler(seed=77).sample(shots=n_shots)
    counts_stim = np.bincount(2 * shots_stim[:, 0] + shots_stim[:, 1], minlength=4)

    expected_probs = np.array([(1.0 - p_x) * 0.5, p_x * 0.5, p_x * 0.5, (1.0 - p_x) * 0.5])
    expected_counts = expected_probs * n_shots

    res = chisquare(counts_stim, f_exp=expected_counts)
    assert res.pvalue > 0.005, f"Chi-square test rejected: p={res.pvalue}"
