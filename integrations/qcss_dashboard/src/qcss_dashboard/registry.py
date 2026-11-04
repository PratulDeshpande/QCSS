"""Parameter registry: every configurable field of every QCSS layer, with the text the UI shows next to it.

Fields come from the code itself (Pydantic models, protobuf descriptors, the chassis dataclass), so a new field shows up
here automatically; its explanation comes from explanations/*.yaml. A test fails when a field has no explanation or an
explanation names no field, so the dashboard never shows an undocumented knob and never documents a removed one.
"""
from __future__ import annotations

import dataclasses
import enum
import functools
import pathlib
import typing
from dataclasses import dataclass
from typing import Any

import annotated_types
import yaml
from google.protobuf.descriptor import FieldDescriptor
from pydantic import BaseModel
from pydantic_core import PydanticUndefined

from qcss.admin.v1 import admin_pb2
from qcss.chassis import ChassisConfig
from qcss.config import device as device_mod
from qcss.config import profile as profile_mod
from qcss.v1 import calibration_pb2, job_pb2

EXPLANATIONS_DIR = pathlib.Path(__file__).parent / "explanations"

# The five places a QCSS parameter can live, each owned by a different actor and changing at a different time.
LAYERS: list[dict[str, str]] = [
    {"id": "A", "name": "Hardware profile", "owner": "operator", "file": "src/qcss/config/profile.py",
     "when": "read once when the chassis starts",
     "summary": "The control electronics: clock, ports, generators (sequencers, AWGs, NCOs), acquisition limits and "
                "feedback latencies of one vendor instrument. Every hardware rule the validator enforces comes "
                "from here."},
    {"id": "B", "name": "Device (hidden truth)", "owner": "operator", "file": "src/qcss/config/device.py",
     "when": "read once at start; drifts afterwards on the lab clock",
     "summary": "The chip itself: transmons, couplers, readout resonators, slow dynamics (drift, TLS defects, "
                "cosmic-ray bursts) and hidden faults. Lab clients never see these numbers, only their effect."},
    {"id": "C", "name": "Calibration", "owner": "lab client (Qibocal or the OS)",
     "file": "proto/qcss/v1/calibration.proto",
     "when": "written over the lab link with compare-and-swap; pinned when a job is planned",
     "summary": "What the lab believes about the chip: drive and readout frequencies, discriminator, mixer and "
                "flux-line corrections. QCSS never writes it; the virtual technician measures the truth and does."},
    {"id": "D", "name": "Job", "owner": "lab client", "file": "proto/qcss/v1/job.proto",
     "when": "per job (and per sweep point)",
     "summary": "One experiment: waveforms, a timed instruction list on channels, acquisitions, sweeps, shots and "
                "the requested fidelity tier."},
    {"id": "E", "name": "Chassis and live mode", "owner": "operator (admin channel)", "file": "src/qcss/chassis.py",
     "when": "startup options, plus the admin channel live mode and scenarios",
     "summary": "How the virtual lab runs: listeners, tokens, persistence, the pace of the lab clock, determinism, "
                "the physics tier policy, and the admin-only scenario and fault controls."},
]

APPLY_BY_LAYER = {"A": "restart", "B": "restart", "C": "next-job", "D": "per-job", "E": "restart"}
APPLY_MODES = {
    "restart": "Takes effect when the chassis restarts with the new file.",
    "next-job": "Takes effect for jobs planned after the write (calibration is pinned at planning).",
    "per-job": "Set by each job; nothing global changes.",
    "live": "Takes effect immediately through the admin channel.",
}

# Longest suffix first: the unit is inferred from the field name (an explanation may override it).
_UNIT_SUFFIXES = [("_per_s", "1/s"), ("_cm2", "cm²"), ("_ghz", "GHz"), ("_mhz", "MHz"), ("_hz", "Hz"),
                  ("_ns", "ns"), ("_us", "µs"), ("_mk", "mK"), ("_mm", "mm"), ("_rad", "rad"),
                  ("_ticks", "ticks"), ("_samples", "samples"), ("_s", "s")]

_LIVE_PROTOS = [admin_pb2.Mode.DESCRIPTOR, admin_pb2.DriftStepRequest.DESCRIPTOR,
                admin_pb2.TlsCollisionRequest.DESCRIPTOR, admin_pb2.BurstRequest.DESCRIPTOR,
                admin_pb2.InjectInstrumentFaultRequest.DESCRIPTOR]


@dataclass(frozen=True)
class SchemaField:
    key: str                     # "<Model>.<field>"
    model: str
    field: str
    layer: str
    type: str
    default: Any = None
    required: bool = False
    repeated: bool = False
    constraints: dict[str, Any] = dataclasses.field(default_factory=dict)
    choices: list[str] = dataclasses.field(default_factory=list)
    apply: str = ""


def _unit(name: str) -> str:
    return next((u for suf, u in _UNIT_SUFFIXES if name.endswith(suf)), "")


def _jsonable(v: Any) -> Any:
    if isinstance(v, BaseModel):
        return v.model_dump(mode="json")
    if isinstance(v, enum.Enum):
        return v.value
    if isinstance(v, tuple | list):
        return [_jsonable(x) for x in v]
    return v


def _type_name(t: Any) -> str:
    if isinstance(t, type):
        return t.__name__
    return str(t).replace("typing.", "").replace("qcss.config.profile.", "").replace("qcss.config.device.", "")


def _nested_models(t: Any) -> list[type[BaseModel]]:
    if isinstance(t, type) and issubclass(t, BaseModel):
        return [t]
    out: list[type[BaseModel]] = []
    for a in typing.get_args(t):
        out += _nested_models(a)
    return out


def _enum_choices(t: Any) -> list[str]:
    if isinstance(t, type) and issubclass(t, enum.Enum):
        return [str(m.value) for m in t]
    for a in typing.get_args(t):
        if c := _enum_choices(a):
            return c
    return []


def _constraints(meta: list[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for m in meta:
        for attr, cls in (("gt", annotated_types.Gt), ("ge", annotated_types.Ge), ("lt", annotated_types.Lt),
                          ("le", annotated_types.Le)):
            if isinstance(m, cls):
                out[attr] = getattr(m, attr)
    return out


def _is_repeated(t: Any) -> bool:
    origin = typing.get_origin(t)
    if origin is list:
        return True
    return origin is tuple and Ellipsis in typing.get_args(t)


def _walk_pydantic(model: type[BaseModel], layer: str, seen: set[str], out: list[SchemaField]) -> None:
    if model.__name__ in seen:
        return
    seen.add(model.__name__)
    for name, info in model.model_fields.items():
        t = info.annotation
        default = None if info.default is PydanticUndefined else _jsonable(info.default)
        out.append(SchemaField(f"{model.__name__}.{name}", model.__name__, name, layer, _type_name(t), default,
                               info.is_required(), _is_repeated(t), _constraints(info.metadata), _enum_choices(t),
                               APPLY_BY_LAYER[layer]))
        for sub in _nested_models(t):
            _walk_pydantic(sub, layer, seen, out)


_PROTO_TYPES = {FieldDescriptor.TYPE_DOUBLE: "float", FieldDescriptor.TYPE_FLOAT: "float",
                FieldDescriptor.TYPE_INT64: "int", FieldDescriptor.TYPE_UINT64: "int",
                FieldDescriptor.TYPE_INT32: "int", FieldDescriptor.TYPE_UINT32: "int",
                FieldDescriptor.TYPE_BOOL: "bool", FieldDescriptor.TYPE_STRING: "str",
                FieldDescriptor.TYPE_BYTES: "bytes"}


def _walk_proto(d: Any, layer: str, apply: str, seen: set[str], out: list[SchemaField]) -> None:
    if d.full_name in seen:
        return
    seen.add(d.full_name)
    f: Any
    for f in d.fields:
        mt = f.message_type
        is_map = mt is not None and mt.GetOptions().map_entry
        nested: Any
        if mt is not None and is_map:
            val = mt.fields_by_name["value"]
            inner = val.message_type.name if val.message_type else _PROTO_TYPES.get(val.type, "?")
            tname, nested = f"map<str, {inner}>", val.message_type
        elif mt is not None:
            tname, nested = mt.name, mt
        elif f.enum_type is not None:
            tname, nested = f.enum_type.name, None
        else:
            tname, nested = _PROTO_TYPES.get(f.type, "?"), None
        choices = [v.name for v in f.enum_type.values] if f.enum_type is not None else []
        out.append(SchemaField(f"{d.name}.{f.name}", d.name, f.name, layer, tname, None, False,
                               f.label == FieldDescriptor.LABEL_REPEATED and not is_map, {}, choices, apply))
        if nested is not None and nested.file.package.startswith("qcss"):
            _walk_proto(nested, layer, apply, seen, out)


@functools.cache
def _schema_fields() -> tuple[SchemaField, ...]:
    out: list[SchemaField] = []
    seen: set[str] = set()
    _walk_pydantic(profile_mod.HardwareProfile, "A", seen, out)
    _walk_pydantic(device_mod.DeviceSpec, "B", seen, out)
    _walk_proto(calibration_pb2.CalibrationSnapshot.DESCRIPTOR, "C", "next-job", seen, out)
    _walk_proto(job_pb2.Job.DESCRIPTOR, "D", "per-job", seen, out)
    for f in dataclasses.fields(ChassisConfig):
        if f.name in ("profile", "device"):
            continue
        default = None if f.default is dataclasses.MISSING else f.default
        out.append(SchemaField(f"ChassisConfig.{f.name}", "ChassisConfig", f.name, "E", _type_name(f.type),
                               default, f.default is dataclasses.MISSING, False, {}, [], "restart"))
    for d in _LIVE_PROTOS:
        _walk_proto(d, "E", "live", seen, out)
    return tuple(out)


def schema_fields() -> list[SchemaField]:
    """Every field of every layer, discovered from the code."""
    return list(_schema_fields())


@functools.cache
def _explanations() -> dict[str, dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for path in sorted(EXPLANATIONS_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for model, entries in data.items():
            merged.setdefault(model, {}).update(entries or {})
    return merged


def _entry(raw: Any) -> dict[str, Any]:
    return {"summary": raw} if isinstance(raw, str) else dict(raw or {})


@functools.cache
def _build() -> dict[str, Any]:
    expl = _explanations()
    fields_out: list[dict[str, Any]] = []
    models: dict[str, dict[str, Any]] = {}
    known: set[tuple[str, str]] = set()
    for f in schema_fields():
        known.add((f.model, f.field))
        e = _entry(expl.get(f.model, {}).get(f.field))
        if f.model not in models:
            about = _entry(expl.get(f.model, {}).get("_about"))
            models[f.model] = {"name": f.model, "layer": f.layer, "summary": about.get("summary", ""),
                               "detail": about.get("detail", ""), "source": about.get("source", ""), "fields": []}
        models[f.model]["fields"].append(f.key)
        fields_out.append({
            **dataclasses.asdict(f),
            "unit": e.get("unit", _unit(f.field)),
            "summary": e.get("summary", ""),
            "detail": e.get("detail", ""),
            "equation": e.get("equation", ""),
            "source": e.get("source", ""),
            "inert": bool(e.get("inert", False)),
            "apply": e.get("apply", f.apply),
        })
    known_models = {m for m, _ in known}
    orphans = [f"{m}.{k}" for m, entries in expl.items() for k in entries
               if k != "_about" and (m, k) not in known]
    orphans += [f"{m}._about" for m in expl if m not in known_models]
    return {"layers": LAYERS, "apply_modes": APPLY_MODES, "models": models, "fields": fields_out,
            "orphans": orphans}


def build_registry() -> dict[str, Any]:
    """The registry as JSON-ready data: layers, models, fields (with explanations), orphan explanations."""
    return _build()
