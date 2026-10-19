"""Single-qutrit T2 oracles run through the real runtime (the path gRPC and the CLI execute).

Rabi, Ramsey, T1, Hahn echo, thermal equilibrium and inter-shot carry-over (plan Phase 3),
each compared with its analytic formula at 5 sigma plus a small model tolerance for qutrit
leakage / AC-Stark terms and the ~0.5 % physical readout error.
"""
from __future__ import annotations

import asyncio

import numpy as np

from qcss.config.device import DeviceSpec
from qcss.config.loader import load_profile
from qcss.core.ndarray import from_proto
from qcss.core.timebase import TimeBase
from qcss.physics.transmon import nbar_from_temperature, thermal_populations
from qcss.runtime.runner import create_simulation_runner
from qcss.v1 import job_pb2
from tests.stats import assert_binomial

PROFILE = load_profile("src/qcss/config/profiles/test_ideal_1q.yaml")
OMEGA = 2 * np.pi * 0.05            # rad/ns at amplitude 1 (rabi_max_ghz 0.05)
T1_NS, T2_NS = 50_000.0, 30_000.0


def device(t1_us=50.0, t2_us=30.0, **qubit) -> DeviceSpec:
    q = {"qubit_index": 0, "f_max_ghz": 5.0, "ec_ghz": 0.3, "t1_us": t1_us, "t2_star_us": t2_us}
    q.update(qubit)
    return DeviceSpec.model_validate({
        "device_name": "oracle", "qubits": [q],
        "resonators": [{"qubit_index": 0, "f_r_ghz": 7.0, "kappa_mhz": 1.0, "pulls_mhz": [0.0, -1.5, -3.0],
                        "cable_delay_ns": 100.0, "eta": 0.5}]})


DEV = device()


def p1(ops, acq_at, shots=2000, dev=DEV, waveforms=None, **jobkw) -> float:
    j = job_pb2.Job(num_shots=shots, requested_tier=job_pb2.FIDELITY_TIER_T2_LINDBLAD, random_seed=3, **jobkw)
    for k, n in (waveforms or {}).items():
        j.waveform_library[k].CopyFrom(job_pb2.Waveform(shape=job_pb2.WAVEFORM_SHAPE_SQUARE, length_samples=n))
    for op in ops:
        j.main.instructions.add().CopyFrom(op)
    j.main.instructions.add(start_tick=acq_at, acquire=job_pb2.Acquire(
        channel_id="ro_q0", integration_ticks=1000, mode=job_pb2.ACQUISITION_MODE_DISCRIMINATED, result_key="q0"))
    runner = create_simulation_runner(PROFILE, dev, TimeBase.from_clocks("1e9"))

    async def go():
        return [c async for c in runner("oracle", j, asyncio.Event())]
    s = np.concatenate([from_proto(c.acquisitions[0].states) for c in asyncio.run(go())])
    return float(s.mean())


def play(t, wid, amp, phase=0.0):
    return job_pb2.Instruction(start_tick=t, play=job_pb2.Play(channel_id="xy_q0", waveform_id=wid, amplitude=amp,
                                                               phase_offset_rad=phase))


def detune(hz):
    return job_pb2.Instruction(start_tick=0, set_frequency=job_pb2.SetFrequency(frame_id="q0", frequency_hz=hz))


def test_rabi_oscillation():
    amp = 0.25                                   # 12.5 MHz Rabi: little leakage
    for n in (8, 16, 24, 40):
        theta = amp * OMEGA * n
        got = p1([play(0, f"sq{n}", amp)], n + 4, waveforms={f"sq{n}": n})
        assert_binomial(int(got * 2000), 2000, np.sin(theta / 2) ** 2, delta_model=0.02)


def test_ramsey_fringe_from_nco_detuning():
    # pi/2 (20 ns at amplitude 0.25), free evolution tau, pi/2; the NCO is 2 MHz off the qubit
    for tau, expected in ((0, 1.0), (250, 0.0), (500, 1.0)):
        got = p1([detune(2e6), play(0, "h", 0.25), play(20 + tau, "h", 0.25)], 44 + tau, waveforms={"h": 20})
        decay = np.exp(-(20 + tau) / T2_NS)
        assert_binomial(int(got * 2000), 2000, 0.5 * (1 - decay) + expected * decay, delta_model=0.03)


def test_t1_decay():
    tau = 20_000
    got = p1([play(0, "pi", 0.5)], 20 + tau, waveforms={"pi": 20})
    assert_binomial(int(got * 2000), 2000, np.exp(-tau / T1_NS), delta_model=0.02)


def test_hahn_echo_refocuses_detuning():
    # X90 - tau/2 - Y180 - tau/2 - X90 ends in |1> whatever the static detuning: the Ramsey test above
    # gives ~0 at the same tau (2 MHz, half a turn); the echo refocuses it. (An all-X echo would be a
    # 2 pi rotation back to |0>.)
    tau = 250
    ops = [detune(2e6), play(0, "h", 0.25), play(20 + tau // 2, "pi", 0.5, np.pi / 2), play(40 + tau, "h", 0.25)]
    got = p1(ops, 64 + tau, waveforms={"h": 20, "pi": 20})
    assert_binomial(int(got * 2000), 2000, 0.5 * (1 + np.exp(-(60 + tau) / T2_NS)), delta_model=0.03)


def test_thermal_equilibrium_population():
    dev = device(t_eff_mk=80.0)
    nbar = nbar_from_temperature(5.0, 80.0)
    got = p1([], 0, shots=20000, dev=dev)
    expected = thermal_populations(nbar)[1:].sum()          # binary readout reports |2> as 1
    assert_binomial(int(got * 20000), 20000, expected, delta_model=0.005)


def test_carry_over_without_reset():
    # pi + measure every shot, repetition delay = T1, no reset: the start population p obeys
    # p' = (1 - p) e^{-1}  ->  p* = e^{-1} / (1 + e^{-1}); the measured P1 is 1 - p*.
    dev = device(t1_us=5.0, t2_us=5.0)
    got = p1([play(0, "pi", 0.5)], 20, shots=1500, dev=dev, waveforms={"pi": 20}, repetition_delay_ticks=5000)
    p_star = np.exp(-1) / (1 + np.exp(-1))
    # the 1.1 us readout window adds a little decay before the next shot: allow 0.04
    assert_binomial(int(got * 1500), 1500, 1 - p_star, delta_model=0.04)
