"""Execution takes wall time like an instrument: upload latency, then shots paced by lab time / time_scale."""
from __future__ import annotations

import asyncio
import time

import pytest

from qcss.timing.instrument_time import InstrumentPacer

pytestmark = pytest.mark.anyio


async def test_a_job_lasts_its_lab_time_divided_by_the_time_scale():
    pacer = InstrumentPacer(lambda: 10.0, upload_median_s=0.0)
    cancel = asyncio.Event()
    t0 = time.monotonic()
    run = await pacer.begin(cancel)
    await run.pace(3.0, cancel)                    # 3 lab seconds at 10x = 0.3 wall seconds
    assert 0.28 <= time.monotonic() - t0 < 0.6


async def test_a_zero_time_scale_does_not_pace():
    pacer = InstrumentPacer(lambda: 0.0, upload_median_s=1.0)
    cancel = asyncio.Event()
    t0 = time.monotonic()
    run = await pacer.begin(cancel)
    await run.pace(1000.0, cancel)
    assert time.monotonic() - t0 < 0.1


async def test_upload_latency_is_paid_once_per_job():
    pacer = InstrumentPacer(lambda: 1.0, upload_median_s=0.2, upload_sigma_ln=0.0)
    cancel = asyncio.Event()
    t0 = time.monotonic()
    run = await pacer.begin(cancel)
    assert 0.18 <= time.monotonic() - t0 < 0.4
    await run.pace(0.0, cancel)
    assert time.monotonic() - t0 < 0.4


async def test_cancel_cuts_the_wait_short():
    pacer = InstrumentPacer(lambda: 1.0, upload_median_s=0.0)
    cancel = asyncio.Event()
    run = await pacer.begin(cancel)
    asyncio.get_running_loop().call_later(0.1, cancel.set)
    t0 = time.monotonic()
    await run.pace(30.0, cancel)
    assert time.monotonic() - t0 < 0.5
