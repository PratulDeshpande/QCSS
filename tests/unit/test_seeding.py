"""Unit tests for deterministic seeding streams."""
from __future__ import annotations

import numpy as np
import pytest

from qcss.core.seeding import Domain, chunks, job_key, stim_seed, stream


def _draw(n_workers: int) -> np.ndarray:
    key = job_key(None, "job-42")
    parts = {}
    work = chunks(2500)
    for w in range(n_workers):
        for ci, n in work[w::n_workers]:
            parts[ci] = stream(7, key, Domain.SHOTS, 0, ci).random(n)
    return np.concatenate([parts[i] for i in sorted(parts)])


def test_chunk_invariance():
    assert np.array_equal(_draw(1), _draw(4))


def test_same_key_same_stream():
    key = job_key(42, "job-abc")
    s1 = stream(123, key, Domain.SHOTS, 1, 2).random(10)
    s2 = stream(123, key, Domain.SHOTS, 1, 2).random(10)
    assert np.array_equal(s1, s2)


def test_negative_rejected():
    with pytest.raises(ValueError, match="non-negative"):
        job_key(-5, "job-x")
    with pytest.raises(ValueError, match="non-negative"):
        stream(-1, 10, Domain.SHOTS, 0, 0)


def test_stim_seed_deterministic():
    s1 = stim_seed(100, 200, 0, 1)
    s2 = stim_seed(100, 200, 0, 1)
    assert s1 == s2
    assert s1 >= 0


def test_a_chassis_without_a_seed_draws_one_from_entropy():
    from qcss.core.seeding import chassis_seed
    assert chassis_seed(7) == 7
    drawn = {chassis_seed(None) for _ in range(4)}
    assert len(drawn) == 4 and all(s >= 0 for s in drawn)
