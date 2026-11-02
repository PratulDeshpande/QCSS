"""How the technician puts a calibration in place: whole sets only, and only physically possible ones (M1, M2)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from qcss.technician import Technician, calibration_set_digest


def _params(amplitude: float = 0.5, duration: float = 40, frequency: float = 5.0e9) -> dict:
    return {
        "settings": {"nshots": 1000, "relaxation_time": 300000},
        "configs": {"0/drive": {"kind": "iq", "frequency": frequency}},
        "native_gates": {"single_qubit": {"0": {"RX": [["0/drive", {
            "kind": "pulse", "duration": duration, "amplitude": amplitude,
            "envelope": {"kind": "gaussian", "rel_sigma": 0.2}, "relative_phase": 0.0}]]}}},
    }


def _write_set(folder: Path, params: dict, calibration: dict) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "parameters.json").write_text(json.dumps(params), encoding="utf-8")
    (folder / "calibration.json").write_text(json.dumps(calibration), encoding="utf-8")


@pytest.fixture
def tech(tmp_path) -> Technician:
    _write_set(tmp_path / "platforms" / "p", _params(), {"single_qubits": {"0": {"t1": [20e-6, 1e-6]}}})
    return Technician(tmp_path / "platforms", "p", reports=tmp_path / "reports")


def test_a_failed_second_replace_rolls_back_to_the_old_set(tech, tmp_path, monkeypatch):
    new = tmp_path / "new"
    _write_set(new, _params(amplitude=0.6), {"single_qubits": {"0": {"t1": [25e-6, 1e-6]}}})
    before = calibration_set_digest(tech.platform_dir)
    real_replace = os.replace

    def flaky_replace(src, dst):
        if Path(dst).name == "calibration.json" and ".bak" not in str(src):
            raise PermissionError("calibration.json is open in another process")
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    with pytest.raises(PermissionError):
        tech._install(new)
    monkeypatch.setattr(os, "replace", real_replace)
    assert calibration_set_digest(tech.platform_dir) == before               # never a mixed set
    assert sorted(os.listdir(tech.platform_dir)) == ["calibration.json", "parameters.json"]   # no debris


def test_a_whole_set_is_installed_and_no_staging_files_are_left(tech, tmp_path):
    new = tmp_path / "new"
    _write_set(new, _params(amplitude=0.6), {"single_qubits": {}})
    assert sorted(tech._install(new)) == ["calibration.json", "parameters.json"]
    assert json.loads((tech.platform_dir / "parameters.json").read_text(encoding="utf-8")) == _params(amplitude=0.6)
    assert sorted(os.listdir(tech.platform_dir)) == ["calibration.json", "parameters.json"]


@pytest.mark.parametrize("bad, why", [
    (_params(amplitude=1.4), "amplitude"),             # beyond full scale: Qibolab would clip it
    (_params(amplitude=float("nan")), "NaN"),
    (_params(duration=0), "duration"),
    (_params(frequency=-3e9), "frequency"),
])
def test_a_physically_impossible_fit_is_refused(tech, tmp_path, bad, why):
    new = tmp_path / "new"
    new.mkdir()
    (new / "parameters.json").write_text(json.dumps(bad), encoding="utf-8")   # json writes NaN as NaN
    ok, message = tech._plausible(new)
    assert not ok
    assert why in message


def test_a_sound_fit_is_accepted(tech, tmp_path):
    new = tmp_path / "new"
    new.mkdir()
    (new / "parameters.json").write_text(json.dumps(_params(amplitude=-0.7)), encoding="utf-8")
    assert tech._plausible(new) == (True, "")
