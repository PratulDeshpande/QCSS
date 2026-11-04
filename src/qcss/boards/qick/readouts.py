"""Readout register models: what a readout channel was configured to capture.

A PFB readout output (``axis_pfb_readout_v4``) is configured by ``config_mux_readout``: the client's
config dict per output port carries the frequency it downconverts (``f_rounded``, MHz, the requested
frequency after rounding to the PFB's DDS grid). Its average buffer (``config_avg``) sets the window:
``length`` decimated samples at the PFB output rate (``f_output``), starting at the readout trigger.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from qcss.boards.qick.soc import ReadoutState


@dataclass(frozen=True)
class Readout:
    freq_hz: float | None             # None: never configured (it captures, but nothing is downconverted)
    sample_rate_hz: float             # decimated samples per second
    length: int                       # decimated samples per window (accumulated buffer)
    edge_counting: bool = False

    @property
    def window_s(self) -> float:
        return self.length / self.sample_rate_hz


def readout_of(ro: ReadoutState) -> Readout:
    cfg = ro.cfg
    src = ro.pfb if ro.pfb is not None else ro.regs if isinstance(ro.regs, dict) else None
    freq = None if src is None or src.get("f_rounded") is None else float(src["f_rounded"]) * 1e6
    avg = ro.avg or {}
    return Readout(freq, float(cfg["f_output"]) * 1e6, int(avg.get("length", 0)), bool(avg.get("edge_counting")))
