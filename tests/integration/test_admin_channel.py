"""The admin channel: separate address and token; scenarios, modes, truth and instrument faults."""
from __future__ import annotations

import asyncio
import time
from typing import Self

import grpc
import pytest

from qcss.adapters.admin_server import AdminService, serve_admin
from qcss.adapters.grpc_server import describe_device, serve
from qcss.adapters.instrument_faults import InstrumentFaults
from qcss.admin.v1 import admin_pb2 as apb
from qcss.admin.v1 import admin_pb2_grpc as apbg
from qcss.config.loader import load_device, load_profile
from qcss.runtime.jobs import JobManager
from qcss.runtime.runner import SimulationContext, create_simulation_runner, create_simulation_validator
from qcss.v1 import control_service_pb2 as pb
from qcss.v1 import control_service_pb2_grpc as pbg
from qcss.v1 import job_pb2, result_pb2
from tests.integration.test_grpc_end_to_end import _can_connect_loopback, _free_port

pytestmark = pytest.mark.anyio
PROFILE = load_profile("src/qcss/config/profiles/test_ideal_1q.yaml")
DEVICE = load_device("src/qcss/config/devices/test_ideal_1q.yaml")
LAB, ADMIN = "lab-token", "admin-token"


def pi_job(shots: int = 100) -> job_pb2.Job:
    j = job_pb2.Job(job_key="t", num_shots=shots)
    j.waveform_library["pi"].CopyFrom(job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=20))
    j.main.instructions.add(start_tick=0, play=job_pb2.Play(channel_id="xy_q0", waveform_id="pi", amplitude=0.5))
    j.main.instructions.add(start_tick=24, acquire=job_pb2.Acquire(
        channel_id="ro_q0", integration_ticks=400, mode=job_pb2.ACQUISITION_MODE_DISCRIMINATED, result_key="q0"))
    return j


def auth(token: str):
    return (("authorization", f"Bearer {token}"),)


class Lab:
    """A chassis: lab link and admin link on two addresses, as `qcss serve` wires them."""

    async def __aenter__(self) -> Self:
        if not _can_connect_loopback():
            pytest.skip("Loopback socket connection not permitted in current sandbox environment")
        self.ctx = SimulationContext(PROFILE, DEVICE, honour_job_seed=False, tier_policy="AUTO")
        runner = create_simulation_runner(PROFILE, DEVICE, context=self.ctx)
        self.jobs = JobManager(runner, create_simulation_validator(PROFILE, self.ctx.tb, DEVICE, context=self.ctx),
                               expose_diagnostics=False)
        self.faults = InstrumentFaults(on_reboot=self.jobs.abort_all)
        self.lab_addr, self.admin_addr = f"127.0.0.1:{_free_port()}", f"127.0.0.1:{_free_port()}"
        self.lab = await serve(self.lab_addr, self.jobs, describe_device(PROFILE, self.ctx.bindings),
                               self.ctx.calibration, token=LAB, faults=self.faults)
        self.admin = await serve_admin(self.admin_addr, AdminService(self.ctx, self.jobs, self.faults), token=ADMIN)
        self.lab_ch = grpc.aio.insecure_channel(self.lab_addr)
        self.admin_ch = grpc.aio.insecure_channel(self.admin_addr)
        self.control = pbg.ControlServiceStub(self.lab_ch)
        self.adm = apbg.AdminServiceStub(self.admin_ch)
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.lab_ch.close()
        await self.admin_ch.close()
        await self.lab.stop(None)
        await self.admin.stop(None)
        await self.jobs.close()


async def test_the_admin_channel_needs_its_own_token():
    async with Lab() as lab:
        with pytest.raises(grpc.aio.AioRpcError) as err:
            await lab.adm.GetMode(apb.GetModeRequest(), metadata=auth(LAB))
        assert err.value.code() == grpc.StatusCode.UNAUTHENTICATED
        await lab.adm.GetMode(apb.GetModeRequest(), metadata=auth(ADMIN))


async def test_the_lab_link_does_not_serve_admin_calls():
    async with Lab() as lab:
        stub = apbg.AdminServiceStub(lab.lab_ch)
        with pytest.raises(grpc.aio.AioRpcError) as err:
            await stub.GetMode(apb.GetModeRequest(), metadata=auth(LAB))
        assert err.value.code() == grpc.StatusCode.UNIMPLEMENTED


async def test_killing_a_qubit_shows_in_the_truth():
    async with Lab() as lab:
        before = await lab.adm.ReadTruth(apb.ReadTruthRequest(), metadata=auth(ADMIN))
        await lab.adm.KillQubit(apb.KillQubitRequest(qubit_index=0), metadata=auth(ADMIN))
        after = await lab.adm.ReadTruth(apb.ReadTruthRequest(), metadata=auth(ADMIN))
        assert after.qubits[0].dead and not before.qubits[0].dead
        assert after.qubits[0].t1_s < 1e-6 < before.qubits[0].t1_s
        assert after.properties.qubits                                # the full error model is admin-only


async def test_scenarios_reach_the_device_state():
    async with Lab() as lab:
        md = auth(ADMIN)
        await lab.adm.DriftStep(apb.DriftStepRequest(qubit_index=0, delta_frequency_hz=2e6, t1_factor=0.5),
                                metadata=md)
        t = await lab.adm.ReadTruth(apb.ReadTruthRequest(), metadata=md)
        f0, t10 = lab.ctx.qdef[0].f01_ghz * 1e9, lab.ctx.qdef[0].t1_ns * 1e-9
        assert t.qubits[0].frequency_hz == pytest.approx(f0 + 2e6)
        assert t.qubits[0].t1_s == pytest.approx(0.5 * t10)
        await lab.adm.ClearScenarios(apb.ClearScenariosRequest(), metadata=md)
        t = await lab.adm.ReadTruth(apb.ReadTruthRequest(), metadata=md)
        assert t.qubits[0].frequency_hz == pytest.approx(f0)
        with pytest.raises(grpc.aio.AioRpcError) as err:
            await lab.adm.KillQubit(apb.KillQubitRequest(qubit_index=9), metadata=md)
        assert err.value.code() == grpc.StatusCode.NOT_FOUND


async def test_set_mode_changes_how_the_chassis_runs():
    async with Lab() as lab:
        mode = apb.Mode(time_scale=60.0, deterministic=True, tier_policy=job_pb2.FIDELITY_TIER_T2_LINDBLAD)
        got = await lab.adm.SetMode(apb.SetModeRequest(mode=mode), metadata=auth(ADMIN))
        assert got.mode == mode
        assert lab.ctx.time_scale == 60.0 and lab.ctx.honour_job_seed and lab.ctx.tier_policy == "T2"
        read = await lab.adm.GetMode(apb.GetModeRequest(), metadata=auth(ADMIN))
        assert read.mode == mode


async def test_inspect_job_reports_what_the_lab_link_hides():
    async with Lab() as lab:
        sub = await lab.control.SubmitJob(pb.SubmitJobRequest(job=pi_job()), metadata=auth(LAB))
        st = await lab.control.GetJobStatus(pb.GetJobStatusRequest(job_id=sub.job_id), metadata=auth(LAB))
        assert st.status.tier_used == 0
        info = await lab.adm.InspectJob(apb.InspectJobRequest(job_id=sub.job_id), metadata=auth(ADMIN))
        assert info.tier_used == job_pb2.FIDELITY_TIER_T1B_STATEVECTOR


async def test_a_dropped_connection_fails_the_next_call_only():
    async with Lab() as lab:
        await lab.adm.InjectInstrumentFault(apb.InjectInstrumentFaultRequest(
            fault=apb.INSTRUMENT_FAULT_DROP, count=1), metadata=auth(ADMIN))
        with pytest.raises(grpc.aio.AioRpcError) as err:
            await lab.control.DescribeDevice(pb.DescribeDeviceRequest(), metadata=auth(LAB))
        assert err.value.code() == grpc.StatusCode.UNAVAILABLE
        await lab.control.DescribeDevice(pb.DescribeDeviceRequest(), metadata=auth(LAB))


async def test_a_hang_delays_the_next_call():
    async with Lab() as lab:
        await lab.adm.InjectInstrumentFault(apb.InjectInstrumentFaultRequest(
            fault=apb.INSTRUMENT_FAULT_HANG, count=1, duration_s=0.5), metadata=auth(ADMIN))
        t0 = time.monotonic()
        await lab.control.DescribeDevice(pb.DescribeDeviceRequest(), metadata=auth(LAB))
        assert time.monotonic() - t0 >= 0.45
        t0 = time.monotonic()
        await lab.control.DescribeDevice(pb.DescribeDeviceRequest(), metadata=auth(LAB))
        assert time.monotonic() - t0 < 0.45


async def test_a_slow_upload_delays_submission_only():
    async with Lab() as lab:
        await lab.adm.InjectInstrumentFault(apb.InjectInstrumentFaultRequest(
            fault=apb.INSTRUMENT_FAULT_SLOW_UPLOAD, count=1, duration_s=0.5), metadata=auth(ADMIN))
        t0 = time.monotonic()
        await lab.control.DescribeDevice(pb.DescribeDeviceRequest(), metadata=auth(LAB))
        assert time.monotonic() - t0 < 0.45
        await lab.control.SubmitJob(pb.SubmitJobRequest(job=pi_job()), metadata=auth(LAB))
        assert time.monotonic() - t0 >= 0.45


async def test_a_reboot_fails_running_jobs_and_refuses_calls_for_a_while():
    async with Lab() as lab:
        sub = await lab.control.SubmitJob(pb.SubmitJobRequest(job=pi_job(shots=200_000)), metadata=auth(LAB))
        await asyncio.sleep(0.2)
        await lab.adm.InjectInstrumentFault(apb.InjectInstrumentFaultRequest(
            fault=apb.INSTRUMENT_FAULT_REBOOT, duration_s=0.5), metadata=auth(ADMIN))
        assert lab.jobs.status(sub.job_id).state == result_pb2.JOB_STATE_FAILED
        with pytest.raises(grpc.aio.AioRpcError) as err:
            await lab.control.DescribeDevice(pb.DescribeDeviceRequest(), metadata=auth(LAB))
        assert err.value.code() == grpc.StatusCode.UNAVAILABLE
        await asyncio.sleep(0.6)
        await lab.control.DescribeDevice(pb.DescribeDeviceRequest(), metadata=auth(LAB))
