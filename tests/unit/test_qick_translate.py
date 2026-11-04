"""Shot timelines to QCSS jobs: what the board plays, shot by shot, as the chassis's program points.

A QICK round is one long program; the chassis runs program points of identical shots. The translator
cuts the interpreter's output at the shot counter, turns each shot's port writes into timed IR
(resolving generator queueing first, as the hardware does), folds identical shots into one point, and
keeps the true shot order so results go back where the board would have put them.
"""
# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
from __future__ import annotations

import asyncio

import numpy as np
import pytest

pytest.importorskip("qick")
from qick.asm_v2 import AveragerProgramV2

from qcss.boards.qick.soc import QcssQickSoc
from qcss.boards.qick.tproc_v2_run import run
from qcss.boards.qick.translate import translate
from qcss.config.loader import load_device, load_profile
from qcss.core.timebase import TimeBase
from qcss.ir.compiler import build_bindings
from qcss.runtime.runner import create_simulation_validator
from tests.unit.test_qick_tproc_v2 import SOCCFG, Rabi, _base

PROFILE = load_profile("src/qcss/config/profiles/qick_zcu216_5q.yaml")
DEVICE = load_device("src/qcss/config/devices/transmon_5q.yaml")
BINDINGS = build_bindings(PROFILE, DEVICE)
REPS, POINTS = 3, 5
TICKS_PER_CYCLE = 80                      # 34406.4 MHz ticks per 430.08 MHz timing-clock cycle


def _translate(prog_cls, reps=REPS, **kw):
    soc = QcssQickSoc(SOCCFG._cfg)
    prog = prog_cls(SOCCFG, reps=reps, final_delay=kw.pop("final_delay", 1.0), cfg={})
    prog.config_all(soc)
    prog.config_bufs(soc, enable_avg=True, enable_buf=False)
    return translate(run(soc.state.binprog), soc.state, BINDINGS, PROFILE), prog


def _ops(point, kind):
    return [i for i in point.main.instructions if i.WhichOneof("op") == kind]


def test_identical_shots_fold_into_one_point_per_sweep_step():
    tr, _ = _translate(Rabi)
    assert len(tr.jobs) == 1
    job = tr.jobs[0]
    assert len(job.program_points) == POINTS and job.num_shots == REPS
    # the reps loop is outermost: shot s is sweep point s % POINTS, its (s // POINTS)-th occurrence
    assert [(j, p, k) for j, p, k in tr.shots] == [(0, s % POINTS, s // POINTS) for s in range(REPS * POINTS)]


def test_a_point_plays_the_drive_at_its_gain_and_reads_at_the_readout_frequency():
    tr, prog = _translate(Rabi)
    job = tr.jobs[0]
    amps = [_ops(p, "play")[0].play.amplitude for p in job.program_points]
    np.testing.assert_allclose(amps, np.linspace(0, 1, POINTS), atol=1e-4)
    p = job.program_points[1]
    play = _ops(p, "play")[0]
    assert play.play.channel_id == "xy_q0"
    freqs = {i.set_frequency.frame_id: i.set_frequency.frequency_hz for i in _ops(p, "set_frequency")}
    assert freqs["q0"] == pytest.approx(4500e6, abs=2)
    assert freqs["ro_q0"] == pytest.approx(7150e6, abs=1e3)
    (tone,) = [i for i in _ops(p, "play") if i.play.channel_id == "ro_q0"]  # the mux probe, at its gain
    assert tone.play.amplitude == pytest.approx(0.3, abs=1e-4)
    (acq,) = _ops(p, "acquire")
    assert acq.acquire.channel_id == "ro_q0"
    assert acq.acquire.integration_ticks == prog.ro_chs[0]["length"] * 448     # decimated samples at 76.8 MHz
    assert acq.start_tick > play.start_tick


def test_the_gap_between_shots_becomes_the_repetition_delay():
    tr, _ = _translate(Rabi, final_delay=1.0)
    delay_us = tr.jobs[0].repetition_delay_ticks / float(PROFILE.clock.tick_hz) * 1e6
    assert 5.9 < float(delay_us) < 6.2         # the body's delay_auto(5.0), final_delay 1.0, less the readout tail


class Queue(AveragerProgramV2):
    def _initialize(self, cfg):
        _base(self)
        self.add_pulse(ch=0, name="long", style="const", freq=4500, phase=0, length=0.1, gain=0.5)

    def _body(self, cfg):
        self.pulse(ch=0, name="long", t=0)
        self.pulse(ch=0, name="long", t=0.02)                 # due while the first still plays
        self.pulse(ch=MUX, name="probe", t=0.3)
        self.trigger(ros=[0], t=0.3)


MUX = 10


def test_a_busy_generator_plays_the_next_pulse_when_it_is_free():
    tr, _ = _translate(Queue, reps=1)
    a, b = [i for i in _ops(tr.jobs[0].program_points[0], "play") if i.play.channel_id == "xy_q0"]
    n = round(0.1 * 430.08) * TICKS_PER_CYCLE                # the first pulse's length, in ticks
    assert b.start_tick == a.start_tick + n


def test_the_chassis_validator_accepts_the_translated_job():
    tr, _ = _translate(Rabi)
    validate = create_simulation_validator(PROFILE, TimeBase.from_clocks(PROFILE.clock.tick_hz), DEVICE)
    asyncio.run(validate(tr.jobs[0]))
