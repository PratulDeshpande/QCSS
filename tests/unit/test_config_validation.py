"""A profile or device file with an impossible value is refused when loaded, with the field named."""
from __future__ import annotations

import copy
from typing import Any

import pytest
from pydantic import ValidationError

from qcss.config.device import DeviceSpec
from qcss.config.loader import load_yaml
from qcss.config.profile import HardwareProfile
from tests.conftest import PROFILES_DIR, REPO_ROOT

PROFILE = load_yaml(PROFILES_DIR / "qblox_cluster_5q.yaml")
DEVICE = load_yaml(REPO_ROOT / "src" / "qcss" / "config" / "devices" / "transmon_5q.yaml")


def _profile(edit) -> dict[str, Any]:
    d = copy.deepcopy(PROFILE)
    edit(d)
    return d


def _device(edit) -> dict[str, Any]:
    d = copy.deepcopy(DEVICE)
    edit(d)
    return d


def test_the_shipped_files_are_valid():
    HardwareProfile.model_validate(PROFILE)
    DeviceSpec.model_validate(DEVICE)


@pytest.mark.parametrize("name, edit, match", [
    ("bad clock", lambda d: d["clock"].update(tick_hz="fast"), "tick_hz"),
    ("zero clock", lambda d: d["clock"].update(tick_hz="0"), "tick_hz"),
    ("bad sample rate", lambda d: d["generators"][0].update(sample_rate_hz="-1"), "sample_rate_hz"),
    ("duplicate generator", lambda d: d["generators"][1].update(generator_id=d["generators"][0]["generator_id"]),
     "duplicate"),
    ("duplicate port", lambda d: d["ports"][1].update(port_id=d["ports"][0]["port_id"]), "duplicate"),
    ("unknown port kind", lambda d: d["ports"][0].update(kind="quantum"), "kind"),
    ("inverted nco range", lambda d: d["generators"][0].update(nco_freq_range_hz=[5e8, -5e8]), "nco_freq_range"),
    ("latency to nowhere", lambda d: d["feedback"]["latencies"][0].update(dst="nope"), "latency"),
    ("unknown convention", lambda d: d["acquisition"].update(integration_convention="median"), "convention"),
])
def test_a_bad_profile_is_refused(name, edit, match):
    with pytest.raises(ValidationError, match=match):
        HardwareProfile.model_validate(_profile(edit))


@pytest.mark.parametrize("name, edit, match", [
    ("duplicate qubit", lambda d: d["qubits"][1].update(qubit_index=d["qubits"][0]["qubit_index"]), "duplicate"),
    ("resonator for no qubit", lambda d: d["resonators"][0].update(qubit_index=99), "no qubit"),
    ("negative temperature", lambda d: d["qubits"][0].update(t_eff_mk=-5, p_excited=None), "t_eff_mk"),
    ("population above one", lambda d: d["qubits"][0].update(p_excited=1.5, t_eff_mk=None), "p_excited"),
    ("efficiency above one", lambda d: d["resonators"][0].update(eta=1.5), "eta"),
    ("asymmetry above one", lambda d: d["qubits"][0].update(d_asym=2.0), "d_asym"),
])
def test_a_bad_device_is_refused(name, edit, match):
    with pytest.raises(ValidationError, match=match):
        DeviceSpec.model_validate(_device(edit))


def test_the_cli_names_the_bad_field_instead_of_dumping_a_traceback(tmp_path):
    from click.testing import CliRunner

    from qcss.cli import app
    bad = tmp_path / "bad.yaml"
    bad.write_text("clock: {tick_hz: fast}\n")
    result = CliRunner().invoke(app, ["validate", "examples/jobs/pi_q0.json", "--profile", str(bad)])
    assert result.exit_code == 1 and "tick_hz" in result.output and "Traceback" not in result.output
    assert not isinstance(result.exception, ValidationError)
