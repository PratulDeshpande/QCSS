"""The tProc v1 (``axis_tproc64x32_x8``): decode its 64-bit words and run them to the board's outputs.

Word layout (qick ``asm_v1.QickProgram.instructions``): the opcode in bits 56-63, then fields at fixed
bit positions: register page (3 bits at 53), output channel (3 at 50), ALU/condition code (4 at 46),
registers (5 bits at 41, 36, 31, 26, 21, 16, 11) and a 31-bit immediate, time, address or label at 0.
Registers are eight pages of 32 words; register 0 of every page reads zero.

Running a program (``run``) follows tprocv1.rst: the core executes about one instruction per timing
cycle while a reference time ``t_ref`` (moved by ``synci``/``sync``) places every output at
``t_ref + t``; ``waiti`` stalls the core until the master clock gets there. Channel 0 is the trigger
register (``axis_set_reg``): ``seti 0`` writes its bits, and each bit that rises or falls is an
``Event`` (``bit_set``/``bit_clr``, port = the bit). Channels 1-7 drive generators; ``set`` hands one its
five registers (freq, phase, addr, gain, mode), and the generator behind a tProc mux is named by the mode
register's top byte. Pulses come out with ``port`` = the generator's index and its registers in the v2
layout (freq, phase, env, gain, length, conf), so the same generator models read both. A shot ends where
the program writes a larger count to the counter's data-memory word (qick's ``COUNTER_ADDR``, 1).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from qcss.boards.qick.tproc_v2_run import Event, Trace

MASK = 0xFFFFFFFF
COUNTER_ADDR = 1

# name -> (opcode, type, ((arg index, bit position), ...)), as qick 0.2.370's asm_v1 encodes them
_TABLE: dict[str, tuple[int, str, tuple[tuple[int, int], ...]]] = {
    "pushi": (0b00010000, "I", ((0, 53), (1, 41), (2, 36), (3, 0))),
    "popi": (0b00010001, "I", ((0, 53), (1, 41))),
    "mathi": (0b00010010, "I", ((0, 53), (1, 41), (2, 36), (3, 46), (4, 0))),
    "seti": (0b00010011, "I", ((1, 53), (0, 50), (2, 36), (3, 0))),
    "synci": (0b00010100, "I", ((0, 0),)),
    "waiti": (0b00010101, "I", ((0, 50), (1, 0))),
    "bitwi": (0b00010110, "I", ((0, 53), (3, 46), (1, 41), (2, 36), (4, 0))),
    "memri": (0b00010111, "I", ((0, 53), (1, 41), (2, 0))),
    "memwi": (0b00011000, "I", ((0, 53), (1, 31), (2, 0))),
    "regwi": (0b00011001, "I", ((0, 53), (1, 41), (2, 0))),
    "setbi": (0b00011010, "I", ((0, 53), (1, 41), (2, 0))),
    "loopnz": (0b00110000, "J1", ((0, 53), (1, 41), (2, 0))),
    "end": (0b00111111, "J1", ()),
    "condj": (0b00110001, "J2", ((0, 53), (2, 46), (1, 36), (3, 31), (4, 0))),
    "math": (0b01010000, "R", ((0, 53), (3, 46), (1, 41), (2, 36), (4, 31))),
    "set": (0b01010001, "R", ((1, 53), (0, 50), (2, 36), (7, 31), (3, 26), (4, 21), (5, 16), (6, 11))),
    "sync": (0b01010010, "R", ((0, 53), (1, 31))),
    "read": (0b01010011, "R", ((1, 53), (0, 50), (2, 46), (3, 41))),
    "wait": (0b01010100, "R", ((1, 53), (0, 50), (2, 31))),
    "bitw": (0b01010101, "R", ((0, 53), (1, 41), (2, 36), (3, 46), (4, 31))),
    "memr": (0b01010110, "R", ((0, 53), (1, 41), (2, 36))),
    "memw": (0b01010111, "R", ((0, 53), (2, 36), (1, 31))),
    "setb": (0b01011000, "R", ((0, 53), (2, 36), (1, 31))),
}
_BY_CODE = {v[0]: k for k, v in _TABLE.items()}
_WIDTH = {53: 3, 50: 3, 46: 4, 0: 31}                     # every other position holds a 5-bit register
# the op field's meaning depends on the instruction family
_MATH = {0b1000: "+", 0b1001: "-", 0b1010: "*"}
_COND = {0b0000: ">", 0b0001: ">=", 0b0010: "<", 0b0011: "<=", 0b0100: "==", 0b0101: "!="}
_BITW = {0b0000: "&", 0b0001: "|", 0b0010: "^", 0b0011: "~", 0b0100: "<<", 0b0101: ">>"}
_READ = {0b1010: "upper", 0b0101: "lower"}
_OP_ARG = {"mathi": (3, _MATH), "math": (3, _MATH), "bitwi": (3, _BITW), "bitw": (3, _BITW),
           "condj": (2, _COND), "read": (2, _READ)}
_LABEL_ARG = {"loopnz": 2, "condj": 4}


@dataclass(frozen=True)
class Inst1:
    name: str
    args: tuple[int, ...]             # in qick's argument order; ops as codes, labels as addresses


def decode(words: Sequence[int] | np.ndarray) -> list[Inst1]:
    out = []
    for w in np.asarray(words, dtype=np.uint64).tolist():
        w = int(w)
        name = _BY_CODE.get(w >> 56)
        if name is None:
            raise ValueError(f"unknown tProc v1 opcode {w >> 56:#010b}")
        fields = _TABLE[name][2]
        n = max((i for i, _ in fields), default=-1) + 1
        args = [0] * n
        for i, pos in fields:
            args[i] = (w >> pos) & ((1 << _WIDTH.get(pos, 5)) - 1)
        out.append(Inst1(name, tuple(args)))
    return out


def to_qick(inst: Inst1) -> dict[str, Any]:
    """The instruction as qick's assembler takes it (``compile_instruction``): ops as text, labels ``L<n>``."""
    args: list[Any] = list(inst.args)
    if inst.name in _OP_ARG:
        k, table = _OP_ARG[inst.name]
        args[k] = table[args[k]]
    if inst.name in _LABEL_ARG:
        args[_LABEL_ARG[inst.name]] = f"L{args[_LABEL_ARG[inst.name]]}"
    return {"name": inst.name, "args": args}


def _s32(v: int) -> int:
    v &= MASK
    return v - (1 << 32) if v >> 31 else v


def _sext31(v: int) -> int:
    return v - (1 << 31) if v >> 30 else v


def _v2_wave(gen: dict[str, Any], regs: tuple[int, ...]) -> tuple[int, ...]:
    """A v1 ``set``'s five registers in the v2 wave layout (freq, phase, env, gain, length, conf)."""
    ra, rb, rc, rd, re = regs
    if gen["type"].startswith("axis_sg_mux"):
        return (0, 0, 0, 0, ra, rb & 0xFF)                # length, then the tone mask
    mc = (re >> 16) & 0xFF                                # v1: phrst<<3 | periodic<<2 | outsel
    conf = (mc & 0b11) | (mc >> 2 & 1) << 2 | (mc >> 3 & 1) << 4
    return (ra, rb, rc, _s32(rd), re & 0xFFFF, conf)


class _Machine:
    def __init__(self, words: Sequence[int] | np.ndarray, gens: Sequence[dict[str, Any]],
                 dmem: Sequence[int] | None = None) -> None:
        self.prog = decode(words)
        self.r = [[0] * 32 for _ in range(8)]
        self.dmem = [0] * 4096
        if dmem is not None:
            for i, v in enumerate(dmem):
                self.dmem[i] = int(v)
        self.stack: list[int] = []
        self.t_ref = 0
        self.core_t = 0
        self.out0 = 0                                     # the trigger register's current bits
        self.slots: dict[tuple[int, int | None], int] = {}
        for i, g in enumerate(gens):
            self.slots[(int(g["tproc_ch"]), g.get("tmux_ch"))] = i
        self.gens = list(gens)
        self.trace = Trace(by_gen=True, counters={COUNTER_ADDR: 0})
        self._shot: list[Event] = []

    def get(self, p: int, i: int) -> int:
        return 0 if i == 0 else self.r[p][i]

    def put(self, p: int, i: int, v: int) -> None:
        if i:
            self.r[p][i] = _s32(v)

    def mem_write(self, addr: int, v: int) -> None:
        v = _s32(v)
        if addr == COUNTER_ADDR and v > self.dmem[addr]:      # the shot counter counts up: a shot has ended
            self.trace.shots.append(self._shot)
            self._shot = []
            assert self.trace.counters is not None
            self.trace.counters[COUNTER_ADDR] = v
        self.dmem[addr] = v

    def emit(self, ev: Event) -> None:
        self.trace.events.append(ev)
        self._shot.append(ev)

    def at(self, t_rel: int) -> tuple[int, bool]:
        scheduled = self.t_ref + t_rel
        return max(scheduled, self.core_t), self.core_t > scheduled

    @staticmethod
    def math(op: int, a: int, b: int) -> int:
        return {0b1000: a + b, 0b1001: a - b, 0b1010: a * b}[op]

    @staticmethod
    def bitw(op: int, a: int, b: int) -> int:
        if op == 0b0011:
            return ~b
        return {0b0000: a & b, 0b0001: a | b, 0b0010: a ^ b, 0b0100: a << (b & 31),
                0b0101: (a & MASK) >> (b & 31)}[op]

    def run(self, max_steps: int) -> Trace:
        pc, steps = 0, 0
        prog = self.prog
        while steps < max_steps and pc < len(prog):
            i = prog[pc]
            a = i.args
            steps += 1
            self.core_t += 1
            nxt = pc + 1
            n = i.name
            if n == "regwi":
                self.put(a[0], a[1], _sext31(a[2]))
            elif n == "mathi":
                self.put(a[0], a[1], self.math(a[3], self.get(a[0], a[2]), _sext31(a[4])))
            elif n == "math":
                self.put(a[0], a[1], self.math(a[3], self.get(a[0], a[2]), self.get(a[0], a[4])))
            elif n == "bitwi":
                self.put(a[0], a[1], self.bitw(a[3], self.get(a[0], a[2]), _sext31(a[4])))
            elif n == "bitw":
                self.put(a[0], a[1], self.bitw(a[3], self.get(a[0], a[2]), self.get(a[0], a[4])))
            elif n == "memri":
                self.put(a[0], a[1], self.dmem[a[2] % len(self.dmem)])
            elif n == "memwi":
                self.mem_write(a[2] % len(self.dmem), self.get(a[0], a[1]))
            elif n == "memr":
                self.put(a[0], a[1], self.dmem[self.get(a[0], a[2]) % len(self.dmem)])
            elif n == "memw":
                self.mem_write(self.get(a[0], a[2]) % len(self.dmem), self.get(a[0], a[1]))
            elif n == "loopnz":
                v = self.get(a[0], a[1])
                if v != 0:
                    self.put(a[0], a[1], v - 1)
                    nxt = a[2]
            elif n == "condj":
                x, y = self.get(a[0], a[1]), self.get(a[0], a[3])
                if {0: x > y, 1: x >= y, 2: x < y, 3: x <= y, 4: x == y, 5: x != y}[a[2]]:
                    nxt = a[4]
            elif n == "end":
                self.trace.halted = True
                break
            elif n == "synci":
                self.t_ref += _sext31(a[0])
            elif n == "sync":
                self.t_ref += self.get(a[0], a[1])
            elif n == "waiti":
                self.core_t = max(self.core_t, self.t_ref + _sext31(a[1]))
            elif n == "wait":
                self.core_t = max(self.core_t, self.t_ref + self.get(a[1], a[2]))
            elif n == "seti":
                self.output(a[0], self.get(a[1], a[2]), _sext31(a[3]))
            elif n == "set":
                regs = tuple(self.get(a[1], x) for x in a[2:7])
                t, late = self.at(self.get(a[1], a[7]))
                tmux = (regs[4] >> 24) & 0xFF
                g = self.slots.get((a[0], tmux), self.slots.get((a[0], None)))
                if g is not None:
                    self.emit(Event(t, "pulse", g, wave=_v2_wave(self.gens[g], regs), late=late))
            elif n == "pushi":
                self.stack.append(self.get(a[0], a[2]))
                self.put(a[0], a[1], _sext31(a[3]))
            elif n == "popi":
                self.put(a[0], a[1], self.stack.pop() if self.stack else 0)
            else:
                raise NotImplementedError(f"tProc v1 instruction {n} is not emulated yet")
            pc = nxt
        if self._shot:
            self.trace.shots.append(self._shot)
        return self.trace

    def output(self, ch: int, value: int, t_rel: int) -> None:
        if ch != 0:
            return                                         # data to a generator without a pulse: no output
        t, late = self.at(t_rel)
        value &= 0xFFFF
        for bit in range(16):
            was, now = self.out0 >> bit & 1, value >> bit & 1
            if now and not was:
                self.emit(Event(t, "bit_set", bit, late=late))
            elif was and not now:
                self.emit(Event(t, "bit_clr", bit, late=late))
        self.out0 = value


def run(words: Sequence[int] | np.ndarray, gens: Sequence[dict[str, Any]], dmem: Sequence[int] | None = None,
        max_steps: int = 200_000_000) -> Trace:
    """Run a compiled v1 program from reset; ``gens`` is the firmware's generator list (``cfg["gens"]``)."""
    return _Machine(words, gens, dmem).run(max_steps)

