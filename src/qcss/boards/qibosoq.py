"""A Qibosoq-compatible board: QCSS behind the TCP/JSON protocol of a qibosoq server on an RFSoC.

Qibolab's own RFSoC driver talks to it unchanged, so a lab platform differs from this one
only by the board's address. Everything here follows qibosoq (main @2c37627) and QICK:

- framing: a 4-byte big-endian length and a JSON request; the JSON reply, then the board
  closes the connection; a failure is answered with the traceback string;
- timing in microseconds, as start delays relative to the previous element's start, snapped
  to the tProc cycle; waveforms in whole 16-sample fabric cycles;
- frequencies in MHz, synthesised directly (no LO); amplitudes as gains (fractions of full
  scale); phases in degrees;
- envelopes as qibosoq hands them to QICK, quirks included: sigma = n / rel_sigma * sqrt(2);
- results: per ADC, per readout, then per sweep point and per shot, each I/Q the window mean
  (QICK's accumulated sum over the window length); averaged when cfg.average is set.
"""
from __future__ import annotations

import asyncio
import contextlib
import itertools
import json
import math
import socket
import struct
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from qcss.config.profile import HardwareProfile
from qcss.core.errors import QCSSError
from qcss.core.ndarray import from_proto, to_proto
from qcss.ir.program import ChannelBinding, ChannelKind
from qcss.v1 import job_pb2, result_pb2

EXECUTE_PULSE_SEQUENCE, EXECUTE_PULSE_SEQUENCE_RAW, EXECUTE_SWEEPS = 1, 2, 3
FABRIC_SAMPLES = 16             # one full-speed DAC fabric cycle
_SWEEP_FIELDS = {"freq": "frequency", "gain": "amplitude", "phase": "relative_phase", "t": "start_delay",
                 "duration": "duration"}
MAX_REQUEST_BYTES = 16 << 20    # the lab link's gRPC message cap: neither face takes a larger request
MAX_PROGRAM_ELEMENTS = 1 << 18  # sweep points x sequence elements: ~50 B each, so a job stays under 16 MiB
REQUEST_TIMEOUT_S = 30.0        # a client sends its whole request at once; one that stalls is dropped


class BoardResourcesExceeded(QCSSError):
    """A request larger than the board can hold. On the wire only the board's own words are sent."""


@dataclass(frozen=True)
class BoardWiring:
    """Which chassis channel each DAC drives and each ADC reads."""
    dac: Mapping[int, ChannelBinding]
    adc: Mapping[int, ChannelBinding]

    @classmethod
    def from_bindings(cls, bindings: Mapping[str, ChannelBinding]) -> BoardWiring:
        dac, adc = {}, {}
        for b in bindings.values():
            if b.kind in (ChannelKind.DRIVE, ChannelKind.FLUX) and b.port_id.startswith("dac"):
                dac[int(b.port_id.removeprefix("dac"))] = b
            elif b.kind is ChannelKind.READOUT:
                adc[b.qubits[0]] = b                       # ADC n reads qubit n's resonator
        return cls(dac, adc)


@dataclass
class BoardJob:
    job: job_pb2.Job
    readout_keys: list[str]                                # in reply order: by ADC, then sequence order
    readout_adcs: list[int]
    windows: dict[str, int] = field(default_factory=dict)  # result key -> decimated samples in the window
    sweep_shape: tuple[int, ...] = ()
    average: bool = False


def _envelope(el: Mapping[str, Any], n: int) -> np.ndarray:
    """The waveform QICK plays for one element, peak 1 (the gain scales it)."""
    shape = el.get("shape", "rectangular")
    x = np.arange(n)
    if shape == "rectangular":
        return np.ones(n, dtype=np.complex128)
    if shape in ("gaussian", "drag"):
        si, mu = n / el["rel_sigma"] * math.sqrt(2), n / 2 - 0.5
        g = np.exp(-(x - mu) ** 2 / (2 * si ** 2))
        if shape == "gaussian":
            return g.astype(np.complex128)
        # QICK DRAG with det = 0 and delta = -fs/2 (qibosoq): Q = -alpha * dG / (2 pi delta), in samples
        dg = -(x - mu) / si ** 2 * g
        return g + 1j * (-el["beta"] * dg / (2 * math.pi * -0.5))
    if shape == "flattop":
        half = n // 2                                      # qibosoq: Gaussian ramps of n/2, flat for n/2
        si, mu = half / el["rel_sigma"] * math.sqrt(2), half / 2 - 0.5
        ramp = np.exp(-(np.arange(half) - mu) ** 2 / (2 * si ** 2))
        k = half // 2
        return np.concatenate([ramp[:k], np.ones(n - 2 * k), ramp[k:2 * k]]).astype(np.complex128)
    if shape == "hann":
        return (np.sin(np.pi * np.arange(0, 1, 1 / n)) ** 2).astype(np.complex128)
    if shape == "fluxexponential":
        v = np.exp(-x / el["upsilon"]) + el["weight"] * np.exp(-x / el["tau"])
        return (v / (1 + el["weight"])).astype(np.complex128)
    if shape == "arbitrary":
        i, q = np.asarray(el["i_values"], dtype=float), np.asarray(el["q_values"], dtype=float)
        if len(i) != n or len(q) != n:
            raise ValueError(f"arbitrary pulse '{el.get('name')}': {len(i)} samples, the pulse needs {n}")
        return i + 1j * q
    raise ValueError(f"pulse shape '{shape}' is not supported by this board")


def request_to_job(data: Mapping[str, Any], wiring: BoardWiring, profile: HardwareProfile) -> BoardJob:
    """One qibosoq request as one chassis job (each sweep point its own program)."""
    op = int(data["operation_code"])
    if op == EXECUTE_PULSE_SEQUENCE_RAW:
        raise NotImplementedError("decimated (raw) acquisition is not supported by this board")
    if op not in (EXECUTE_PULSE_SEQUENCE, EXECUTE_SWEEPS):
        raise NotImplementedError(f"Operation code {op} not supported")
    for q in data.get("qubits", []):
        if q.get("bias"):
            raise ValueError(f"DC bias {q['bias']} on dac {q.get('dac')}: flux bias is not supported by this board")
    cfg = data["cfg"]
    tick_hz = float(profile.clock.tick_hz)
    gen = profile.generators[0]
    grid_ticks = gen.rt_granularity_ticks
    sample_rate = float(gen.sample_rate_hz)
    acq = profile.acquisition

    def ticks(us: float) -> int:
        return round(us * 1e-6 * tick_hz / grid_ticks) * grid_ticks

    job = job_pb2.Job(num_shots=int(cfg["reps"]), repetition_delay_ticks=round(float(cfg["relaxation_time"]) *
                                                                                 1e-6 * tick_hz))
    sequence = list(data["sequence"])
    readouts = sorted((k for k, el in enumerate(sequence) if el["type"] == "readout"),
                      key=lambda k: (sequence[k]["adc"], k))
    keys = {k: f"r{n}" for n, k in enumerate(readouts)}

    sweepers = list(data.get("sweepers") or [])
    shape = tuple(int(sw["expts"]) for sw in sweepers)
    if any(n < 1 for n in shape):
        raise ValueError(f"sweep of {shape} points: a sweep needs at least one point")
    if math.prod(shape) * max(1, len(sequence)) > MAX_PROGRAM_ELEMENTS:   # checked before anything is built
        raise BoardResourcesExceeded(f"{math.prod(shape)} sweep points x {len(sequence)} elements")
    axes = []
    for sw in sweepers:
        vals = [np.linspace(a, b, int(sw["expts"])) for a, b in zip(sw["starts"], sw["stops"], strict=True)]
        for p in sw["parameters"]:
            if p == "bias":
                raise ValueError("sweeping the DC bias is not supported by this board")
            if p not in _SWEEP_FIELDS:
                raise ValueError(f"sweep parameter '{p}' is not supported by this board")
        axes.append((sw, vals))
    windows: dict[str, int] = {}
    wf: dict[bytes, str] = {}

    for idx in itertools.product(*(range(n) for n in shape)):
        seq = [dict(el) for el in sequence]
        for (sw, vals), i in zip(axes, idx, strict=True):
            for p, el_idx, v in zip(sw["parameters"], sw["indexes"], vals, strict=True):
                seq[el_idx][_SWEEP_FIELDS[p]] = float(v[i])
        ins = job.program_points.add(indices=list(idx)).main.instructions
        t_us = 0.0
        for k, el in enumerate(seq):
            t_us += float(el["start_delay"])
            t = ticks(t_us)
            if el["type"] == "readout":
                ro = wiring.adc.get(int(el["adc"]))
                if ro is None:
                    raise ValueError(f"adc {el['adc']} is not connected")
                n_dec = max(1, round(ticks(float(el["duration"])) / acq.integration_granularity_ticks))
                windows[keys[k]] = n_dec
                ins.add(start_tick=t, set_frequency=job_pb2.SetFrequency(
                    frame_id=ro.frame_id, frequency_hz=float(el["frequency"]) * 1e6))
                ins.add(start_tick=t, acquire=job_pb2.Acquire(
                    channel_id=ro.channel_id, integration_ticks=n_dec * acq.integration_granularity_ticks,
                    mode=job_pb2.ACQUISITION_MODE_INTEGRATED, register_index=len(windows) % 8, result_key=keys[k]))
                continue
            b = wiring.dac.get(int(el["dac"]))
            if b is None:
                raise ValueError(f"dac {el['dac']} is not connected")
            n = max(FABRIC_SAMPLES, round(float(el["duration"]) * 1e-6 * sample_rate / FABRIC_SAMPLES)
                    * FABRIC_SAMPLES)
            samples = _envelope(el, n)
            key = samples.tobytes()
            if key not in wf:
                wf[key] = f"w{len(wf)}"
                job.waveform_library[wf[key]].CopyFrom(job_pb2.Waveform(
                    shape=job_pb2.WAVEFORM_SHAPE_ARBITRARY, samples=to_proto(samples), length_samples=n))
            if b.kind is ChannelKind.DRIVE:
                ins.add(start_tick=t, set_frequency=job_pb2.SetFrequency(
                    frame_id=b.frame_id, frequency_hz=float(el["frequency"]) * 1e6))
            ins.add(start_tick=t, play=job_pb2.Play(
                channel_id=b.channel_id, waveform_id=wf[key], amplitude=float(el["amplitude"]),
                phase_offset_rad=math.radians(float(el["relative_phase"]))))
    return BoardJob(job, [keys[k] for k in readouts], [int(sequence[k]["adc"]) for k in readouts], windows, shape,
                    bool(cfg.get("average", False)))


def board_reply(chunks: Iterable[result_pb2.ResultChunk], bj: BoardJob) -> dict[str, list]:
    """Chassis results as a qibosoq server returns them: {"i": [adc][readout]..., "q": ...}."""
    shots: dict[str, dict[tuple[int, ...], list[tuple[int, np.ndarray]]]] = {}
    for c in chunks:
        for a in c.acquisitions:
            shots.setdefault(a.result_key, {}).setdefault(tuple(c.sweep_point), []).append(
                (c.shot_offset, np.asarray(from_proto(a.iq))))
    points = list(itertools.product(*(range(n) for n in bj.sweep_shape)))
    per_adc: dict[int, list[np.ndarray]] = {}
    for key, adc in zip(bj.readout_keys, bj.readout_adcs, strict=True):
        rows = [np.concatenate([v for _, v in sorted(shots.get(key, {}).get(p, []), key=lambda t: t[0])])
                / bj.windows[key] for p in points]
        data = np.stack(rows) if bj.sweep_shape else rows[0]       # (points, reps) or (reps,)
        if bj.average:
            data = data.mean(axis=-1)
        per_adc.setdefault(adc, []).append(data)
    adcs = sorted(per_adc)
    return {"i": [[np.real(d).tolist() for d in per_adc[a]] for a in adcs],
            "q": [[np.imag(d).tolist() for d in per_adc[a]] for a in adcs]}


def _board_error(exc: Exception) -> str:
    if isinstance(exc, QCSSError) and not isinstance(exc, ValueError):
        return "RuntimeError: the sequence exceeds the board's resources"
    return f"{type(exc).__name__ if type(exc).__module__ == 'builtins' else 'RuntimeError'}: {exc}"


def _reset(writer: asyncio.StreamWriter) -> None:
    """Abort the connection with a TCP reset, not an orderly close: the client sees ConnectionResetError
    (what a board that reboots or loses its link gives), not an empty reply it would fail to parse."""
    sock = writer.get_extra_info("socket")
    if sock is not None:
        with contextlib.suppress(OSError):
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
    writer.transport.abort()
    # Windows' proactor transport shuts the socket down (an orderly FIN) before closing it, so the client
    # would read EOF first. Closing the raw socket now, linger 0, sends the reset; the transport then
    # finds it closed and skips its shutdown. Without the attribute the drop is an orderly close.
    raw = getattr(writer.transport, "_sock", None)
    if isinstance(raw, socket.socket):
        with contextlib.suppress(OSError):
            raw.close()


class QibosoqBoard:
    """The board's TCP server. One request per connection, as the qibosoq server handles them."""

    def __init__(self, jobs: Any, wiring: BoardWiring, profile: HardwareProfile, faults: Any = None,
                 request_timeout_s: float = REQUEST_TIMEOUT_S) -> None:
        self._jobs, self._wiring, self._profile, self._faults = jobs, wiring, profile, faults
        self._timeout = request_timeout_s
        self._server: asyncio.base_events.Server | None = None

    async def start(self, address: str) -> None:
        host, port = address.rsplit(":", 1)
        self._server = await asyncio.start_server(self._handle, host, int(port))

    async def stop(self) -> None:
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            if self._faults is not None and not await self._faults.admit(uploads=True):
                _reset(writer)                               # the board drops the connection, as a reboot does
                return
            try:
                async with asyncio.timeout(self._timeout):    # bounds the read only, never the run
                    count = int.from_bytes(await reader.readexactly(4), "big")
                    body = await reader.readexactly(count) if count <= MAX_REQUEST_BYTES else None
            except TimeoutError:
                return                                       # a stalled client is dropped
            try:
                if body is None:                             # refused unread: never buffer an unbounded body
                    raise BoardResourcesExceeded(f"a request of {count} bytes")
                reply: Any = await self._execute(json.loads(body))
            except Exception as exc:                         # noqa: BLE001 - a board answers with the error
                reply = _board_error(exc)                        # the board's words, not the simulator's
            writer.write(json.dumps(reply).encode("utf-8"))
            await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    async def _execute(self, data: Mapping[str, Any]) -> dict[str, list]:
        bj = request_to_job(data, self._wiring, self._profile)
        job_id = await self._jobs.submit(bj.job)
        chunks = [c async for c in self._jobs.results(job_id)]
        st = self._jobs.status(job_id)
        if st.state != result_pb2.JOB_STATE_COMPLETED:
            raise RuntimeError(f"exception in readout loop: {st.message}")
        return board_reply(chunks, bj)
