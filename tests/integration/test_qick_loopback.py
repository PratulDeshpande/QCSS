"""A bench test cable on the virtual board: a generator wired straight into a readout's ADC.

QICK's first tutorials assume one (DAC -> ADC loopback). With ``qick_loopback=((gen, ro),)`` the chassis
cables generator ``gen`` to readout ``ro``: the generator no longer reaches the chip, the readout no longer
hears the resonator, and the readout captures the generator's own pulses, delayed by the DAC -> ADC path,
downconverted at the readout's frequency, with a little ADC noise. The delay and level are the ones
QICK's own demo 00 recorded on hardware (its saved loopback trace).
"""
# qick 0.2.370 annotates times and channels loosely and acquire() as returning None: its hints are wrong here.
# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportOptionalMemberAccess=false, reportOptionalSubscript=false, reportCallIssue=false, reportGeneralTypeIssues=false
from __future__ import annotations

import asyncio
import socket
import threading
import time

import numpy as np
import pytest

pytest.importorskip("qick")
pytest.importorskip("Pyro4")
from qick import QickConfig
from qick.asm_v2 import AveragerProgramV2

from qcss.chassis import Chassis, ChassisConfig
from qcss.config.loader import load_device, load_profile

GEN, RO, F = 1, 0, 250.0                 # generator 1 cabled to readout 0; tone and readout at 250 MHz
TOF_NS = 331.0                           # DAC -> ADC through a cable, as QICK demo 00's saved hardware trace shows it
FULL_SCALE = 1365.0                      # counts per decimated sample at gain 1 (same trace: ~125 at gain 0.0916)
SAMPLE_NS = 1e3 / 76.8                   # one decimated sample


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def board():
    chassis = Chassis(ChassisConfig(
        profile=load_profile("src/qcss/config/profiles/qick_zcu216_5q.yaml"),
        device=load_device("src/qcss/config/devices/transmon_5q.yaml"), lab_address=f"127.0.0.1:{_free_port()}",
        time_scale=0.0, seed=40, qick_ns=f"127.0.0.1:{_free_port()}", qick_start_ns=True,
        qick_loopback=((GEN, RO),)))
    loop = asyncio.new_event_loop()
    threading.Thread(target=loop.run_forever, daemon=True).start()
    asyncio.run_coroutine_threadsafe(chassis.start(), loop).result(60)
    soc = chassis.qick_soc
    yield soc, QickConfig(soc.get_cfg())
    asyncio.run_coroutine_threadsafe(chassis.stop(), loop).result(60)
    loop.call_soon_threadsafe(loop.stop)


class Loopback(AveragerProgramV2):
    def _initialize(self, cfg):
        self.declare_gen(ch=GEN, nqz=1)
        self.declare_readout(ch=RO, length=1.0, freq=F, gen_ch=GEN)
        self.add_pulse(ch=GEN, name="p", style="const", freq=F, phase=0, gain=cfg["gain"], length=0.3)

    def _body(self, cfg):
        self.trigger(ros=[RO], t=0)
        self.pulse(ch=GEN, name="p", t=0)


def test_the_raw_window_shows_the_pulse_after_the_cable_delay(board):
    soc, soccfg = board
    tr = Loopback(soccfg, reps=1, final_delay=1.0, cfg={"gain": 0.5}).acquire_decimated(soc, rounds=10,
                                                                                         progress=False)[0]
    mag = np.hypot(tr[:, 0], tr[:, 1])
    first = int(TOF_NS / SAMPLE_NS)                                   # last sample before the pulse arrives
    end = int((TOF_NS + 300) / SAMPLE_NS)                             # the pulse is 300 ns long
    on = mag[first + 2:end - 1]
    assert on.min() > 20 * max(mag[:first - 1].max(), 1.0)            # nothing comes back before the delay
    assert np.std(on) < 0.05 * on.mean()                              # a flat top: tone and readout match
    assert mag[end + 2:].max() < 0.05 * on.mean()                     # and nothing after the pulse ends
    assert on.mean() == pytest.approx(0.5 * FULL_SCALE, rel=0.1)       # a bench cable's level, not the ADC's range


def test_the_signal_grows_with_the_generators_gain(board):
    soc, soccfg = board
    a = [np.hypot(*Loopback(soccfg, reps=50, final_delay=1.0, cfg={"gain": g}).acquire(soc, progress=False)[0][0])
         for g in (0.2, 0.8)]
    assert a[1] / a[0] == pytest.approx(4.0, rel=0.05)


def test_a_cabled_round_needs_no_chip_simulation(board):
    soc, soccfg = board
    t0 = time.perf_counter()
    Loopback(soccfg, reps=2000, final_delay=1.0, cfg={"gain": 0.5}).acquire(soc, progress=False)
    assert time.perf_counter() - t0 < 30
    assert soc.get_tproc_counter(addr=1) == 2000
