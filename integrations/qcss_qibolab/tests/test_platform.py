"""The QCSS platforms, loaded and run through Qibolab exactly as a lab's platform is."""
from __future__ import annotations

import pytest

pytest.importorskip("qibolab", reason="the qibolab extra is not installed")

import os
from collections.abc import Iterator

import numpy as np
from qibolab import AcquisitionType, AveragingMode, Parameter, Sweeper, create_platform

from tests.integration.test_admin_cli import _ChassisThread
from tests.integration.test_grpc_end_to_end import _can_connect_loopback

PLATFORMS = os.path.abspath("platforms")


@pytest.fixture(scope="module")
def platform(tmp_path_factory) -> Iterator:
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    with _ChassisThread(str(tmp_path_factory.mktemp("chassis"))) as chassis:
        old = {k: os.environ.get(k) for k in ("QIBOLAB_PLATFORMS", "QCSS_QBLOX_5Q_ADDRESS")}
        os.environ["QIBOLAB_PLATFORMS"] = PLATFORMS
        os.environ["QCSS_QBLOX_5Q_ADDRESS"] = chassis.chassis.config.lab_address
        try:
            p = create_platform("qcss_qblox_5q")
            p.connect()
            yield p
            p.disconnect()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


def test_a_rabi_amplitude_sweep_through_qibolab(platform):
    natives = platform.natives.single_qubit[0]
    rx = natives.RX()
    seq = rx | natives.MZ()
    pulse = next(p for _, p in rx)
    sweep = Sweeper(parameter=Parameter.amplitude, values=np.linspace(0, pulse.amplitude * 1.6, 9), pulses=[pulse])
    acq = next(r for _, r in seq.acquisitions)
    res = platform.execute([seq], [[sweep]], nshots=300, acquisition_type=AcquisitionType.DISCRIMINATION,
                           averaging_mode=AveragingMode.CYCLIC)[acq.id]
    assert res.shape == (9,)
    assert res[0] < 0.1 and res.max() > 0.85               # ground, then the qubit is driven to |1>


def test_a_circuit_runs_through_qibolabs_compiler_on_the_lab_natives(platform):
    from qibo import Circuit, gates
    from qibolab._core.backends import QibolabBackend
    backend = QibolabBackend(platform)
    c = Circuit(5, wire_names=[0, 1, 2, 3, 4])
    c.add(gates.GPI(0, 0.0))                              # X, as a transpiled circuit reaches the platform
    c.add(gates.M(0, 1))
    freqs: dict[str, int] = dict(backend.execute_circuit(c, nshots=500).frequencies())
    assert freqs.get("10", 0) / 500 > 0.85                # clbit order as Qibo prints it: q0 then q1
