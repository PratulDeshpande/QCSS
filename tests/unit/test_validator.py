"""Unit tests for Validator against HardwareProfile constraints."""
from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from qcss.config.loader import load_profile
from qcss.core.timebase import TimeBase
from qcss.ir.program import (
    Acquire,
    Branch,
    ChannelBinding,
    ChannelKind,
    Condition,
    FrameOp,
    Play,
    Program,
)
from qcss.ir.validator import Validator


def test_validator_qblox_rules(qblox_profile, timebase_1ghz):
    tb = timebase_1ghz
    prof = qblox_profile

    binds = {
        "xy_q0": ChannelBinding("xy_q0", ChannelKind.DRIVE, "qcm_rf0_seq0", "qcm_rf0_out0", "q0", (0,)),
        "ro_q0": ChannelBinding("ro_q0", ChannelKind.READOUT, "qrm_rf0_seq0", "qrm_rf0_out0", "q0", (0,)),
    }

    prog = Program(binds, waveforms={"x": 20}, repetition_delay=250_000)
    prog.ops = [
        Play("job.main.instructions[0]", "xy_q0", 21, 20, "x", 0.5),  # 21 ns start: LEGAL on Qblox
        Play("job.main.instructions[1]", "xy_q0", 41, 20, "x", 0.5),  # same waveform: memory counted once
        FrameOp("job.main.instructions[2]", "q0", 62, "shift", 1.0),  # not on 4-tick NCO grid
        Acquire("job.main.instructions[3]", "ro_q0", 100, 1000, "discriminated", register=0),
        Branch(
            "job.main.instructions[4]",
            "qcm_rf0_seq0",
            1300,
            40,
            Condition("eq", (0,), 1),
            then_ops=(Play("job.main.instructions[4].then[0]", "xy_q0", 1300, 20, "x", 1.0),),
        ),
    ]

    rep = Validator(prof, tb, tof_ticks={"ro_q0": 153}).validate(prog)
    paths = [p for p, _ in rep.violations]

    # NCO op at tick 62 rejected (62 % 4 != 0)
    assert "job.main.instructions[2].start_tick" in paths
    # Branch at tick 1300 rejected (100 + 153 + 1000 + 388 = 1641)
    assert "job.main.instructions[4].start_tick" in paths
    # 21 ns start is legal on Qblox (rt_granularity = 1 ns)
    assert not any("instructions[0]" in p for p in paths)
    # Memory is 20 samples, not 40 -> no memory violation
    assert not any("generator[qcm_rf0_seq0]" in p for p in paths)


def test_validator_min_duration(qblox_profile, timebase_1ghz):
    prof = qblox_profile
    tb = timebase_1ghz
    binds = {"xy_q0": ChannelBinding("xy_q0", ChannelKind.DRIVE, "qcm_rf0_seq0", "qcm_rf0_out0", "q0", (0,))}

    prog = Program(binds, waveforms={"short": 2})
    # Qblox rt_min_duration is 4 ticks
    prog.ops = [Play("job.main.instructions[0]", "xy_q0", 0, 2, "short", 0.5)]

    rep = Validator(prof, tb).validate(prog)
    assert any("duration 2 < minimum 4" in msg for _, msg in rep.violations)


def test_validator_unknown_channel(qblox_profile, timebase_1ghz):
    prof = qblox_profile
    tb = timebase_1ghz
    prog = Program({}, waveforms={"x": 20})
    prog.ops = [Play("job.main.instructions[0]", "nonexistent", 0, 20, "x", 0.5)]

    rep = Validator(prof, tb).validate(prog)
    assert any("unknown channel" in msg for _, msg in rep.violations)


def test_validator_amplitude_clipping_flag(qblox_profile, timebase_1ghz):
    prof = qblox_profile
    tb = timebase_1ghz
    binds = {"xy_q0": ChannelBinding("xy_q0", ChannelKind.DRIVE, "qcm_rf0_seq0", "qcm_rf0_out0", "q0", (0,))}

    prog = Program(binds, waveforms={"x": 20})
    prog.ops = [Play("job.main.instructions[0]", "xy_q0", 0, 20, "x", 1.5)]

    rep = Validator(prof, tb).validate(prog)
    assert any("|amplitude| 1.5 > 1" in msg for _, msg in rep.violations)


_CACHED_QBLOX = load_profile("src/qcss/config/profiles/qblox_cluster_5q.yaml")
_CACHED_TB = TimeBase.from_clocks("1e9")
_CACHED_BINDS = {"xy_q0": ChannelBinding("xy_q0", ChannelKind.DRIVE, "qcm_rf0_seq0", "qcm_rf0_out0", "q0", (0,))}


@given(st.integers(min_value=0, max_value=500))
def test_hypothesis_nco_grid(nco_start):
    prog = Program(_CACHED_BINDS)
    prog.ops = [FrameOp("inst[0]", "q0", nco_start, "shift", 0.1)]

    rep = Validator(_CACHED_QBLOX, _CACHED_TB).validate(prog)
    if nco_start % 4 == 0:
        assert not any("inst[0].start_tick" in p for p, _ in rep.violations)
    else:
        assert any("inst[0].start_tick" in p for p, _ in rep.violations)
