"""The chassis as `qcss serve` runs it: lab link, admin link, persistence across restarts."""
from __future__ import annotations

import grpc
import pytest

from qcss.admin.v1 import admin_pb2 as apb
from qcss.admin.v1 import admin_pb2_grpc as apbg
from qcss.chassis import Chassis, ChassisConfig
from qcss.config.loader import load_device, load_profile
from qcss.v1 import control_service_pb2 as pb
from qcss.v1 import control_service_pb2_grpc as pbg
from tests.integration.test_grpc_end_to_end import _can_connect_loopback, _free_port

pytestmark = pytest.mark.anyio
PROFILE = load_profile("src/qcss/config/profiles/qblox_cluster_5q.yaml")
DEVICE = load_device("src/qcss/config/devices/transmon_5q.yaml")
ADMIN = (("authorization", "Bearer admin-token"),)


def config(state_dir, **kw) -> ChassisConfig:
    return ChassisConfig(profile=PROFILE, device=DEVICE, lab_address=f"127.0.0.1:{_free_port()}",
                         admin_address=f"127.0.0.1:{_free_port()}", admin_token="admin-token",
                         state_dir=state_dir, **kw)


async def truth(cfg: ChassisConfig) -> apb.ReadTruthResponse:
    assert cfg.admin_address is not None
    async with grpc.aio.insecure_channel(cfg.admin_address) as ch:
        return await apbg.AdminServiceStub(ch).ReadTruth(apb.ReadTruthRequest(), metadata=ADMIN)


async def test_the_chip_survives_a_chassis_restart(tmp_path):
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    first = Chassis(config(tmp_path, time_scale=0.0))
    await first.start()
    try:
        assert first.config.admin_address is not None
        async with grpc.aio.insecure_channel(first.config.admin_address) as ch:
            await apbg.AdminServiceStub(ch).KillQubit(apb.KillQubitRequest(qubit_index=3), metadata=ADMIN)
        before = await truth(first.config)
    finally:
        await first.stop()

    second = Chassis(config(tmp_path, time_scale=0.0))
    await second.start()
    try:
        after = await truth(second.config)
        assert [q.dead for q in after.qubits] == [q.dead for q in before.qubits]
        assert after.qubits[3].dead
        assert [q.frequency_hz for q in after.qubits] == pytest.approx([q.frequency_hz for q in before.qubits])
    finally:
        await second.stop()


async def test_a_lab_chassis_hides_the_simulation(tmp_path):
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    chassis = Chassis(config(tmp_path))
    await chassis.start()
    try:
        assert chassis.ctx.tier_policy == "AUTO" and not chassis.ctx.honour_job_seed
        assert chassis.ctx.time_scale == 1.0
        async with grpc.aio.insecure_channel(chassis.config.lab_address) as ch:
            with pytest.raises(grpc.aio.AioRpcError) as err:
                await pbg.ControlServiceStub(ch).GetDeviceProperties(pb.GetDevicePropertiesRequest())
            assert err.value.code() == grpc.StatusCode.UNIMPLEMENTED
            with pytest.raises(grpc.aio.AioRpcError) as err:
                await apbg.AdminServiceStub(ch).ReadTruth(apb.ReadTruthRequest(), metadata=ADMIN)
            assert err.value.code() == grpc.StatusCode.UNIMPLEMENTED
    finally:
        await chassis.stop()


async def test_a_deterministic_chassis_replays_seeds(tmp_path):
    chassis = Chassis(config(tmp_path, deterministic=True, seed=11))
    assert chassis.ctx.honour_job_seed and chassis.ctx.global_seed == 11
