"""Host-boundary latency emulation (virtual time stays exact, host latency injected at RPC edges)."""
from __future__ import annotations

import asyncio

import numpy as np


class HostLatency:
    """Log-normal queue/RPC latency injected at the RPC boundary only."""

    def __init__(self, median_ms: float = 1.0, sigma_ln: float = 0.3, rng: np.random.Generator | None = None) -> None:
        self.mu = np.log(max(1e-3, median_ms))
        self.s = sigma_ln
        self.rng = rng if rng is not None else np.random.default_rng()

    async def delay(self) -> float:
        """Sample log-normal latency in milliseconds, yield to event loop via asyncio.sleep, and return ms."""
        ms = float(np.exp(self.mu + self.s * self.rng.standard_normal()))
        await asyncio.sleep(ms / 1000.0)  # yields without blocking GIL
        return ms
