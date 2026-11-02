"""`qcss admin ...` against a running chassis, as an operator or a CI job drives it."""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from typing import Self

import pytest
from click.testing import CliRunner

from qcss.chassis import Chassis, ChassisConfig
from qcss.cli import app
from qcss.config.loader import load_device, load_profile
from tests.integration.test_grpc_end_to_end import _can_connect_loopback, _free_port

TOKEN = "admin-cli-token"


# A fixed, typical chip (every qubit T1 >= 46 us): with fresh entropy about 1 start in 10-20 draws a TLS
# defect onto a qubit (T1 ~ 4 us) and physics assertions fail by luck. Entropy itself is tested elsewhere.
TEST_CHIP_SEED = 40


class _ChassisThread:
    def __init__(self, tmp: str) -> None:
        self.chassis = Chassis(ChassisConfig(
            profile=load_profile("src/qcss/config/profiles/qblox_cluster_5q.yaml"),
            device=load_device("src/qcss/config/devices/transmon_5q.yaml"),
            lab_address=f"127.0.0.1:{_free_port()}", admin_address=f"127.0.0.1:{_free_port()}",
            admin_token=TOKEN, state_dir=None, time_scale=0.0, seed=TEST_CHIP_SEED))
        self.admin = self.chassis.config.admin_address
        self._ready = threading.Event()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self.chassis.start())
        self._ready.set()
        self._loop.run_forever()

    def __enter__(self) -> Self:
        self._thread.start()
        assert self._ready.wait(10)
        return self

    def __exit__(self, *exc: object) -> None:
        asyncio.run_coroutine_threadsafe(self.chassis.stop(), self._loop).result(10)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(10)


@pytest.fixture
def chassis(tmp_path) -> Iterator[_ChassisThread]:
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    with _ChassisThread(str(tmp_path)) as c:
        yield c


def _admin(chassis: _ChassisThread, *args: str):
    assert chassis.admin is not None
    return CliRunner().invoke(app, ["admin", *args, "--target", chassis.admin, "--token", TOKEN])


def test_kill_then_truth_shows_the_dead_qubit(chassis):
    r = _admin(chassis, "kill", "2")
    assert r.exit_code == 0, r.output
    r = _admin(chassis, "truth")
    assert r.exit_code == 0, r.output
    line = next(ln for ln in r.output.splitlines() if ln.strip().startswith("2 "))
    assert "DEAD" in line


def test_mode_shows_and_sets_how_the_chassis_runs(chassis):
    r = _admin(chassis, "mode", "--time-scale", "50", "--deterministic", "--tier", "t2")
    assert r.exit_code == 0, r.output
    assert chassis.chassis.ctx.time_scale == 50 and chassis.chassis.ctx.honour_job_seed
    assert chassis.chassis.ctx.tier_policy == "T2"
    r = _admin(chassis, "mode")
    assert "time_scale 50" in r.output and "deterministic yes" in r.output and "tier T2" in r.output


def test_drift_and_clear(chassis):
    f0 = chassis.chassis.ctx.device_parameters(chassis.chassis.ctx.lab_time_s)[0][0]
    assert _admin(chassis, "drift", "0", "--df-hz", "3e6").exit_code == 0
    f1 = chassis.chassis.ctx.device_parameters(chassis.chassis.ctx.lab_time_s)[0][0]
    assert f1 - f0 == pytest.approx(3e-3, abs=1e-6)
    assert _admin(chassis, "clear").exit_code == 0
    f2 = chassis.chassis.ctx.device_parameters(chassis.chassis.ctx.lab_time_s)[0][0]
    assert f2 == pytest.approx(f0, abs=1e-6)


def test_fault_injects_an_instrument_fault(chassis):
    r = _admin(chassis, "fault", "drop", "--count", "2")
    assert r.exit_code == 0, r.output
    assert chassis.chassis.jobs is not None


def test_a_wrong_token_is_refused(chassis):
    assert chassis.admin is not None
    r = CliRunner().invoke(app, ["admin", "truth", "--target", chassis.admin, "--token", "nope"])
    assert r.exit_code != 0
    assert "UNAUTHENTICATED" in r.output


def test_serve_refuses_a_network_admin_bind_without_tls():
    r = CliRunner().invoke(app, ["serve", "--admin-listen", "0.0.0.0:50052", "--profile", "test_ideal_1q"])
    assert r.exit_code != 0
    assert "refusing to bind 0.0.0.0:50052" in r.output
