"""A stand-in for Quark's Qibolab adapter (L7 LLD 7.4), for acceptance tests of the virtual lab.

Physical OpenQASM 3 on hardware qubits ($n) goes in; Qibolab compiles it from the platform's
own native-gate definitions and runs it on the platform's instrument; counts come back keyed
with classical bit 0 rightmost across all registers (HAL LLD 6.2). The job is pinned to a
calibration set (the digest of the platform's calibration files) and refused at execution if
the lab has recalibrated since it was planned.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import numpy as np
import openqasm3
from openqasm3 import ast
from qibo import Circuit, gates
from qibolab import create_platform
from qibolab._core.backends import QibolabBackend

from qcss.technician import calibration_set_digest


class CalibrationSetStale(RuntimeError):
    """CALIBRATION-SET-STALE: the lab recalibrated after the job was planned."""


def _qubit(node: Any) -> int:
    name = node.name if isinstance(node, ast.Identifier) else str(node)
    if not name.startswith("$"):
        raise ValueError(f"physical programs address hardware qubits ($n), got {name}")
    return int(name[1:])


_CONSTANTS = {"pi": np.pi, "π": np.pi, "tau": 2 * np.pi, "τ": 2 * np.pi, "euler": np.e, "ℇ": np.e}


def _number(node: Any) -> float:
    """A gate angle: a literal, an OpenQASM 3 constant (pi, tau, euler), or arithmetic on them."""
    if isinstance(node, ast.IntegerLiteral | ast.FloatLiteral):
        return float(node.value)
    if isinstance(node, ast.Identifier) and node.name in _CONSTANTS:
        return float(_CONSTANTS[node.name])
    if isinstance(node, ast.UnaryExpression) and node.op.name == "-":
        return -_number(node.expression)
    if isinstance(node, ast.BinaryExpression) and node.op.name in ("+", "-", "*", "/"):
        a, b = _number(node.lhs), _number(node.rhs)
        if node.op.name == "/":
            return a / b
        return {"+": a + b, "-": a - b, "*": a * b}[node.op.name]
    raise ValueError(f"unsupported gate angle {node!r}")


class QibolabAdapter:
    def __init__(self, platform: str, platforms_dir: Path) -> None:
        self.name = platform
        self.platform_dir = Path(platforms_dir) / platform
        self._platform: Any = None
        self._loaded_set = ""

    def calibration_set(self) -> str:
        """The current set identity; read until two reads agree (Qibocal rewrites files in place)."""
        prev = calibration_set_digest(self.platform_dir)
        while (cur := calibration_set_digest(self.platform_dir)) != prev:
            prev = cur
        return cur

    def close(self) -> None:
        if self._platform is not None:
            self._platform.disconnect()
            self._platform = None

    def run(self, qasm: str, *, shots: int, calibration_set: str) -> dict[str, int]:
        current = self.calibration_set()
        if calibration_set != current:
            raise CalibrationSetStale(f"job pinned to {calibration_set[:12]}, the platform is at {current[:12]}")
        if self._platform is None or self._loaded_set != current:
            self.close()
            self._platform = create_platform(self.name)          # the platform as calibrated now
            self._platform.connect()
            self._loaded_set = current
        circuit, measured, n_bits = self._circuit(qasm)
        result = QibolabBackend(self._platform).execute_circuit(circuit, nshots=shots)
        samples = np.asarray(result.samples(), dtype=int)       # shots x measured qubits, in measure order
        counts: dict[str, int] = {}
        for shot in samples:
            bits = ["0"] * n_bits
            for (_, clbit), value in zip(measured, shot, strict=True):
                bits[clbit] = str(value)
            key = "".join(reversed(bits))                          # classical bit 0 rightmost
            counts[key] = counts.get(key, 0) + 1
        return counts

    def _circuit(self, qasm: str) -> tuple[Circuit, list[tuple[int, int]], int]:
        program = openqasm3.parse(qasm)
        qubits = list(self._platform.qubits)
        c = Circuit(len(qubits), wire_names=qubits)
        offsets: dict[str, int] = {}
        n_bits = 0
        measured: list[tuple[int, int]] = []
        statements: list[Any] = list(program.statements)          # the AST is loosely typed
        for st in statements:
            if isinstance(st, ast.ClassicalDeclaration) and isinstance(st.type, ast.BitType):
                size_node: Any = st.type.size
                size = int(size_node.value) if size_node is not None else 1
                offsets[st.identifier.name] = n_bits
                n_bits += size
            elif isinstance(st, ast.QuantumGate):
                name, qs = st.name.name, [qubits.index(_qubit(q)) for q in st.qubits]
                if name == "x":
                    c.add(gates.GPI(qs[0], 0.0))
                elif name == "sx":
                    c.add(gates.GPI2(qs[0], 0.0))
                elif name == "rz":
                    c.add(gates.RZ(qs[0], _number(st.arguments[0])))
                elif name == "cz":
                    c.add(gates.CZ(qs[0], qs[1]))
                else:
                    raise ValueError(f"'{name}' is not a native gate of this device")
            elif isinstance(st, ast.QuantumMeasurementStatement):
                target: Any = st.target
                reg = target.name.name if isinstance(target, ast.IndexedIdentifier) else target.name
                idx = int(cast(Any, target).indices[0][0].value) if isinstance(target, ast.IndexedIdentifier) else 0
                measured.append((qubits.index(_qubit(st.measure.qubit)), offsets[reg] + idx))
        c.add(gates.M(*[q for q, _ in measured]))
        return c, measured, n_bits
