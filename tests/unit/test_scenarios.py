"""Admin scenario controls act on the hidden device state (they never touch what the lab reports)."""
from __future__ import annotations

import numpy as np
import pytest

from qcss.config.loader import load_device
from qcss.device.state import DeviceState

DYN = load_device("src/qcss/config/devices/transmon_5q.yaml")          # drift, TLS and bursts enabled
STATIC = load_device("src/qcss/config/devices/test_ideal_1q.yaml")     # no dynamics block


def state(dev=DYN, seed=1) -> DeviceState:
    return DeviceState(dev, np.random.default_rng(seed))


@pytest.mark.parametrize("dev", [DYN, STATIC])
def test_a_killed_qubit_loses_coherence_and_moves_off_resonance_until_revived(dev):
    s = state(dev)
    f0, t10 = s.snapshot()
    s.kill_qubit(0)
    f1, t11 = s.snapshot()
    assert t11[0] < 1e3                       # under 1 us
    assert abs(f1[0] - f0[0]) > 0.05          # >50 MHz away from where it was calibrated
    if len(t10) > 1:
        assert t11[1] == pytest.approx(t10[1])
    s.revive_qubit(0)
    f2, t12 = s.snapshot()
    assert f2[0] == pytest.approx(f0[0]) and t12[0] == pytest.approx(t10[0])


@pytest.mark.parametrize("dev", [DYN, STATIC])
def test_drift_steps_accumulate(dev):
    s = state(dev)
    f0, t10 = s.snapshot()
    s.drift_step(0, df_ghz=0.001, t1_factor=0.5)
    s.drift_step(0, df_ghz=0.002)
    f1, t11 = s.snapshot()
    assert f1[0] - f0[0] == pytest.approx(0.003)
    assert t11[0] < 0.6 * t10[0]


def test_freezing_stops_drift_but_not_the_clock():
    s = state()
    s.freeze(True)
    before = s.snapshot()
    s.advance_time(6 * 3600.0)
    assert s.snapshot() == before
    assert s.clock.t_s == 6 * 3600.0
    s.freeze(False)
    s.advance_time(6 * 3600.0)
    assert s.snapshot() != before


@pytest.mark.parametrize("dev", [DYN, STATIC])
def test_a_tls_collision_shortens_t1_of_that_qubit_only(dev):
    s = state(dev)
    _, t10 = s.snapshot()
    s.tls_collision(0)
    _, t11 = s.snapshot()
    assert t11[0] < 0.5 * t10[0]
    assert t11[1:] == pytest.approx(t10[1:])


def test_an_injected_burst_raises_decay_now_and_fades():
    s = state()
    s.freeze(True)                             # isolate the burst from drift
    _, t10 = s.snapshot()
    s.burst(2)
    _, t11 = s.snapshot()
    assert t11[2] < 0.5 * t10[2]
    s.advance_time(1.0)                        # 40 recovery times later
    _, t12 = s.snapshot()
    assert t12[2] == pytest.approx(t10[2], rel=1e-3)


def test_unknown_qubit_is_refused():
    with pytest.raises(KeyError):
        state().kill_qubit(42)


def test_clear_scenarios_restores_the_untouched_device():
    s = state(STATIC)
    before = s.snapshot()
    s.kill_qubit(0)
    s.tls_collision(0)
    s.clear_scenarios()
    assert s.snapshot() == before
