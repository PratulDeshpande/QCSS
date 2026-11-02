"""The board face of a chassis, driven by qibosoq's own client over TCP, as Qibolab's RFSoC driver does."""
from __future__ import annotations

import asyncio
import threading
from collections.abc import Iterator
from typing import Self

import numpy as np
import pytest

from qcss.chassis import Chassis, ChassisConfig
from qcss.config.loader import load_device, load_profile
from tests.integration.test_admin_cli import TEST_CHIP_SEED
from tests.integration.test_grpc_end_to_end import _can_connect_loopback, _free_port
from tests.unit.test_qibosoq_board import drive, readout, request

client = pytest.importorskip("qibosoq.client", reason="qibosoq is not installed")


class _Board:
    def __init__(self) -> None:
        self.port = _free_port()
        self.chassis = Chassis(ChassisConfig(
            profile=load_profile("src/qcss/config/profiles/qick_zcu216_5q.yaml"),
            device=load_device("src/qcss/config/devices/transmon_5q.yaml"),
            lab_address=f"127.0.0.1:{_free_port()}", board_address=f"127.0.0.1:{self.port}", time_scale=0.0,
            seed=TEST_CHIP_SEED))
        self._loop = asyncio.new_event_loop()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self.chassis.start())
        self._ready.set()
        self._loop.run_forever()

    def __enter__(self) -> Self:
        self._thread.start()
        assert self._ready.wait(10)
        return self

    def __exit__(self, *exc: object) -> None:
        asyncio.run_coroutine_threadsafe(self.chassis.stop(), self._loop).result(10)
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(10)


@pytest.fixture(scope="module")
def board() -> Iterator[_Board]:
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    with _Board() as b:
        yield b


def test_the_qibosoq_client_gets_shots_nested_per_adc_and_readout(board):
    i, q = client.connect(request([drive(), readout()], reps=50), "127.0.0.1", board.port)
    assert np.asarray(i).shape == (1, 1, 50) == np.asarray(q).shape


def test_a_gain_sweep_returns_one_row_per_point_and_drives_the_qubit(board):
    sw = {"expts": 5, "parameters": ["gain"], "indexes": [0], "starts": [0.0], "stops": [1.0]}
    i, q = client.connect(request([drive(), readout()], [sw], average=True, reps=200), "127.0.0.1", board.port)
    z = np.asarray(i)[0, 0] + 1j * np.asarray(q)[0, 0]
    assert z.shape == (5,)
    assert np.ptp(np.abs(z - z[0])) > 0                     # the readout signal follows the drive


def test_a_bad_request_is_answered_with_the_boards_traceback(board):
    data = request([drive(dac=13), readout()])
    with pytest.raises(client.QibosoqError, match="dac 13 is not connected"):
        client.connect(data, "127.0.0.1", board.port)


def test_a_dropped_connection_reaches_the_client(board):
    from qcss.admin.v1 import admin_pb2 as apb
    assert board.chassis.faults is not None
    board.chassis.faults.inject(apb.INSTRUMENT_FAULT_DROP, 1)
    with pytest.raises(ConnectionError):                 # a reset, as a rebooting board gives - not a bad reply (M4)
        client.connect(request([drive(), readout()], reps=10), "127.0.0.1", board.port)
    client.connect(request([drive(), readout()], reps=10), "127.0.0.1", board.port)
