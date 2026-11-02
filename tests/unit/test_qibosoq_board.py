"""A Qibosoq board request becomes a chassis job; results come back nested as a Qibosoq server sends them."""
from __future__ import annotations

import numpy as np
import pytest

from qcss.boards.qibosoq import BoardWiring, board_reply, request_to_job
from qcss.config.loader import load_device, load_profile
from qcss.core.ndarray import from_proto, to_proto
from qcss.ir.compiler import build_bindings
from qcss.v1 import job_pb2, result_pb2

PROFILE = load_profile("src/qcss/config/profiles/qick_zcu216_5q.yaml")
WIRING = BoardWiring.from_bindings(build_bindings(PROFILE, load_device("src/qcss/config/devices/transmon_5q.yaml")))
TICK = 34406.4e6


def drive(**kw) -> dict:
    return {"type": "drive", "frequency": 5050.0, "start_delay": 0.0, "duration": 0.04, "adc": 0, "dac": 0,
            "amplitude": 0.5, "relative_phase": 0.0, "name": "rx", "shape": "gaussian", "rel_sigma": 5.0, **kw}


def readout(**kw) -> dict:
    return {"type": "readout", "frequency": 7150.0, "start_delay": 0.04, "duration": 2.0, "adc": 0, "dac": 10,
            "amplitude": 0.1, "relative_phase": 0.0, "name": "mz", "shape": "rectangular", **kw}


def request(sequence: list[dict], sweepers: list[dict] | None = None, average: bool = False, reps: int = 100) -> dict:
    data = {"operation_code": 3 if sweepers else 1,
            "cfg": {"relaxation_time": 100.0, "ro_time_of_flight": 200, "reps": reps, "soft_avgs": 1,
                    "average": average},
            "sequence": sequence, "qubits": [{"bias": 0.0, "dac": 5 + q} for q in range(5)]}
    if sweepers:
        data["sweepers"] = sweepers
    return data


def ops(pt) -> list[tuple[int, str]]:
    return [(i.start_tick, str(i.WhichOneof("op"))) for i in pt.main.instructions]


def test_a_drive_and_a_readout_become_a_job_on_the_wired_channels():
    bj = request_to_job(request([drive(), readout()]), WIRING, PROFILE)
    (pt,) = bj.job.program_points
    kinds = [k for _, k in ops(pt)]
    assert kinds == ["set_frequency", "play", "set_frequency", "acquire"]
    sf, play, ro_sf, acq = (i for i in pt.main.instructions)
    assert sf.set_frequency.frame_id == "q0" and sf.set_frequency.frequency_hz == pytest.approx(5.05e9)
    assert play.play.channel_id == "xy_q0" and play.play.amplitude == pytest.approx(0.5)
    assert ro_sf.set_frequency.frame_id == "ro_q0" and ro_sf.set_frequency.frequency_hz == pytest.approx(7.15e9)
    assert acq.acquire.channel_id == "ro_q0" and acq.start_tick == round(0.04e-6 * TICK / 80) * 80
    assert acq.acquire.mode == job_pb2.ACQUISITION_MODE_INTEGRATED
    assert bj.job.num_shots == 100 and bj.job.repetition_delay_ticks == round(100e-6 * TICK)


def test_the_gaussian_is_the_boards_not_qibolabs():
    """qibosoq hands QICK sigma = n / rel_sigma * sqrt(2): a real board's Gaussian, quirk included."""
    bj = request_to_job(request([drive(), readout()]), WIRING, PROFILE)
    wid = bj.job.program_points[0].main.instructions[1].play.waveform_id
    w = np.real(from_proto(bj.job.waveform_library[wid].samples))
    n = len(w)
    x = np.arange(n)
    np.testing.assert_allclose(w, np.exp(-(x - (n / 2 - 0.5)) ** 2 / (2 * (n / 5.0 * np.sqrt(2)) ** 2)), atol=1e-12)
    assert n % 16 == 0                                    # whole fabric cycles


def test_start_delays_accumulate_from_one_element_to_the_next():
    seq = [drive(), drive(start_delay=0.1, name="rx2"), readout(start_delay=0.1)]
    (pt,) = request_to_job(request(seq), WIRING, PROFILE).job.program_points
    starts = [t for t, k in ops(pt) if k in ("play", "acquire")]
    assert starts == [0, round(0.1e-6 * TICK / 80) * 80, round(0.2e-6 * TICK / 80) * 80]


def test_a_gain_sweep_becomes_one_program_per_point():
    sw = {"expts": 3, "parameters": ["gain"], "indexes": [0], "starts": [0.0], "stops": [1.0]}
    bj = request_to_job(request([drive(), readout()], [sw]), WIRING, PROFILE)
    assert bj.sweep_shape == (3,)
    assert [pt.main.instructions[1].play.amplitude for pt in bj.job.program_points] == pytest.approx([0, 0.5, 1])


def test_a_nonzero_dc_bias_is_refused_like_an_unsupported_board_feature():
    data = request([drive(), readout()])
    data["qubits"][0]["bias"] = 0.2
    with pytest.raises(ValueError, match="bias"):
        request_to_job(data, WIRING, PROFILE)


def _chunk(idx: tuple[int, ...], iq: np.ndarray, key: str) -> result_pb2.ResultChunk:
    return result_pb2.ResultChunk(sweep_point=list(idx), num_shots_in_chunk=len(iq), acquisitions=[
        result_pb2.AcquisitionResult(result_key=key, iq=to_proto(iq.astype(np.complex64)))])


@pytest.mark.parametrize(("average", "swept", "shape"), [
    (False, False, (1, 1, 4)), (True, False, (1, 1)), (False, True, (1, 1, 2, 4)), (True, True, (1, 1, 2))])
def test_replies_nest_per_adc_readout_point_and_shot(average, swept, shape):
    sweepers = [{"expts": 2, "parameters": ["gain"], "indexes": [0], "starts": [0.0], "stops": [1.0]}] if swept else None
    bj = request_to_job(request([drive(), readout()], sweepers, average=average, reps=4), WIRING, PROFILE)
    (key,) = bj.readout_keys
    points = [(0,), (1,)] if swept else [()]
    chunks = [_chunk(p, np.arange(4) + 1j * (k + 1), key) for k, p in enumerate(points)]
    reply = board_reply(chunks, bj)
    assert np.asarray(reply["i"]).shape == shape and np.asarray(reply["q"]).shape == shape
