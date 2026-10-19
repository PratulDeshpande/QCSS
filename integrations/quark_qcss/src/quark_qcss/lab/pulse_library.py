"""Schema of the lab-owned native-op -> pulse library (see lab_examples/*/pulse_library.yaml)."""
from __future__ import annotations

import pathlib
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

Shape = Literal["square", "gaussian", "drag"]


class QubitChannels(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    drive: str
    frame: str
    readout: str
    flux: str | None = None
    drive_sequencer: str | None = None       # plays and frame shifts on one sequencer are serialised
    readout_sequencer: str | None = None     # acquisitions on one sequencer must be spaced


class SingleQubitDefaults(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    shape: Shape = "square"
    length_samples: int = Field(default=20, gt=0)
    pi_amplitude: float = Field(default=0.5, gt=0, le=1)
    drag_beta_samples: float = 0.0


class ReadoutSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    integration_ticks: int = Field(default=1000, gt=0)
    mode: Literal["discriminated", "integrated"] = "discriminated"


class TwoQubitPulse(BaseModel):
    """A calibrated CZ: one flux pulse plus the single-qubit phase corrections that follow it."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    channel: str
    sequencer: str | None = None              # pulses on one sequencer are serialised
    shape: Shape = "square"
    length_samples: int = Field(gt=0)
    amplitude: float = Field(ge=-1, le=1)
    phase_corrections: dict[int, float] = {}


class PulseLibrary(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    grid_ticks: int = Field(default=4, gt=0)
    min_acquire_spacing_ticks: int = Field(default=0, ge=0)
    qubits: dict[int, QubitChannels]
    single_qubit: SingleQubitDefaults = SingleQubitDefaults()
    readout: ReadoutSpec = ReadoutSpec()
    two_qubit: dict[str, TwoQubitPulse] = {}

    def pair(self, a: int, b: int) -> TwoQubitPulse | None:
        return self.two_qubit.get(f"{min(a, b)}-{max(a, b)}")


def load_pulse_library(path: str | pathlib.Path) -> PulseLibrary:
    return PulseLibrary.model_validate(yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8")))
