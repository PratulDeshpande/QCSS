"""Config store: read shipped profiles and devices, validate drafts, diff them, save copies in the user workspace."""
from __future__ import annotations

import pytest
import yaml

from qcss_dashboard.configs import ConfigError, ConfigStore


@pytest.fixture
def store(tmp_path) -> ConfigStore:
    return ConfigStore(tmp_path)


def test_lists_shipped_profiles_and_devices(store):
    assert {"qblox_cluster_5q", "qick_zcu216_5q", "zi_shfqc_5q"} <= {c["name"] for c in store.list("profile")}
    assert "transmon_5q" in {c["name"] for c in store.list("device")}
    assert all(c["source"] == "builtin" for c in store.list("device"))


def test_read_reports_unverified_blocks_of_a_profile(store):
    out = store.read("profile", "qblox_cluster_5q")
    assert out["data"]["profile_name"] == "qblox_cluster_5q"
    assert out["yaml"].startswith(("#", "profile_name", "vendor")) or "profile_name" in out["yaml"]
    assert isinstance(out["unverified"], list) and out["unverified"]


def test_validate_reports_pydantic_errors_with_locations(store):
    text = store.read("device", "transmon_5q")["yaml"]
    data = yaml.safe_load(text)
    data["qubits"][0]["t2_star_us"] = 10 * data["qubits"][0]["t1_us"]          # T2* > 2 T1 is unphysical
    res = store.validate("device", yaml.safe_dump(data))
    assert not res["ok"]
    assert any("T2*" in e["msg"] for e in res["errors"])


def test_validate_rejects_non_mapping_yaml(store):
    res = store.validate("profile", "- just\n- a list\n")
    assert not res["ok"] and res["errors"]


def test_diff_maps_changed_values_to_registry_keys(store):
    base = store.read("device", "transmon_5q")
    data = yaml.safe_load(base["yaml"])
    old = data["qubits"][1]["t1_us"]
    data["qubits"][1]["t1_us"] = old * 2
    d = store.diff("device", "transmon_5q", yaml.safe_dump(data))
    change = next(c for c in d["changes"] if c["path"] == "qubits[1].t1_us")
    assert change["before"] == old and change["after"] == old * 2
    assert change["key"] == "QubitSpec.t1_us"
    assert "t1_us" in d["unified"]


def test_save_writes_a_user_copy_and_lists_it(store, tmp_path):
    text = store.read("device", "transmon_5q")["yaml"]
    store.save("device", "my_chip", text)
    assert (tmp_path / "configs" / "devices" / "my_chip.yaml").exists()
    assert {"name": "my_chip", "source": "user"} in [{k: c[k] for k in ("name", "source")} for c in store.list("device")]
    assert store.load_device("my_chip").device_name


def test_save_refuses_builtin_names_invalid_names_and_invalid_content(store):
    text = store.read("device", "transmon_5q")["yaml"]
    with pytest.raises(ConfigError):
        store.save("device", "transmon_5q", text)          # never shadow or overwrite a shipped file
    with pytest.raises(ConfigError):
        store.save("device", "../escape", text)
    with pytest.raises(ConfigError):
        store.save("device", "broken", "qubits: 3\n")


def test_unknown_kind_and_name_are_errors(store):
    with pytest.raises(ConfigError):
        store.list("chip")
    with pytest.raises(ConfigError):
        store.read("profile", "no_such_profile")
