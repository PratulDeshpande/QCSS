"""Unit tests for TimeBase integer-tick time model."""
from __future__ import annotations

import pytest

from qcss.core.errors import TimebaseError
from qcss.core.timebase import TimeBase


def test_qblox_21ns_is_legal_tick():
    tb = TimeBase.from_clocks("1e9")
    # 21 ns is exactly 21 ticks at 1 GHz
    assert tb.ns_to_ticks(21) == 21
    assert tb.ticks_to_ns(21) == 21.0


def test_hdawg_16_samples():
    tb = TimeBase.from_clocks("2.4e9", "300e6")
    # 16 samples at 2.4 GSa/s
    ticks = tb.samples_to_ticks(16, "2.4e9")
    assert ticks == 16
    assert abs(tb.ticks_to_ns(ticks) - 6.666666666666667) < 1e-9


def test_qick_commensurate():
    # QICK t_clk 430.08 MHz and generator 599.04 MHz
    tb = TimeBase.from_clocks("430.08e6", "599.04e6")
    assert tb.ticks_per("430.08e6") == 39
    assert tb.ticks_per("599.04e6") == 28


def test_non_integer_rejected():
    tb = TimeBase.from_clocks("1e9")
    with pytest.raises(TimebaseError):
        tb.ns_to_ticks(0.3, exact=True)
    assert tb.ns_to_ticks(0.3, exact=False) == 0


def test_ticks_to_samples_incommensurate():
    tb = TimeBase.from_clocks("2.4e9")
    with pytest.raises(TimebaseError):
        tb.ticks_to_samples(1, "1.2e9")  # 1 tick = 0.5 samples at 1.2 GHz
