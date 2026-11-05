"""Regressions for the final review: chip-state races, scenario timing, routing and lab-link wording."""
from __future__ import annotations

import asyncio
import contextlib
import json
import threading
from typing import Any, cast

import grpc
import pytest
from click.testing import CliRunner

from qcss.adapters.admin_server import AdminService
from qcss.adapters.grpc_server import serve
from qcss.adapters.instrument_faults import InstrumentFaults
from qcss.admin.v1 import admin_pb2 as apb
from qcss.chassis import Chassis, ChassisConfig
from qcss.cli import app
from qcss.config.loader import load_device, load_profile
from qcss.core.errors import TierRoutingError
from qcss.runtime.jobs import JobManager
from qcss.runtime.runner import SimulationContext
from qcss.technician import CalibrationOutcome
from qcss.technician.schedule import Shift
from qcss.v1 import control_service_pb2 as pb
from qcss.v1 import control_service_pb2_grpc as pbg
from qcss.v1 import job_pb2
from tests.integration.test_grpc_end_to_end import _can_connect_loopback, _free_port
from tests.integration.test_indistinguishability import TELLS

QBLOX = load_profile("src/qcss/config/profiles/qblox_cluster_5q.yaml")
DEV = load_device("src/qcss/config/devices/transmon_5q.yaml")


def test_i1_a_chassis_runs_one_job_at_a_time():
    chassis = Chassis(ChassisConfig(profile=QBLOX, device=DEV, lab_address=f"127.0.0.1:{_free_port()}"))

    async def go():
        await chassis.start()
        try:
            assert chassis.jobs is not None
            return chassis.jobs.max_concurrent_jobs
        finally:
            await chassis.stop()
    assert asyncio.run(go()) == 1                           # one chip, one sequencer program at a time


def test_i2_concurrent_readers_advance_the_chip_once(monkeypatch):
    import time as _time
    ctx = SimulationContext(QBLOX, DEV)
    assert ctx.device_state is not None
    real = ctx.device_state.advance_time

    def slow(dt):                                           # widen the read-compute-advance window
        _time.sleep(0.02)
        real(dt)
    monkeypatch.setattr(ctx.device_state, "advance_time", slow)
    barrier = threading.Barrier(8)

    def read():
        barrier.wait()
        ctx.device_parameters(100.0)
    threads = [threading.Thread(target=read) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert ctx.device_state is not None and ctx.device_state.clock.t_s == pytest.approx(100.0)


def test_i3_a_burst_on_an_idle_chassis_hits_now():
    now = [0.0]
    ctx = SimulationContext(QBLOX, DEV, time_scale=1.0, wall_clock=lambda: now[0])
    admin = AdminService(ctx, JobManager.__new__(JobManager), InstrumentFaults())
    assert ctx.device_state is not None
    ctx.device_state.freeze(True)
    _, t1_before = ctx.device_parameters(ctx.lab_time_s)
    now[0] += 10.0                                          # idle for 10 s of lab time
    asyncio.run(admin.Burst(apb.BurstRequest(qubit_index=2), None))     # type: ignore[arg-type]
    _, t1_after = ctx.device_parameters(ctx.lab_time_s)
    assert t1_after[2] < 0.5 * t1_before[2]


def test_i4_a_drive_beside_a_flux_pulse_on_a_neighbour_stays_on_the_gate_tier():
    ctx = SimulationContext(QBLOX, DEV)
    j = job_pb2.Job(num_shots=10, requested_tier=job_pb2.FIDELITY_TIER_T1B_STATEVECTOR)
    j.waveform_library["pi"].CopyFrom(job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=20))
    j.waveform_library["fx"].CopyFrom(job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=40))
    ins = j.main.instructions
    ins.add(start_tick=0, play=job_pb2.Play(channel_id="flux_q1", waveform_id="fx", amplitude=0.05))
    ins.add(start_tick=8, play=job_pb2.Play(channel_id="xy_q0", waveform_id="pi", amplitude=0.5))
    ins.add(start_tick=60, acquire=job_pb2.Acquire(channel_id="ro_q0", integration_ticks=400,
                                                   mode=job_pb2.ACQUISITION_MODE_DISCRIMINATED, result_key="q0"))
    assert ctx.plan(j).tier == "T1B"                        # q0 is an exchange partner, not flux-tuned


@pytest.mark.anyio
async def test_i5_routing_refusals_on_the_lab_link_say_nothing_about_tiers():
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")

    async def refuse(job):
        raise TierRoutingError("Tier routing failed: Requested tier 'AUTO' cannot satisfy the job (n_qubits=5)")

    async def runner(job_id, job, cancel):
        yield  # pragma: no cover
    jobs = JobManager(cast(Any, runner), refuse, expose_diagnostics=False)
    addr = f"127.0.0.1:{_free_port()}"
    server = await serve(addr, jobs)
    try:
        async with grpc.aio.insecure_channel(addr) as ch:
            with pytest.raises(grpc.aio.AioRpcError) as err:
                await pbg.ControlServiceStub(ch).SubmitJob(pb.SubmitJobRequest(job=job_pb2.Job(num_shots=1)))
        assert err.value.code() == grpc.StatusCode.FAILED_PRECONDITION, err.value
        text = f"{err.value.details()} {err.value.trailing_metadata()}"
        assert not TELLS.search(text), text
    finally:
        await server.stop(None)
        await jobs.close()


def test_i6_a_bad_or_failing_request_does_not_block_the_shift(tmp_path):
    ran: list[str] = []
    req = tmp_path / "requests"
    req.mkdir()
    (req / "0001-bad.json").write_text("{not json", encoding="utf-8")
    (req / "0002-unknown.json").write_text(json.dumps({"scope": ["teleport"]}), encoding="utf-8")
    (req / "0003-two.json").write_text(json.dumps({"scope": ["quick", "cz"]}), encoding="utf-8")
    cards = {"quick": tmp_path / "quick.yml", "cz": tmp_path / "cz.yml"}

    def calibrate(runcard):
        ran.append(runcard.stem)
        return CalibrationOutcome(True, tmp_path)
    s = Shift(calibrate, {}, req, cards, clock=lambda: 0.0)
    for _ in range(4):
        s.step()
    assert ran == ["quick", "cz"]                           # every scope of the request ran
    assert sorted(p.name for p in (req / "failed").glob("*.json")) == ["0001-bad.json", "0002-unknown.json"]
    assert not list(req.glob("*.json"))


def test_i6_a_failing_scheduled_runcard_backs_off_and_lets_others_run(tmp_path):
    ran: list[str] = []

    def calibrate(runcard):
        ran.append(runcard.stem)
        return CalibrationOutcome(runcard.stem != "quick", tmp_path)
    s = Shift(calibrate, {tmp_path / "quick.yml": 3600.0, tmp_path / "full.yml": 86400.0}, tmp_path / "r", {},
              clock=lambda: 0.0)
    for _ in range(3):
        s.step()
    assert ran == ["quick", "full"]                         # the failed quick check waits its back-off


def test_m3_an_admin_channel_beside_a_tokened_lab_link_needs_its_own_token():
    r = CliRunner().invoke(app, ["serve", "--token", "lab", "--admin-listen", "127.0.0.1:50052",
                                 "--profile", "test_ideal_1q"])
    assert r.exit_code != 0 and "--admin-token" in r.output
    r = CliRunner().invoke(app, ["serve", "--token", "same", "--admin-token", "same", "--admin-listen",
                                 "127.0.0.1:50052", "--profile", "test_ideal_1q"])
    assert r.exit_code != 0 and "differ" in r.output


def _overlapping_drive_and_flux_on_q0(tier):
    j = job_pb2.Job(num_shots=10, requested_tier=tier)
    j.waveform_library["pi"].CopyFrom(job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=40))
    j.waveform_library["fx"].CopyFrom(job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=40))
    ins = j.main.instructions
    ins.add(start_tick=0, play=job_pb2.Play(channel_id="xy_q0", waveform_id="pi", amplitude=0.5))
    ins.add(start_tick=8, play=job_pb2.Play(channel_id="flux_q0", waveform_id="fx", amplitude=0.05))
    ins.add(start_tick=80, acquire=job_pb2.Acquire(channel_id="ro_q0", integration_ticks=400,
                                                   mode=job_pb2.ACQUISITION_MODE_DISCRIMINATED, result_key="q0"))
    return j


def test_overlapping_pulses_on_one_qubit_need_pulse_level_physics():
    ctx = SimulationContext(QBLOX, DEV)
    assert ctx.plan(_overlapping_drive_and_flux_on_q0(job_pb2.FIDELITY_TIER_AUTO)).tier == "T2"
    with pytest.raises(TierRoutingError):
        ctx.plan(_overlapping_drive_and_flux_on_q0(job_pb2.FIDELITY_TIER_T1B_STATEVECTOR))


def test_a_raw_trace_job_runs_on_t2_under_the_chassis_auto_policy():
    ctx = SimulationContext(QBLOX, DEV)
    ctx.tier_policy = "AUTO"                                # what every chassis sets
    j = job_pb2.Job(num_shots=10, requested_tier=job_pb2.FIDELITY_TIER_T2_LINDBLAD)
    j.waveform_library["pi"].CopyFrom(job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=20))
    ins = j.main.instructions
    ins.add(start_tick=0, play=job_pb2.Play(channel_id="xy_q0", waveform_id="pi", amplitude=0.5))
    ins.add(start_tick=20, acquire=job_pb2.Acquire(channel_id="ro_q0", integration_ticks=400,
                                                   mode=job_pb2.ACQUISITION_MODE_RAW_TRACE, result_key="q0"))
    assert ctx.plan(j).tier == "T2"


def test_a_get_then_set_mode_round_trip_keeps_honouring_the_requested_tier():
    ctx = SimulationContext(QBLOX, DEV)
    assert ctx.tier_policy is None                          # each job's requested tier is honoured
    admin = AdminService(ctx, JobManager.__new__(JobManager), InstrumentFaults())
    mode = asyncio.run(admin.GetMode(apb.GetModeRequest(), None)).mode    # type: ignore[arg-type]
    mode.time_scale = 2.0
    asyncio.run(admin.SetMode(apb.SetModeRequest(mode=mode), None))      # type: ignore[arg-type]
    assert ctx.tier_policy is None and ctx.time_scale == 2.0
    mode.tier_policy = job_pb2.FIDELITY_TIER_AUTO
    asyncio.run(admin.SetMode(apb.SetModeRequest(mode=mode), None))      # type: ignore[arg-type]
    assert ctx.tier_policy == "AUTO"
    mode.tier_policy = job_pb2.FIDELITY_TIER_UNSPECIFIED                  # back to the job's own choice
    asyncio.run(admin.SetMode(apb.SetModeRequest(mode=mode), None))      # type: ignore[arg-type]
    assert ctx.tier_policy is None


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_a_slow_periodic_save_does_not_stall_the_event_loop(monkeypatch, tmp_path):
    import time as _time
    chassis = Chassis(ChassisConfig(profile=QBLOX, device=DEV, lab_address=f"127.0.0.1:{_free_port()}",
                                    state_dir=tmp_path, save_interval_s=0.01))
    monkeypatch.setattr(chassis, "save", lambda: _time.sleep(0.5))   # a slow disk, fsync and all

    async def go():
        saver = asyncio.create_task(chassis._save_periodically())
        await asyncio.sleep(0.05)                           # let a save start
        t0 = _time.perf_counter()
        await asyncio.sleep(0.01)
        lag = _time.perf_counter() - t0
        saver.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await saver
        return lag
    assert asyncio.run(go()) < 0.2
