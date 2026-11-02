"""Qibolab sequences and sweepers -> one instrument job; result chunks -> Qibolab's result arrays."""
from __future__ import annotations

import pytest

pytest.importorskip("qibolab", reason="the qibolab extra is not installed")

import numpy as np
from qibolab import (
    Acquisition,
    AcquisitionConfig,
    AcquisitionType,
    AveragingMode,
    Delay,
    ExecutionParameters,
    Gaussian,
    IqConfig,
    Parameter,
    Pulse,
    PulseSequence,
    Readout,
    Rectangular,
    Sweeper,
    VirtualZ,
)

from qcss.core.ndarray import from_proto, to_proto
from qcss.v1 import job_pb2, result_pb2
from qcss_qibolab.translate import assemble, translate

LOS = {"xy_q0": 4.9e9, "ro_q0": 7.0e9, "xy_q1": 4.9e9, "ro_q1": 7.0e9, "flux_q0": 0.0, "flux_q1": 0.0}
CONFIGS = {
    "0/drive": IqConfig(frequency=5.05e9), "0/probe": IqConfig(frequency=7.15e9),
    "0/acquisition": AcquisitionConfig(delay=0.0, smearing=0.0, threshold=0.25, iq_angle=0.5),
}


def rx() -> Pulse:
    return Pulse(duration=40, amplitude=0.5, envelope=Gaussian(rel_sigma=0.2))


def mz() -> Readout:
    return Readout(acquisition=Acquisition(duration=2000),
                   probe=Pulse(duration=2000, amplitude=0.1, envelope=Rectangular()))


def opts(**kw) -> ExecutionParameters:
    return ExecutionParameters(**{"nshots": 100, "relaxation_time": 50_000,
                                  "acquisition_type": AcquisitionType.DISCRIMINATION,
                                  "averaging_mode": AveragingMode.SINGLESHOT, **kw})


def ops(point: job_pb2.ProgramPoint) -> list[tuple[int, str]]:
    return [(i.start_tick, str(i.WhichOneof("op"))) for i in point.main.instructions]


def test_a_gate_and_a_readout_become_a_play_and_an_acquisition():
    ro = mz()
    seq = PulseSequence([("0/drive", rx())]) | PulseSequence([("0/acquisition", ro)])     # readout after the gate
    tr = translate(seq, CONFIGS, opts(), [], los=LOS)
    (pt,) = tr.job.program_points
    assert [o for o in ops(pt) if o[1] != "wait"] == [(0, "play"), (40, "acquire")]
    play, acq = pt.main.instructions[0].play, pt.main.instructions[1].acquire
    assert play.channel_id == "xy_q0" and play.amplitude == 1.0
    samples = from_proto(tr.job.waveform_library[play.waveform_id].samples)
    np.testing.assert_allclose(np.real(samples), rx().i(1.0))
    np.testing.assert_allclose(np.imag(samples), rx().q(1.0))
    assert acq.channel_id == "ro_q0" and acq.integration_ticks == 2000
    assert acq.mode == job_pb2.ACQUISITION_MODE_DISCRIMINATED and acq.result_key == str(ro.acquisition.id)
    assert tr.job.num_shots == 100 and tr.job.repetition_delay_ticks == 50_000


def test_virtual_z_and_relative_phase_follow_qibolab_conventions():
    p = Pulse(duration=40, amplitude=0.5, envelope=Gaussian(rel_sigma=0.2), relative_phase=0.3)
    seq = PulseSequence([("0/drive", VirtualZ(phase=1.2)), ("0/drive", Delay(duration=16)), ("0/drive", p)])
    (pt,) = translate(seq, CONFIGS, opts(), [], los=LOS).job.program_points
    assert ops(pt) == [(0, "shift_phase"), (16, "play")]
    assert pt.main.instructions[0].shift_phase.frame_id == "q0"
    assert pt.main.instructions[0].shift_phase.delta_rad == pytest.approx(1.2)
    assert pt.main.instructions[1].play.phase_offset_rad == pytest.approx(0.3)


def test_an_amplitude_sweep_becomes_one_program_per_point():
    p = rx()
    seq = PulseSequence([("0/drive", p), ("0/acquisition", mz())])
    sw = Sweeper(parameter=Parameter.amplitude, values=np.array([0.0, 0.25, 0.5]), pulses=[p])
    tr = translate(seq, CONFIGS, opts(), [[sw]], los=LOS)
    assert tr.sweep_shape == (3,)
    peaks = []
    for k, pt in enumerate(tr.job.program_points):
        assert list(pt.indices) == [k]
        wid = pt.main.instructions[0].play.waveform_id
        peaks.append(np.max(np.abs(from_proto(tr.job.waveform_library[wid].samples))))
    np.testing.assert_allclose(np.array(peaks) / peaks[-1], [0.0, 0.5, 1.0], atol=1e-12)


def test_frequency_sweeps_set_the_frame_nco_of_each_point():
    seq = PulseSequence([("0/drive", rx()), ("0/acquisition", mz())])
    drive = Sweeper(parameter=Parameter.frequency, values=np.array([5.0e9, 5.1e9]), channels=["0/drive"])
    probe = Sweeper(parameter=Parameter.frequency, values=np.array([7.1e9, 7.2e9]), channels=["0/probe"])
    tr = translate(seq, CONFIGS, opts(), [[drive], [probe]], los=LOS)
    assert tr.sweep_shape == (2, 2)
    last = tr.job.program_points[-1]
    sets = {i.set_frequency.frame_id: i.set_frequency.frequency_hz for i in last.main.instructions
            if i.WhichOneof("op") == "set_frequency"}
    assert sets == {"q0": pytest.approx(5.1e9 - 4.9e9), "ro_q0": pytest.approx(7.2e9 - 7.0e9)}


def test_the_instrument_is_programmed_with_the_platform_configs():
    seq = PulseSequence([("0/drive", rx()), ("0/acquisition", mz())])
    cal = translate(seq, CONFIGS, opts(), [], los=LOS).calibration
    (qc,) = cal.qubits
    assert qc.qubit_index == 0 and qc.drive_frequency_hz == 5.05e9 and qc.readout_frequency_hz == 7.15e9
    assert qc.readout_threshold == 0.25
    assert qc.readout_rotation_rad == pytest.approx(-0.5)      # Qibolab rotates by +iq_angle, QCSS by -rotation


def test_coupler_flux_lines_are_refused():
    seq = PulseSequence([("coupler_0/flux", Pulse(duration=30, amplitude=0.1, envelope=Rectangular()))])
    with pytest.raises(ValueError, match="coupler_0/flux"):
        translate(seq, CONFIGS, opts(), [], los=LOS)


def _chunks(per_point_states: dict[tuple[int, ...], np.ndarray], key: str):
    for idx, states in per_point_states.items():
        iq = states.astype(np.complex64) + np.complex64(0.5j)
        yield result_pb2.ResultChunk(sweep_point=list(idx), shot_offset=0, num_shots_in_chunk=len(states),
                                     acquisitions=[result_pb2.AcquisitionResult(
                                         result_key=key, states=to_proto(states.astype(np.uint8)),
                                         iq=to_proto(iq))])


@pytest.mark.parametrize(("acq", "avg", "shape"), [
    (AcquisitionType.DISCRIMINATION, AveragingMode.SINGLESHOT, (4, 2)),
    (AcquisitionType.DISCRIMINATION, AveragingMode.CYCLIC, (2,)),
    (AcquisitionType.INTEGRATION, AveragingMode.SINGLESHOT, (4, 2, 2)),
    (AcquisitionType.INTEGRATION, AveragingMode.CYCLIC, (2, 2)),
])
def test_results_take_qibolabs_shape(acq, avg, shape):
    p, ro = rx(), mz()
    seq = PulseSequence([("0/drive", p), ("0/acquisition", ro)])
    sw = Sweeper(parameter=Parameter.amplitude, values=np.array([0.0, 0.5]), pulses=[p])
    o = opts(nshots=4, acquisition_type=acq, averaging_mode=avg)
    tr = translate(seq, CONFIGS, o, [[sw]], los=LOS)
    out = assemble(_chunks({(0,): np.array([0, 0, 0, 1]), (1,): np.array([1, 1, 1, 0])},
                           str(ro.acquisition.id)), tr, o)
    res = out[ro.acquisition.id]
    assert res.shape == shape == o.results_shape([[sw]])
    if acq is AcquisitionType.DISCRIMINATION and avg is AveragingMode.CYCLIC:
        np.testing.assert_allclose(res, [0.25, 0.75])
