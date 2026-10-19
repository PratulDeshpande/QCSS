"""Pydantic mirrors of the Quark-QOS contracts this driver produces and consumes (HLD Appendix B).

The field names follow the HLD sketch so the driver can switch to `quark.contracts` once the
Contracts LLD is frozen: replace these imports and delete this module. Only what the HAL and the
driver exchange is modelled here.
"""
from __future__ import annotations

import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class NativeOp(BaseModel):
    """One native operation from the device profile (ADR-0054: the profile is the single source)."""
    model_config = ConfigDict(extra="forbid")
    name: str
    arity: int
    addressing: Literal["individual", "global", "subset"] = "individual"
    params: list[dict[str, Any]] = []
    definition: str
    clifford: bool | str
    duration_s: float


class DeviceDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str
    modality: Literal["superconducting", "trapped_ion", "neutral_atom"]
    trap_type: str | None = None
    maturity_level: Literal["L0", "L1", "L2", "L3", "L4"]
    profile_source: str
    sites: list[dict[str, Any]]
    coupling: list[list[int]] | Literal["all_to_all"]
    native_ops: list[NativeOp]
    program_types: list[str]
    transport_model: str = "none"
    capabilities: dict[str, Any]
    requires_approval: bool = False
    control_stack: dict[str, Any] = {}                 # dynamic facts from the stack (DescribeDevice)


class CalibrationEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device_id: str
    resource: str                                      # "q3", "q3-q4", or "device"
    parameter: str
    value: float
    uncertainty: float | None = None
    unit: str = ""
    measured_at: datetime.datetime
    valid_until: datetime.datetime | None = None
    source: Literal["lab", "vendor", "collector", "manual"] = "lab"
    adapter: str
    raw_name: str
    assumed: bool = False
    quality_flags: list[str] = []


class NativeJob(BaseModel):
    """What the Scheduler hands the driver: the chosen plan's physical program at the submission level."""
    model_config = ConfigDict(extra="forbid")
    job_id: str
    program: str                                       # physical OpenQASM 3
    program_type: Literal["gate"] = "gate"
    shots: int = Field(gt=0)
    seed: int | None = None
    calibration_epoch: int | None = None               # the control stack's epoch the plan was made with
    options: dict[str, Any] = {}


class Handle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    job_id: str                                        # Quark's job id
    backend_job_id: str                                # QCSS job id
    calibration_epoch: int
    clbits: list[str]                                  # bit order of the counts, bit 0 first
    submitted_at: datetime.datetime


class JobStatus(str, Enum):
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RawResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    counts: dict[str, int]                             # bitstrings with the last declared bit leftmost
    shots: int
    executed_as_submitted: bool
    calibration_epoch: int
    backend: dict[str, Any] = {}                       # tier used, warnings, backend job id
    timings: dict[str, float] = {}


class Ack(BaseModel):
    accepted: bool
    reason: str = ""
