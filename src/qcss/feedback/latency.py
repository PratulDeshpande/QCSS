"""Feedback latency lookup and readout time of flight, both read from the profile.

Vendor latency figures mean "last ADC sample in -> first conditional DAC sample out";
time of flight (instrument-internal + cable + enabled output filters) and integration are
added separately (FB-05). There is no built-in fallback number: a route the profile does
not list is an error the validator reports.
"""
from __future__ import annotations

import math

import numpy as np

from qcss.config.device import DeviceSpec
from qcss.config.profile import HardwareProfile
from qcss.core.timebase import TimeBase
from qcss.ir.program import ChannelBinding


class LatencyRouteError(KeyError):
    """The profile has no feedback latency for this (source, destination, routing)."""


def lookup_latency(profile: HardwareProfile, src_gen: str, dst_gen: str,
                   payload: str = "bit") -> tuple[int, int]:
    """Most specific matching entry -> (latency_ticks, jitter_ticks)."""
    routing = profile.routing(src_gen, dst_gen)
    best = None
    for e in profile.feedback.latencies:
        if e.payload != payload or e.routing != routing:
            continue
        if e.src not in (src_gen, "*") or e.dst not in (dst_gen, "*"):
            continue
        score = (e.src == src_gen) + (e.dst == dst_gen)
        if best is None or score > best[0]:
            best = (score, e.latency_ticks, e.jitter_ticks)
    if best is None:
        raise LatencyRouteError(f"no feedback latency for {src_gen}->{dst_gen} ({payload}, {routing}) "
                                f"in profile {profile.profile_name}")
    return best[1], best[2]


class FeedbackLatencyResolver:
    def __init__(self, profile: HardwareProfile, rng: np.random.Generator | None = None) -> None:
        self.profile = profile
        self.rng = rng

    def latency_ticks(self, src_gen: str, dst_gen: str, payload: str = "bit") -> int:
        """Latency in ticks; profile jitter (if any) is drawn from the seeded JITTER stream."""
        base, jitter = lookup_latency(self.profile, src_gen, dst_gen, payload)
        if jitter > 0 and self.rng is not None:
            return max(1, base + int(self.rng.integers(-jitter, jitter + 1)))
        return base

    def resolve(self, src_gen: str, dst_gen: str, payload: str = "bit") -> int:
        return self.latency_ticks(src_gen, dst_gen, payload)

    def __call__(self, src_gen: str, dst_gen: str, payload: str = "bit") -> int:
        return self.latency_ticks(src_gen, dst_gen, payload)


def readout_tof_ticks(profile: HardwareProfile, device: DeviceSpec | None, binding: ChannelBinding,
                      timebase: TimeBase) -> int:
    """Instrument-internal ToF + cable delay of the qubit's resonator + output filter latency (ticks)."""
    ticks = profile.acquisition.internal_tof_ticks + profile.port(binding.port_id).output_latency_ticks
    if device is not None and binding.qubits:
        r = device.resonator(binding.qubits[0])
        if r is not None:
            ticks += math.ceil(r.cable_delay_ns * float(timebase.tick_hz) * 1e-9 - 1e-9)
    return ticks
