"""Unit tests for FrameTracker, NCO accumulation, and virtual Z frame bindings."""
from __future__ import annotations

import math
from fractions import Fraction

from qcss.ir.frames import FrameTracker


def test_virtual_z_updates_only_its_frame():
    """A virtual Z changes the explicit phase of its own frame and no other."""
    tick_hz = Fraction(1_000_000_000, 1)  # 1 GHz
    # Frames for q0 and q1
    frames = {"q0": 50e6, "q1": 70e6}
    tracker = FrameTracker(tick_hz, frames, latched=False)

    # Shift phase of q1 by pi/2 (virtual Z)
    tracker.shift_phase("q1", math.pi / 2, tick=0)

    phase_q1 = tracker.explicit_phase("q1")
    assert math.isclose(phase_q1, math.pi / 2, rel_tol=1e-5)
    # q0 must remain unaffected
    assert math.isclose(tracker.explicit_phase("q0"), 0.0, abs_tol=1e-7)


def test_latched_nco_semantics():
    tick_hz = Fraction(1_000_000_000, 1)
    tracker = FrameTracker(tick_hz, {"q0": 50e6}, latched=True)

    # Shift phase while latched -> should not take effect immediately
    tracker.shift_phase("q0", 1.234, tick=10)
    assert math.isclose(tracker.explicit_phase("q0"), 0.0, abs_tol=1e-7)

    # Trigger real-time instruction latch
    tracker.on_rt_instruction("q0", tick=20)
    assert math.isclose(tracker.explicit_phase("q0"), 1.234, rel_tol=1e-5)


def test_frequency_switch_phase_continuity():
    tick_hz = Fraction(1_000_000_000, 1)  # 1 ns per tick
    tracker = FrameTracker(tick_hz, {"q0": 100e6}, latched=False, phase_continuous_freq_switch=True)

    # At tick 10 (10 ns), phase at 100 MHz is 2*pi * 100e6 * 10e-9 = 2*pi
    phase_before = tracker.phase_at("q0", tick=10)

    # Switch frequency to 200 MHz at tick 10
    tracker.set_frequency("q0", 200e6, tick=10)
    phase_after = tracker.phase_at("q0", tick=10)

    # Phase must be continuous across the switch
    assert math.isclose(phase_before, phase_after, abs_tol=1e-5)


def test_reset_phase():
    tick_hz = Fraction(1_000_000_000, 1)
    tracker = FrameTracker(tick_hz, {"q0": 100e6}, latched=False)

    tracker.shift_phase("q0", 1.5, tick=0)
    assert tracker.explicit_phase("q0") > 0

    tracker.reset_phase("q0", tick=50)
    assert math.isclose(tracker.explicit_phase("q0"), 0.0, abs_tol=1e-7)
    # Accumulated phase restarts from tick 50
    assert math.isclose(tracker.phase_at("q0", tick=50), 0.0, abs_tol=1e-7)


def test_virtual_z_reaches_the_cross_resonance_drive():
    """CR channels bind to the TARGET frame (McKay 2017): a virtual Z on q1 must rotate the drive axis
    of the cr_q0_q1 pulse by exactly that angle, as lifted from the rendered samples."""
    import numpy as np

    from qcss.config.device import DeviceSpec
    from qcss.config.loader import load_profile
    from qcss.core.timebase import TimeBase
    from qcss.runtime.runner import SimulationContext
    from qcss.v1 import job_pb2

    dev = DeviceSpec.model_validate({
        "device_name": "pair",
        "qubits": [{"qubit_index": 0, "f_max_ghz": 5.0, "ec_ghz": 0.3, "t1_us": 50, "t2_star_us": 40},
                   {"qubit_index": 1, "f_max_ghz": 5.1, "ec_ghz": 0.3, "t1_us": 50, "t2_star_us": 40}],
        "couplers": [{"qubit_pair": [0, 1], "j_mhz": 3.0}]})
    prof = load_profile("src/qcss/config/profiles/test_ideal_1q.yaml")

    def lifted_cr(theta: float) -> np.ndarray:
        j = job_pb2.Job(num_shots=1, requested_tier=job_pb2.FIDELITY_TIER_T1B_STATEVECTOR)
        j.waveform_library["cr"].CopyFrom(job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=40))
        j.main.instructions.add(start_tick=0, shift_phase=job_pb2.ShiftPhase(frame_id="q1", delta_rad=theta))
        j.main.instructions.add(start_tick=0, play=job_pb2.Play(channel_id="cr_q0_q1", waveform_id="cr", amplitude=0.3))
        ctx = SimulationContext(prof, dev, TimeBase.from_clocks("1e9"))
        plan = ctx.plan(j)
        (ev,) = ctx.dry_run_lift(plan.points[0], plan.qubits, ctx.calibration.snapshot())
        assert ev.qubits == (plan.qubits.index(0),)            # the CR pulse drives the control qubit
        return ev.unitary

    u0, u1 = lifted_cr(0.0), lifted_cr(math.pi / 2)
    shift = np.angle(u1[1, 0]) - np.angle(u0[1, 0])
    assert math.isclose((shift + math.pi) % (2 * math.pi) - math.pi, math.pi / 2, abs_tol=1e-6)