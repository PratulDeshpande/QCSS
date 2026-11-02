"""GetDeviceProperties: the error-model numbers an OS predictor needs (T1, T2*, readout and gate errors)."""
from __future__ import annotations

import math

import grpc
import pytest

from qcss.adapters.grpc_server import serve
from qcss.config.loader import load_device, load_profile
from qcss.runtime.jobs import JobManager
from qcss.runtime.runner import SimulationContext
from qcss.v1 import control_service_pb2 as pb
from qcss.v1 import control_service_pb2_grpc as pbg
from tests.conftest import PROFILES_DIR, REPO_ROOT
from tests.integration.test_grpc_end_to_end import _can_connect_loopback, _free_port, fake_runner, fake_validator

DEVICES_DIR = REPO_ROOT / "src" / "qcss" / "config" / "devices"


@pytest.fixture(scope="module")
def ctx() -> SimulationContext:
    return SimulationContext(load_profile(PROFILES_DIR / "qblox_cluster_5q.yaml"),
                             load_device(DEVICES_DIR / "transmon_5q.yaml"))


def test_every_device_qubit_and_coupler_is_reported(ctx):
    props = ctx.device_properties()
    assert sorted(q.qubit_index for q in props.qubits) == [0, 1, 2, 3, 4]
    assert sorted(tuple(p.qubits) for p in props.pairs) == [(0, 1), (0, 2), (1, 2), (1, 3), (2, 4), (3, 4)]
    assert props.source == "device-model"
    assert props.measured_at.seconds > 0


def test_coherence_times_are_the_current_drifted_values(ctx):
    props = ctx.device_properties()
    _, t1_ns = ctx.device_parameters(ctx.lab_time_s)
    by_q = {q.qubit_index: q for q in props.qubits}
    for i, q in enumerate(ctx.qdef):
        assert by_q[q].t1_s == pytest.approx(t1_ns[i] * 1e-9)
    assert by_q[0].t2_star_s == pytest.approx(45e-6)


def test_readout_errors_come_from_the_physical_readout_model(ctx):
    for q in ctx.device_properties().qubits:
        assert 0.0 <= q.prob_meas1_prep0 < 0.2
        assert 0.0 < q.prob_meas0_prep1 < 0.2
        assert q.prob_meas0_prep1 > q.prob_meas1_prep0   # T1 decay during readout makes 1→0 the larger error


def test_single_qubit_gate_error_is_the_coherence_limit(ctx):
    for q in ctx.device_properties().qubits:
        t = q.single_qubit_gate_duration_s
        f_avg = (3 + math.exp(-t / q.t1_s) + 2 * math.exp(-t / q.t2_star_s)) / 6
        assert q.single_qubit_gate_error == pytest.approx(1 - f_avg)
        assert 1e-5 < q.single_qubit_gate_error < 1e-3


def test_two_qubit_gate_error_exceeds_either_single_qubit_error(ctx):
    props = ctx.device_properties()
    e1 = {q.qubit_index: q.single_qubit_gate_error for q in props.qubits}
    for p in props.pairs:
        assert p.coupling_hz > 0
        assert p.two_qubit_gate_duration_s == pytest.approx(1 / (2 * math.sqrt(2) * p.coupling_hz))
        assert p.two_qubit_gate_error > max(e1[p.qubits[0]], e1[p.qubits[1]])


def test_device_without_a_resonator_reports_perfect_readout():
    ctx = SimulationContext(load_profile(PROFILES_DIR / "test_ideal_1q.yaml"))     # no device file: no resonator
    qubits = ctx.device_properties().qubits
    assert qubits and all(q.prob_meas0_prep1 == 0.0 and q.prob_meas1_prep0 == 0.0 for q in qubits)


@pytest.mark.anyio
async def test_get_device_properties_over_grpc(ctx):
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    jobs = JobManager(fake_runner, fake_validator)
    addr = f"127.0.0.1:{_free_port()}"
    server = await serve(addr, jobs, calibration=ctx.calibration, properties=ctx.device_properties)
    try:
        async with grpc.aio.insecure_channel(addr) as ch:
            r = await pbg.ControlServiceStub(ch).GetDeviceProperties(pb.GetDevicePropertiesRequest())
            assert len(r.properties.qubits) == 5
            assert r.properties.calibration_epoch == ctx.calibration.epoch
    finally:
        await server.stop(None)
        await jobs.close()


@pytest.mark.anyio
async def test_get_device_properties_is_unimplemented_without_a_device_model():
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    jobs = JobManager(fake_runner, fake_validator)
    addr = f"127.0.0.1:{_free_port()}"
    server = await serve(addr, jobs)
    try:
        async with grpc.aio.insecure_channel(addr) as ch:
            with pytest.raises(grpc.aio.AioRpcError) as err:
                await pbg.ControlServiceStub(ch).GetDeviceProperties(pb.GetDevicePropertiesRequest())
            assert err.value.code() == grpc.StatusCode.UNIMPLEMENTED
            assert "model" not in (err.value.details() or "")     # says nothing about being a simulator
    finally:
        await server.stop(None)
        await jobs.close()
