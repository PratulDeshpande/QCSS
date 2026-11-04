"""Live links: a real chassis embedded in the bridge, driven through the admin channel and the lab link."""
from __future__ import annotations

import socket

import pytest
from fastapi.testclient import TestClient

from qcss_dashboard.app import create_app
from qcss_dashboard.settings import Settings

MUTATE = {"X-QCSS-Dashboard": "1"}


def _loopback_ok() -> bool:
    try:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
        return True
    except OSError:
        return False


@pytest.fixture
def live(tmp_path):
    if not _loopback_ok():
        pytest.skip("loopback sockets not permitted")
    s = Settings(workspace=tmp_path, embedded_chassis=True, chassis_time_scale=0.0, poll_interval_s=0.2)
    with TestClient(base_url="http://127.0.0.1", app=create_app(s)) as c:
        yield c


def test_embedded_chassis_answers_on_both_links(live):
    h = live.get("/api/health").json()
    assert h["lab"]["ok"] and h["admin"]["ok"]
    d = live.get("/api/lab/describe").json()
    assert d["profile_name"] == "qblox_cluster_5q" and d["channels"]


def test_admin_state_shows_the_hidden_truth(live):
    st = live.get("/api/admin/state").json()
    assert len(st["truth"]["qubits"]) == 5 and st["mode"]["time_scale"] == 0.0
    assert all(q["frequency_hz"] > 4e9 for q in st["truth"]["qubits"])


def test_admin_actions_change_the_truth_and_are_audited(live):
    r = live.post("/api/admin/action", json={"action": "kill", "qubit": 1}, headers=MUTATE)
    assert r.status_code == 200, r.text
    q1 = next(q for q in live.get("/api/admin/state").json()["truth"]["qubits"] if q["qubit_index"] == 1)
    assert q1["dead"]
    live.post("/api/admin/action", json={"action": "clear"}, headers=MUTATE)
    log = live.get("/api/audit").json()["entries"]
    assert [e["action"] for e in log[-2:]] == ["kill", "clear"] and log[-2]["ok"]


def test_admin_mode_change_is_live(live):
    r = live.post("/api/admin/action", json={"action": "mode", "deterministic": True, "tier": "t1b"}, headers=MUTATE)
    assert r.status_code == 200, r.text
    mode = live.get("/api/admin/state").json()["mode"]
    assert mode["deterministic"] and mode["tier_policy"] == "FIDELITY_TIER_T1B_STATEVECTOR"


def test_unknown_admin_action_is_a_400(live):
    r = live.post("/api/admin/action", json={"action": "explode"}, headers=MUTATE)
    assert r.status_code == 400


def test_lab_bench_runs_an_experiment_over_the_lab_link(live):
    r = live.post("/api/lab/run", json={"kind": "rabi", "qubit": 0, "points": 5, "shots": 100}, headers=MUTATE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "lab" and len(body["p1"]) == 5 and body["job_id"]
    jobs = live.get("/api/lab/jobs").json()["jobs"]
    assert jobs[-1]["job_id"] == body["job_id"] and jobs[-1]["state"] == "JOB_STATE_COMPLETED"
    ins = live.get(f"/api/admin/inspect/{body['job_id']}").json()
    assert ins["tier_used"].startswith("FIDELITY_TIER_")


def test_calibration_round_trip_uses_compare_and_swap(live):
    cal = live.get("/api/lab/calibration").json()
    epoch = cal.get("calibration_epoch", 0)
    snap = {"qubits": [{"qubit_index": 0, "drive_frequency_hz": cal["qubits"][0]["drive_frequency_hz"] + 1e5}]}
    r = live.put("/api/lab/calibration", json={"snapshot": snap, "expected_epoch": epoch}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["new_epoch"] == epoch + 1
    r = live.put("/api/lab/calibration", json={"snapshot": snap, "expected_epoch": epoch}, headers=MUTATE)
    assert r.status_code == 409


def test_event_stream_pushes_state_without_tokens(live):
    with live.websocket_connect("ws://127.0.0.1/api/events") as ws:
        msg = ws.receive_text()
    assert '"truth"' in msg and "Bearer" not in msg
    settings = live.app.state.settings
    assert settings.lab_token and settings.lab_token not in msg and settings.admin_token not in msg


def test_sandbox_and_view_routes_answer(live):
    assert live.get("/api/views/hardware?profile=qick_zcu216_5q").json()["tick_hz"] > 3e10
    assert live.get("/api/views/chip?device=transmon_5q&hours=1&steps=4").json()["qubits"]
    r = live.post("/api/sandbox/experiment", json={"kind": "t1", "qubit": 0, "points": 4, "shots": 50,
                                                   "tier": "T1B"}, headers=MUTATE)
    assert r.status_code == 200 and r.json()["source"] == "sandbox"


def test_restart_applies_another_profile(live):
    r = live.post("/api/chassis/restart", json={"profile": "zi_shfqc_5q", "device": "transmon_5q",
                                                "time_scale": 0.0}, headers=MUTATE)
    assert r.status_code == 200, r.text
    assert live.get("/api/lab/describe").json()["profile_name"] == "zi_shfqc_5q"
