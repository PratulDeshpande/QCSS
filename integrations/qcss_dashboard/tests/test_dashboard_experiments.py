"""Standard experiments, built as real QCSS jobs and run in process (the sandbox) through QCSS's own runner."""
from __future__ import annotations

import numpy as np
import pytest

from qcss.config.loader import load_device, load_profile
from qcss.runtime.runner import SimulationContext
from qcss_dashboard.experiments import EXPERIMENTS, build_job, run_in_sandbox

PROFILE = load_profile("src/qcss/config/profiles/qblox_cluster_5q.yaml")
DEVICE = load_device("src/qcss/config/devices/transmon_5q.yaml")


@pytest.mark.parametrize("kind", sorted(EXPERIMENTS))
def test_every_experiment_compiles_and_validates_against_the_profile(kind):
    ctx = SimulationContext(PROFILE, DEVICE)
    job, axis = build_job(kind, ctx, qubit=0, points=5, shots=50)
    plan = ctx.plan(job)                     # raises on any hardware violation
    assert len(plan.points) == len(axis["values"]) == (2 if kind == "single_shot" else 5)


def test_rabi_population_rises_then_falls_and_the_fit_finds_pi():
    res = run_in_sandbox("rabi", PROFILE, DEVICE, qubit=0, points=11, shots=300, seed=11, tier="T1B")
    p1 = np.asarray(res["p1"])
    assert p1[0] < 0.15                                  # no drive: ground state (thermal + readout error)
    assert p1.max() > 0.8                                # some amplitude flips the qubit
    assert 0.0 < res["fit"]["pi_amplitude"] <= 1.0
    assert res["tier"] == "T1B" and res["axis"]["unit"] == "FS"


def test_t1_decays_towards_the_ground_state():
    res = run_in_sandbox("t1", PROFILE, DEVICE, qubit=0, points=6, shots=300, seed=5, tier="T1B",
                         max_delay_us=200.0)
    p1 = np.asarray(res["p1"])
    assert p1[0] > 0.7 and p1[-1] < p1[0] - 0.3
    assert 10.0 < res["fit"]["t1_us"] < 500.0


def test_single_shot_returns_two_iq_clouds_and_a_fidelity():
    res = run_in_sandbox("single_shot", PROFILE, DEVICE, qubit=0, points=2, shots=200, seed=3, tier="T1B")
    assert set(res["iq"]) == {"0", "1"} and len(res["iq"]["0"]) == 200
    assert 0.5 < res["fit"]["assignment_fidelity"] <= 1.0


def test_same_seed_same_result_different_seed_different_result():
    a = run_in_sandbox("rabi", PROFILE, DEVICE, qubit=0, points=5, shots=100, seed=1, tier="T1B")
    b = run_in_sandbox("rabi", PROFILE, DEVICE, qubit=0, points=5, shots=100, seed=1, tier="T1B")
    c = run_in_sandbox("rabi", PROFILE, DEVICE, qubit=0, points=5, shots=100, seed=2, tier="T1B")
    assert a["p1"] == b["p1"] and a["p1"] != c["p1"]
