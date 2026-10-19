"""Tier T1a: Clifford stabilizer simulation via Stim + PyMatching QEC decoding.

Supports both:
1. High-throughput compiled batch sampling (microsecond/shot) for QEC circuits.
2. Per-shot execution via stim.TableauSimulator on the shared timeline: each rendered pulse is
   lifted to its actual unitary, snapped to the nearest Clifford, and the residual coherent
   error is Pauli-twirled (noise_fidelity = "twirled"). Idle noise is the Ghosh PTA.
"""
from __future__ import annotations

import re

import numpy as np
import pymatching
import stim

from qcss.ir.frames import TWO_PI
from qcss.ir.program import FrameOp
from qcss.physics.lifter import GateEvent, is_clifford_rz, nearest_unitary, pauli_twirl
from qcss.physics.pta import idle_pta

_PAULI_NAMES = ["I", "X", "Y", "Z"]


def _extract_qubits_from_str(s: str) -> tuple[int, ...]:
    nums = [int(m) for m in re.findall(r"q(\d+)", s)]
    return tuple(nums) if nums else (0,)


class StimT1a:
    tier = "T1A"
    noise_fidelity = "twirled"
    pulse_level = False

    def __init__(
        self,
        n: int,
        t1_ns: list[float] | None = None,
        t2_ns: list[float] | None = None,
        p_meas_err: float = 0.0,
        circuit: stim.Circuit | None = None,
        seed: int = 42,
    ) -> None:
        self.n = n
        self.t1 = [1e9] * n if t1_ns is None else list(t1_ns)
        self.t2 = [1e9] * n if t2_ns is None else list(t2_ns)
        self.p_meas_err = float(p_meas_err)
        self.circuit = circuit if circuit is not None else stim.Circuit()
        self.sim = stim.TableauSimulator()
        self.clock = np.zeros(n, dtype=float)
        self.rng = np.random.default_rng(seed)
        self._cached_matcher: pymatching.Matching | None = None
        self._tableaux: dict[bytes, stim.Tableau] = {}

    def set_parameters(self, f01_ghz: list[float] | None = None, t1_ns: list[float] | None = None) -> None:
        if t1_ns is not None:
            self.t1 = list(t1_ns)

    def reset_state(self) -> None:
        """Reset the dynamic tableau simulator to |0>^n and zero clocks."""
        self.sim = stim.TableauSimulator()
        self.clock.fill(0.0)

    # -- per-shot execution on the shared timeline --

    def advance_to(self, t_ns: float, rng: np.random.Generator | None = None) -> None:
        """Advance every qubit to absolute time t_ns, applying idle PTA noise."""
        for q in range(self.n):
            self._idle_qubit(q, t_ns, rng)

    def _idle_qubit(self, q: int, t_ns: float, rng: np.random.Generator | None) -> None:
        dt = t_ns - self.clock[q]
        if dt > 0:
            px, py, pz = idle_pta(dt, self.t1[q], self.t2[q])
            self._apply_pauli_noise(q, px, py, pz, rng)
            self.clock[q] = t_ns

    def relax(self, t_ns: float, rng: np.random.Generator) -> None:
        """Inter-shot repetition delay: stochastic reset rho -> (1-g) rho + g |0><0|, g = 1 - e^{-t/T1}.

        The Pauli twirl is unital (it would drive an idle qubit to the maximally mixed state), so it
        must not model relaxation between shots. A probabilistic reset is a stabilizer operation and
        reproduces the population decay exactly.
        """
        for q in range(self.n):
            dt = t_ns - self.clock[q]
            if dt > 0:
                if rng.random() < -np.expm1(-dt / self.t1[q]):
                    self.sim.reset(q)
                self.clock[q] = t_ns

    def idle(self, duration_ns: float, rng: np.random.Generator | None = None) -> None:
        """Idle all qubits for duration_ns."""
        if duration_ns <= 0:
            return
        for q in range(self.n):
            self._idle_qubit(q, self.clock[q] + float(duration_ns), rng)

    def _apply_pauli_noise(self, q: int, px: float, py: float, pz: float, rng: np.random.Generator | None = None) -> None:
        """Apply single-qubit Pauli noise according to given probabilities using provided rng."""
        gen = rng if rng is not None else self.rng
        r = gen.random()
        if r < px:
            self.sim.x(q)
        elif r < px + py:
            self.sim.y(q)
        elif r < px + py + pz:
            self.sim.z(q)

    def _tableau(self, c: np.ndarray) -> stim.Tableau:
        key = np.round(c, 9).tobytes()
        tab = self._tableaux.get(key)
        if tab is None:
            tab = stim.Tableau.from_unitary_matrix(c, endian="big")
            self._tableaux[key] = tab
        return tab

    def apply_event(self, ev: GateEvent, rng: np.random.Generator) -> None:
        """Apply the nearest Clifford of the lifted pulse, then its twirled residual error."""
        if ev.clifford is None:
            raise ValueError(f"StimT1a needs a Clifford gate; pulse '{ev.name}' is not one "
                             f"(fidelity to nearest Clifford {ev.clifford_fidelity:.4f})")
        for q in ev.qubits:
            self._idle_qubit(q, ev.t_start, rng)
        self.sim.do_tableau(self._tableau(ev.clifford), list(ev.qubits))
        err = nearest_unitary(ev.unitary) @ ev.clifford.conj().T
        probs = pauli_twirl(err)
        k = int(rng.choice(len(probs), p=probs))
        if k:
            names = [_PAULI_NAMES[k]] if len(ev.qubits) == 1 else [_PAULI_NAMES[k // 4], _PAULI_NAMES[k % 4]]
            for q, p in zip(ev.qubits, names, strict=True):
                if p != "I":
                    getattr(self.sim, p.lower())(q)
        for q in ev.qubits:
            self._idle_qubit(q, ev.t_end, rng)

    def frame_op(self, op: FrameOp, tick: int) -> None:
        """Direct-use helper: a virtual Z by a Clifford angle, as e^{-i phi n} on the state."""
        self.advance_to(float(tick))
        if op.kind in ("shift", "set"):
            angle = op.value % TWO_PI
            if not is_clifford_rz(angle):
                raise ValueError(f"StimT1a only supports Clifford virtual-Z (multiples of pi/2), got {angle} rad")
            k = round(float(angle / (np.pi / 2.0))) % 4
            target = _extract_qubits_from_str(op.frame_id)[0]
            if k == 1:
                self.sim.s_dag(target)
            elif k == 2:
                self.sim.z(target)
            elif k == 3:
                self.sim.s(target)

    def apply_gate(self, gate_name: str, targets: tuple[int, ...]) -> None:
        """Apply a named Clifford gate (direct circuit construction, not used by the executor)."""
        g = gate_name.upper()
        single = {"H": "h", "X": "x", "NOT": "x", "Y": "y", "Z": "z", "S": "s", "S_DAG": "s_dag",
                  "SDAG": "s_dag", "SQRT_X": "sqrt_x", "SX": "sqrt_x", "SQRT_X_DAG": "sqrt_x_dag",
                  "SX_DAG": "sqrt_x_dag", "SQRT_Y": "sqrt_y", "SY": "sqrt_y", "SQRT_Y_DAG": "sqrt_y_dag",
                  "SY_DAG": "sqrt_y_dag"}
        pair = {"CX": "cx", "CNOT": "cx", "CZ": "cz", "CY": "cy", "SWAP": "swap"}
        if g in ("I", "ID"):
            return
        if g in single:
            for q in targets:
                getattr(self.sim, single[g])(q)
        elif g in pair:
            for i in range(0, len(targets), 2):
                getattr(self.sim, pair[g])(targets[i], targets[i + 1])
        else:
            raise ValueError(f"Unsupported Clifford gate in StimT1a: {gate_name}")

    def measure(self, qubit: int, t_now: float | None = None, rng: np.random.Generator | None = None) -> int:
        """Measure qubit in Z basis with optional measurement bit-flip error."""
        if t_now is not None:
            self.advance_to(t_now, rng)
        res = int(self.sim.measure(qubit))
        if self.p_meas_err > 0.0:
            gen = rng if rng is not None else self.rng
            if gen.random() < self.p_meas_err:
                res ^= 1
        return res

    def level_probabilities(self, qubit: int) -> np.ndarray:
        """Return [p0, p1, 0.0] without collapsing the state."""
        peek = self.sim.peek_z(qubit)
        p1 = 0.0 if peek == 1 else (1.0 if peek == -1 else 0.5)
        return np.array([1.0 - p1, p1, 0.0], dtype=np.float64)

    def state_vector(self, endian: str = "big") -> np.ndarray:
        """Return state vector from tableau simulator."""
        return self.sim.state_vector(endian=endian)

    # -- Circuit & Batch Sampling Methods (High-Throughput QEC) --

    def compile_sampler(self, seed: int | None = None) -> stim.CompiledMeasurementSampler:
        return self.circuit.compile_sampler(seed=seed)

    def compile_detector_sampler(self, seed: int | None = None) -> stim.CompiledDetectorSampler:
        return self.circuit.compile_detector_sampler(seed=seed)

    def sample(self, shots: int, seed: int | None = None) -> np.ndarray:
        return self.compile_sampler(seed=seed).sample(shots=shots)

    def sample_detectors(self, shots: int, seed: int | None = None) -> tuple[np.ndarray, np.ndarray]:
        return self.compile_detector_sampler(seed=seed).sample(shots=shots, separate_observables=True)

    def get_detector_error_model(self, decompose_errors: bool = True) -> stim.DetectorErrorModel:
        return self.circuit.detector_error_model(decompose_errors=decompose_errors)

    def decode_syndromes(self, dets: np.ndarray) -> np.ndarray:
        """Decode detection events using PyMatching reference decoder."""
        if self._cached_matcher is None:
            self._cached_matcher = pymatching.Matching.from_detector_error_model(self.get_detector_error_model())
        return self._cached_matcher.decode_batch(dets)

    def evaluate_logical_error_rate(self, shots: int, seed: int | None = None) -> float:
        """Sample detectors and observables, decode with PyMatching, and return logical error rate."""
        dets, obs = self.sample_detectors(shots=shots, seed=seed)
        predictions = self.decode_syndromes(dets)
        return float(np.sum(np.any(predictions != obs, axis=1)) / shots)

    @staticmethod
    def generate_surface_code(
        distance: int,
        rounds: int,
        physical_error_rate: float,
        code_type: str = "surface_code:rotated_memory_z",
    ) -> StimT1a:
        """Factory: generate a rotated surface code memory circuit with depolarizing noise."""
        p = float(physical_error_rate)
        circ = stim.Circuit.generated(
            code_type,
            rounds=rounds,
            distance=distance,
            after_clifford_depolarization=p,
            before_round_data_depolarization=p,
            before_measure_flip_probability=p,
            after_reset_flip_probability=p,
        )
        return StimT1a(n=circ.num_qubits, circuit=circ)
