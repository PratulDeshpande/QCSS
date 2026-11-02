"""Acceptance through the path Quark's Qibolab adapter takes (L7 LLD 7.4): physical QASM in, counts out."""
from __future__ import annotations

import json
import os
import shutil
import time
from collections.abc import Iterator

import pytest
from click.testing import CliRunner

pytest.importorskip("qibolab", reason="the qibolab extra is not installed")

from qcss.cli import app
from tests.integration.test_admin_cli import TOKEN, _ChassisThread
from tests.integration.test_grpc_end_to_end import _can_connect_loopback
from tests.virtual_lab.harness import CalibrationSetStale, QibolabAdapter

pytestmark = pytest.mark.virtual_lab

BIT_ORDER = """OPENQASM 3.0;
bit[2] a;
bit[2] b;
x $0;
x $1;
a[0] = measure $0;
a[1] = measure $1;
b[0] = measure $2;
b[1] = measure $3;
"""

ONE = "OPENQASM 3.0;\nbit[1] c;\n"
X0 = ONE + "x $0;\nc[0] = measure $0;\n"
MIN_FRACTION = 0.8              # the platform holds its last-cooldown calibration, not a fresh one


@pytest.fixture
def lab(tmp_path) -> Iterator[tuple[QibolabAdapter, _ChassisThread]]:
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    shutil.copytree("platforms/qcss_qblox_5q", tmp_path / "platforms" / "qcss_qblox_5q")
    with _ChassisThread(str(tmp_path)) as chassis:
        old = {k: os.environ.get(k) for k in ("QIBOLAB_PLATFORMS", "QCSS_QBLOX_5Q_ADDRESS")}
        os.environ["QIBOLAB_PLATFORMS"] = str(tmp_path / "platforms")
        os.environ["QCSS_QBLOX_5Q_ADDRESS"] = str(chassis.chassis.config.lab_address)
        try:
            a = QibolabAdapter("qcss_qblox_5q", tmp_path / "platforms")
            yield a, chassis
            a.close()
        finally:
            for k, v in old.items():
                if v is None:
                    os.environ.pop(k, None)
                else:
                    os.environ[k] = v


@pytest.fixture
def adapter(lab) -> QibolabAdapter:
    return lab[0]


def _admin(chassis: _ChassisThread, *args: str) -> None:
    r = CliRunner().invoke(app, ["admin", *args, "--target", str(chassis.admin), "--token", TOKEN])
    assert r.exit_code == 0, r.output


def _frac(counts: dict[str, int], key: str) -> float:
    return counts.get(key, 0) / max(1, sum(counts.values()))


# Gate checks, ported from the integrations/quark_qcss conformance run (L3) to the Qibolab path.
def test_x_reads_1(adapter):
    c = adapter.run(X0, shots=300, calibration_set=adapter.calibration_set())
    assert _frac(c, "1") >= MIN_FRACTION, c


def test_idle_reads_0(adapter):
    c = adapter.run(ONE + "c[0] = measure $0;\n", shots=300, calibration_set=adapter.calibration_set())
    assert _frac(c, "0") >= MIN_FRACTION, c


def test_two_sx_read_1_and_a_virtual_z_between_them_undoes_it(adapter):
    cs = adapter.calibration_set()
    c1 = adapter.run(ONE + "sx $0;\nsx $0;\nc[0] = measure $0;\n", shots=300, calibration_set=cs)
    c2 = adapter.run(ONE + "sx $0;\nrz(pi) $0;\nsx $0;\nc[0] = measure $0;\n", shots=300, calibration_set=cs)
    assert _frac(c1, "1") >= MIN_FRACTION, c1
    assert _frac(c2, "0") >= MIN_FRACTION, c2


def test_simultaneous_x_and_readout_on_two_qubits(adapter):
    c = adapter.run("OPENQASM 3.0;\nbit[2] c;\nx $0;\nx $1;\nc[0] = measure $0;\nc[1] = measure $1;\n",
                    shots=300, calibration_set=adapter.calibration_set())
    assert _frac(c, "11") >= MIN_FRACTION * MIN_FRACTION, c


def test_a_non_native_gate_is_refused(adapter):
    with pytest.raises(ValueError, match="not a native gate"):
        adapter.run(ONE + "h $0;\nc[0] = measure $0;\n", shots=10, calibration_set=adapter.calibration_set())


def test_bit_order_is_clbit0_rightmost_across_registers(adapter):
    counts = adapter.run(BIT_ORDER, shots=500, calibration_set=adapter.calibration_set())
    top = max(counts, key=lambda k: counts[k])
    assert top == "0011" and counts[top] / 500 > 0.8          # HAL LLD 6.2: b[1] b[0] a[1] a[0]


# Calibration binding.
def test_the_calibration_set_is_stable_while_nobody_recalibrates(adapter):
    before = adapter.calibration_set()
    adapter.run(X0, shots=50, calibration_set=before)
    assert adapter.calibration_set() == before


def test_a_job_pinned_to_a_superseded_calibration_set_is_refused(adapter):
    pinned = adapter.calibration_set()
    params = adapter.platform_dir / "parameters.json"
    data = json.loads(params.read_text(encoding="utf-8"))
    data["settings"]["nshots"] = 2048                           # the lab recalibrated: the set changed
    params.write_text(json.dumps(data, indent=2), encoding="utf-8")
    with pytest.raises(CalibrationSetStale):
        adapter.run(BIT_ORDER, shots=100, calibration_set=pinned)
    adapter.run(BIT_ORDER, shots=100, calibration_set=adapter.calibration_set())     # re-planned: runs


# Realism, driven from the admin channel as an operator would.
def test_a_dead_qubit_collapses_its_outcomes(lab):
    adapter, chassis = lab
    cs = adapter.calibration_set()
    assert _frac(adapter.run(X0, shots=300, calibration_set=cs), "1") >= MIN_FRACTION
    _admin(chassis, "kill", "0")
    c = adapter.run(X0, shots=300, calibration_set=cs)
    assert _frac(c, "1") < 0.2, c                               # it decays before it is read


def test_a_reboot_fails_the_call_and_the_next_job_runs(lab):
    adapter, chassis = lab
    cs = adapter.calibration_set()
    adapter.run(X0, shots=50, calibration_set=cs)               # connected, settings uploaded
    _admin(chassis, "fault", "reboot", "--duration", "0.5")
    with pytest.raises((ConnectionError, RuntimeError)):
        adapter.run(X0, shots=50, calibration_set=cs)
    time.sleep(0.6)
    assert _frac(adapter.run(X0, shots=300, calibration_set=cs), "1") >= MIN_FRACTION
