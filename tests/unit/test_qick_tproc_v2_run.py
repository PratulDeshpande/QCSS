"""The tProc v2 interpreter: a compiled QICK program runs to the timed outputs the board would emit."""
from __future__ import annotations

import time

import numpy as np
import pytest

pytest.importorskip("qick")

from qcss.boards.qick.tproc_v2_run import run
from tests.unit.test_qick_tproc_v2 import SOCCFG, Rabi

REPS, POINTS = 3, 5                 # Rabi sweeps "amp" over 5 points
DRIVE_PORT, MUX_PORT = 0, 10        # the generators' tproc_ch in the firmware description
RO_TRIGGER = SOCCFG["readouts"][0]["trigger_port"]


def _trace(reps=REPS):
    prog = Rabi(SOCCFG, reps=reps, final_delay=1.0, cfg={})
    return run(prog.binprog)


def test_every_shot_ends_with_one_count_and_the_program_halts():
    tr = _trace()
    assert tr.halted
    assert tr.counter(1) == REPS * POINTS                   # what get_tproc_counter(addr=1) reads
    assert len(tr.shots) == REPS * POINTS


def test_each_shot_plays_the_drive_then_the_probe_and_triggers_the_readout():
    for shot in _trace().shots:
        kinds = [(e.kind, e.port) for e in shot]
        assert ("pulse", DRIVE_PORT) in kinds and ("pulse", MUX_PORT) in kinds
        assert ("trig_set", RO_TRIGGER) in kinds and ("trig_clr", RO_TRIGGER) in kinds
        t = {k: e.t for e in shot for k in [(e.kind, e.port)]}
        assert t[("pulse", DRIVE_PORT)] < t[("pulse", MUX_PORT)] <= t[("trig_set", RO_TRIGGER)]


def test_the_swept_gain_steps_through_the_sweep_and_restarts_every_rep():
    gains = [e.wave[3] for shot in _trace().shots for e in shot
             if (e.kind, e.port) == ("pulse", DRIVE_PORT) and e.wave is not None]
    per_rep = np.array(gains).reshape(REPS, POINTS)
    assert (per_rep == per_rep[0]).all()                     # every rep sweeps the same points
    steps = np.diff(per_rep[0])
    assert (steps == steps[0]).all() and steps[0] > 0         # a linear sweep from 0 upwards
    assert per_rep[0, 0] == 0


def test_shots_follow_each_other_at_a_constant_period():
    starts = [shot[0].t for shot in _trace().shots]
    assert len(set(np.diff(starts))) == 1


def test_a_thousand_reps_run_in_a_moment_because_waits_are_skipped_not_spun():
    t0 = time.perf_counter()
    tr = _trace(reps=1000)
    assert tr.counter(1) == 1000 * POINTS
    assert time.perf_counter() - t0 < 10
