"""The tProc v2 decoder: QICK's own assembler is the oracle.

Every program a client compiles reaches the board as 72-bit words. The decoder's disassembly, fed back
through qick's tprocv2 assembler, must reproduce those words bit for bit: a field the decoder misreads
cannot survive the round trip.
"""
# qick 0.2.370 annotates v2 times as int (they are float microseconds) and leaves
# Assembler.str_asm2bin without @staticmethod: its hints, not these calls, are wrong.
# pyright: reportArgumentType=false, reportAttributeAccessIssue=false
from __future__ import annotations

import numpy as np
import pytest

qick = pytest.importorskip("qick")
from qick import QickConfig
from qick.asm_v2 import AveragerProgramV2, QickSweep1D
from qick.tprocv2_assembler import Assembler

from qcss.boards.qick.firmware import description
from qcss.boards.qick.tproc_v2 import decode, disassemble

SOCCFG = QickConfig(description("zcu216_v2_5q"))
RO, MUX = 7150.0, 10


def _assemble(asm: str) -> np.ndarray:
    return np.array(Assembler.str_asm2bin(asm)[1], dtype=np.int64).astype(np.int32)


def _base(prog):
    prog.declare_gen(ch=0, nqz=2)
    prog.declare_gen(ch=MUX, nqz=2, ro_ch=0, mux_freqs=[RO], mux_gains=[0.3])
    prog.declare_readout(ch=0, length=1.0, freq=RO, gen_ch=MUX)
    prog.add_pulse(ch=MUX, name="probe", style="const", length=1.0, mask=[0])


class Rabi(AveragerProgramV2):
    def _initialize(self, cfg):
        _base(self)
        self.add_loop("amp", 5)
        self.add_pulse(ch=0, name="pi", style="const", freq=4500, phase=0, length=0.05,
                       gain=QickSweep1D("amp", 0, 1))

    def _body(self, cfg):
        self.pulse(ch=0, name="pi", t=0)
        self.delay_auto(0.01)
        self.pulse(ch=MUX, name="probe", t=0)
        self.trigger(ros=[0], pins=[0], t=0.05)
        self.wait_auto()
        self.delay_auto(5.0)


class Ramsey(AveragerProgramV2):
    def _initialize(self, cfg):
        _base(self)
        self.add_loop("wait", 4)
        self.add_pulse(ch=0, name="x90", style="const", freq=4500, length=0.02, gain=0.5,
                       phase=QickSweep1D("wait", 0, 270))

    def _body(self, cfg):
        self.pulse(ch=0, name="x90", t=0)
        self.delay(QickSweep1D("wait", 0.1, 2.0))                # a swept, register-timed delay
        self.pulse(ch=0, name="x90", t=0)
        self.delay_auto(0.01)
        self.pulse(ch=MUX, name="probe", t=0)
        self.trigger(ros=[0], t=0.05)
        self.wait_auto()
        self.delay_auto(5.0)


class ActiveReset(AveragerProgramV2):
    def _initialize(self, cfg):
        _base(self)
        self.add_pulse(ch=0, name="pi", style="const", freq=4500, phase=0, length=0.05, gain=1.0)

    def _body(self, cfg):
        self.pulse(ch=MUX, name="probe", t=0)
        self.trigger(ros=[0], t=0.05)
        self.wait_auto()
        self.read_and_jump(ro_ch=0, component="I", threshold=1000, test="<", label="skip")
        self.pulse(ch=0, name="pi", t=0)
        self.label("skip")
        self.write_dmem(addr=5, src=1)
        self.read_dmem(dst="r5", addr=5)
        self.delay_auto(5.0)


@pytest.mark.parametrize("program", [Rabi, Ramsey, ActiveReset], ids=lambda p: p.__name__)
def test_a_compiled_program_survives_the_round_trip_through_qicks_assembler(program):
    pmem = np.asarray(program(SOCCFG, reps=3, final_delay=1.0, cfg={}).binprog["pmem"], dtype=np.int64).astype(np.int32)
    np.testing.assert_array_equal(_assemble(disassemble(pmem)), pmem)


HAND_WRITTEN = """
start:
REG_WR s12 imm #0
TIME #430 inc_ref
WPORT_WR p0 wmem [&0] @0
TRIG p10 set @22
TRIG p10 clr @32
REG_WR r2 op -op(s8 - #100)
REG_WR r3 op -op(r1 + r2)
REG_WR r5 op -op(r1 ASR #2)
REG_WR w3 op -op(w3 + #8191)
REG_WR r_wave wmem [&0]
DMEM_WR [&3] imm #7
REG_WR r4 dmem [&3]
DPORT_RD p0
DPORT_WR p1 imm 5
DIV r1 #3
ARITH T r1 r2
FLAG set
TEST -op(r1 - #4)
JUMP start -if(NZ) -wr(r1 op) -op(r1 + #1)
CALL sub
JUMP s15
sub:
RET
"""


def test_hand_written_assembly_of_every_instruction_class_survives_the_round_trip():
    words = _assemble(HAND_WRITTEN)
    np.testing.assert_array_equal(_assemble(disassemble(words)), words)


def test_decode_reads_the_fields_the_interpreter_needs():
    words = _assemble("TIME #430 inc_ref\nWPORT_WR p10 wmem [&1] @22\nREG_WR s12 op -op(s12 + #1)\n")
    nop, time, wport, inc = decode(words)
    assert nop.kind == "NOP"
    assert (time.kind, time.ctrl_op, time.imm) == ("TIME", "inc_ref", 430)
    assert (wport.kind, wport.port, wport.wmem_addr, wport.time) == ("WPORT_WR", 10, 1, 22)
    assert (inc.kind, inc.dst, inc.alu, inc.src_a, inc.imm) == ("REG_WR", "s12", "+", "s12", 1)


def test_a_word_no_assembler_produces_is_refused():
    with pytest.raises(ValueError, match="opcode"):
        decode(np.array([[0, 0, 0b11100000, 0, 0, 0, 0, 0]], dtype=np.int32))   # opcode 111
