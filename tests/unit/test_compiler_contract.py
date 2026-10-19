"""Compiler contract: UNSPECIFIED enums rejected (D14) and sweep expansion (D16)."""
from __future__ import annotations

import numpy as np
import pytest

from qcss.core.errors import HardwareValidationError
from qcss.core.ndarray import to_proto
from qcss.ir.compiler import compile_job, expand_sweeps
from qcss.v1 import job_pb2


def _job(**kw) -> job_pb2.Job:
    j = job_pb2.Job(num_shots=10, **kw)
    j.waveform_library["x"].CopyFrom(job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=20))
    return j


def _paths(exc: HardwareValidationError) -> list[str]:
    return [p for p, _ in exc.violations]


def test_unspecified_waveform_shape_rejected(qblox_profile, timebase_1ghz):
    j = _job()
    j.waveform_library["w"].CopyFrom(job_pb2.Waveform(length_samples=20))
    with pytest.raises(HardwareValidationError) as e:
        compile_job(j, qblox_profile, timebase_1ghz)
    assert "job.waveform_library[w].shape" in _paths(e.value)


def test_unspecified_acquisition_mode_rejected(qblox_profile, timebase_1ghz):
    j = _job()
    j.main.instructions.add(start_tick=0, acquire=job_pb2.Acquire(channel_id="ro_q0", integration_ticks=100))
    with pytest.raises(HardwareValidationError) as e:
        compile_job(j, qblox_profile, timebase_1ghz)
    assert "job.main.instructions[0].acquire.mode" in _paths(e.value)


def test_unspecified_condition_op_rejected(qblox_profile, timebase_1ghz):
    j = _job()
    br = job_pb2.Branch(sequencer_id="qcm_rf0_seq0", duration_ticks=20,
                        condition=job_pb2.Condition(register_indices=[0]))
    j.main.instructions.add(start_tick=0, branch=br)
    with pytest.raises(HardwareValidationError) as e:
        compile_job(j, qblox_profile, timebase_1ghz)
    assert "job.main.instructions[0].branch.condition.op" in _paths(e.value)


def test_arbitrary_waveform_length_mismatch_rejected(qblox_profile, timebase_1ghz):
    j = _job()
    j.waveform_library["arb"].CopyFrom(job_pb2.Waveform(
        shape=job_pb2.WAVEFORM_SHAPE_ARBITRARY, length_samples=16, samples=to_proto(np.ones(12, np.complex64))))
    with pytest.raises(HardwareValidationError) as e:
        compile_job(j, qblox_profile, timebase_1ghz)
    assert "job.waveform_library[arb].samples" in _paths(e.value)


def test_no_sweeps_is_one_point():
    pts = expand_sweeps(_job())
    assert [p.indices for p in pts] == [()]


def test_amplitude_sweep_sets_play_amplitude():
    j = _job()
    j.main.instructions.add(start_tick=0, play=job_pb2.Play(channel_id="xy_q0", waveform_id="x", amplitude=0.1))
    j.sweeps.add(axis=0, amplitude=job_pb2.AmplitudeTarget(instruction_index=0),
                 values=to_proto(np.array([0.2, 0.4, 0.6])))
    pts = expand_sweeps(j)
    assert [p.indices for p in pts] == [(0,), (1,), (2,)]
    assert [round(p.job.main.instructions[0].play.amplitude, 6) for p in pts] == [0.2, 0.4, 0.6]


def test_two_axes_form_a_grid_and_same_axis_zips():
    j = _job()
    j.main.instructions.add(start_tick=0, play=job_pb2.Play(channel_id="xy_q0", waveform_id="x", amplitude=0.1))
    j.main.instructions.add(start_tick=0, set_frequency=job_pb2.SetFrequency(frame_id="q0", frequency_hz=1e6))
    j.sweeps.add(axis=0, amplitude=job_pb2.AmplitudeTarget(instruction_index=0), values=to_proto(np.array([0.2, 0.4])))
    j.sweeps.add(axis=0, duration=job_pb2.DurationTarget(waveform_id="x"), values=to_proto(np.array([20.0, 40.0])))
    j.sweeps.add(axis=1, frequency=job_pb2.FrequencyTarget(frame_id="q0"), values=to_proto(np.array([1e6, 2e6, 3e6])))
    pts = expand_sweeps(j)
    assert len(pts) == 6
    last = pts[-1].job
    assert pts[-1].indices == (1, 2)
    assert last.waveform_library["x"].length_samples == 40
    assert last.main.instructions[0].play.amplitude == pytest.approx(0.4)


def test_zipped_axis_length_mismatch_rejected():
    j = _job()
    j.main.instructions.add(start_tick=0, play=job_pb2.Play(channel_id="xy_q0", waveform_id="x", amplitude=0.1))
    j.sweeps.add(axis=0, amplitude=job_pb2.AmplitudeTarget(instruction_index=0), values=to_proto(np.array([0.2, 0.4])))
    j.sweeps.add(axis=0, duration=job_pb2.DurationTarget(waveform_id="x"), values=to_proto(np.array([20.0])))
    with pytest.raises(HardwareValidationError):
        expand_sweeps(j)
