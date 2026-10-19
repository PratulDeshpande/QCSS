"""Unit tests for port IQ rendering and saturation check."""
from __future__ import annotations

import numpy as np

from qcss.config.profile import SaturationPolicy
from qcss.ir.saturation import check as check_saturation
from qcss.ir.saturation import render_port_iq


def test_render_port_iq():
    fs = 1e9  # 1 GS/s
    n = 100
    env = np.ones(50, dtype=np.complex128)
    # Play at start sample 10 with amp 0.5, IF 100 MHz, phi0 = 0
    plays = [(10, env, 0.5, 100e6, 0.0)]
    stream = render_port_iq(n, fs, plays)

    assert len(stream) == 100
    assert np.all(stream[:10] == 0.0)
    assert np.all(stream[60:] == 0.0)
    assert np.max(np.abs(stream[10:60])) <= 0.50001


def test_saturation_reject():
    x = np.array([0.5 + 0.5j, 1.2 + 0.2j], dtype=np.complex128)
    _out, errors, _warnings = check_saturation(x, full_scale=1.0, policy=SaturationPolicy.REJECT, port_id="port_0")
    assert len(errors) == 1
    assert "exceeds full scale" in errors[0]


def test_saturation_clip():
    x = np.array([0.5 + 0.5j, 1.5 - 2.0j], dtype=np.complex128)
    clipped, errors, warnings = check_saturation(x, full_scale=1.0, policy=SaturationPolicy.CLIP, port_id="port_0")
    assert len(errors) == 0
    assert len(warnings) == 1
    assert np.max(np.abs(np.real(clipped))) <= 1.0
    assert np.max(np.abs(np.imag(clipped))) <= 1.0
    assert clipped[1].real == 1.0
    assert clipped[1].imag == -1.0


def test_saturation_wrap():
    x = np.array([1.2 + 0.0j], dtype=np.complex128)
    wrapped, errors, warnings = check_saturation(x, full_scale=1.0, policy=SaturationPolicy.WRAP, port_id="port_0")
    assert len(errors) == 0
    assert len(warnings) == 1
    # Wrapped: (1.2 + 1.0) % 2 - 1 = 0.2 - 1 = -0.8
    assert np.isclose(wrapped[0].real, -0.8)
