"""The virtual technician: real Qibocal calibrates the platform against the chassis, and only Qibocal writes it."""
from __future__ import annotations

import json
import os
import shutil
from collections.abc import Iterator

import pytest

pytest.importorskip("qibocal", reason="the qibocal extra is not installed")

from qcss.technician import Technician, calibration_set_digest
from tests.integration.test_admin_cli import _ChassisThread
from tests.integration.test_grpc_end_to_end import _can_connect_loopback

RABI = """platform: qcss_qblox_5q
targets: [0]
actions:
  - id: rabi
    operation: rabi_amplitude
    parameters:
      min_amp: 0.0
      max_amp: {max_amp}
      step_amp: {step_amp}
      nshots: 1000
      relaxation_time: 300000
"""


@pytest.fixture
def lab(tmp_path) -> Iterator[tuple[_ChassisThread, Technician, float]]:
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    platforms = tmp_path / "platforms"
    shutil.copytree("platforms/qcss_qblox_5q", platforms / "qcss_qblox_5q")
    params = platforms / "qcss_qblox_5q" / "parameters.json"
    data = json.loads(params.read_text(encoding="utf-8"))
    right = data["native_gates"]["single_qubit"]["0"]["RX"][0][1]["amplitude"]
    for gate, scale in (("RX", 0.8), ("RX90", 0.8)):                      # a drifted, miscalibrated pi pulse
        data["native_gates"]["single_qubit"]["0"][gate][0][1]["amplitude"] *= scale
    params.write_text(json.dumps(data, indent=2), encoding="utf-8")
    with _ChassisThread(str(tmp_path)) as chassis:
        tech = Technician(platforms, "qcss_qblox_5q", reports=tmp_path / "reports",
                          env={"QCSS_QBLOX_5Q_ADDRESS": str(chassis.chassis.config.lab_address)})
        yield chassis, tech, right


def test_qibocal_recalibrates_the_pi_pulse_and_the_calibration_set_changes(lab, tmp_path):
    _, tech, right = lab
    before = calibration_set_digest(tech.platform_dir)
    runcard = tmp_path / "rabi.yml"
    runcard.write_text(RABI.format(max_amp=round(min(0.95, 1.8 * right), 4), step_amp=round(0.05 * right, 4)),
                       encoding="utf-8")                   # Qibolab caps amplitudes at full scale
    outcome = tech.calibrate(runcard)
    assert outcome.ok, outcome.log
    params = json.loads((tech.platform_dir / "parameters.json").read_text(encoding="utf-8"))
    fitted = params["native_gates"]["single_qubit"]["0"]["RX"][0][1]["amplitude"]
    assert fitted == pytest.approx(right, rel=0.07)                     # back to a pi pulse
    assert calibration_set_digest(tech.platform_dir) != before
    assert sorted(os.listdir(tech.platform_dir)) == sorted(outcome.files_after)   # nothing half-written left


def test_a_failed_calibration_leaves_the_platform_as_it_was(lab, tmp_path):
    _, tech, _ = lab
    before = calibration_set_digest(tech.platform_dir)
    runcard = tmp_path / "bad.yml"
    runcard.write_text("platform: qcss_qblox_5q\ntargets: [0]\nactions:\n  - id: x\n    operation: no_such_routine\n",
                       encoding="utf-8")
    outcome = tech.calibrate(runcard)
    assert not outcome.ok
    assert calibration_set_digest(tech.platform_dir) == before
