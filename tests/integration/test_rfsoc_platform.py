"""Qibolab's own RFSoC driver on a QCSS board: the platform differs from a lab's only by the board address."""
from __future__ import annotations

import os
import pathlib
from collections.abc import Iterator

import numpy as np
import pytest

pytest.importorskip("qibolab", reason="the qibolab extra is not installed")
pytest.importorskip("qibosoq", reason="qibosoq is not installed")

from qibolab import AcquisitionType, AveragingMode, Parameter, Sweeper, create_platform

from tests.integration.test_grpc_end_to_end import _can_connect_loopback
from tests.integration.test_qibosoq_board_server import _Board

PLATFORMS = os.path.abspath("platforms")


@pytest.fixture(scope="module")
def platform() -> Iterator:
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    with _Board() as board:
        old = {k: os.environ.get(k) for k in ("QIBOLAB_PLATFORMS", "QCSS_RFSOC_5Q_ADDRESS")}
        os.environ["QIBOLAB_PLATFORMS"] = PLATFORMS
        os.environ["QCSS_RFSOC_5Q_ADDRESS"] = f"127.0.0.1:{board.port}"
        try:
            p = create_platform("qcss_rfsoc_5q")
            p.connect()
            yield p
            p.disconnect()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def test_the_platform_names_no_simulator():
    """Its platform.py is a stock Qibolab RFSoC platform: the stock driver and a board address."""
    src = (pathlib.Path(PLATFORMS) / "qcss_rfsoc_5q" / "platform.py").read_text(encoding="utf-8")
    assert "from qibolab.instruments.qibosoq import RFSoC" in src
    assert "qcss_qibolab" not in src and "QcssController" not in src


def test_a_rabi_sweep_through_qibolabs_rfsoc_driver(platform):
    natives = platform.natives.single_qubit[0]
    rx = natives.RX()
    seq = rx | natives.MZ()
    pulse = next(p for _, p in rx)
    sweep = Sweeper(parameter=Parameter.amplitude, values=np.linspace(0, min(1.0, pulse.amplitude * 1.6), 9),
                    pulses=[pulse])
    acq = next(r for _, r in seq.acquisitions)
    res = platform.execute([seq], [[sweep]], nshots=300, acquisition_type=AcquisitionType.INTEGRATION,
                           averaging_mode=AveragingMode.CYCLIC)[acq.id]
    assert res.shape == (9, 2)
    signal = np.abs((res[:, 0] + 1j * res[:, 1]) - (res[0, 0] + 1j * res[0, 1]))
    assert signal.argmax() not in (0,) and signal.max() > 5 * signal[1:3].min()       # a Rabi oscillation


def test_single_shots_are_discriminated_by_the_driver_with_the_platform_threshold(platform):
    natives = platform.natives.single_qubit[0]
    ground, excited = natives.MZ(), natives.RX() | natives.MZ()
    p = []
    for seq in (ground, excited):
        acq = next(r for _, r in seq.acquisitions)
        res = platform.execute([seq], nshots=400, acquisition_type=AcquisitionType.DISCRIMINATION,
                               averaging_mode=AveragingMode.CYCLIC)[acq.id]
        p.append(float(res))
    assert p[0] < 0.15 and p[1] > 0.8, p
