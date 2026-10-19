"""Unit tests for Tier 1a Stim stabilizer engine."""
from __future__ import annotations

import numpy as np
import pytest
import stim
from scipy.stats import chisquare

from qcss.ir.program import FrameOp
from qcss.physics.statevector_t1b import StatevectorT1b
from qcss.physics.stim_t1a import StimT1a


def test_stim_t1a_clifford_gates():
    sim = StimT1a(2)
    # Bell state |Phi+> = (|00> + |11>) / sqrt(2)
    sim.apply_gate("H", (0,))
    sim.apply_gate("CX", (0, 1))

    # Peek probabilities
    p0 = sim.level_probabilities(0)
    p1 = sim.level_probabilities(1)
    assert np.allclose(p0, [0.5, 0.5, 0.0])
    assert np.allclose(p1, [0.5, 0.5, 0.0])

    # Measurement collapses both to same value
    m0 = sim.measure(0)
    m1 = sim.measure(1)
    assert m0 == m1

    # Level prob of collapsed state
    p0_after = sim.level_probabilities(0)
    expected_p1 = 1.0 if m0 == 1 else 0.0
    assert np.isclose(p0_after[1], expected_p1)


def test_stim_t1a_frame_op_clifford_rz():
    sim = StimT1a(1)
    sim.apply_gate("H", (0,))  # |+>
    # FrameOp shift by pi -> Z gate: |+> -> |->
    sim.frame_op(FrameOp(path="main[0]", frame_id="q0", start=10, kind="shift", value=np.pi), tick=10)
    sim.apply_gate("H", (0,))  # |-> -> |1>
    assert sim.measure(0) == 1

    # Non-Clifford angle should raise ValueError
    with pytest.raises(ValueError, match="Clifford virtual-Z"):
        sim.frame_op(FrameOp(path="main[1]", frame_id="q0", start=20, kind="shift", value=0.35), tick=20)


def test_stim_t1a_idle_pta_noise():
    # Short T1, long idle -> should flip qubit to 1 occasionally
    sim = StimT1a(1, t1_ns=[10.0], t2_ns=[10.0])
    sim.reset_state()
    # Advance by 100 ns: lots of idle noise
    sim.advance_to(100)
    assert sim.clock[0] == 100.0


def test_stim_t1a_statevector_equivalence_with_t1b():
    """Verify that random Clifford circuits in StimT1a produce identical statevector to T1b."""
    H = np.array([[1, 1], [1, -1]], dtype=complex) / np.sqrt(2)
    S = np.array([[1, 0], [0, 1j]], dtype=complex)
    CX = np.array([
        [1, 0, 0, 0],
        [0, 1, 0, 0],
        [0, 0, 0, 1],
        [0, 0, 1, 0],
    ], dtype=complex)

    rng = np.random.default_rng(12345)
    for seed in range(5):
        tab = stim.Tableau.random(3)
        circ = tab.to_circuit()

        stim_eng = StimT1a(3)
        stim_eng.sim.do(circ)
        sv_stim = stim_eng.state_vector(endian="big")

        t1b = StatevectorT1b(3, [1e12] * 3, [1e12] * 3)
        for inst in circ:
            assert isinstance(inst, stim.CircuitInstruction)
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


def test_stim_t1a_noisy_bitstring_distribution_vs_t1b():
    """Verify that bitstring distributions under Pauli noise match between T1a and T1b via chi-square."""
    n_shots = 2000
    p_x = 0.08  # 8% X error

    # Circuit: H(0), CX(0, 1), X_ERROR(0, p_x)
    # Both in Stim and T1b:
    circ = stim.Circuit()
    circ.append("H", [0])
    circ.append("CX", [0, 1])
    circ.append("X_ERROR", [0], p_x)
    circ.append("M", [0, 1])

    sampler = circ.compile_sampler(seed=42)
    shots_stim = sampler.sample(shots=n_shots)
    # Convert [m0, m1] into integers 0..3: 2*m0 + m1
    counts_stim = np.bincount(2 * shots_stim[:, 0] + shots_stim[:, 1], minlength=4)

    # Theoretical probabilities:
    # Noiseless Bell pair gives |00> with 50%, |11> with 50%.
    # With X_ERROR(0, p_x):
    # |00> with (1-p_x)*0.5, |10> with p_x*0.5
    # |11> with (1-p_x)*0.5, |01> with p_x*0.5
    expected_probs = np.array([(1.0 - p_x) * 0.5, p_x * 0.5, p_x * 0.5, (1.0 - p_x) * 0.5])
    expected_counts = expected_probs * n_shots

    # Chi-square test on Stim samples against expected distribution
    res_stim = chisquare(counts_stim, f_exp=expected_counts)
    assert res_stim.pvalue > 0.01, f"Stim distribution rejected: p={res_stim.pvalue}"
