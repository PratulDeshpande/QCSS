"""A deliberately small parser for *physical* OpenQASM 3: the native-gate programs Quark's
Compilation Pipeline emits after layout, routing and native translation (HLD §5.4.2).

Accepted:
  OPENQASM 3[.0]; include "...";               (ignored)
  qubit[n] q; qubit q; qreg q[n];              (virtual registers map to physical 0, 1, ... in order)
  bit[n] c; bit c; creg c[n];
  <gate>[(<angle>, ...)] <qubit>, ...;          qubit = $k | q[k] | q
  c[i] = measure <qubit>;  measure <qubit> -> c[i];
  barrier [<qubit>, ...];
Angles are arithmetic on numbers and pi (π); nothing is evaluated as code. Anything else (gate
definitions, classical control, loops, delays) raises QasmError naming the line.
"""
from __future__ import annotations

import ast
import math
import operator
import re
from dataclasses import dataclass, field


class QasmError(ValueError):
    pass


@dataclass(frozen=True)
class Op:
    name: str
    qubits: tuple[int, ...]
    params: tuple[float, ...] = ()
    clbits: tuple[tuple[str, int], ...] = ()      # measure targets as (register, index)
    line: int = 0


@dataclass
class Program:
    ops: list[Op] = field(default_factory=list)
    cregs: dict[str, int] = field(default_factory=dict)       # declaration order is bit order


_BINOPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv}
MAX_ANGLE_CHARS = 200                         # compiler output is short; this bounds parse and evaluation work
_UNARY = {ast.USub: operator.neg, ast.UAdd: operator.pos}


def _angle(expr: str, line: int) -> float:
    if len(expr) > MAX_ANGLE_CHARS:
        raise QasmError(f"line {line}: angle expression longer than {MAX_ANGLE_CHARS} characters")

    def ev(node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
            return float(node.value)
        if isinstance(node, ast.Name) and node.id in ("pi", "π"):
            return math.pi
        if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
            return _BINOPS[type(node.op)](ev(node.left), ev(node.right))
        if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
            return _UNARY[type(node.op)](ev(node.operand))
        raise QasmError(f"line {line}: unsupported angle expression {expr!r}")
    try:
        value = ev(ast.parse(expr.strip(), mode="eval").body)
    except (SyntaxError, ArithmeticError, RecursionError, MemoryError, ValueError) as err:
        raise QasmError(f"line {line}: cannot evaluate angle {expr!r}") from err
    if not math.isfinite(value):
        raise QasmError(f"line {line}: angle {expr!r} is not finite")
    return value


_DECL_Q = re.compile(r"^(?:qubit(?:\[(\d+)\])?\s+(\w+)|qreg\s+(\w+)\[(\d+)\])$")
_DECL_C = re.compile(r"^(?:bit(?:\[(\d+)\])?\s+(\w+)|creg\s+(\w+)\[(\d+)\])$")
_MEAS_ASSIGN = re.compile(r"^(\w+)(?:\[(\d+)\])?\s*=\s*measure\s+(.+)$")
_MEAS_ARROW = re.compile(r"^measure\s+(.+?)\s*->\s*(\w+)(?:\[(\d+)\])?$")
_GATE = re.compile(r"^([A-Za-z_]\w*)\s*(?:\((.*)\))?\s*(.*)$")


def parse(text: str) -> Program:
    prog = Program()
    qregs: dict[str, tuple[int, int]] = {}                    # name -> (first physical index, size)
    next_q = 0

    def qubit(tok: str, line: int) -> int:
        tok = tok.strip()
        if m := re.fullmatch(r"\$(\d+)", tok):
            return int(m.group(1))
        m = re.fullmatch(r"(\w+)(?:\[(\d+)\])?", tok)
        if m and m.group(1) in qregs:
            base, size = qregs[m.group(1)]
            idx = int(m.group(2) or 0)
            if idx >= size:
                raise QasmError(f"line {line}: {tok} is out of range")
            return base + idx
        raise QasmError(f"line {line}: unknown qubit {tok!r}")

    def clbit(name: str, idx: str | None, line: int) -> tuple[str, int]:
        i = int(idx or 0)
        if name not in prog.cregs or i >= prog.cregs[name]:
            raise QasmError(f"line {line}: bit {name}[{i}] is not declared")
        return name, i

    for n, raw in enumerate(text.splitlines(), start=1):
        for stmt in (s.strip() for s in raw.split("//", 1)[0].split(";")):
            if not stmt or stmt.startswith(("OPENQASM", "include")):
                continue
            if m := _DECL_Q.match(stmt):
                name, size = (m.group(2), int(m.group(1) or 1)) if m.group(2) else (m.group(3), int(m.group(4)))
                qregs[name] = (next_q, size)
                next_q += size
            elif m := _DECL_C.match(stmt):
                name, size = (m.group(2), int(m.group(1) or 1)) if m.group(2) else (m.group(3), int(m.group(4)))
                prog.cregs[name] = size
            elif m := _MEAS_ASSIGN.match(stmt):
                prog.ops.append(Op("measure", (qubit(m.group(3), n),), clbits=(clbit(m.group(1), m.group(2), n),),
                                   line=n))
            elif m := _MEAS_ARROW.match(stmt):
                prog.ops.append(Op("measure", (qubit(m.group(1), n),), clbits=(clbit(m.group(2), m.group(3), n),),
                                   line=n))
            elif stmt.startswith(("if", "for", "while", "gate", "def", "delay", "reset", "box", "input", "output")):
                raise QasmError(f"line {n}: '{stmt.split()[0].split('(')[0]}' is not supported in physical programs")
            elif m := _GATE.match(stmt):
                name, args, operands = m.group(1), m.group(2), m.group(3).strip()
                params = tuple(_angle(a, n) for a in args.split(",")) if args else ()
                qs = tuple(qubit(t, n) for t in operands.split(",")) if operands else ()
                prog.ops.append(Op(name, qs, params, line=n))
            else:
                raise QasmError(f"line {n}: cannot parse {stmt!r}")
    return prog
