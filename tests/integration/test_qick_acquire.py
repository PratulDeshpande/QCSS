"""A QICK program runs on the virtual board: acquire(), acquire_decimated() and run_rounds() end to end.

The qick client is unmodified and talks to the board object the chassis serves (in process, so no
Pyro hop; test_qick_pyro_board.py covers the wire). The chassis simulates the chip, so the data are
the chip's: a readout tone's gain shows in the signal, the resonator turns the phase as the probe
crosses it, and a raw window shows the time of flight before the tone comes back.
"""
# qick 0.2.370 annotates times and channels loosely and acquire() as returning None: its hints are wrong here.
# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportOptionalMemberAccess=false, reportOptionalSubscript=false, reportCallIssue=false, reportGeneralTypeIssues=false
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
from qcss.config.loader import load_device, load_profile

RO, MUX = 7150.0, 10


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def board():
    chassis = Chassis(ChassisConfig(
        profile=load_profile("src/qcss/config/profiles/qick_zcu216_5q.yaml"),
        device=load_device("src/qcss/config/devices/transmon_5q.yaml"), lab_address=f"127.0.0.1:{_free_port()}",
        time_scale=0.0, seed=40, qick_ns=f"127.0.0.1:{_free_port()}", qick_start_ns=True))
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    asyncio.run_coroutine_threadsafe(chassis.start(), loop).result(60)
    soc = chassis.qick_soc
    yield soc, QickConfig(soc.get_cfg())
    asyncio.run_coroutine_threadsafe(chassis.stop(), loop).result(60)
    loop.call_soon_threadsafe(loop.stop)


def _readout(prog, gain=0.5, freq=RO, length=1.0):
    prog.declare_gen(ch=MUX, nqz=2, ro_ch=0, mux_freqs=[freq], mux_gains=[gain])
    prog.declare_readout(ch=0, length=length, freq=freq, gen_ch=MUX)
    prog.add_pulse(ch=MUX, name="probe", style="const", length=length, mask=[0])


class Measure(AveragerProgramV2):
    def _initialize(self, cfg):
        _readout(self, gain=cfg["gain"], freq=cfg["freq"])

    def _body(self, cfg):
        self.pulse(ch=MUX, name="probe", t=0)
        self.trigger(ros=[0], t=cfg.get("trig", 0.3))


def test_acquire_returns_one_averaged_point_per_readout_in_the_clients_shape(board):
    soc, soccfg = board
    prog = Measure(soccfg, reps=50, final_delay=1.0, cfg={"gain": 0.5, "freq": RO})
    iq = prog.acquire(soc, progress=False)
    assert len(iq) == 1 and iq[0].shape == (1, 2)                     # (reads, I/Q) for one readout
    assert np.all(np.isfinite(iq[0]))
    assert soc.get_tproc_counter(addr=1) == 50                         # the round counted every shot


def test_a_stronger_probe_gives_a_proportionally_larger_signal(board):
    soc, soccfg = board
    a = [np.hypot(*Measure(soccfg, reps=400, final_delay=1.0, cfg={"gain": g, "freq": RO})
                  .acquire(soc, progress=False)[0][0]) for g in (0.2, 0.8)]
    assert a[1] / a[0] == pytest.approx(4.0, rel=0.25)


def test_the_resonator_turns_the_phase_as_the_probe_crosses_it(board):
    soc, soccfg = board                       # mux tones are fixed per program: a scan reruns it per frequency
    freqs = np.linspace(RO - 4, RO + 4, 17)
    iq = np.array([Measure(soccfg, reps=200, final_delay=1.0, cfg={"gain": 0.5, "freq": f})
                   .acquire(soc, progress=False)[0][0] for f in freqs])
    phase = np.unwrap(np.angle(iq[:, 0] + 1j * iq[:, 1]))
    steps = np.abs(np.diff(phase))
    assert steps.max() > 5 * np.median(steps)                          # a sharp turn near the resonator


def test_a_decimated_window_shows_the_time_of_flight(board):
    soc, soccfg = board
    prog = Measure(soccfg, reps=1, final_delay=1.0, cfg={"gain": 0.9, "freq": RO, "trig": 0.0})
    tr = prog.acquire_decimated(soc, rounds=20, progress=False)[0]
    assert tr.shape == (prog.ro_chs[0]["length"], 2)
    mag = np.hypot(tr[:, 0], tr[:, 1])
    assert mag[:5].mean() < 0.3 * mag[-20:].mean()                    # the tone is not back yet at the start


def test_run_rounds_runs_the_program_without_reading_data(board):
    soc, soccfg = board
    Measure(soccfg, reps=10, final_delay=1.0, cfg={"gain": 0.5, "freq": RO}).run_rounds(soc, progress=False)
    assert soc.get_tproc_counter(addr=1) == 10


# -- tProc v1 firmware: the same chip behind the older processor and its averager programs ------------

@pytest.fixture(scope="module")
def board_v1():
    chassis = Chassis(ChassisConfig(
        profile=load_profile("src/qcss/config/profiles/qick_zcu216_5q.yaml"),
        device=load_device("src/qcss/config/devices/transmon_5q.yaml"), lab_address=f"127.0.0.1:{_free_port()}",
        time_scale=0.0, seed=40, qick_ns=f"127.0.0.1:{_free_port()}", qick_start_ns=True,
        qick_firmware="zcu216_v1_5q"))
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    asyncio.run_coroutine_threadsafe(chassis.start(), loop).result(60)
    soc = chassis.qick_soc
    yield soc, QickConfig(soc.get_cfg())
    asyncio.run_coroutine_threadsafe(chassis.stop(), loop).result(60)
    loop.call_soon_threadsafe(loop.stop)


def _v1_readout(prog, gain):
    prog.declare_gen(ch=MUX, nqz=2, ro_ch=0, mux_freqs=[RO], mux_gains=[gain])
    prog.declare_readout(ch=0, length=prog.us2cycles(1.0, ro_ch=0), freq=RO, gen_ch=MUX)
    prog.set_pulse_registers(ch=MUX, style="const", length=prog.us2cycles(1.0, gen_ch=MUX), mask=[0])
    prog.synci(200)


def _v1_classes():
    from qick.averager_program import AveragerProgram, NDAveragerProgram, QickSweep, RAveragerProgram

    class Measure1(AveragerProgram):
        def initialize(self):
            _v1_readout(self, self.cfg["gain"])

        def body(self):
            self.measure(pulse_ch=MUX, adcs=[0], adc_trig_offset=self.us2cycles(0.3), wait=True,
                         syncdelay=self.us2cycles(1))

    class Rabi1(RAveragerProgram):
        def initialize(self):
            _v1_readout(self, 0.5)
            self.declare_gen(ch=0, nqz=2)
            self.set_pulse_registers(ch=0, style="const", freq=self.freq2reg(4500, gen_ch=0), phase=0,
                                     gain=self.cfg["start"], length=self.us2cycles(0.05, gen_ch=0))
            self.q_rp, self.r_gain = self.ch_page(0), self.sreg(0, "gain")

        def body(self):
            self.pulse(ch=0, t=0)
            self.sync_all(self.us2cycles(0.05))
            self.measure(pulse_ch=MUX, adcs=[0], adc_trig_offset=self.us2cycles(0.3), wait=True,
                         syncdelay=self.us2cycles(1))

        def update(self):
            self.mathi(self.q_rp, self.r_gain, self.r_gain, "+", self.cfg["step"])

    class Sweep1(NDAveragerProgram):
        def initialize(self):
            _v1_readout(self, 0.5)
            self.declare_gen(ch=0, nqz=2)
            self.set_pulse_registers(ch=0, style="const", freq=self.freq2reg(4500, gen_ch=0), phase=0, gain=0,
                                     length=self.us2cycles(0.05, gen_ch=0))
            self.add_sweep(QickSweep(self, self.get_gen_reg(0, "gain"), 0, 20000, 4))

        def body(self):
            self.pulse(ch=0, t=0)
            self.sync_all(self.us2cycles(0.05))
            self.measure(pulse_ch=MUX, adcs=[0], adc_trig_offset=self.us2cycles(0.3), wait=True,
                         syncdelay=self.us2cycles(1))

    return Measure1, Rabi1, Sweep1


def test_a_v1_averager_program_acquires_and_its_probe_gain_shows(board_v1):
    soc, soccfg = board_v1
    Measure1, _, _ = _v1_classes()
    a = []
    for g in (0.2, 0.8):
        avgi, avgq = Measure1(soccfg, {"reps": 400, "gain": g}).acquire(soc, progress=False)
        assert np.shape(avgi) == (1, 1)                                 # v1: (readouts, reads)
        a.append(np.hypot(avgi[0][0], avgq[0][0]))
    assert a[1] / a[0] == pytest.approx(4.0, rel=0.25)
    assert soc.get_tproc_counter(addr=1) == 400


def test_a_v1_raverager_returns_one_point_per_experiment(board_v1):
    soc, soccfg = board_v1
    _, Rabi1, _ = _v1_classes()
    _, avgi, _ = Rabi1(soccfg, {"reps": 50, "expts": 5, "start": 0, "step": 5000}).acquire(soc, progress=False)
    assert np.shape(avgi) == (1, 1, 5) and np.all(np.isfinite(avgi))


def test_a_v1_nd_averager_sweeps_a_register(board_v1):
    soc, soccfg = board_v1
    _, _, Sweep1 = _v1_classes()
    _, avgi, _ = Sweep1(soccfg, {"reps": 50}).acquire(soc, progress=False)
    assert np.shape(avgi) == (1, 1, 4) and np.all(np.isfinite(avgi))


def test_a_v1_decimated_window_has_the_programs_length(board_v1):
    soc, soccfg = board_v1
    Measure1, _, _ = _v1_classes()
    prog = Measure1(soccfg, {"reps": 1, "gain": 0.9, "soft_avgs": 5})
    tr = prog.acquire_decimated(soc, progress=False)
    assert np.shape(tr) == (1, 2, prog.ro_chs[0]["length"])             # v1: (readouts, I/Q, samples)


class NoReadout(AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_gen(ch=0, nqz=2)
        self.add_pulse(ch=0, name="x", style="const", freq=4500, phase=0, gain=0.1, length=0.05)

    def _body(self, cfg):
        self.pulse(ch=0, name="x", t=0)


def test_a_round_without_a_readout_still_counts_every_shot(board):
    soc, soccfg = board
    NoReadout(soccfg, reps=10, final_delay=1.0, cfg={}).run_rounds(soc, progress=False)
    assert soc.get_tproc_counter(addr=1) == 10
