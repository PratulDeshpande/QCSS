"""The QICK tProc v2 (``qick_processor``) instruction set: decode the words a client uploads.

A QICK v2 program reaches the board as program memory: one row of eight int32 per 72-bit instruction,
``[bits 40-71, bits 8-39, bits 0-7, 0, 0, 0, 0, 0]`` (bit 0 most significant), as qick's
``tprocv2_assembler.Assembler.list2bin`` packs it. Every instruction shares one layout::

    op[0:3] AI[3] DF[4:6] C[6:9] CFG[9:16] ADDR[16:33]=A0(11)+A1(6) DATA[33:65] RD[65:72]

- ``op``: 000 config/NOP/TEST, 001 branch, 010/011 control, 100 register write, 101 memory write, 110 port;
- ``DF``: the data format. 11 is a 32-bit immediate, 01 is two source registers and a 16-bit immediate,
  10 is one source register and a 24-bit immediate;
- ``C``: the condition, or for wave and port writes the flags ``Ww Sp Wp``.

``decode`` turns the words into ``Inst`` records the interpreter executes. ``disassemble`` renders them as
QICK assembly, the oracle of the tests: qick's own assembler must turn the text back into the same words.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

COND = {0: "1", 1: "Z", 2: "S", 3: "NZ", 4: "NS", 5: "F", 6: "NF", 7: "0"}
ALU4 = {0b0000: "+", 0b0010: "-", 0b0100: "AND", 0b0110: "ASR", 0b1000: "ABS", 0b1010: "MSH", 0b1100: "LSH",
        0b1110: "SWP", 0b0001: "NOT", 0b0011: "OR", 0b0101: "XOR", 0b0111: "CAT", 0b1001: "RFU", 0b1011: "PAR",
        0b1101: "SL", 0b1111: "SR"}
ALU2 = {0: "+", 1: "-", 2: "AND", 3: "ASR"}
UNARY = {"ABS", "MSH", "LSH", "SWP", "PAR", "NOT"}
ARITH = {0: "T", 1: "TP", 2: "TM", 3: "PT", 4: "PTP", 5: "PTM", 6: "MT", 7: "MTP", 8: "MTM"}
_ARITH_ARGS = {"T": "AB", "TP": "ABC", "TM": "ABC", "PT": "DAB", "MT": "DAB", "PTP": "DABC", "PTM": "DABC",
               "MTP": "DABC", "MTM": "DABC"}
TIME_OPS = {0b0001: "rst", 0b0010: "updt", 0b0100: "set_ref", 0b1000: "inc_ref"}
FLAG_OPS = {0b0001: "set", 0b0010: "clr", 0b0100: "inv"}
_REG = "srw"                     # register file by type code: 00 special, 01 data, 10 wave


def _signed(v: int, bits: int) -> int:
    return v - (1 << bits) if v >> (bits - 1) else v


def _reg7(code: int) -> str:
    """A 7-bit register code (2-bit type, 5-bit index): s0..s31, r0..r31, w0..w5."""
    return f"{_REG[code >> 5]}{code & 31}"


def _reg_src(code: int) -> str:
    """An 8-bit source-register code (a leading 0, then a 7-bit register code)."""
    return _reg7(code & 0x7F)


def _reg_addr(code: int) -> str:
    """A 6-bit address-register code: 0 then an sreg index, 1 then a dreg index."""
    return f"{'r' if code >> 5 else 's'}{code & 31}"


@dataclass(frozen=True)
class Inst:
    """One decoded instruction. Fields not used by its ``kind`` keep their defaults."""
    addr: int
    kind: str                                    # NOP TEST REG_WR DMEM_WR WMEM_WR WPORT_WR DPORT_WR DPORT_RD
    #                                              TRIG JUMP CALL RET TIME FLAG DIV ARITH
    word: int                                    # the 72-bit instruction
    cond: str = "1"                              # -if(): "1" always
    uf: bool = False                             # -uf: update the ALU flags
    dst: str | None = None                       # register written (REG_WR) or None
    src: str | None = None                       # REG_WR source: op, imm, dmem, wmem
    alu: str | None = None                       # -op() operator ("+" for a copy)
    src_a: str | None = None                     # -op() first operand (a register)
    src_b: str | None = None                     # -op() second operand register, if any
    imm: int | None = None                       # immediate operand / literal / time value
    wr: tuple[str, str] | None = None            # -wr(reg op|imm)
    mem: tuple[str | None, str | int] | None = None   # [base + offset]: (base reg or None, reg or literal)
    port: int | None = None                      # p<N>
    wmem_addr: int | None = None                 # WPORT_WR/REG_WR wmem [&N] when literal
    time: int | None = None                      # @t (WPORT_WR, TRIG, DPORT_WR, WMEM_WR)
    target: int | None = None                    # JUMP/CALL literal target address (None: s15)
    ctrl_op: str | None = None                   # TIME/FLAG operation, TRIG set/clr, ARITH operation
    regs: tuple[str, ...] = field(default=())    # ARITH operands, DIV numerator/denominator

    def asm(self, labels: dict[int, str]) -> str:
        return _render(self, labels)


class _Bits:
    def __init__(self, word: int) -> None:
        self.w = word

    def __getitem__(self, s: slice | int) -> int:
        """Bits [a:b] (or the single bit a) of the word, bit 0 being the most significant."""
        a, b = (s, s + 1) if isinstance(s, int) else (s.start, s.stop)
        return (self.w >> (72 - b)) & ((1 << (b - a)) - 1)


def _word(row: np.ndarray) -> int:
    n0, n1, n2 = (int(x) & 0xFFFFFFFF for x in row[:3])
    if n2 >> 8 or any(int(x) for x in row[3:]):
        raise ValueError(f"not a tProc v2 instruction row: {list(row)}")
    return (n2 << 64) | (n1 << 32) | n0


def _operand(b: _Bits, alu4: bool) -> tuple[str, str | None, str | None, int | None]:
    """The -op() of an instruction: (operator, first register, second register, immediate)."""
    df = b[4:6]
    alu_code = b[12:16] if alu4 else b[14:16]
    alu = (ALU4 if alu4 else ALU2)[alu_code]
    if df == 0b01:
        return alu, _reg_src(b[33:41]), _reg_src(b[41:49]), _signed(b[49:65], 16)
    if df == 0b10:
        return alu, _reg_src(b[33:41]), None, _signed(b[41:65], 24)
    return alu, None, None, _signed(b[33:65], 32)


def _mem(b: _Bits) -> tuple[str | None, str | int]:
    a0, a1 = b[16:27], b[27:33]
    off: str | int = a0 if b[3] else _reg_addr(a0 & 0x3F)
    return (_reg_addr(a1) if a1 else None), off


def _wr(b: _Bits) -> tuple[str, str] | None:
    return (_reg7(b[65:72]), "imm" if b[13] else "op") if b[12] else None


def decode_word(addr: int, word: int) -> Inst:
    b = _Bits(word)
    op, cond, cfg = b[0:3], COND[b[6:9]], b[9:16]
    if op == 0b000:
        if word == 0:
            return Inst(addr, "NOP", word)
        alu, a, bb, imm = _operand(b, alu4=False)
        return Inst(addr, "TEST", word, cond=cond, uf=bool(b[11]), alu=alu, src_a=a, src_b=bb, imm=imm, wr=_wr(b))
    if op == 0b001:
        kind = {0b00: "JUMP", 0b10: "CALL", 0b11: "RET"}[b[9:11]]
        alu, a, bb, imm = _operand(b, alu4=False)
        has_op = b[4:6] != 0b11 or imm != 0
        return Inst(addr, kind, word, cond=cond, uf=bool(b[11]), wr=_wr(b),
                    alu=alu if has_op else None, src_a=a, src_b=bb, imm=imm if has_op else None,
                    target=b[16:27] if (b[3] and kind != "RET") else None)
    if op == 0b100:
        src = {0b00: "op", 0b11: "imm", 0b01: "dmem", 0b10: "wmem"}[b[9:11]]
        uf = bool(b[11])
        if src == "op":
            alu, a, bb, imm = _operand(b, alu4=True)
            return Inst(addr, "REG_WR", word, cond=cond, uf=uf, dst=_reg7(b[65:72]), src=src, alu=alu,
                        src_a=a, src_b=bb, imm=imm)
        if src == "imm":
            return Inst(addr, "REG_WR", word, cond=cond, uf=uf, dst=_reg7(b[65:72]), src=src,
                        imm=_signed(b[33:65], 32))
        if src == "dmem":
            return Inst(addr, "REG_WR", word, cond=cond, uf=uf, dst=_reg7(b[65:72]), src=src, mem=_mem(b))
        return Inst(addr, "REG_WR", word, uf=uf, dst="r_wave", src=src, wr=_wr(b),
                    wmem_addr=b[16:27] if b[3] else None, mem=_mem(b), ctrl_op=f"{b[6]}{b[7]}{b[8]}")
    if op == 0b101:
        if b[9]:                                     # WMEM_WR: CFG 1 TI UF Wr Rdi alu2
            return Inst(addr, "WMEM_WR", word, uf=bool(b[11]), wr=_wr(b), wmem_addr=b[16:27] if b[3] else None,
                        mem=_mem(b), time=_signed(b[33:65], 32) if b[10] else None)
        di = bool(b[10])                             # DMEM_WR: CFG 0 DI UF Wr Rdi alu2
        if di:
            return Inst(addr, "DMEM_WR", word, cond=cond, uf=bool(b[11]), src="imm", imm=_signed(b[33:65], 32),
                        mem=_mem(b), wr=_wr(b))
        alu, a, bb, imm = _operand(b, alu4=False)
        return Inst(addr, "DMEM_WR", word, cond=cond, uf=bool(b[11]), src="op", alu=alu, src_a=a, src_b=bb,
                    imm=imm, mem=_mem(b), wr=_wr(b))
    if op == 0b110:
        so, to, ww, sp, wp = b[9], b[10], b[6], b[7], b[8]
        port, a0 = b[27:33], b[16:27]
        time = _signed(b[33:65], 32) if to else None
        if so:                                       # WPORT_WR from wmem [&N] or from r_wave
            return Inst(addr, "WPORT_WR", word, port=port, src="r_wave" if sp else "wmem",
                        wmem_addr=a0 if (b[3] and not sp) or ww else None, time=time,
                        ctrl_op="ww" if ww else None)
        if wp and port >= 32:
            return Inst(addr, "TRIG", word, port=port - 32, ctrl_op="set" if a0 else "clr", time=time)
        if wp:
            data: int | str = _signed(a0, 11) if b[3] else _reg_addr(a0 & 0x3F)
            return Inst(addr, "DPORT_WR", word, port=port, src="imm" if b[3] else "reg",
                        imm=data if isinstance(data, int) else None,
                        src_a=data if isinstance(data, str) else None, time=time)
        return Inst(addr, "DPORT_RD", word, port=port)
    if op == 0b010:
        unit, code = b[9:12], b[12:16]
        a0, a1 = b[16:27], b[27:33]
        if unit == 0b000:
            lit = b[4:6] == 0b11
            return Inst(addr, "TIME", word, cond=cond, ctrl_op=TIME_OPS[code],
                        imm=_signed(b[33:65], 32) if lit else None,
                        src_a=None if lit else _reg_src(b[41:49]))
        if unit == 0b001:
            return Inst(addr, "FLAG", word, cond=cond, ctrl_op=FLAG_OPS[code])
        if unit == 0b011:
            lit = b[4:6] == 0b11
            return Inst(addr, "DIV", word, cond=cond, regs=(_reg_addr(a1),),
                        imm=_signed(b[33:65], 32) if lit else None, src_b=None if lit else _reg_src(b[41:49]))
        if unit == 0b010:
            name = ARITH[code]
            ops = {"A": _reg_src(b[33:41]), "B": _reg_src(b[41:49]), "C": _reg_addr(a0 & 0x3F),
                   "D": _reg_addr(a1)}
            return Inst(addr, "ARITH", word, cond=cond, ctrl_op=name, regs=tuple(ops[k] for k in _ARITH_ARGS[name]))
    raise ValueError(f"instruction {addr}: opcode {op:03b} (unit {cfg >> 4:03b}) is not part of this tProc's "
                     "instruction set")


def decode(pmem: np.ndarray) -> list[Inst]:
    """Program memory (rows of eight int32, as load_bin_program receives it) as instructions."""
    rows = np.asarray(pmem, dtype=np.int64).reshape(-1, 8)
    return [decode_word(i, _word(r)) for i, r in enumerate(rows)]


# -- rendering (the tests' oracle) ------------------------------------------------------------------------

def _op_text(i: Inst) -> str:
    if i.alu is None or (i.src_a is None and i.src_b is None):
        return ""
    if i.alu in UNARY:
        return f" -op({i.alu} {i.src_b if i.alu == 'ABS' else i.src_a})"
    if i.src_b is not None:
        if i.src_b == "s0" and i.alu == "+" and not i.imm:
            return f" -op({i.src_a})"
        return f" -op({i.src_a} {i.alu} {i.src_b})" + (f" #{i.imm}" if i.imm else "")
    return f" -op({i.src_a} {i.alu} #{i.imm})"


def _mem_text(mem: tuple[str | None, str | int]) -> str:
    base, off = mem
    off_s = f"&{off}" if isinstance(off, int) else off
    return f"[{base} + {off_s}]" if base else f"[{off_s}]"


def _flags(i: Inst, uf_default: bool = False) -> str:
    out = ""
    if i.cond != "1":
        out += f" -if({i.cond})"
    if i.wr is not None:
        out += f" -wr({i.wr[0]} {i.wr[1]})"
    if i.uf and not uf_default:
        out += " -uf"
    return out


def _render(i: Inst, labels: dict[int, str]) -> str:
    t = f" @{i.time}" if i.time is not None else ""
    if i.kind == "NOP":
        return "NOP"
    if i.kind == "TEST":
        return "TEST" + _op_text(i) + _flags(i, uf_default=True)
    if i.kind in ("JUMP", "CALL"):
        where = labels[i.target] if i.target is not None else "s15"
        return f"{i.kind} {where}" + _flags(i) + _op_text(i)
    if i.kind == "RET":
        return "RET" + _flags(i)
    if i.kind == "REG_WR":
        if i.src == "op":
            return f"REG_WR {i.dst} op" + _op_text(i) + _flags(i)
        if i.src == "imm":
            return f"REG_WR {i.dst} imm #{i.imm}" + _flags(i)
        if i.src == "dmem":
            assert i.mem is not None
            return f"REG_WR {i.dst} dmem {_mem_text(i.mem)}" + _flags(i)
        assert i.mem is not None
        return f"REG_WR r_wave wmem {_mem_text(i.mem)}" + _flags(i)
    if i.kind == "WMEM_WR":
        assert i.mem is not None
        return f"WMEM_WR {_mem_text(i.mem)}" + t + _flags(i)
    if i.kind == "DMEM_WR":
        assert i.mem is not None
        src = f"imm #{i.imm}" if i.src == "imm" else "op" + _op_text(i)
        return f"DMEM_WR {_mem_text(i.mem)} {src}" + _flags(i)
    if i.kind == "WPORT_WR":
        src = f"wmem [&{i.wmem_addr}]" if i.src == "wmem" else "r_wave"
        return f"WPORT_WR p{i.port} {src}" + t
    if i.kind == "TRIG":
        return f"TRIG p{i.port} {i.ctrl_op}" + t
    if i.kind == "DPORT_WR":
        return f"DPORT_WR p{i.port} " + (f"imm {i.imm}" if i.src == "imm" else f"reg {i.src_a}") + t
    if i.kind == "DPORT_RD":
        return f"DPORT_RD p{i.port}"
    if i.kind == "TIME":
        # the assembler's two spellings: TIME #430 inc_ref, and TIME inc_ref r2
        return f"TIME #{i.imm} {i.ctrl_op}" if i.src_a is None else f"TIME {i.ctrl_op} {i.src_a}"
    if i.kind == "FLAG":
        return f"FLAG {i.ctrl_op}"
    if i.kind == "DIV":
        return f"DIV {i.regs[0]} {f'#{i.imm}' if i.src_b is None else i.src_b}"
    if i.kind == "ARITH":
        return f"ARITH {i.ctrl_op} " + " ".join(i.regs)
    raise ValueError(f"cannot render {i.kind}")


def disassemble(pmem: np.ndarray) -> str:
    """QICK assembly for program memory; word 0 (a NOP, which the assembler always prepends) is implied."""
    insts = decode(pmem)
    targets = sorted({i.target for i in insts if i.target is not None and i.kind in ("JUMP", "CALL")})
    labels = {a: f"L{a}" for a in targets}
    lines = []
    for i in insts[1:]:
        if i.addr in labels:
            lines.append(f"{labels[i.addr]}:")
        lines.append(i.asm(labels))
    return "\n".join(lines) + "\n"
