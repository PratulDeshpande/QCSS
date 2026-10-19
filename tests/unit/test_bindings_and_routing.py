"""Channel bindings, feedback routing and latency lookup (defects D1, D2, D5, D18)."""
from __future__ import annotations

import pytest

from qcss.config.loader import load_device, load_profile
from qcss.core.timebase import TimeBase
from qcss.feedback.latency import FeedbackLatencyResolver, LatencyRouteError
from qcss.ir.compiler import build_bindings
from qcss.ir.program import Acquire, Branch, ChannelBinding, ChannelKind, Condition, Play, Program
from qcss.ir.validator import Validator

PROFILES = "src/qcss/config/profiles/"
DEVICES = "src/qcss/config/devices/"


def test_bindings_with_coupled_device(qblox_profile):
    dev = load_device(DEVICES + "transmon_5q.yaml")
    b = build_bindings(qblox_profile, dev)
    cr = b["cr_q0_q1"]
    assert cr.kind is ChannelKind.CROSS_RESONANCE
    assert cr.qubits == (0, 1)
    assert cr.frame_id == "q1"          # CR binds to the TARGET qubit's frame


def test_readout_channels_bind_only_to_readout_generators(qblox_profile):
    dev = load_device(DEVICES + "test_ideal_1q.yaml")
    gens = {g.generator_id: g for g in qblox_profile.generators}
    b = build_bindings(qblox_profile, dev)
    for ch in b.values():
        is_ro = gens[ch.generator_id].is_readout
        assert is_ro == (ch.kind is ChannelKind.READOUT), ch


def test_flux_channels_prefer_baseband_ports(qblox_profile):
    dev = load_device(DEVICES + "test_ideal_1q.yaml")
    b = build_bindings(qblox_profile, dev)
    ports = {p.port_id: p for p in qblox_profile.ports}
    assert ports[b["flux_q0"].port_id].kind == "baseband"


def test_routing_uses_modules_not_ports(qblox_profile, zi_profile):
    assert qblox_profile.routing("qrm_rf0_seq0", "qcm_rf0_seq0") == "inter"
    assert qblox_profile.routing("qcm_rf0_seq0", "qcm_rf0_seq0") == "self"
    # SHFQC+: QA and SG channels live in one instrument -> 350 ns internal feedback
    assert zi_profile.routing("qa_gen0", "sg_gen0") == "intra"
    v = Validator(zi_profile, TimeBase.from_clocks(zi_profile.clock.tick_hz))
    assert v.latency("qa_gen0", "sg_gen0") == 700


def test_missing_latency_route_is_a_violation_not_a_crash(qblox_profile, timebase_1ghz):
    prof = qblox_profile.model_copy(update={"feedback": qblox_profile.feedback.model_copy(update={"latencies": ()})})
    b = {"xy_q0": ChannelBinding("xy_q0", ChannelKind.DRIVE, "qcm_rf0_seq0", "qcm_rf0_out0", "q0", (0,)),
         "ro_q0": ChannelBinding("ro_q0", ChannelKind.READOUT, "qrm_rf0_seq0", "qrm_rf0_out0", "ro_q0", (0,))}
    prog = Program(b, waveforms={"x": 20})
    prog.ops = [Acquire("a", "ro_q0", 0, 100, "discriminated", register=0),
                Branch("br", "qcm_rf0_seq0", 5000, 20, Condition("eq", (0,), 1),
                       then_ops=(Play("t", "xy_q0", 5000, 20, "x", 1.0),))]
    rep = Validator(prof, timebase_1ghz).validate(prog)
    assert any(p == "br.condition" and "no feedback latency" in m for p, m in rep.violations)


def test_resolver_has_no_hardcoded_fallback(qblox_profile):
    prof = qblox_profile.model_copy(update={"feedback": qblox_profile.feedback.model_copy(update={"latencies": ()})})
    with pytest.raises(LatencyRouteError):
        FeedbackLatencyResolver(prof).latency_ticks("qrm_rf0_seq0", "qcm_rf0_seq0")


@pytest.mark.parametrize("name", ["qblox_cluster_5q", "zi_shfqc_5q", "qick_zcu216_4q", "test_ideal_1q"])
def test_every_shipped_profile_supports_readout_feedback(name):
    prof = load_profile(PROFILES + f"{name}.yaml")
    b = build_bindings(prof)
    ro = b["ro_q0"]
    xy = b["xy_q0"]
    assert ro.kind is ChannelKind.READOUT
    v = Validator(prof, TimeBase.from_clocks(prof.clock.tick_hz))
    assert v.latency(ro.generator_id, xy.generator_id) > 0


def test_qick_profile_clocks_are_commensurate():
    prof = load_profile(PROFILES + "qick_zcu216_4q.yaml")
    tb = TimeBase.from_clocks(prof.clock.tick_hz)
    rates = {g.generator_id: tb.ticks_per(g.sample_rate_hz) for g in prof.generators}
    assert rates["gen0"] == 5          # 6881.28 Msps DAC
    assert tb.ticks_per("430.08e6") == 80   # tProc cycle
    assert any(g.is_readout for g in prof.generators)
