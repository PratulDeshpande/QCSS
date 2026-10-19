"""PhysicsEngine protocol definition for all simulation tiers."""
from __future__ import annotations

from typing import Protocol

import numpy as np

from qcss.physics.lifter import GateEvent


class PhysicsEngine(Protocol):
    """Every tier exposes the same time-aware interface (absolute time in ns).

    Pulse-level tiers (T2) evolve under the rendered drive samples; gate-level tiers
    (T0, T1a, T1b) receive the lifted unitary of the very same samples. Virtual Z is a frame
    change carried by the drive phase, so no tier rotates its state for a frame op.
    """
    tier: str                         # "T0" | "T1A" | "T1B" | "T2"
    noise_fidelity: str               # "surrogate" | "twirled" | "physical"
    pulse_level: bool

    def reset_state(self) -> None: ...
    def advance_to(self, t_ns: float, rng: np.random.Generator | None = None) -> None: ...
    def measure(self, q: int, t_now: float | None = None, rng: np.random.Generator | None = None) -> int: ...
    def level_probabilities(self, q: int) -> np.ndarray: ...
    def set_parameters(self, f01_ghz: list[float] | None = None, t1_ns: list[float] | None = None) -> None: ...


class PulseLevelEngine(PhysicsEngine, Protocol):
    def evolve_segment(self, t0_ns: float, dt_ns: float,
                       drives: dict[int, np.ndarray] | None,
                       flux_detuning: dict[int, np.ndarray] | None) -> None: ...


class GateLevelEngine(PhysicsEngine, Protocol):
    def apply_event(self, ev: GateEvent, rng: np.random.Generator) -> None: ...
