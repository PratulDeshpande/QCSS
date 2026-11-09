"""Inputs at the edge of what the simulator accepts: each must give a clear error or an exact answer, never a hang."""
from __future__ import annotations

import asyncio
import math
from fractions import Fraction
from typing import Any, cast

import grpc
import numpy as np
import pytest
from click.testing import CliRunner

from qcss.adapters.admin_server import AdminService
from qcss.adapters.instrument_faults import InstrumentFaults
from qcss.admin.v1 import admin_pb2 as apb
from qcss.boards.qibosoq import _envelope
from qcss.cli import app
from qcss.config.loader import load_device, load_profile
from qcss.core.errors import HardwareValidationError
from qcss.core.seeding import chunks
from qcss.core.timebase import TimeBase, _as_fraction_hz
from qcss.readout.phenomenological import PhenomenologicalReadout
from qcss.readout.resonator import DispersiveReadout, ResonatorParams
from qcss.runtime.jobs import JobManager
from qcss.runtime.runner import SimulationContext, create_simulation_runner
from qcss.v1 import job_pb2
from tests.conftest import PROFILES_DIR, REPO_ROOT
from tests.integration.test_grpc_calibration import DEV1, IDEAL, _pi_job
from tests.integration.test_grpc_end_to_end import MockServicerContext


def test_a_chunk_size_that_makes_no_progress_is_refused():
    for size in (0, -5):
        with pytest.raises(ValueError, match="chunk"):
            chunks(10, size)


def test_the_cli_refuses_a_chunk_size_below_one():
    result = CliRunner().invoke(app, ["run", "examples/jobs/pi_q0.json", "--chunk-size", "0"])
    assert result.exit_code == 2 and "chunk-size" in result.output


def test_a_clock_given_in_scientific_notation_is_exact():
    assert _as_fraction_hz("1.23456789012345e9") == Fraction("1.23456789012345e9")
    assert _as_fraction_hz("430.08e6") == 430_080_000
    assert TimeBase.from_clocks("1.23456789012345e9").tick_hz == Fraction("1.23456789012345e9")


def test_a_readout_whose_levels_cannot_be_told_apart_says_so_instead_of_looping_forever():
    readout = PhenomenologicalReadout(np.eye(2), np.zeros(2), sigma=1.0)
    with pytest.raises(ValueError, match="centroid"):
        readout.sample(np.array([1]), np.random.default_rng(0))


def test_overlapping_but_distinct_levels_still_sample():
    readout = PhenomenologicalReadout(np.eye(2), np.array([0, 1.0]), sigma=1.0)
    labels, iq = readout.sample(np.ones(50, dtype=int), np.random.default_rng(0))
    assert labels.tolist() == [1] * 50 and iq is not None and np.isfinite(iq).all()


def test_a_decay_that_never_happens_is_an_infinite_t1_not_a_division_by_zero():
    readout = DispersiveReadout(ResonatorParams(0.05, (0.0, 0.01, 0.02), 0.0, 0.5, 0))
    traces = readout.traces(np.array([0, 1, 2]), np.ones(20, dtype=np.complex128), math.inf,
                            np.random.default_rng(0))
    assert np.isfinite(traces).all()


@pytest.mark.parametrize("n", [1, 7, 20, 100, 784, 1999])
def test_every_envelope_shape_has_exactly_the_requested_length(n):
    for shape in ("rectangular", "gaussian", "flattop", "hann"):
        el = {"shape": shape, "rel_sigma": 5.0}
        assert len(_envelope(el, n)) == n, (shape, n)


def _job_with_empty_condition() -> job_pb2.Job:
    job = _pi_job(shots=4)
    cond = job_pb2.Condition(op=job_pb2.CONDITION_OP_EQUAL, register_indices=[])
    job.main.instructions.add(start_tick=2000, branch=job_pb2.Branch(condition=cond, duration_ticks=20,
                                                                    sequencer_id=IDEAL.generators[0].generator_id))
    return job


def test_a_branch_with_no_condition_register_is_refused_before_it_runs():
    ctx = SimulationContext(IDEAL, DEV1, TimeBase.from_clocks(IDEAL.clock.tick_hz))
    with pytest.raises(HardwareValidationError) as err:
        ctx.plan(_job_with_empty_condition())
    assert any("condition" in path and "register" in why for path, why in err.value.violations)


def _sweeps_of_two_kinds(*, frequency_axis: int, amplitude_axis: int) -> job_pb2.Job:
    from qcss.core.ndarray import to_proto
    job = _pi_job(shots=4)
    job.sweeps.add(axis=frequency_axis, frequency=job_pb2.FrequencyTarget(frame_id="q0"),
                   values=to_proto(np.array([5.0e9, 5.001e9])))
    job.sweeps.add(axis=amplitude_axis, amplitude=job_pb2.AmplitudeTarget(instruction_index=0),
                   values=to_proto(np.array([0.1, 0.2, 0.3])))
    return job


@pytest.mark.parametrize("frequency_axis, amplitude_axis", [(0, 1), (1, 0)])
def test_a_frequency_sweep_does_not_shift_the_instruction_an_amplitude_sweep_targets(frequency_axis, amplitude_axis):
    from qcss.ir.compiler import expand_sweeps
    points = expand_sweeps(_sweeps_of_two_kinds(frequency_axis=frequency_axis, amplitude_axis=amplitude_axis))
    assert len(points) == 6
    for pt in points:
        play = next(i.play for i in pt.job.main.instructions if i.WhichOneof("op") == "play")
        assert play.amplitude == pytest.approx([0.1, 0.2, 0.3][pt.indices[amplitude_axis]])


def _service() -> tuple[AdminService, SimulationContext, JobManager]:
    ctx = SimulationContext(load_profile(PROFILES_DIR / "qblox_cluster_5q.yaml"),
                            load_device(REPO_ROOT / "src" / "qcss" / "config" / "devices" / "transmon_5q.yaml"))

    async def accept(job: job_pb2.Job) -> None:
        return None

    async def nothing(job_id, job, cancel):
        return
        yield
    jobs = JobManager(nothing, accept)
    return AdminService(ctx, jobs, InstrumentFaults()), ctx, jobs


@pytest.mark.anyio
@pytest.mark.parametrize("scale", [math.nan, math.inf, -1.0, 1e9])
async def test_a_time_scale_that_is_not_a_sane_number_is_refused_and_changes_nothing(scale):
    svc, ctx, jobs = _service()
    try:
        before, mock = ctx.time_scale, MockServicerContext()
        with pytest.raises(grpc.RpcError):
            await svc.SetMode(apb.SetModeRequest(mode=apb.Mode(time_scale=scale)), cast(Any, mock))
        assert mock.code == grpc.StatusCode.INVALID_ARGUMENT and ctx.time_scale == before
    finally:
        await jobs.close()


@pytest.mark.parametrize("args", [
    {"duration_s": math.nan}, {"duration_s": math.inf}, {"duration_s": 1e12}, {"count": 4_000_000_000},
])
def test_a_fault_with_an_absurd_duration_or_count_is_refused(args):
    with pytest.raises(ValueError):
        InstrumentFaults().inject(apb.INSTRUMENT_FAULT_HANG, **args)


def test_an_ordinary_fault_is_still_accepted():
    InstrumentFaults().inject(apb.INSTRUMENT_FAULT_HANG, count=3, duration_s=2.0)


@pytest.mark.anyio
async def test_a_job_that_fails_partway_still_ages_the_chip_by_the_shots_it_ran(monkeypatch):
    ctx = SimulationContext(IDEAL, DEV1, TimeBase.from_clocks(IDEAL.clock.tick_hz), time_scale=0.0)
    real, calls = ctx.simulate_chunk, []

    def fail_on_the_second_chunk(*args, **kwargs):
        calls.append(1)
        if len(calls) == 2:
            raise RuntimeError("worker died")
        return real(*args, **kwargs)
    monkeypatch.setattr(ctx, "simulate_chunk", fail_on_the_second_chunk)
    runner = create_simulation_runner(IDEAL, DEV1, context=ctx, chunk_size=10)
    with pytest.raises(RuntimeError, match="worker died"):
        [c async for c in runner("j", _pi_job(shots=20), asyncio.Event())]
    assert ctx.lab_time_s > 0.0
