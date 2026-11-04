"""One round on the virtual board: the program runs, the chip answers, the buffers fill in shot order.

``Round`` is what the board's readout hardware holds while a program runs: the shot counter
(``get_tproc_counter``), each readout's accumulated buffer (a ring of ``avg_maxlen`` I/Q sums, as the
streamer reads it) and decimated buffer (``buf_maxlen`` samples, filled once). The chassis may run far
ahead of a client's reads, so every sum is kept and the ring is a view of the latest ones: a slow reader
gets the data a fast board's streamer would have, never an overflow. A worker thread runs the
round: the interpreter, the translation, then the chassis jobs; results arrive per program point and are
written back in the order the board would have taken the shots, so the counter only ever counts shots
whose data is in the buffers.

ADC units. The chassis integrates the window it simulated (a boxcar sum, in model units). The board's
values are ADC counts: each decimated sample is the window's mean over its span times
``ADC_COUNTS_PER_UNIT``, plus the readout's fixed offset (``iq_offset``, which qick subtracts again),
truncated to an integer as the firmware's arithmetic does; the accumulated value is their sum.
"""
from __future__ import annotations

import asyncio
import math
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from fractions import Fraction
from typing import TYPE_CHECKING, Any

import numpy as np

from qcss.boards.qick.tproc_v1 import COUNTER_ADDR
from qcss.boards.qick.tproc_v1 import run as run_v1
from qcss.boards.qick.tproc_v2_run import run
from qcss.boards.qick.translate import Translation, translate
from qcss.config.profile import HardwareProfile
from qcss.core.ndarray import from_proto
from qcss.ir.program import ChannelBinding
from qcss.v1 import job_pb2, result_pb2

if TYPE_CHECKING:
    from qcss.boards.qick.soc import BoardState

ADC_COUNTS_PER_UNIT = 100.0      # model field units -> ADC counts per decimated sample; verified: false


class ChassisLink:
    """The board's way into the chassis: submit a job, stream its result chunks."""

    def __init__(self, jobs: Any, loop: asyncio.AbstractEventLoop, bindings: Mapping[str, ChannelBinding],
                 profile: HardwareProfile, loopback: Mapping[int, int] | None = None) -> None:
        self.jobs, self.loop, self.bindings, self.profile = jobs, loop, bindings, profile
        self.loopback = dict(loopback or {})          # bench test cables: generator -> readout

    def run(self, job: job_pb2.Job, on_chunk: Callable[[result_pb2.ResultChunk], None]) -> None:
        """Run one job to its end (blocking; call from a thread other than the chassis loop)."""
        asyncio.run_coroutine_threadsafe(self._run(job, on_chunk), self.loop).result()

    async def _run(self, job: job_pb2.Job, on_chunk: Callable[[result_pb2.ResultChunk], None]) -> None:
        job_id = await self.jobs.submit(job)
        async for chunk in self.jobs.results(job_id):
            on_chunk(chunk)
        st = self.jobs.status(job_id)
        if st.state != result_pb2.JOB_STATE_COMPLETED:
            raise RuntimeError(st.message or "the program did not complete")


def ro_offset(ro_cfg: Mapping[str, Any], pfb: Mapping[str, Any] | None) -> float:
    """The DC offset on each decimated I and Q sample (qick's ``_ro_offset``, which the client removes)."""
    off = float(ro_cfg.get("iq_offset", 0.0))
    if pfb is not None and "pfb_ch" in pfb and pfb.get("f_int") == (pfb["pfb_ch"] % 2) * (2 ** ro_cfg["b_dds"] // 2):
        off *= 2
    return off


@dataclass
class Round:
    total: int                                        # shots the program will count
    acc: dict[int, list[tuple[int, int]]]             # readout -> every (I, Q) sum, in read order
    avg_maxlen: dict[int, int]
    dec: dict[int, np.ndarray]                        # readout -> (I, Q) int16 decimated samples
    counter: int = 0
    done: bool = False
    error: BaseException | None = None
    dec_written: dict[int, int] = field(default_factory=dict)
    cond: threading.Condition = field(default_factory=threading.Condition)
    t_start: float = field(default_factory=time.time)
    # streaming readout (start_readout / poll_data)
    stream: tuple[int, list[int], list[int]] | None = None    # (total, ch_list, reads_per_shot)
    streamed: int = 0

    def ring(self, ch: int, address: int, length: int) -> np.ndarray:
        """``length`` entries of readout ``ch``'s accumulated ring from ``address``, as the DMA reads them."""
        hist, size = self.acc[ch], self.avg_maxlen[ch]
        out = np.zeros((length, 2), dtype=np.int32)
        written = len(hist)
        for i in range(length):
            pos = (address + i) % size
            if written > pos:
                out[i] = hist[pos + size * ((written - 1 - pos) // size)]
        return out

    def history(self, ch: int, start: int, length: int) -> np.ndarray:
        return np.asarray(self.acc[ch][start:start + length], dtype=np.int32).reshape(-1, 2)

    def wait(self, pred: Callable[[], bool], timeout: float | None) -> bool:
        with self.cond:
            return self.cond.wait_for(lambda: pred() or self.error is not None or self.done, timeout)


def _adc(z: complex, n_fine: int, dt_ns: float, n_dec: int, offset: float) -> tuple[int, int]:
    mean = z / (n_fine * dt_ns) * ADC_COUNTS_PER_UNIT              # per decimated sample
    return (math.floor(n_dec * (mean.real + offset)), math.floor(n_dec * (mean.imag + offset)))


def _decimate(trace: np.ndarray, n_dec: int, offset: float) -> np.ndarray:
    """A fine trace binned into ``n_dec`` decimated samples, in ADC counts."""
    bins = np.minimum((np.arange(len(trace)) * n_dec) // max(len(trace), 1), n_dec - 1)
    cnt = np.bincount(bins, minlength=n_dec)
    i = np.bincount(bins, weights=np.real(trace), minlength=n_dec) / np.maximum(cnt, 1)
    q = np.bincount(bins, weights=np.imag(trace), minlength=n_dec) / np.maximum(cnt, 1)
    out = np.stack([i, q], axis=1) * ADC_COUNTS_PER_UNIT + offset
    return np.clip(np.floor(out), -32768, 32767).astype(np.int16)


def start_round(state: BoardState, link: ChassisLink | None, on_error: Callable[[BaseException], None] | None = None,
                max_steps: int = 200_000_000) -> Round:
    """Start the loaded program; returns at once, the round fills in a worker thread."""
    ros = state.readouts
    rnd = Round(0, {i: [] for i in range(len(ros))}, {i: int(r.cfg["avg_maxlen"]) for i, r in enumerate(ros)},
                {i: np.zeros((int(r.cfg["buf_maxlen"]), 2), dtype=np.int16) for i, r in enumerate(ros)})
    binprog = state.binprog
    tproc = state.tproc_cfg

    def work() -> None:
        try:
            if tproc["type"] == "axis_tproc64x32_x8":
                trace = run_v1(binprog, [g.cfg for g in state.gens], max_steps=max_steps)
            else:
                trace = run(binprog, f_core=tproc.get("f_core", 200.0), f_time=tproc["f_time"], max_steps=max_steps)
            with rnd.cond:
                rnd.total = len(trace.shots)
            if link is None:                          # nothing to measure: the shots happen, the buffers stay
                _count_all(rnd, trace.counter(COUNTER_ADDR))
                return
            tr = translate(trace, state, link.bindings, link.profile, link.loopback)
            _execute(rnd, tr, state, link)
        except BaseException as exc:                  # noqa: BLE001 - surfaces through the board's RPCs
            with rnd.cond:
                rnd.error = exc
                rnd.cond.notify_all()
            if on_error is not None:
                on_error(exc)
        finally:
            with rnd.cond:
                rnd.done = True
                rnd.cond.notify_all()

    threading.Thread(target=work, name="qick-round", daemon=True).start()
    return rnd


def _count_all(rnd: Round, n: int) -> None:
    with rnd.cond:
        rnd.counter = n
        rnd.cond.notify_all()


def _execute(rnd: Round, tr: Translation, state: BoardState, link: ChassisLink) -> None:
    tick_hz = Fraction(link.profile.clock.tick_hz)
    ros = state.readouts
    fine_ticks = int(tick_hz / Fraction(str(state.gens[-1].cfg["fs"])) / 10 ** 6)      # the readout's sample
    dt_ns = float(Fraction(fine_ticks) / tick_hz * 10 ** 9)
    dec_ticks = {i: tick_hz / Fraction(str(r.cfg["f_output"])) / 10 ** 6 for i, r in enumerate(ros)}
    offsets = {i: ro_offset(r.cfg, r.pfb) for i, r in enumerate(ros)}
    n_dec = {i: int((r.avg or {}).get("length", 0)) for i, r in enumerate(ros)}
    results: dict[tuple[int, int], dict[str, list[Any]]] = {}     # (job, point) -> key -> per-shot values
    arrived: dict[tuple[int, int], int] = {}
    next_shot = 0

    def place(shot: int) -> None:
        j, p, occ = tr.shots[shot]
        res = results.get((j, p), {})
        for read in tr.reads[j][p]:
            v = tr.cabled[shot][read.key] if read.cabled else res[read.key][occ]
            ch = read.ro_ch
            if isinstance(v, np.ndarray):            # a raw window: the decimated buffer, and its sum
                d = _decimate(v, n_dec[ch], offsets[ch])
                w = rnd.dec_written.get(ch, 0)
                room = max(0, len(rnd.dec[ch]) - w)
                rnd.dec[ch][w:w + min(room, len(d))] = d[:room]
                rnd.dec_written[ch] = w + min(room, len(d))
                acc = (int(d[:, 0].astype(np.int64).sum()), int(d[:, 1].astype(np.int64).sum()))
            else:
                n_fine = max(1, int(n_dec[ch] * dec_ticks[ch]) // fine_ticks)
                acc = _adc(complex(v), n_fine, dt_ns, n_dec[ch], offsets[ch])
            rnd.acc[ch].append(acc)

    # a point the chassis reads nothing from (no readout, or only cabled ones) has its shots at once:
    # its chunks report no shots, so waiting for them would never end
    for j, flags in enumerate(tr.chassis_reads):
        for p, reads_chip in enumerate(flags):
            if not reads_chip:
                arrived[(j, p)] = len(tr.shots)

    def flush() -> None:
        nonlocal next_shot
        with rnd.cond:
            while next_shot < len(tr.shots):
                jj, pp, occ = tr.shots[next_shot]
                if arrived.get((jj, pp), 0) <= occ:
                    break
                place(next_shot)
                next_shot += 1
            rnd.counter = next_shot
            rnd.cond.notify_all()

    def on_chunk(j: int, chunk: result_pb2.ResultChunk) -> None:
        p = int(chunk.sweep_point[0])
        res = results.setdefault((j, p), {})
        for a in chunk.acquisitions:
            vals = from_proto(a.iq)
            res.setdefault(a.result_key, []).extend(list(vals))
        if tr.chassis_reads[j][p]:
            arrived[(j, p)] = arrived.get((j, p), 0) + int(chunk.num_shots_in_chunk)
        flush()

    flush()                                           # shots that wait on no chip measurement
    for j, job in enumerate(tr.jobs):
        if any(tr.chassis_reads[j]):                  # a job with nothing to read is not worth running
            link.run(job, lambda c, j=j: on_chunk(j, c))
    flush()
    if next_shot < len(tr.shots):
        raise RuntimeError(f"the round ended after {next_shot} of {len(tr.shots)} shots")
