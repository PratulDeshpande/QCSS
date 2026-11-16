"""Self-test for the notebook helpers: the lab starts as its own process, answers, and goes away.

Run: uv run python -m pytest notebooks/test_helpers.py
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import _lab  # noqa: E402
import _proof  # noqa: E402


def test_lab_starts_reads_truth_and_stops():
    lab = _lab.start(seed=7)
    try:
        truth = lab.truth()
        assert len(truth) == 5 and all(q["frequency_hz"] > 1e9 and q["t1_s"] > 0 for q in truth)
        assert "f01" in lab.admin("truth")
    finally:
        lab.stop()
    assert not any(_lab._port_open(p) for p in lab.ports)


def test_truth_table_fails_outside_tolerance():
    _proof.truth_table([("ok", 1.01, 1.0, 0.05)])
    with pytest.raises(AssertionError, match="bad"):
        _proof.truth_table([("bad", 1.2, 1.0, 0.05)])


def test_result_shape_checks_shape_and_dtype():
    _proof.result_shape("iq", np.zeros((2, 10)), (2, 10), np.floating)
    with pytest.raises(AssertionError):
        _proof.result_shape("iq", np.zeros(3), (2, 10))
