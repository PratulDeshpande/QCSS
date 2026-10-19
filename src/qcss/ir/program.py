"""Program IR: what the compiler hands to the validator and the executor.

All times are integer ticks. Ops are grouped per GENERATOR (sequencer / AWG core),
because that is where hardware enforces memory, grids and ordering.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ChannelKind(StrEnum):
    DRIVE = "drive"
    FLUX = "flux"
    READOUT = "readout"
    CROSS_RESONANCE = "cross_resonance"


@dataclass(frozen=True, slots=True)
class ChannelBinding:
    channel_id: str
    kind: ChannelKind
    generator_id: str
    port_id: str
    frame_id: str                    # CR channels bind to the TARGET qubit's frame
    qubits: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class Play:
    path: str                        # proto field path for error reporting
    channel_id: str
    start: int
    duration: int
    waveform_id: str
    amplitude: float
    phase_offset: float = 0.0


@dataclass(frozen=True, slots=True)
class FrameOp:
    path: str
    frame_id: str
    start: int
    kind: str                        # "shift" | "set" | "reset" | "freq"
    value: float = 0.0


@dataclass(frozen=True, slots=True)
class Acquire:
    path: str
    channel_id: str
    start: int
    integration: int
    mode: str                        # "raw_trace" | "integrated" | "discriminated"
    weights_id: str = ""
    register: int = 0
    result_key: str = ""


@dataclass(frozen=True, slots=True)
class Condition:
    op: str                          # "eq" | "ne" | "and" | "or" | "xor"
    registers: tuple[int, ...]
    value: int = 0
    mask: int = 0

    def evaluate(self, regs: dict[int, int]) -> bool:
        bits = 0
        for i, r in enumerate(self.registers):
            bits |= (regs.get(r, 0) & 1) << i
        if self.op == "eq":
            return regs.get(self.registers[0], 0) == self.value
        if self.op == "ne":
            return regs.get(self.registers[0], 0) != self.value
        if self.op == "and":
            return (bits & self.mask) == self.mask
        if self.op == "or":
            return (bits & self.mask) != 0
        if self.op == "xor":
            return (bits & self.mask).bit_count() % 2 == 1
        raise ValueError(self.op)


@dataclass(frozen=True, slots=True)
class Branch:
    path: str
    sequencer_id: str                # the generator that waits on the condition
    start: int                       # earliest tick at which the conditional ops may begin
    duration: int                    # both arms padded to this
    condition: Condition
    then_ops: tuple = ()
    else_ops: tuple = ()


@dataclass
class Program:
    bindings: dict[str, ChannelBinding]
    ops: list = field(default_factory=list)            # Play | FrameOp | Acquire | Branch, program order
    waveforms: dict[str, int] = field(default_factory=dict)   # waveform_id -> length in samples
    weights: dict[str, int] = field(default_factory=dict)     # weights_id -> length in samples
    duration: int = 0
    repetition_delay: int | None = 0                     # None = job left it unset (runtime picks the default)
