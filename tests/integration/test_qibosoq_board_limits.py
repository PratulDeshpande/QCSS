"""The board face bounds what one connection can make it hold: request size, read time and program size.

Each limit answers the way a board does (the board's error reply, or a closed connection), so a lab
client sees an instrument's resource limit and nothing else.
"""
from __future__ import annotations

import asyncio
import json
import math
import time

import pytest

from qcss.boards.qibosoq import MAX_PROGRAM_ELEMENTS, MAX_REQUEST_BYTES, QibosoqBoard, request_to_job
from tests.integration.test_grpc_end_to_end import _can_connect_loopback, _free_port
from tests.integration.test_indistinguishability import TELLS
from tests.unit.test_qibosoq_board import PROFILE, WIRING, drive, readout, request

pytestmark = pytest.mark.skipif(not _can_connect_loopback(), reason="loopback sockets not permitted here")


class _NoJobs:
    """No request in these tests should reach the chassis."""

    async def submit(self, job):  # pragma: no cover - reaching it is the failure
        raise AssertionError("an over-limit request reached the chassis")


async def _exchange(payload: bytes, timeout_s: float = 30.0) -> tuple[bytes, float]:
    board = QibosoqBoard(_NoJobs(), WIRING, PROFILE, request_timeout_s=timeout_s)
    port = _free_port()
    await board.start(f"127.0.0.1:{port}")
    try:
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(payload)
        await writer.drain()
        t0 = time.monotonic()
        reply = await asyncio.wait_for(reader.read(), 10)        # the board replies (or not), then closes
        writer.close()
        return reply, time.monotonic() - t0
    finally:
        await board.stop()


def test_a_length_prefix_over_the_cap_is_refused_without_reading_the_body():
    reply, _ = asyncio.run(_exchange((MAX_REQUEST_BYTES + 1).to_bytes(4, "big")))
    text = reply.decode("utf-8")
    assert "exceeds the board's resources" in text and not TELLS.search(text), text


def test_a_client_that_stalls_mid_request_is_disconnected():
    reply, waited = asyncio.run(_exchange((100).to_bytes(4, "big") + b"{", timeout_s=0.3))
    assert reply == b"" and waited < 5


def test_a_sweep_too_large_for_the_board_is_refused_before_it_is_built():
    n = math.isqrt(MAX_PROGRAM_ELEMENTS) + 1                       # n * n points x 2 elements > the cap
    sw = [{"expts": n, "parameters": ["gain"], "indexes": [0], "starts": [0.0], "stops": [1.0]}] * 2
    body = json.dumps(request([drive(), readout()], sw)).encode()
    t0 = time.monotonic()
    reply, _ = asyncio.run(_exchange(len(body).to_bytes(4, "big") + body))
    text = reply.decode("utf-8")
    assert "exceeds the board's resources" in text and not TELLS.search(text), text
    assert time.monotonic() - t0 < 5                               # refused up front, not after building


def test_a_sweep_with_no_points_is_refused():
    sw = [{"expts": 0, "parameters": ["gain"], "indexes": [0], "starts": [0.0], "stops": [1.0]}]
    with pytest.raises(ValueError, match="at least one point"):
        request_to_job(request([drive(), readout()], sw), WIRING, PROFILE)


def test_a_large_but_realistic_sweep_still_runs():
    """A 100 x 100 chevron, the size Qibocal asks for, stays well inside the cap."""
    sw = [{"expts": 100, "parameters": ["gain"], "indexes": [0], "starts": [0.0], "stops": [1.0]},
          {"expts": 100, "parameters": ["freq"], "indexes": [0], "starts": [5000.0], "stops": [5100.0]}]
    bj = request_to_job(request([drive(), readout()], sw), WIRING, PROFILE)
    assert len(bj.job.program_points) == 10_000
