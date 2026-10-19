"""Unit tests for discrete-event simulation engine."""
from __future__ import annotations

import pytest

from qcss.timing.des import DES, Prio


def test_des_priority_ordering():
    engine = DES(now=0)
    executed = []

    # Schedule in arbitrary order at the same tick
    engine.schedule_at(10, Prio.BOOKKEEPING, lambda: executed.append("bookkeeping"))
    engine.schedule_at(10, Prio.PLAYBACK, lambda: executed.append("playback"))
    engine.schedule_at(10, Prio.FRAME_UPDATE, lambda: executed.append("frame_update"))
    engine.schedule_at(10, Prio.ACQ_COMPLETE, lambda: executed.append("acq_complete"))
    engine.schedule_at(10, Prio.BRANCH_DECISION, lambda: executed.append("branch_decision"))

    engine.run_until(10)
    assert executed == ["frame_update", "acq_complete", "branch_decision", "playback", "bookkeeping"]
    assert engine.now == 10


def test_des_fifo_for_equal_priority():
    engine = DES(now=0)
    order = []
    engine.schedule_at(5, Prio.PLAYBACK, lambda: order.append(1))
    engine.schedule_at(5, Prio.PLAYBACK, lambda: order.append(2))
    engine.schedule_at(5, Prio.PLAYBACK, lambda: order.append(3))

    engine.run_until(5)
    assert order == [1, 2, 3]


def test_des_cancellation():
    engine = DES(now=0)
    events = []

    ev1 = engine.schedule_at(5, Prio.PLAYBACK, lambda: events.append("ev1"))
    _ev2 = engine.schedule_at(10, Prio.PLAYBACK, lambda: events.append("ev2"))
    ev3 = engine.schedule_at(15, Prio.PLAYBACK, lambda: events.append("ev3"))

    assert engine.peek_tick() == 5
    engine.cancel(ev1)
    assert engine.peek_tick() == 10

    engine.cancel(ev3)
    engine.run_until(20)

    assert events == ["ev2"]
    assert engine.now == 20


def test_des_rejects_floats():
    engine = DES(now=0)
    with pytest.raises(TypeError, match="tick must be int"):
        engine.schedule_at(10.5, Prio.PLAYBACK, lambda: None)  # type: ignore

    with pytest.raises(ValueError, match="delay must be a non-negative int"):
        engine.schedule_in(10.5, Prio.PLAYBACK, lambda: None)  # type: ignore


def test_des_rejects_past_or_negative():
    engine = DES(now=10)
    with pytest.raises(ValueError, match="cannot schedule in the past"):
        engine.schedule_at(5, Prio.PLAYBACK, lambda: None)

    with pytest.raises(ValueError, match="non-negative int"):
        engine.schedule_in(-1, Prio.PLAYBACK, lambda: None)


def test_des_run_until_advances_horizon():
    engine = DES(now=0)
    engine.schedule_at(5, Prio.PLAYBACK, lambda: None)
    engine.run_until(100)
    assert engine.now == 100


def test_des_trace():
    engine = DES(now=0, trace_len=10)
    engine.schedule_at(1, Prio.FRAME_UPDATE, lambda: None)
    engine.schedule_at(2, Prio.PLAYBACK, lambda: None)
    engine.run_until(2)

    assert engine.trace is not None                 # enabled by trace_len
    assert len(engine.trace) == 2
    assert engine.trace[0][0] == 1
    assert engine.trace[0][1] == Prio.FRAME_UPDATE
    assert engine.trace[1][0] == 2
    assert engine.trace[1][1] == Prio.PLAYBACK
