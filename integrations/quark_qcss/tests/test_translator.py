"""Lab translator: physical OpenQASM 3 subset -> qcss.v1.Job, using the lab's pulse library."""
from __future__ import annotations

import math
import pathlib
import re

import pytest

from qcss.v1 import calibration_pb2, job_pb2
from quark_qcss.lab.pulse_library import PulseLibrary, load_pulse_library
from quark_qcss.lab.qasm import QasmError, parse
from quark_qcss.lab.translator import Translator, UnsupportedProgramError

LIB = pathlib.Path(__file__).parents[1] / "lab_examples" / "qcss_transmon_5q" / "pulse_library.yaml"
HEADER = 'OPENQASM 3.0;\ninclude "stdgates.inc";\nbit[2] c;\n'


@pytest.fixture(scope="module")
def tr() -> Translator:
    return Translator(load_pulse_library(LIB))


def ops(job: job_pb2.Job) -> list[tuple[int, str, str]]:
    out = []
    for ins in job.main.instructions:
        kind = ins.WhichOneof("op")
        body = getattr(ins, kind)
        out.append((ins.start_tick, kind, getattr(body, "channel_id", "") or getattr(body, "frame_id", "")))
    return out


def test_parse_accepts_physical_and_register_qubits():
    p = parse(HEADER + "x $0;\nqubit[2] q;\nsx q[1];\nc[1] = measure $1;\nmeasure q[0] -> c[0];\n")
    assert [(o.name, o.qubits) for o in p.ops] == [("x", (0,)), ("sx", (1,)), ("measure", (1,)), ("measure", (0,))]
    assert p.cregs == {"c": 2}
    assert p.ops[2].clbits == (("c", 1),)


@pytest.mark.parametrize(("expr", "value"), [("pi/2", math.pi / 2), ("-pi/4", -math.pi / 4), ("3*pi/2", 3 * math.pi / 2),
                                             ("0.5", 0.5), ("π", math.pi), ("-(pi - 1)", 1 - math.pi)])
def test_parse_evaluates_angle_expressions(expr, value):
    (op,) = parse(f"rz({expr}) $0;").ops
    assert op.params == (pytest.approx(value),)


def test_parse_rejects_code_in_angle_expressions():
    with pytest.raises(QasmError, match="line 1"):
        parse("rz(__import__('os')) $0;")


def test_x_then_measure_on_the_tick_grid(tr):
    t = tr.translate(HEADER + "x $0;\nc[0] = measure $0;", None, shots=100)
    assert ops(t.job) == [(0, "play", "xy_q0"), (20, "acquire", "ro_q0")]
    play = t.job.main.instructions[0].play
    assert play.amplitude == pytest.approx(0.5)
    wf = t.job.waveform_library[play.waveform_id]
    assert (wf.shape, wf.length_samples) == (job_pb2.WAVEFORM_SHAPE_SQUARE, 20)
    acq = t.job.main.instructions[1].acquire
    assert (acq.result_key, acq.integration_ticks, acq.mode) == ("c[0]", 1000, job_pb2.ACQUISITION_MODE_DISCRIMINATED)
    assert t.job.num_shots == 100
    assert t.clbits == ["c[0]", "c[1]"]


def test_sx_is_half_a_pi_pulse(tr):
    t = tr.translate("sx $0;", None, shots=1)
    assert t.job.main.instructions[0].play.amplitude == pytest.approx(0.25)


def test_rz_is_a_merged_virtual_frame_shift_before_the_next_pulse(tr):
    t = tr.translate("rz(pi/2) $0;\nrz(pi/2) $0;\nx $0;", None, shots=1)
    assert ops(t.job) == [(0, "shift_phase", "q0"), (0, "play", "xy_q0")]
    assert t.job.main.instructions[0].shift_phase.delta_rad == pytest.approx(-math.pi)


def test_trailing_rz_emits_nothing(tr):
    t = tr.translate(HEADER + "x $0;\nrz(0.3) $0;\nc[0] = measure $0;", None, shots=1)
    assert [k for _, k, _ in ops(t.job)] == ["play", "acquire"]


def test_live_calibration_selects_a_drag_pulse(tr):
    snap = calibration_pb2.CalibrationSnapshot(calibration_epoch=3)
    snap.qubits.add(qubit_index=0, pi_amplitude=0.8, pi_length_samples=40, drag_beta_samples=0.5)
    t = tr.translate("x $0;\nsx $0;", snap, shots=1)
    first, second = (i.play for i in t.job.main.instructions)
    wf = t.job.waveform_library[first.waveform_id]
    assert (wf.shape, wf.length_samples, wf.drag_beta_samples) == (job_pb2.WAVEFORM_SHAPE_DRAG, 40, 0.5)
    assert wf.sigma_samples == pytest.approx(10.0)
    assert (first.amplitude, second.amplitude) == (pytest.approx(0.8), pytest.approx(0.4))
    assert [i.start_tick for i in t.job.main.instructions] == [0, 40]


def test_barrier_aligns_qubits(tr):
    t = tr.translate("x $0;\nbarrier $0, $1;\nx $1;", None, shots=1)
    assert ops(t.job) == [(0, "play", "xy_q0"), (20, "play", "xy_q1")]


def test_parallel_gates_on_different_qubits_start_together(tr):
    t = tr.translate("x $0;\nx $1;", None, shots=1)
    assert [s for s, _, _ in ops(t.job)] == [0, 0]


def test_repeated_measurement_on_one_channel_respects_acquire_spacing(tr):
    t = tr.translate(HEADER + "c[0] = measure $0;\nx $0;\nc[1] = measure $0;", None, shots=1)
    acquires = [s for s, k, _ in ops(t.job) if k == "acquire"]
    assert acquires[1] - acquires[0] >= 1000 + 20


def test_job_options_are_passed_through(tr):
    t = tr.translate("x $0;", None, shots=7, seed=11, expected_epoch=4, job_key="quark-1",
                     tier=job_pb2.FIDELITY_TIER_T1B_STATEVECTOR)
    j = t.job
    assert (j.num_shots, j.random_seed, j.expected_calibration_epoch, j.job_key, j.requested_tier) == (
        7, 11, 4, "quark-1", job_pb2.FIDELITY_TIER_T1B_STATEVECTOR)


@pytest.mark.parametrize(("program", "message"), [
    ("h $0;", "line 1: gate 'h' is not a native operation"),
    ("x $9;", "line 1: qubit 9 is not in the pulse library"),
    ("cz $0, $1;", "line 1: cz on qubits (0, 1) is not calibrated"),
    ("bit[1] c;\nc[3] = measure $0;", "line 2: bit c[3] is not declared"),
    ("if (c[0]) x $0;", "line 1"),
])
def test_unsupported_programs_name_the_line(tr, program, message):
    with pytest.raises(UnsupportedProgramError, match=re.escape(message)):
        tr.translate(program, None, shots=1)


def test_cz_uses_the_calibrated_flux_pulse_and_phase_corrections():
    data = load_pulse_library(LIB).model_dump()
    data["two_qubit"] = {"0-1": {"channel": "flux_q0", "shape": "square", "length_samples": 60, "amplitude": 0.3,
                                 "phase_corrections": {0: 0.1, 1: -0.2}}}
    lib = PulseLibrary.model_validate(data)
    t = Translator(lib).translate("x $1;\ncz $0, $1;\nx $0;\nx $1;", None, shots=1)
    assert ops(t.job) == [(0, "play", "xy_q1"), (20, "play", "flux_q0"), (80, "shift_phase", "q0"),
                          (80, "play", "xy_q0"), (80, "shift_phase", "q1"), (80, "play", "xy_q1")]
    assert t.job.main.instructions[2].shift_phase.delta_rad == pytest.approx(-0.1)
    assert t.job.main.instructions[4].shift_phase.delta_rad == pytest.approx(0.2)


def test_preview_lists_the_pulse_schedule(tr):
    t = tr.translate(HEADER + "x $0;\nc[0] = measure $0;", None, shots=1)
    assert [(e["t_ticks"], e["op"], e["channel"]) for e in t.schedule] == [(0, "play", "xy_q0"),
                                                                           (20, "acquire", "ro_q0")]
    assert t.schedule[0]["waveform"]["shape"] == "square"


def test_acquisitions_sharing_a_readout_sequencer_are_spaced(tr):
    t = tr.translate(HEADER + "c[0] = measure $0;\nc[1] = measure $1;", None, shots=1)
    a, b = (s for s, k, _ in ops(t.job) if k == "acquire")
    assert abs(b - a) >= 300                    # both qubits read out through qrm_rf0_seq0
