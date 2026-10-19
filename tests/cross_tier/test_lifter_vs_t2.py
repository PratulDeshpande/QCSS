"""Cross-tier test: Lifter vs T2 Lindblad propagator in the dissipationless limit."""
from __future__ import annotations

import numpy as np

from qcss.ir.frames import TWO_PI
from qcss.physics.lifter import lift_1q
from qcss.physics.lindblad_t2 import LindbladT2, QutritParams


def test_lifter_vs_t2_dissipationless_fidelity():
    """With T1, T2 -> infty, the lifted unitary must reproduce T2 final state with fidelity >= 1 - 1e-6."""
    alpha_ghz = -0.3
    alpha_rad_ns = TWO_PI * alpha_ghz
    dt_ns = 0.5
    dur_ns = 20.0
    n_samp = int(dur_ns / dt_ns)

    # Drive samples (e.g. Gaussian or flat-top drive)
    t = np.linspace(-3, 3, n_samp)
    env = np.exp(-0.5 * t**2)
    omega = 0.05 * TWO_PI * env.astype(complex)

    # Lifted unitary on 2x2 qubit subspace
    u_lifted, _leak = lift_1q(omega, dt_ns, alpha_rad_ns)

    # T2 Lindblad simulation with zero decoherence
    params = QutritParams(
        f01_ghz=[5.0],
        alpha_ghz=[alpha_ghz],
        t1_ns=[1e12],
        t2_ns=[1e12],
        nbar=[0.0],
        frame_ghz=[5.0],
    )
    sim = LindbladT2(params)
    sim.evolve_segment(0.0, dt_ns, drives={0: omega})

    # Expected pure state from U_lifted acting on |0>
    psi_expected = u_lifted @ np.array([1.0, 0.0], dtype=complex)
    norm = np.linalg.norm(psi_expected)
    if norm > 0:
        psi_expected /= norm

    # T2 density matrix projected to qubit subspace
    rho_2x2 = sim.rho.full()[:2, :2]
    tr2 = np.trace(rho_2x2).real
    if tr2 > 0:
        rho_2x2 = rho_2x2 / tr2

    # Fidelity: <psi| rho |psi>
    fid = float(np.real(psi_expected.conj().T @ rho_2x2 @ psi_expected))
    assert fid >= 1.0 - 1e-5, f"Lifter vs T2 fidelity too low: {fid}"
