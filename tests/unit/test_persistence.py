"""The chip outlives the chassis process: drift, scenarios and lab time survive a restart."""
from __future__ import annotations

import pytest

from qcss.config.loader import load_device, load_profile
from qcss.runtime.persistence import load_state, save_state
from qcss.runtime.runner import SimulationContext

QBLOX = load_profile("src/qcss/config/profiles/qblox_cluster_5q.yaml")
DEV = load_device("src/qcss/config/devices/transmon_5q.yaml")
IDEAL = load_profile("src/qcss/config/profiles/test_ideal_1q.yaml")
DEV1 = load_device("src/qcss/config/devices/test_ideal_1q.yaml")


def ctx(**kw) -> SimulationContext:
    return SimulationContext(QBLOX, DEV, global_seed=5, **kw)


def test_a_restored_chip_continues_the_same_trajectory(tmp_path):
    a = ctx()
    a.device_parameters(3600.0)
    assert a.device_state is not None
    a.device_state.kill_qubit(1)
    a.lab_time_s = 3600.0
    save_state(tmp_path / "chip.state", a, wall_now=1000.0)

    b = ctx()
    assert load_state(tmp_path / "chip.state", b, wall_now=1000.0)
    assert b.lab_time_s == pytest.approx(3600.0)
    assert b.device_parameters(7200.0) == a.device_parameters(7200.0)      # same RNG state, same drift
    assert b.device_state is not None
    assert 1 in {DEV.qubits[r].qubit_index for r in b.device_state.scenarios.dead}


def test_downtime_counts_as_lab_time(tmp_path):
    a = ctx(time_scale=2.0, wall_clock=lambda: 0.0)
    a.lab_time_s = 100.0
    save_state(tmp_path / "chip.state", a, wall_now=1000.0)
    b = ctx(time_scale=2.0, wall_clock=lambda: 0.0)
    load_state(tmp_path / "chip.state", b, wall_now=1030.0)               # 30 s powered off
    assert b.lab_time_s == pytest.approx(160.0)


def test_a_missing_state_file_means_a_fresh_chip(tmp_path):
    assert load_state(tmp_path / "none.state", ctx()) is False


def test_state_from_another_device_is_refused(tmp_path):
    save_state(tmp_path / "chip.state", ctx())
    other = SimulationContext(IDEAL, DEV1)
    with pytest.raises(ValueError, match="different device"):
        load_state(tmp_path / "chip.state", other)


def test_saving_is_atomic(tmp_path):
    save_state(tmp_path / "chip.state", ctx())
    save_state(tmp_path / "chip.state", ctx())
    assert sorted(p.name for p in tmp_path.iterdir()) == ["chip.state"]


def test_the_state_file_is_plain_json(tmp_path):
    import json
    a = ctx()
    assert a.device_state is not None
    a.device_state.kill_qubit(2)
    a.device_state.tls_collision(0)
    save_state(tmp_path / "chip.state", a)
    data = json.loads((tmp_path / "chip.state").read_text(encoding="utf-8"))   # no executable format
    assert data["format"] == 2


def test_a_pickle_in_place_of_the_state_is_refused_not_executed(tmp_path):
    import pickle

    class Boom:
        def __reduce__(self):
            return (exec, ("raise SystemExit('executed')",))
    (tmp_path / "chip.state").write_bytes(pickle.dumps({"format": 1, "x": Boom()}))
    with pytest.raises(ValueError, match="not a chip state"):
        load_state(tmp_path / "chip.state", ctx())
