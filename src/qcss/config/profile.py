"""Hardware-profile schema (Pydantic v2).

Every number that differs between vendors or firmware versions lives here, with
provenance. Times are in TICKS of ``clock.tick_hz`` unless a field name says
otherwise (e.g. ``*_samples``).
"""
from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Provenance(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    source_url: str | None = None      # documentation page the value came from
    firmware_version: str | None = None
    verified: bool = False             # False => shown as "UNVERIFIED" in `qcss profile show`
    note: str | None = None


class SaturationPolicy(StrEnum):
    REJECT = "reject"
    CLIP = "clip"       # QM documents sum-then-clip
    WRAP = "wrap"
    WARN = "warn"       # clip + warning in result metadata


class OverlapPolicy(StrEnum):
    REJECT = "reject"
    TRUNCATE_PREVIOUS = "truncate_previous"   # Qblox: a new play interrupts the running one


class AcqMode(StrEnum):
    RAW_TRACE = "raw_trace"
    INTEGRATED = "integrated"
    DISCRIMINATED = "discriminated"


class ClockSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    tick_hz: str                                  # decimal string, parsed exactly (Fraction)
    provenance: Provenance = Provenance()


class GeneratorSpec(BaseModel):
    """A sequencer / AWG core / signal generator: owns memory, NCO(s), timing rules."""
    model_config = ConfigDict(frozen=True, extra="forbid")
    generator_id: str
    port_id: str
    module_id: str | None = None                        # instrument/module; feedback routing is per module
    sample_rate_hz: str
    rt_granularity_ticks: Annotated[int, Field(ge=1)]   # Qblox 1 ns; ZI 16 Sa; QM 4 ns
    rt_min_duration_ticks: Annotated[int, Field(ge=1)]  # Qblox 4 ns; HDAWG 32 Sa
    wave_granularity_samples: Annotated[int, Field(ge=1)] = 1
    wave_min_samples: Annotated[int, Field(ge=1)] = 1
    wave_mem_samples: Annotated[int, Field(ge=0)]       # Qblox 16384 per sequencer
    max_waveforms: Annotated[int, Field(ge=1)] = 1024
    instr_mem: Annotated[int, Field(ge=1)] = 16384      # QCM 16384, QRM 12288
    max_wait_ticks_per_instr: Annotated[int, Field(ge=1)] = 2**16 - 1
    nco_count: Annotated[int, Field(ge=0)] = 1
    nco_grid_ticks: Annotated[int, Field(ge=1)] = 1      # Qblox 4 ns
    nco_min_spacing_ticks: Annotated[int, Field(ge=0)] = 0  # Qblox 4 or 8
    nco_latched: bool = True                             # applied at next RT instruction
    nco_phase_steps: int = 10**9                         # Qblox: 1e9 steps per 2*pi
    nco_freq_resolution_hz: float = 0.25
    nco_freq_range_hz: tuple[float, float] = (-500e6, 500e6)
    phase_continuous_freq_switch: bool = True            # per profile flag
    overlap_policy: OverlapPolicy = OverlapPolicy.REJECT
    is_readout: bool = False
    provenance: Provenance = Provenance()


class PortSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    port_id: str
    kind: str                                   # "rf_iq" | "baseband" | "rf_direct"
    max_generators: Annotated[int, Field(ge=1)] = 6
    full_scale_per_path: float = 1.0            # normalised units per I/Q path
    saturation_policy: SaturationPolicy = SaturationPolicy.WARN
    lo_frequency_hz: float | None = None
    output_latency_ticks: int = 0               # extra latency from enabled predistortion filters
    provenance: Provenance = Provenance()


class AcquisitionSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    modes: tuple[AcqMode, ...]
    max_discriminated_states: Annotated[int, Field(ge=2)] = 2     # Qblox binary; ZI up to 4
    integration_granularity_ticks: Annotated[int, Field(ge=1)] = 4
    max_square_integration_ticks: int = 16_777_212
    max_weighted_integration_ticks: int = 16_380
    max_weight_sets: int = 32
    min_acq_spacing_ticks: int = 300
    internal_tof_ticks: int = 0                 # instrument-internal delay (Qblox ~149-153 ns)
    integration_convention: str = "sum"         # "sum" or "mean"
    provenance: Provenance = Provenance()


class LatencyEntry(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    src: str            # generator id or "*" wildcard
    dst: str
    payload: str        # "bit" | "iq"
    routing: str        # "self" | "intra" | "inter" | "central"
    latency_ticks: int  # last ADC sample in -> first conditional DAC sample out
    jitter_ticks: int = 0
    provenance: Provenance = Provenance()


class FeedbackSpec(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    latencies: tuple[LatencyEntry, ...]
    branch_equal_duration_required: bool = True
    trigger_grid_ticks: int = 1             # Qblox trigger network: 28 ns
    trigger_min_period_ticks: int = 0       # Qblox: 252 ns
    max_condition_addresses: int = 15


class HardwareProfile(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    profile_name: str
    vendor: str
    clock: ClockSpec
    ports: tuple[PortSpec, ...]
    generators: tuple[GeneratorSpec, ...]
    acquisition: AcquisitionSpec
    feedback: FeedbackSpec

    @model_validator(mode="after")
    def _check_refs(self) -> HardwareProfile:
        ports = {p.port_id: p for p in self.ports}
        per_port: dict[str, int] = {}
        for g in self.generators:
            if g.port_id not in ports:
                raise ValueError(f"generator {g.generator_id} references unknown port {g.port_id}")
            per_port[g.port_id] = per_port.get(g.port_id, 0) + 1
        for pid, n in per_port.items():
            if n > ports[pid].max_generators:
                raise ValueError(f"port {pid}: {n} generators > max {ports[pid].max_generators}")
        return self

    def generator(self, generator_id: str) -> GeneratorSpec:
        for g in self.generators:
            if g.generator_id == generator_id:
                return g
        raise KeyError(f"unknown generator '{generator_id}'")

    def port(self, port_id: str) -> PortSpec:
        for p in self.ports:
            if p.port_id == port_id:
                return p
        raise KeyError(f"unknown port '{port_id}'")

    def routing(self, src_gen: str, dst_gen: str) -> str:
        """Feedback route class: same sequencer / same instrument module / across modules.

        Vendors quote latency per module topology (Qblox 160 ns self, 390 ns intra-module,
        388 ns inter-module; ZI SHFQC+ 350 ns internal), not per output port.
        """
        if src_gen == dst_gen:
            return "self"
        gs, gd = self.generator(src_gen), self.generator(dst_gen)
        ms, md = gs.module_id or gs.port_id, gd.module_id or gd.port_id
        return "intra" if ms == md else "inter"
