"""Simulation tier router: maps the requested tier and the job's lifted operations to a tier.

Never downgrades silently: a request the tier cannot honour is refused with the reason
(mapped to FAILED_PRECONDITION at submit time).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

T2_MAX_QUTRITS = 4
T1B_MAX_QUBITS = 26


@dataclass
class RouteDecision:
    tier: str | None
    reason: str


def route(requested: str, lifted: list[Any] | None, n_qubits: int, feedback_kinds: set[str] | None = None,
          needs_leakage: bool = False, needs_non_unital: bool = False) -> RouteDecision:
    """`lifted` = the job's lifted gate events, or None when some pulse cannot be lifted to gates."""
    req = requested.upper()
    feedback_kinds = feedback_kinds or set()

    if req == "T3":
        return RouteDecision(None, "T3 (quantum trajectories) is not implemented; request T2 for pulse-level physics")
    if req == "T0":
        return RouteDecision("T0", "requested")
    if req == "T2":
        if n_qubits <= T2_MAX_QUTRITS:
            return RouteDecision("T2", "requested")
        return RouteDecision(None, f"T2 limited to <= {T2_MAX_QUTRITS} qutrits (got {n_qubits})")

    def clifford_problem() -> str | None:
        if lifted is None:
            return "some pulse cannot be lifted to a gate (route to T2)"
        for g in lifted:
            if not getattr(g, "is_clifford", False):
                return (f"pulse '{getattr(g, 'name', '?')}' on qubits {getattr(g, 'qubits', ())} is not a Clifford "
                        f"(fidelity to nearest Clifford {getattr(g, 'clifford_fidelity', 0.0):.4f})")
        if not feedback_kinds <= {"pauli"}:
            return f"non-Pauli feedback kinds present: {feedback_kinds - {'pauli'}}"
        if needs_leakage or needs_non_unital:
            return "requires physical non-unital / leakage noise"
        return None

    if req in ("T1A", "AUTO"):
        problem = clifford_problem()
        if problem is None:
            return RouteDecision("T1A", "Clifford gates, twirled noise")
        if req == "T1A":
            return RouteDecision(None, f"T1A requires Clifford gates: {problem}")

    if req in ("T1B", "AUTO"):
        if lifted is not None and n_qubits <= T1B_MAX_QUBITS:
            return RouteDecision("T1B", "lifts to gates")
        if req == "T1B":
            if lifted is None:
                return RouteDecision(None, "T1B requires every pulse to lift to a gate")
            return RouteDecision(None, f"T1B limited to <= {T1B_MAX_QUBITS} qubits (got {n_qubits})")

    if req == "AUTO" and n_qubits <= T2_MAX_QUTRITS:
        return RouteDecision("T2", "pulse-level")
    return RouteDecision(None, f"Requested tier '{requested}' cannot satisfy the job (n_qubits={n_qubits})")
