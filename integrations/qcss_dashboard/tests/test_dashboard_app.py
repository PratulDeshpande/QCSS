"""The bridge HTTP API: health, registry, configs, and the guards every mutating call goes through."""
from __future__ import annotations

from fastapi.testclient import TestClient

from qcss_dashboard.app import create_app
from qcss_dashboard.settings import Settings

MUTATE = {"X-QCSS-Dashboard": "1"}


def test_health_reports_version_and_links(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] and body["lab"] is None and body["admin"] is None


def test_registry_endpoint_serves_fields_and_layers(client):
    body = client.get("/api/registry").json()
    assert len(body["fields"]) > 200 and {la["id"] for la in body["layers"]} >= {"A", "B", "C", "D", "E"}


def test_architecture_endpoint_describes_every_layer(client):
    body = client.get("/api/architecture").json()
    ids = {n["id"] for n in body["nodes"]}
    assert {"adapters", "runtime", "compiler", "executor", "render", "parameters", "evolve", "readout"} <= ids
    assert all(n["summary"] and n["packages"] for n in body["nodes"])


def test_config_read_and_validate_round_trip(client):
    cfg = client.get("/api/configs/device/transmon_5q").json()
    r = client.post("/api/configs/device/validate", json={"yaml": cfg["yaml"]}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["ok"]


def test_mutating_calls_need_the_csrf_header(client):
    cfg = client.get("/api/configs/device/transmon_5q").json()
    r = client.put("/api/configs/device/copy1", json={"yaml": cfg["yaml"]})
    assert r.status_code == 403
    r = client.put("/api/configs/device/copy1", json={"yaml": cfg["yaml"]}, headers=MUTATE)
    assert r.status_code == 200


def test_read_only_mode_refuses_writes(tmp_path):
    c = TestClient(base_url="http://127.0.0.1", app=create_app(Settings(workspace=tmp_path, lab_target=None, admin_target=None,
                                       embedded_chassis=False, read_only=True)))
    cfg = c.get("/api/configs/device/transmon_5q").json()
    r = c.put("/api/configs/device/copy1", json={"yaml": cfg["yaml"]}, headers=MUTATE)
    assert r.status_code == 403 and "read-only" in r.json()["detail"]


def test_access_token_guards_every_api_call(tmp_path):
    c = TestClient(base_url="http://127.0.0.1", app=create_app(Settings(workspace=tmp_path, lab_target=None, admin_target=None,
                                       embedded_chassis=False, access_token="s3cret")))
    assert c.get("/api/registry").status_code == 401
    assert c.get("/api/registry", headers={"X-Dashboard-Token": "s3cret"}).status_code == 200
    assert c.get("/api/health").status_code == 200          # health stays open, reveals nothing


def test_tokens_never_appear_in_any_response(tmp_path):
    s = Settings(workspace=tmp_path, lab_target="127.0.0.1:1", admin_target="127.0.0.1:2", lab_token="LABTOKEN",
                 admin_token="ADMINTOKEN", embedded_chassis=False)
    c = TestClient(base_url="http://127.0.0.1", app=create_app(s))
    for path in ("/api/health", "/api/registry", "/api/settings"):
        text = c.get(path).text
        assert "LABTOKEN" not in text and "ADMINTOKEN" not in text, path


def test_config_errors_are_400_with_a_message(client):
    r = client.get("/api/configs/profile/nope")
    assert r.status_code == 404
    r = client.put("/api/configs/device/transmon_5q", json={"yaml": "x: 1"}, headers=MUTATE)
    assert r.status_code == 400 and r.json()["detail"]


def test_dump_turns_edited_data_back_into_yaml_the_validator_accepts(client):
    cfg = client.get("/api/configs/device/transmon_5q").json()
    data = cfg["data"]
    data["qubits"][0]["t1_us"] = 80.5
    r = client.post("/api/configs/device/dump", json={"data": data}, headers=MUTATE)
    assert r.status_code == 200
    text = r.json()["yaml"]
    assert "t1_us: 80.5" in text and text.index("device_name") < text.index("qubits")   # field order kept
    assert client.post("/api/configs/device/validate", json={"yaml": text}, headers=MUTATE).json()["ok"]
