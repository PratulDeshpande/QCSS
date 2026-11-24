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


# -- hand-built programs: the jump and wait paths the compiled Rabi does not take ------------------------------

from qcss.boards.qick.tproc_v2 import Inst
from qcss.boards.qick.tproc_v2_run import _Machine


def _machine(*prog: Inst, s15: int = 0) -> _Machine:
    m = _Machine(Rabi(SOCCFG, reps=1, final_delay=1.0, cfg={}).binprog, 200.0, 430.08)
    m.prog, m.s[15] = [Inst(addr=n, kind=i.kind, word=0, **{k: v for k, v in vars(i).items()
                                                            if k not in ("addr", "kind", "word")})
                       for n, i in enumerate(prog)], s15
    return m


def _mark(n: int, addr: int) -> Inst:
    return Inst(addr=n, kind="DMEM_WR", word=0, src="imm", imm=7, mem=(None, addr))


def _halt(n: int) -> Inst:
    return Inst(addr=n, kind="JUMP", word=0, target=n)


def test_a_jump_to_the_address_in_s15_skips_what_lies_between():
    m = _machine(Inst(addr=0, kind="JUMP", word=0), _mark(1, 5), _mark(2, 6), _halt(3), s15=3)
    assert m.run(100).halted and m.dmem[5] == 0 and m.dmem[6] == 0


def test_a_wait_loop_is_skipped_to_its_end_whichever_way_it_is_laid_out():
    """TEST then JUMP back to the TEST (target pc-1), or to the JUMP itself (target pc)."""
    for back in (-1, 0):
        test = Inst(addr=0, kind="TEST", word=0, alu="-", src_a="s11", imm=10_000_000)
        jump = Inst(addr=1, kind="JUMP", word=0, cond="S", target=1 + back)
        m = _machine(test, jump, _mark(2, 3), _halt(3))
        tr = m.run(50)
        assert tr.halted and m.dmem[3] == 7, back              # past the wait, and not by spinning 10M cycles
        assert m.core_t >= 10_000_000 and not m.neg


def test_the_wait_skip_leaves_the_flags_as_the_loop_would_have_on_exit():
    test = Inst(addr=0, kind="TEST", word=0, alu="-", src_a="s11", imm=500)
    m = _machine(test, Inst(addr=1, kind="JUMP", word=0, cond="S", target=0), _halt(2))
    m.run(20)
    assert not m.neg                                            # s11 - 500 >= 0 once the wait is over


def test_a_negative_memory_address_is_refused_not_wrapped_to_the_end_of_memory():
    bad = Inst(addr=0, kind="DMEM_WR", word=0, src="imm", imm=1, mem=(None, -1))
    with pytest.raises(ValueError, match="address"):
        _machine(bad, _halt(1)).run(10)


def test_a_negative_jump_target_is_refused_not_wrapped_to_the_last_instruction():
    m = _machine(Inst(addr=0, kind="JUMP", word=0), _halt(1), s15=-1)
    with pytest.raises(ValueError, match="address"):
        m.run(10)
