"""Deterministic random streams.

Streams are keyed by (domain, sweep_index, chunk_index) under a root built from
(global_seed, job_key). Chunks have a FIXED size, so results do not depend on the
number of worker processes or on job arrival order. Never use Python ``hash()``
(randomised per process) and never pass negative integers (SeedSequence rejects
them).
"""
from __future__ import annotations

import hashlib
from enum import IntEnum

import numpy as np

CHUNK_SHOTS = 1024          # fixed; changing it changes golden outputs (by design)
_MASK128 = (1 << 128) - 1


class Domain(IntEnum):
    SHOTS = 1      # physics sampling (measurement outcomes, trajectories)
    READOUT = 2    # amplifier noise, readout T1 jumps
    SIGNAL = 3     # DAC noise, amplitude jitter
    DRIFT = 4      # OU / TLS / 1/f processes (advanced on the LAB clock, not per job)
    BURSTS = 5     # cosmic-ray / gamma Poisson arrivals
    JITTER = 6     # timing jitter
    STIM = 7       # seed passed into stim samplers


def job_key(job_seed: int | None, job_id: str) -> int:
    """Client-supplied seed if present, otherwise a stable 128-bit digest of job_id."""
    if job_seed is not None:
        if job_seed < 0:
            raise ValueError("job seed must be non-negative")
        return job_seed & _MASK128
    digest = hashlib.blake2b(job_id.encode("utf-8"), digest_size=16).digest()
    return int.from_bytes(digest, "little")


def seed_sequence(global_seed: int, key: int, domain: Domain,
                  sweep_index: int = 0, chunk_index: int = 0) -> np.random.SeedSequence:
    if min(global_seed, key, sweep_index, chunk_index) < 0:
        raise ValueError("SeedSequence entropy/spawn_key values must be non-negative")
    return np.random.SeedSequence(entropy=[global_seed, key],
                                  spawn_key=(int(domain), sweep_index, chunk_index))


def stream(global_seed: int, key: int, domain: Domain,
           sweep_index: int = 0, chunk_index: int = 0) -> np.random.Generator:
    """A Generator with the BitGenerator pinned explicitly (PCG64)."""
    ss = seed_sequence(global_seed, key, domain, sweep_index, chunk_index)
    return np.random.Generator(np.random.PCG64(ss))


def stim_seed(global_seed: int, key: int, sweep_index: int, chunk_index: int) -> int:
    """A 63-bit int seed for stim samplers derived from the same tree."""
    ss = seed_sequence(global_seed, key, Domain.STIM, sweep_index, chunk_index)
    return int(ss.generate_state(1, dtype=np.uint64)[0] >> np.uint64(1))


def chunks(num_shots: int, chunk: int = CHUNK_SHOTS) -> list[tuple[int, int]]:
    """[(chunk_index, n_in_chunk), ...] -- independent of pool size."""
    out, i, done = [], 0, 0
    while done < num_shots:
        n = min(chunk, num_shots - done)
        out.append((i, n))
        done += n
        i += 1
    return out
