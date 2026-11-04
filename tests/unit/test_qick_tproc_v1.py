"""The tProc v1 decoder and interpreter: qick's own v1 assembler is the oracle.

Every 64-bit word a v1 program compiles to is decoded, turned back into qick's assembly form and
re-encoded by qick's ``compile_instruction``: a field the decoder misreads cannot survive the round
trip. The interpreter then runs the averager programs to the outputs a board emits.
"""
# pyright: reportArgumentType=false, reportAttributeAccessIssue=false, reportCallIssue=false
from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("qick")
from qick import QickConfig
from qick.averager_program import AveragerProgram, RAveragerProgram

from qcss.boards.qick.firmware import description
from qcss.boards.qick.tproc_v1 import decode, run, to_qick

SOCCFG = QickConfig(description("zcu216_v1_5q"))
MUX, RO = 10, 7150.0
QUBITS = range(5)


def _readout(prog, gain=0.3):
    prog.declare_gen(ch=MUX, nqz=2, ro_ch=0, mux_freqs=[RO], mux_gains=[gain])
    prog.declare_readout(ch=0, length=prog.us2cycles(1.0, ro_ch=0), freq=RO, gen_ch=MUX)
    prog.set_pulse_registers(ch=MUX, style="const", length=prog.us2cycles(1.0, gen_ch=MUX), mask=[0])


class Measure(AveragerProgram):
    def initialize(self):
        _readout(self)
        self.declare_gen(ch=0, nqz=2)
        self.set_pulse_registers(ch=0, style="const", freq=self.freq2reg(4500, gen_ch=0), phase=0, gain=1000,
                                 length=self.us2cycles(0.05, gen_ch=0))
        self.declare_gen(ch=6, nqz=1)                  # a flux line, behind the tProc mux
        self.set_pulse_registers(ch=6, style="const", freq=0, phase=0, gain=-2000, length=self.us2cycles(0.1, gen_ch=6))
        self.synci(200)

    def body(self):
        self.pulse(ch=0, t=0)
        self.pulse(ch=6, t=0)
        self.sync_all(self.us2cycles(0.05))
        self.measure(pulse_ch=MUX, adcs=[0], adc_trig_offset=50, wait=True, syncdelay=self.us2cycles(5))


class Rabi(RAveragerProgram):
    def initialize(self):
        _readout(self)
        self.declare_gen(ch=0, nqz=2)
        self.set_pulse_registers(ch=0, style="const", freq=self.freq2reg(4500, gen_ch=0), phase=0,
                                 gain=self.cfg["start"], length=self.us2cycles(0.05, gen_ch=0))
        self.q_rp, self.r_gain = self.ch_page(0), self.sreg(0, "gain")
        self.synci(200)

    def body(self):
        self.pulse(ch=0, t=0)
        self.sync_all(self.us2cycles(0.05))
        self.measure(pulse_ch=MUX, adcs=[0], adc_trig_offset=50, wait=True, syncdelay=self.us2cycles(5))

    def update(self):
        self.mathi(self.q_rp, self.r_gain, self.r_gain, "+", self.cfg["step"])


def _rabi(reps=3, expts=5):
    return Rabi(SOCCFG, {"reps": reps, "expts": expts, "start": 0, "step": 2000})


@pytest.mark.parametrize("prog", [Measure(SOCCFG, {"reps": 3}), _rabi()], ids=["averager", "raverager"])
def test_every_word_survives_the_round_trip_through_qicks_assembler(prog):
    prog.compile()
    words = [int(w) for w in prog.binprog]
    insts = decode(np.asarray(prog.binprog, dtype=np.uint64))
    labels = {f"L{i}": i for i in range(len(words))}
    again = [prog.compile_instruction(to_qick(i), labels) for i in insts]
    assert again == words


def test_a_v1_averager_counts_every_shot_and_triggers_the_readout_each_time():
    prog = Measure(SOCCFG, {"reps": 3})
    prog.compile()
    tr = run(np.asarray(prog.binprog, dtype=np.uint64), SOCCFG["gens"])
    assert tr.halted and tr.counter(1) == 3 and len(tr.shots) == 3
    for shot in tr.shots:
        kinds = [(e.kind, e.port) for e in shot]
        assert ("pulse", 0) in kinds and ("pulse", 6) in kinds and ("pulse", MUX) in kinds   # by generator
        assert ("bit_set", 8) in kinds and ("bit_clr", 8) in kinds                         # readout 0's bit
        t = {k: e.t for e in shot for k in [(e.kind, e.port)]}
        assert t[("pulse", 0)] < t[("pulse", MUX)] < t[("bit_set", 8)]


def test_a_pulse_reads_back_in_the_v2_register_layout():
    prog = Measure(SOCCFG, {"reps": 1})
    prog.compile()
    tr = run(np.asarray(prog.binprog, dtype=np.uint64), SOCCFG["gens"])
    drive = next(e for e in tr.events if (e.kind, e.port) == ("pulse", 0))
    flux = next(e for e in tr.events if (e.kind, e.port) == ("pulse", 6))
    mux = next(e for e in tr.events if (e.kind, e.port) == ("pulse", MUX))
    assert drive.wave is not None and flux.wave is not None and mux.wave is not None
    assert drive.wave[0] & 0xFFFFFFFF == SOCCFG.freq2reg(4500, gen_ch=0) and drive.wave[3] == 1000
    assert drive.wave[4] == SOCCFG.us2cycles(0.05, gen_ch=0) and drive.wave[5] & 0b11 == 1   # outsel dds
    assert flux.wave[3] == -2000
    assert mux.wave[5] & 0xFF == 0b1 and mux.wave[4] == SOCCFG.us2cycles(1.0, gen_ch=MUX)


def test_a_raverager_sweeps_its_register_once_per_experiment():
    tr = run(np.asarray((p := _rabi()).compile() or p.binprog, dtype=np.uint64), SOCCFG["gens"])
    assert tr.counter(1) == 15 and len(tr.shots) == 15
    gains = [e.wave[3] for s in tr.shots for e in s if (e.kind, e.port) == ("pulse", 0) and e.wave]
    assert gains == [g for g in range(0, 10000, 2000) for _ in range(3)]       # expts outer, reps inner
    starts = [s[0].t for s in tr.shots]
    assert len(set(np.diff(starts))) == 1                                        # shots at a fixed period
