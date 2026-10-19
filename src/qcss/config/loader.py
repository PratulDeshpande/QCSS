"""YAML configuration loader with provenance checking."""
from __future__ import annotations

import pathlib
from typing import Any

import yaml

from qcss.config.device import DeviceSpec
from qcss.config.profile import HardwareProfile


def load_yaml(path: str | pathlib.Path) -> dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_profile(path: str | pathlib.Path) -> HardwareProfile:
    data = load_yaml(path)
    return HardwareProfile.model_validate(data)


def load_device(path: str | pathlib.Path) -> DeviceSpec:
    data = load_yaml(path)
    return DeviceSpec.model_validate(data)


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
