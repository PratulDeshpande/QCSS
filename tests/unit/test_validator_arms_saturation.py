"""Validator: exclusive branch arms (D12), DAC saturation and time of flight (D17)."""
from __future__ import annotations

from qcss.config.loader import load_device
from qcss.config.profile import OverlapPolicy, SaturationPolicy
from qcss.feedback.latency import readout_tof_ticks
from qcss.ir.compiler import build_bindings
from qcss.ir.program import Acquire, Branch, ChannelBinding, ChannelKind, Condition, Play, Program
from qcss.ir.validator import Validator


def _reject_profile(prof):
    return prof.model_copy(update={"generators": tuple(
        g.model_copy(update={"overlap_policy": OverlapPolicy.REJECT}) for g in prof.generators)})


BINDS = {"xy_q0": ChannelBinding("xy_q0", ChannelKind.DRIVE, "qcm_rf0_seq0", "qcm_rf0_out0", "q0", (0,)),
         "xy_q1": ChannelBinding("xy_q1", ChannelKind.DRIVE, "qcm_rf0_seq1", "qcm_rf0_out0", "q1", (1,)),
         "ro_q0": ChannelBinding("ro_q0", ChannelKind.READOUT, "qrm_rf0_seq0", "qrm_rf0_out0", "ro_q0", (0,))}


def _two_seq_profile(prof):
    seq0 = next(g for g in prof.generators if g.generator_id == "qcm_rf0_seq0")
    seq1 = seq0.model_copy(update={"generator_id": "qcm_rf0_seq1"})
    return prof.model_copy(update={"generators": prof.generators + (seq1,)})


def test_exclusive_branch_arms_do_not_overlap_each_other(qblox_profile, timebase_1ghz):
    prof = _reject_profile(qblox_profile)
    prog = Program(BINDS, waveforms={"x": 20})
    prog.ops = [Acquire("a", "ro_q0", 0, 100, "discriminated", register=0),
                Branch("br", "qcm_rf0_seq0", 1000, 20, Condition("eq", (0,), 1),
                       then_ops=(Play("t", "xy_q0", 1000, 20, "x", 1.0),),
                       else_ops=(Play("e", "xy_q0", 1000, 20, "x", 0.5),))]
    rep = Validator(prof, timebase_1ghz).validate(prog)
    assert rep.violations == []


def test_arm_overlapping_a_later_main_play_is_still_caught(qblox_profile, timebase_1ghz):
    prof = _reject_profile(qblox_profile)
    prog = Program(BINDS, waveforms={"x": 20})
    prog.ops = [Acquire("a", "ro_q0", 0, 100, "discriminated", register=0),
                Branch("br", "qcm_rf0_seq0", 1000, 20, Condition("eq", (0,), 1),
                       then_ops=(Play("t", "xy_q0", 1000, 20, "x", 1.0),)),
                Play("m", "xy_q0", 1010, 20, "x", 1.0)]
    rep = Validator(prof, timebase_1ghz).validate(prog)
    assert any(p == "m" and "overlaps" in msg for p, msg in rep.violations)


def test_overlapping_plays_on_one_port_saturate(qblox_profile, timebase_1ghz):
    prof = _two_seq_profile(qblox_profile)
    port = next(p for p in prof.ports if p.port_id == "qcm_rf0_out0")
    prof_reject = prof.model_copy(update={"ports": tuple(
        p.model_copy(update={"saturation_policy": SaturationPolicy.REJECT}) if p is port else p for p in prof.ports)})
    prog = Program(BINDS, waveforms={"x": 20})
    prog.ops = [Play("p0", "xy_q0", 0, 20, "x", 0.6), Play("p1", "xy_q1", 0, 20, "x", 0.6)]
    rep = Validator(prof_reject, timebase_1ghz).validate(prog)
    assert any("full scale" in msg for _, msg in rep.violations)
    rep_warn = Validator(prof, timebase_1ghz).validate(prog)       # profile policy: warn
    assert rep_warn.ok and any("full scale" in w for w in rep_warn.warnings)


def test_single_play_below_full_scale_is_clean(qblox_profile, timebase_1ghz):
    prog = Program(BINDS, waveforms={"x": 20}, ops=[Play("p0", "xy_q0", 0, 20, "x", 0.9)])
    rep = Validator(qblox_profile, timebase_1ghz).validate(prog)
    assert rep.ok and not rep.warnings


def test_tof_is_internal_plus_cable_delay(qblox_profile, timebase_1ghz):
    dev = load_device("src/qcss/config/devices/transmon_5q.yaml")
    b = build_bindings(qblox_profile, dev)
    # Qblox RF internal 153 ns + 120 ns cable from the device file
    assert readout_tof_ticks(qblox_profile, dev, b["ro_q0"], timebase_1ghz) == 273
    assert readout_tof_ticks(qblox_profile, None, b["ro_q0"], timebase_1ghz) == 153
