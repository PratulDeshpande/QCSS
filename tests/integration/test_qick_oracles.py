"""Rabi, Ramsey and T1 written as QICK programs agree with the analytic oracles (tests/oracles) at 5 sigma.

The same ideal one-qubit chip as the oracle tests sits behind the virtual ZCU216. Each experiment is an
AveragerProgramV2 run with acquire(); single shots come from qick's own per-shot buffer and are told
apart with a threshold calibrated from |0> and pi-pulse shots, as a user would calibrate it.
"""
# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportOptionalMemberAccess=false, reportOptionalSubscript=false
from __future__ import annotations

import asyncio
import socket
import threading

import numpy as np
import pytest

pytest.importorskip("qick")
pytest.importorskip("Pyro4")
from qick import QickConfig
from qick.asm_v2 import AveragerProgramV2

from qcss.chassis import Chassis, ChassisConfig
from qcss.config.loader import load_profile
from tests.oracles.test_t2_rabi_ramsey_t1_echo import T1_NS, T2_NS, device
from tests.stats import assert_binomial

F01, RO, MUX = 5000.0, 7000.0, 10
CYCLE_NS = 1e3 / 430.08               # one fabric cycle of a full-speed generator
OMEGA = 2 * np.pi * 0.05              # rad/ns at gain 1 (the oracle chip's rabi_max_ghz)
SHOTS = 2000


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def board():
    chassis = Chassis(ChassisConfig(
        profile=load_profile("src/qcss/config/profiles/qick_zcu216_5q.yaml"), device=device(),
        lab_address=f"127.0.0.1:{_free_port()}", time_scale=0.0, seed=40, qick_ns=f"127.0.0.1:{_free_port()}",
        qick_start_ns=True))
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    asyncio.run_coroutine_threadsafe(chassis.start(), loop).result(60)
    soc = chassis.qick_soc
    soccfg = QickConfig(soc.get_cfg())
    yield soc, soccfg, _threshold(soc, soccfg)
    asyncio.run_coroutine_threadsafe(chassis.stop(), loop).result(60)
    loop.call_soon_threadsafe(loop.stop)


class Seq(AveragerProgramV2):
    """Pulses on the qubit (gain, cycles, phase deg, start us, freq MHz), then a 2 us readout."""

    def _initialize(self, cfg):
        self.declare_gen(ch=MUX, nqz=2, ro_ch=0, mux_freqs=[RO], mux_gains=[0.5])
        self.declare_readout(ch=0, length=2.0, freq=RO, gen_ch=MUX)
        self.add_pulse(ch=MUX, name="probe", style="const", length=2.0, mask=[0])
        self.declare_gen(ch=0, nqz=2)                   # 5 GHz is in the second Nyquist zone
        for k, (gain, cycles, phase, _, freq) in enumerate(cfg["pulses"]):
            self.add_pulse(ch=0, name=f"p{k}", style="const", freq=freq, phase=phase, gain=gain,
                           length=cycles * CYCLE_NS / 1e3)

    def _body(self, cfg):
        end = 0.0
        for k, (_, cycles, _, t, _) in enumerate(cfg["pulses"]):
            self.pulse(ch=0, name=f"p{k}", t=t)
            end = max(end, t + cycles * CYCLE_NS / 1e3)
        self.pulse(ch=MUX, name="probe", t=end + 0.01)
        self.trigger(ros=[0], t=end + 0.01)


def _shots(soc, soccfg, pulses, shots=SHOTS) -> np.ndarray:
    prog = Seq(soccfg, reps=shots, final_delay=300.0, cfg={"pulses": pulses})   # 6 T1 between shots
    prog.acquire(soc, progress=False)
    d = prog.acc_buf[0].reshape(-1, 2)
    return d[:, 0] + 1j * d[:, 1]


def _threshold(soc, soccfg):
    pi = 1 / (2 * 0.05 * CYCLE_NS * 0.5)                 # cycles for a pi pulse at gain 0.5
    g = _shots(soc, soccfg, [(0.0, 20, 0, 0.0, F01)], 500)
    e = _shots(soc, soccfg, [(0.5, round(pi), 0, 0.0, F01)], 500)
    rot = np.exp(-1j * np.angle(e.mean() - g.mean()))
    mid = float(np.real((g.mean() + e.mean()) / 2 * rot))
    return rot, mid


def _p1(board, pulses) -> int:
    soc, soccfg, (rot, mid) = board
    return int(np.sum(np.real(_shots(soc, soccfg, pulses) * rot) > mid))


def test_rabi_oscillation(board):
    for cycles in (4, 8, 12):
        theta = 0.25 * OMEGA * cycles * CYCLE_NS
        assert_binomial(_p1(board, [(0.25, cycles, 0, 0.0, F01)]), SHOTS, np.sin(theta / 2) ** 2,
                        delta_model=0.04)


def test_ramsey_fringe_from_detuning(board):
    half = round(np.pi / 2 / (0.25 * OMEGA * CYCLE_NS))  # a pi/2 at gain 0.25
    for tau_ns, expected in ((0.0, 1.0), (250.0, 0.0), (500.0, 1.0)):     # 2 MHz off the qubit
        t2 = (half * CYCLE_NS + tau_ns) / 1e3
        got = _p1(board, [(0.25, half, 0, 0.0, F01 - 2.0), (0.25, half, 0, t2, F01 - 2.0)])
        decay = np.exp(-(half * CYCLE_NS + tau_ns) / T2_NS)
        assert_binomial(got, SHOTS, 0.5 * (1 - decay) + expected * decay, delta_model=0.05)


def test_t1_decay(board):
    pi = round(np.pi / (0.5 * OMEGA * CYCLE_NS))
    tau_us = 20.0
    got = _p1(board, [(0.5, pi, 0, 0.0, F01), (0.0, 3, 0, tau_us, F01)])   # a silent marker sets the wait
    assert_binomial(got, SHOTS, np.exp(-tau_us * 1e3 / T1_NS), delta_model=0.04)
