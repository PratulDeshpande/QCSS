"""ControlService: calibration epochs, FAILED_PRECONDITION mapping, DescribeDevice, and the OS
calibration loop acting on the simulated hardware (defects D13, D16)."""
from __future__ import annotations

import grpc
import numpy as np
import pytest

from qcss.adapters.grpc_server import ControlService, describe_device
from qcss.config.device import DeviceSpec
from qcss.config.loader import load_device, load_profile
from qcss.core.ndarray import from_proto
from qcss.core.timebase import TimeBase
from qcss.runtime.jobs import JobManager
from qcss.runtime.runner import SimulationContext, create_simulation_runner, create_simulation_validator
from qcss.v1 import calibration_pb2, device_pb2, job_pb2
from qcss.v1 import control_service_pb2 as pb

PROFILES = "src/qcss/config/profiles/"
IDEAL = load_profile(PROFILES + "test_ideal_1q.yaml")
QBLOX = load_profile(PROFILES + "qblox_cluster_5q.yaml")
DEV1 = load_device("src/qcss/config/devices/test_ideal_1q.yaml")


class Ctx:
    def __init__(self):
        self.status: tuple = ()             # (code, details) once the servicer aborts

    async def abort(self, code, details=""):
        self.status = (code, details)
        raise grpc.RpcError(details)

    async def abort_with_status(self, status):
        self.status = (status.code, status.details)
        raise grpc.RpcError(status.details)


def _service(profile, device):
    ctx = SimulationContext(profile, device, TimeBase.from_clocks(profile.clock.tick_hz))
    jobs = JobManager(create_simulation_runner(profile, device, context=ctx),
                      create_simulation_validator(profile, ctx.tb, device, context=ctx))
    return ControlService(jobs, describe_device(profile, ctx.bindings), ctx.calibration), jobs


def _pi_job(tier=job_pb2.FIDELITY_TIER_T1B_STATEVECTOR, amp=0.5, shots=4000) -> job_pb2.Job:
    j = job_pb2.Job(num_shots=shots, requested_tier=tier, random_seed=5)
    j.waveform_library["pi"].CopyFrom(job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=20))
    j.main.instructions.add(start_tick=0, play=job_pb2.Play(channel_id="xy_q0", waveform_id="pi", amplitude=amp))
    j.main.instructions.add(start_tick=24, acquire=job_pb2.Acquire(
        channel_id="ro_q0", integration_ticks=1000, mode=job_pb2.ACQUISITION_MODE_DISCRIMINATED, result_key="q0"))
    return j


async def _p1(svc, job) -> float:
    ctx = Ctx()
    resp = await svc.SubmitJob(pb.SubmitJobRequest(job=job), ctx)
    chunks = [m.chunk async for m in svc.StreamResults(pb.StreamResultsRequest(job_id=resp.job_id), ctx)]
    return float(np.concatenate([from_proto(c.acquisitions[0].states) for c in chunks]).mean())


@pytest.mark.anyio
async def test_calibration_epoch_compare_and_swap():
    svc, jobs = _service(IDEAL, DEV1)
    try:
        snap = (await svc.GetCalibration(pb.GetCalibrationRequest(), Ctx())).snapshot
        assert snap.calibration_epoch == 0
        assert snap.qubits[0].drive_frequency_hz == pytest.approx(5.0e9)
        upd = calibration_pb2.CalibrationSnapshot(qubits=[calibration_pb2.QubitCalibration(qubit_index=0)])
        r = await svc.UpdateCalibration(pb.UpdateCalibrationRequest(snapshot=upd, expected_epoch=0), Ctx())
        assert r.new_epoch == 1
        stale = Ctx()
        with pytest.raises(grpc.RpcError):
            await svc.UpdateCalibration(pb.UpdateCalibrationRequest(snapshot=upd, expected_epoch=0), stale)
        assert stale.status[0] == grpc.StatusCode.FAILED_PRECONDITION
        job = _pi_job(shots=10)
        job.expected_calibration_epoch = 0
        ctx = Ctx()
        with pytest.raises(grpc.RpcError):
            await svc.SubmitJob(pb.SubmitJobRequest(job=job), ctx)
        assert ctx.status[0] == grpc.StatusCode.FAILED_PRECONDITION
        job.expected_calibration_epoch = 1
        assert (await svc.SubmitJob(pb.SubmitJobRequest(job=job), Ctx())).calibration_epoch == 1
    finally:
        await jobs.close()


@pytest.mark.anyio
async def test_tier_refusal_is_failed_precondition_with_reason():
    svc, jobs = _service(IDEAL, DEV1)
    try:
        ctx = Ctx()
        with pytest.raises(grpc.RpcError):
            await svc.SubmitJob(pb.SubmitJobRequest(job=_pi_job(job_pb2.FIDELITY_TIER_T1A_STABILIZER, amp=0.13)), ctx)
        assert ctx.status[0] == grpc.StatusCode.FAILED_PRECONDITION
        assert "Clifford" in ctx.status[1]
    finally:
        await jobs.close()


@pytest.mark.anyio
async def test_describe_device_lists_real_channels():
    svc, jobs = _service(QBLOX, load_device("src/qcss/config/devices/transmon_5q.yaml"))
    try:
        d = (await svc.DescribeDevice(pb.DescribeDeviceRequest(), Ctx())).device
        ch = {c.channel_id: c for c in d.channels}
        assert ch["xy_q0"].kind == device_pb2.CHANNEL_KIND_DRIVE
        assert ch["ro_q0"].generator_id == "qrm_rf0_seq0"
        assert ch["cr_q0_q1"].frame_id == "q1"
        assert d.tick_hz == "1e9"
    finally:
        await jobs.close()


@pytest.mark.anyio
async def test_os_mixer_correction_cancels_hidden_gain_imbalance():
    data = DEV1.model_dump()
    data["qubits"][0]["f_max_ghz"] = 5.05                     # IF = 150 MHz under the 4.9 GHz LO
    data["faults"] = {"drive_mixers": [{"qubit_index": 0, "gain_q": 1.3}]}
    dev = DeviceSpec.model_validate(data)
    svc, jobs = _service(QBLOX, dev)
    try:
        p_raw = await _p1(svc, _pi_job())
        fix = calibration_pb2.CalibrationSnapshot(qubits=[calibration_pb2.QubitCalibration(
            qubit_index=0, drive_frequency_hz=5.05e9,
            drive_mixer=calibration_pb2.MixerCorrection(gain_ratio=1 / 1.3))])
        await svc.UpdateCalibration(pb.UpdateCalibrationRequest(snapshot=fix, expected_epoch=0), Ctx())
        p_fixed = await _p1(svc, _pi_job())
        # mu = (1 + 1.3)/2 over-rotates the pi pulse by 15 %: P1 = sin^2(1.15 pi/2) = 0.948
        assert abs(p_raw - 0.948) < 0.03
        assert p_fixed > p_raw + 0.03
    finally:
        await jobs.close()


@pytest.mark.anyio
async def test_os_discriminator_threshold_is_applied_on_t2():
    svc, jobs = _service(IDEAL, DEV1)
    try:
        assert await _p1(svc, _pi_job(job_pb2.FIDELITY_TIER_T2_LINDBLAD, shots=400)) > 0.9
        cal = calibration_pb2.CalibrationSnapshot(qubits=[calibration_pb2.QubitCalibration(
            qubit_index=0, drive_frequency_hz=5.0e9, readout_threshold=1e9, readout_rotation_rad=0.0)])
        await svc.UpdateCalibration(pb.UpdateCalibrationRequest(snapshot=cal, expected_epoch=0), Ctx())
        assert await _p1(svc, _pi_job(job_pb2.FIDELITY_TIER_T2_LINDBLAD, shots=400)) == 0.0
    finally:
        await jobs.close()
