"""Integer-tick time model.

Every time value inside QCSS is an ``int`` number of ticks of ONE profile clock
(``tick_hz``). The tick is chosen so that every clock in the impersonated stack
(DAC sample clocks, sequencer clocks, NCO grids, trigger grids) is an integer
number of ticks. Nanoseconds appear only at API edges and in reports.
"""
from __future__ import annotations

from dataclasses import dataclass
from fractions import Fraction
from math import gcd, lcm

from qcss.core.errors import TimebaseError


def _as_fraction_hz(rate_hz: float | Fraction | str) -> Fraction:
    # Fraction(str) is exact for decimal strings such as "430.08e6"; floats are
    # limited to a sane denominator so 2.4e9 does not become a 52-bit monster.
    if isinstance(rate_hz, Fraction):
        return rate_hz
    if isinstance(rate_hz, str):
        # Handle scientific notation in strings like "1e9" or "430.08e6"
        if "e" in rate_hz.lower():
            f_val = float(rate_hz)
            return Fraction(f_val).limit_denominator(1_000_000_000)
        return Fraction(rate_hz)
    return Fraction(rate_hz).limit_denominator(1_000_000_000)


@dataclass(frozen=True, slots=True)
class TimeBase:
    """A clock whose period is the indivisible unit of simulated time."""

    tick_hz: Fraction

    @classmethod
    def from_clocks(cls, *clock_rates_hz: float | str | Fraction) -> TimeBase:
        """Smallest tick rate that is an integer multiple of every clock rate.

        Example: Qblox (1 GS/s)                     -> 1 GHz tick (1 ns)
                 ZI HDAWG 2.4 GSa/s + 300 MHz seq   -> 2.4 GHz tick
                 ZI SHFQC+ SG 2 GSa/s + HDAWG 2.4   -> 12 GHz tick
                 QICK t_clk 430.08 MHz + gen 599.04 MHz -> 16773.12 MHz tick (39 and 28 ticks)
        """
        if not clock_rates_hz:
            raise TimebaseError("at least one clock rate is required")
        fr = [_as_fraction_hz(r) for r in clock_rates_hz]
        # LCM of rationals p_i/q_i = lcm(p_i) / gcd(q_i) when reduced.
        num = lcm(*(f.numerator for f in fr))
        den = 0
        for f in fr:
            den = gcd(den, f.denominator)
        return cls(Fraction(num, den))

    @property
    def tick_s(self) -> Fraction:
        return 1 / self.tick_hz

    def ticks_per(self, clock_hz: float | str | Fraction) -> int:
        """Ticks in one period of ``clock_hz`` (must be exact)."""
        q = self.tick_hz / _as_fraction_hz(clock_hz)
        if q.denominator != 1:
            raise TimebaseError(f"clock {clock_hz} Hz is not commensurate with tick {self.tick_hz} Hz")
        return int(q)

    def ns_to_ticks(self, ns: float | Fraction, *, exact: bool = True) -> int:
        q = Fraction(ns).limit_denominator(10**9) * self.tick_hz / 10**9
        if q.denominator != 1:
            if exact:
                raise TimebaseError(f"{ns} ns is not an integer number of ticks ({float(q):.6f})")
            return round(q)
        return int(q)

    def ticks_to_ns(self, ticks: int) -> float:
        return float(Fraction(ticks) * 10**9 / self.tick_hz)

    def samples_to_ticks(self, n_samples: int, sample_rate_hz: float | str | Fraction) -> int:
        return n_samples * self.ticks_per(sample_rate_hz)

    def ticks_to_samples(self, ticks: int, sample_rate_hz: float | str | Fraction) -> int:
        per = self.ticks_per(sample_rate_hz)
        if ticks % per:
            raise TimebaseError(f"{ticks} ticks is not a whole number of samples at {sample_rate_hz} Hz")
        return ticks // per
