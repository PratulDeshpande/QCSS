"""The parameter registry: every configurable field of every layer is described for the UI."""
from __future__ import annotations

from qcss_dashboard.registry import LAYERS, build_registry, schema_fields


def test_schema_walk_finds_fields_of_every_layer():
    keys = {f.key for f in schema_fields()}
    assert "QubitSpec.t1_us" in keys                      # B: device truth (pydantic)
    assert "GeneratorSpec.nco_grid_ticks" in keys          # A: hardware profile (pydantic)
    assert "QubitCalibration.drive_frequency_hz" in keys  # C: calibration (proto)
    assert "Job.num_shots" in keys                         # D: job (proto)
    assert "ChassisConfig.time_scale" in keys              # E: chassis (dataclass)
    assert "Mode.tier_policy" in keys                      # E: live admin mode (proto)


def test_schema_walk_records_defaults_and_constraints():
    by_key = {f.key: f for f in schema_fields()}
    t1 = by_key["QubitSpec.t1_us"]
    assert t1.required and t1.constraints == {"gt": 0}
    assert by_key["ResonatorSpec.eta"].default == 0.4
    assert by_key["PortSpec.max_generators"].constraints.get("ge") == 1


def test_every_field_has_an_explanation():
    """Adding a config field without explaining it fails CI: the UI never shows an undocumented knob."""
    reg = build_registry()
    missing = [f["key"] for f in reg["fields"] if not f.get("summary")]
    assert missing == []


def test_every_explanation_names_a_real_field():
    reg = build_registry()
    assert reg["orphans"] == []


def test_fields_carry_layer_unit_and_apply_mode():
    reg = {f["key"]: f for f in build_registry()["fields"]}
    t1 = reg["QubitSpec.t1_us"]
    assert t1["layer"] == "B" and t1["unit"] == "µs" and t1["apply"] == "restart"
    assert reg["QubitCalibration.drive_frequency_hz"]["apply"] == "next-job"
    assert reg["Job.num_shots"]["apply"] == "per-job"
    assert reg["Mode.time_scale"]["apply"] == "live"
    assert {layer["id"] for layer in LAYERS} >= {"A", "B", "C", "D", "E"}


def test_inert_fields_are_flagged():
    reg = {f["key"]: f for f in build_registry()["fields"]}
    for key in ("GeneratorSpec.nco_count", "DeviceSpec.m_dc", "FeedbackSpec.trigger_grid_ticks",
                "QubitCalibration.pi_amplitude", "QubitCalibration.readout_mixer"):
        assert reg[key]["inert"], key
    assert not reg["QubitSpec.t1_us"]["inert"]
