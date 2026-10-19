"""Device specification checks and DeviceState (defects D9, D19)."""
from __future__ import annotations

import numpy as np
import pytest
from pydantic import ValidationError

from qcss.config.device import DeviceSpec
from qcss.config.loader import load_device
from qcss.device.state import DeviceState


def _qubit(**kw):
    q = {"qubit_index": 0, "f_max_ghz": 5.0, "ec_ghz": 0.25, "t1_us": 50.0, "t2_star_us": 40.0}
    q.update(kw)
    return q


def test_inconsistent_temperature_and_population_rejected():
    # 40 mK at 5 GHz implies P_e ~ 0.25 %; a declared 1.5 % is inconsistent (plan, Phase 4)
    with pytest.raises(ValidationError, match="inconsistent"):
        DeviceSpec.model_validate({"device_name": "d", "qubits": [_qubit(t_eff_mk=40.0, p_excited=0.015)]})


def test_consistent_temperature_accepted():
    DeviceSpec.model_validate({"device_name": "d", "qubits": [_qubit(t_eff_mk=40.0, p_excited=0.0025)]})


def test_device_state_constructs_and_is_static_without_dynamics():
    dev = load_device("src/qcss/config/devices/test_ideal_1q.yaml")
    st = DeviceState(dev, np.random.default_rng(0))
    f, t1 = st.snapshot()
    st.advance_time(3600.0)
    assert st.snapshot() == (f, t1)
    assert t1 == [dev.qubits[0].t1_us * 1e3]


def test_device_state_drifts_when_dynamics_enabled():
    dev = load_device("src/qcss/config/devices/transmon_5q.yaml")
    assert dev.dynamics is not None and dev.dynamics.enabled
    st = DeviceState(dev, np.random.default_rng(1))
    _, t1_a = st.snapshot()
    st.advance_time(4 * 3600.0)
    _, t1_b = st.snapshot()
    assert len(t1_a) == 5
    assert t1_a != t1_b
