"""The tProc v2 interpreter: run a program's instructions to the timed port outputs the board emits.

Two clocks, as in the ``qick_processor`` (TRM sections 3 and 5):

- the core executes one instruction per core cycle (``f_core``); time here is counted in cycles of the
  timing clock (``f_time``, the dispatcher's), so one instruction advances ``f_time / f_core`` of them;
- the dispatcher plays each port write at ``t_ref + @t`` on the timing clock, or as soon as it gets there
  when the core was late (``Event.late``): QICK queues a late output, it does not drop it.

``TIME inc_ref`` moves ``t_ref``; ``s11`` reads the user time ``t_abs - t_ref``. The ``WAIT ... time``
macro compiles to a busy loop (``TEST -op(s11 - #T)`` then ``JUMP back -if(S)``) that the interpreter
skips forward instead of spinning, so a long relaxation costs nothing. A shot ends when the program
writes the shot counter ``s12`` (``s_core_w1``, which ``get_tproc_counter(addr=1)`` reads); the program
ends at an unconditional jump to itself (qick's ``JUMP HERE``).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from qcss.boards.qick.tproc_v2 import Inst, decode

MASK = 0xFFFFFFFF
CDC_T_CYCLES = 3                 # core -> dispatcher crossing, timing-clock cycles (TRM 3.2: 2-3)
COUNTER_SREGS = {1: 12, 2: 13}   # get_tproc_counter addr -> s_core_w1 / s_core_w2


def _s32(v: int) -> int:
    v &= MASK
    return v - (1 << 32) if v >> 31 else v


@dataclass(frozen=True)
class Event:
    t: int                           # timing-clock cycle the output happens at
    kind: str                        # pulse, trig_set, trig_clr, dport
    port: int
    wave: tuple[int, ...] | None = None    # pulse: (freq, phase, env, gain, length, conf) register values
    value: int | None = None               # dport: the data written
    late: bool = False                     # the core reached the dispatcher after the scheduled time


@dataclass
class Trace:
    events: list[Event] = field(default_factory=list)
    shots: list[list[Event]] = field(default_factory=list)
    halted: bool = False
    sreg: list[int] = field(default_factory=lambda: [0] * 16)
    by_gen: bool = False                   # pulse ports are generator indices (v1), not tProc ports (v2)
    counters: dict[int, int] | None = None # v1: counter words in data memory, by address

    def counter(self, addr: int) -> int:
        if self.counters is not None:
            return self.counters.get(addr, 0)
        return self.sreg[COUNTER_SREGS[addr]]


class _Machine:
    def __init__(self, binprog: dict[str, Any], f_core: float, f_time: float) -> None:
        self.prog = decode(np.asarray(binprog["pmem"]))
        wmem = binprog.get("wmem")
        dmem = binprog.get("dmem")
        self.wmem = np.zeros((1024, 8), dtype=np.int64)
        if wmem is not None and len(wmem):
            w = np.asarray(wmem, dtype=np.int64)
            self.wmem[:len(w)] = w
        self.dmem = np.zeros(16384, dtype=np.int64)
        if dmem is not None and len(dmem):
            d = np.asarray(dmem, dtype=np.int64).ravel()
            self.dmem[:len(d)] = d
        self.s = [0] * 16
        self.r = [0] * 32
        self.w = [0] * 6
        self.z = self.neg = False
        self.stack: list[int] = []
        self.t_ref = 0
        self.core_t = 0.0                    # in timing-clock cycles
        self.step_t = f_time / f_core
        self.trace = Trace(sreg=self.s)
        self._shot: list[Event] = []

    # -- registers ---------------------------------------------------------------------------------------

    def get(self, name: str) -> int:
        kind, idx = name[0], int(name[1:])
        if kind == "s":
            if idx == 0:
                return 0
            if idx == 11:
                return _s32(math.floor(self.core_t) - self.t_ref)
            return self.s[idx]
        return (self.r if kind == "r" else self.w)[idx]

    def set(self, name: str, value: int) -> None:
        kind, idx = name[0], int(name[1:])
        value = _s32(value)
        if kind == "s":
            if idx in (0, 11):
                return                                   # s_zero and s_usr_time are read-only
            if idx == 12 and value > self.s[12]:         # the shot counter counts up: a shot has ended
                self.trace.shots.append(self._shot)
                self._shot = []
            self.s[idx] = value
        elif kind == "r":
            self.r[idx] = value
        else:
            self.w[idx] = value

    # -- ALU ---------------------------------------------------------------------------------------------

    def alu(self, i: Inst) -> int:
        a = self.get(i.src_a) if i.src_a else 0
        b = self.get(i.src_b) if i.src_b else (i.imm or 0)
        op = i.alu
        if op == "+":
            res = a + b
        elif op == "-":
            res = a - b
        elif op == "AND":
            res = a & b
        elif op == "OR":
            res = a | b
        elif op == "XOR":
            res = a ^ b
        elif op == "NOT":
            res = ~a
        elif op == "ASR":
            res = _s32(a) >> (b & 31)
        elif op == "SL":
            res = a << (b & 31)
        elif op == "SR":
            res = (a & MASK) >> (b & 31)
        elif op == "ABS":
            res = abs(_s32(self.get(i.src_b) if i.src_b else a))
        else:
            raise NotImplementedError(f"tProc ALU operation {op} is not emulated yet")
        return _s32(res)

    def flags(self, res: int) -> None:
        self.z, self.neg = res == 0, res < 0

    def cond(self, c: str) -> bool:
        return {"1": True, "0": False, "Z": self.z, "NZ": not self.z, "S": self.neg, "NS": not self.neg,
                "F": False, "NF": True}[c]               # the external flag is never raised here yet

    # -- memory addresses ----------------------------------------------------------------------------------

    def address(self, mem: tuple[str | None, str | int]) -> int:
        base, off = mem
        return (self.get(base) if base else 0) + (off if isinstance(off, int) else self.get(off))

    # -- outputs -------------------------------------------------------------------------------------------

    def emit(self, kind: str, i: Inst, **kw: Any) -> None:
        scheduled = self.t_ref + (i.time if i.time is not None else self.s[14])
        arrives = math.ceil(self.core_t) + CDC_T_CYCLES
        ev = Event(max(scheduled, arrives), kind, i.port or 0, late=arrives > scheduled, **kw)
        self.trace.events.append(ev)
        self._shot.append(ev)

    # -- execution -----------------------------------------------------------------------------------------

    def run(self, max_steps: int) -> Trace:
        pc, steps, prog = 0, 0, self.prog
        while steps < max_steps:
            if pc >= len(prog):
                break
            i = prog[pc]
            steps += 1
            self.core_t += self.step_t
            nxt = pc + 1
            k = i.kind
            if k == "NOP":
                pass
            elif k == "TEST":
                if self.cond(i.cond):
                    res = self.alu(i)
                    self.flags(res)
                    if i.wr:
                        self.set(i.wr[0], res if i.wr[1] == "op" else (i.imm or 0))
            elif k in ("JUMP", "CALL", "RET"):
                if k == "JUMP" and i.target == pc and i.cond == "1" and i.wr is None:
                    self.trace.halted = True                 # JUMP HERE: the program's end
                    break
                if self.cond(i.cond):
                    if i.alu is not None and i.wr:
                        res = self.alu(i)
                        self.set(i.wr[0], res if i.wr[1] == "op" else (i.imm or 0))
                    if k == "RET":
                        nxt = self.stack.pop()
                    else:
                        if k == "CALL":
                            self.stack.append(pc + 1)
                        nxt = i.target if i.target is not None else self.s[15]
                        self._skip_wait(i, pc)
            elif k == "REG_WR":
                if i.src == "wmem":
                    assert i.mem is not None
                    self.w = [int(x) for x in self.wmem[self.address(i.mem)][:6]]
                elif self.cond(i.cond):
                    if i.src == "op":
                        res = self.alu(i)
                        if i.uf:
                            self.flags(res)
                    elif i.src == "imm":
                        res = i.imm or 0
                    else:
                        assert i.mem is not None
                        res = int(self.dmem[self.address(i.mem)])
                    assert i.dst is not None
                    self.set(i.dst, res)
            elif k == "WMEM_WR":
                assert i.mem is not None
                self.wmem[self.address(i.mem), :6] = self.w
            elif k == "DMEM_WR":
                if self.cond(i.cond):
                    assert i.mem is not None
                    self.dmem[self.address(i.mem)] = (i.imm or 0) if i.src == "imm" else self.alu(i)
            elif k == "WPORT_WR":
                wave = tuple(self.w) if i.src == "r_wave" else tuple(int(x) for x in self.wmem[i.wmem_addr or 0][:6])
                self.emit("pulse", i, wave=wave)
            elif k == "TRIG":
                self.emit("trig_set" if i.ctrl_op == "set" else "trig_clr", i)
            elif k == "DPORT_WR":
                self.emit("dport", i, value=i.imm if i.src == "imm" else self.get(i.src_a or "s0"))
            elif k == "TIME":
                v = i.imm if i.src_a is None else self.get(i.src_a)
                if i.ctrl_op == "inc_ref":
                    self.t_ref += v or 0
                elif i.ctrl_op == "set_ref":
                    self.t_ref = v or 0
                elif i.ctrl_op == "updt":
                    self.core_t += v or 0
                else:
                    self.t_ref, self.core_t = 0, 0.0
            else:
                raise NotImplementedError(f"tProc instruction {k} is not emulated yet")
            pc = nxt
        if self._shot:
            self.trace.shots.append(self._shot)
        return self.trace

    def _skip_wait(self, jump: Inst, pc: int) -> None:
        """The WAIT-time busy loop, TEST -op(s11 - #T) then JUMP to it -if(S): jump straight to its end."""
        if jump.cond != "S" or jump.target != pc - 1:
            return
        test = self.prog[pc - 1]
        if test.kind == "TEST" and test.src_a == "s11" and test.alu == "-" and test.src_b is None:
            self.core_t = max(self.core_t, float(self.t_ref + (test.imm or 0)))


def run(binprog: dict[str, Any], f_core: float = 200.0, f_time: float = 430.08,
        max_steps: int = 200_000_000) -> Trace:
    """Run one round of a compiled tProc v2 program from reset; ``max_steps`` bounds a program that never ends."""
    return _Machine(binprog, f_core, f_time).run(max_steps)
