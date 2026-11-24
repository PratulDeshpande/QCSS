"""YAML configuration loader with provenance checking."""
from __future__ import annotations

import pathlib
from typing import Any

import click
import yaml
from pydantic import BaseModel, ValidationError

from qcss.config.device import DeviceSpec
from qcss.config.profile import HardwareProfile


def load_yaml(path: str | pathlib.Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _validated[M: BaseModel](model: type[M], path: str | pathlib.Path) -> M:
    try:
        return model.model_validate(load_yaml(path))
    except ValidationError as err:
        lines = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in err.errors()]
        raise click.ClickException(f"{path} is not a valid {model.__name__}:\n  " + "\n  ".join(lines)) from err
    except yaml.YAMLError as err:
        raise click.ClickException(f"{path} is not valid YAML: {err}") from err


def load_profile(path: str | pathlib.Path) -> HardwareProfile:
    return _validated(HardwareProfile, path)


def load_device(path: str | pathlib.Path) -> DeviceSpec:
    return _validated(DeviceSpec, path)


def get_unverified_fields(profile: HardwareProfile) -> list[str]:
    """Return all fields in the profile marked with verified: false."""
    unverified = []
    if not profile.clock.provenance.verified:
        unverified.append("clock")
    for p in profile.ports:
        if not p.provenance.verified:
            unverified.append(f"port[{p.port_id}]")
    for g in profile.generators:
        if not g.provenance.verified:
            unverified.append(f"generator[{g.generator_id}]")
    if not profile.acquisition.provenance.verified:
        unverified.append("acquisition")
    for i, lat in enumerate(profile.feedback.latencies):
        if not lat.provenance.verified:
            unverified.append(f"feedback.latency[{i}] ({lat.src}->{lat.dst})")
    return unverified
