"""Unit tests for hardware profiles and loader."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from qcss.config.loader import get_unverified_fields
from qcss.config.profile import (
    AcqMode,
    AcquisitionSpec,
    ClockSpec,
    FeedbackSpec,
    GeneratorSpec,
    HardwareProfile,
    PortSpec,
)


def test_generator_cap(qblox_profile):
    """A Qblox module has 6 sequencers (a cluster has many modules)."""
    per_module: dict[str, int] = {}
    for g in qblox_profile.generators:
        per_module[g.module_id] = per_module.get(g.module_id, 0) + 1
    assert per_module and max(per_module.values()) <= 6


def test_generator_cap_exceeded():
    # If 2 generators reference a port with max_generators=1, validation error
    port = PortSpec(port_id="p0", kind="rf_iq", max_generators=1)
    g1 = GeneratorSpec(generator_id="g1", port_id="p0", sample_rate_hz="1e9",
                       rt_granularity_ticks=1, rt_min_duration_ticks=4, wave_mem_samples=1000, instr_mem=1000)
    g2 = GeneratorSpec(generator_id="g2", port_id="p0", sample_rate_hz="1e9",
                       rt_granularity_ticks=1, rt_min_duration_ticks=4, wave_mem_samples=1000, instr_mem=1000)
    clock = ClockSpec(tick_hz="1e9")
    acq = AcquisitionSpec(modes=(AcqMode.RAW_TRACE,))
    fb = FeedbackSpec(latencies=())

    with pytest.raises(ValidationError, match="max 1"):
        HardwareProfile(
            profile_name="test", vendor="test", clock=clock,
            ports=(port,), generators=(g1, g2), acquisition=acq, feedback=fb
        )


def test_unverified_listed(qblox_profile):
    unverified = get_unverified_fields(qblox_profile)
    # qcm_rf0_out0 saturation is marked verified: false
    assert any("qcm_rf0_out0" in u for u in unverified)
