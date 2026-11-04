"""Regression tests for the final review's findings (I1, I2, I4, I5, I6)."""
from __future__ import annotations

import json
import pathlib
import threading

import numpy as np
import pytest
from fastapi.testclient import TestClient

from qcss.config.loader import load_device, load_profile
from qcss_dashboard import app as app_mod
from qcss_dashboard.app import create_app
from qcss_dashboard.sandbox import explain
from qcss_dashboard.settings import Settings

MUTATE = {"X-QCSS-Dashboard": "1"}
LOCAL = "http://127.0.0.1"
RABI = json.loads(pathlib.Path("examples/jobs/rabi_amplitude_q0.json").read_text())


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(Settings(workspace=tmp_path, lab_target=None, admin_target=None,
                                          embedded_chassis=False)), base_url=LOCAL)


# I1: DNS rebinding and cross-site WebSocket hijacking
def test_requests_for_a_foreign_host_name_are_refused(client):
    assert client.get("/api/registry", headers={"Host": "evil.example"}).status_code == 400
    assert client.get("/api/registry").status_code == 200


def test_cross_origin_mutations_are_refused(client):
    r = client.post("/api/views/signal", json={"mixer": {}}, headers={**MUTATE, "Origin": "https://evil.example"})
    assert r.status_code == 403
    r = client.post("/api/views/signal", json={"mixer": {}}, headers={**MUTATE, "Origin": LOCAL})
    assert r.status_code == 200


def test_cross_origin_websocket_is_refused(client):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect), client.websocket_connect(
            "ws://127.0.0.1/api/events", headers={"Origin": "https://evil.example"}) as ws:
        ws.receive_text()


# I2: the trajectory must evolve each drive sample exactly once
def test_trajectory_ends_where_the_engine_ends():
    out = explain(load_profile("src/qcss/config/profiles/qblox_cluster_5q.yaml"),
                  load_device("src/qcss/config/devices/transmon_5q.yaml"), RABI, tier="T2", seed=1, shots=20, point=6)
    traj_end = np.asarray(out["state"]["trajectory"]["populations"][-1][0])
    engine = np.asarray(out["state"]["populations"][0])
    assert np.allclose(traj_end, engine, atol=0.02), (traj_end, engine)


# I4: bounded computation
def test_oversized_inputs_are_refused(client):
    assert client.post("/api/views/signal", json={"flux": {"samples": 2_000_000_000}}, headers=MUTATE).status_code == 400
    r = client.post("/api/views/readout", json={"device": "transmon_5q", "integration_ns": 1e9}, headers=MUTATE)
    assert r.status_code == 400
    r = client.post("/api/views/readout", json={"device": "transmon_5q", "qubit": 42}, headers=MUTATE)
    assert r.status_code == 400


def test_busy_sandbox_answers_503_instead_of_queueing_forever(client, monkeypatch):
    sem = threading.BoundedSemaphore(1)
    sem.acquire()
    monkeypatch.setattr(app_mod, "SANDBOX_SLOTS", sem)
    monkeypatch.setattr(app_mod, "SANDBOX_WAIT_S", 0.1)
    r = client.post("/api/sandbox/experiment", json={"kind": "rabi", "points": 3, "shots": 10}, headers=MUTATE)
    assert r.status_code == 503


# I5: input errors are 400s with a message, never an opaque 500
def test_bad_job_json_is_a_400_with_the_parser_message(client):
    r = client.post("/api/sandbox/explain", json={"job": {"numShot": 3}}, headers=MUTATE)
    assert r.status_code == 400 and "numShot" in r.json()["detail"]


def test_cleared_numbers_are_a_400_not_a_500(client):
    r = client.post("/api/views/chip", json={"device": "transmon_5q", "hours": None}, headers=MUTATE)
    assert r.status_code in (200, 400)
    r = client.post("/api/sandbox/experiment", json={"kind": "rabi", "points": None}, headers=MUTATE)
    assert r.status_code in (200, 400)


# I6: a failed restart keeps the running chassis
def test_failed_restart_keeps_the_old_chassis(tmp_path, monkeypatch):
    s = Settings(workspace=tmp_path, embedded_chassis=True, chassis_time_scale=0.0)
    with TestClient(create_app(s), base_url=LOCAL) as c:
        before = c.get("/api/lab/describe").json()["profile_name"]
        from qcss_dashboard import chassis_host

        real_start = chassis_host.EmbeddedChassis.start

        def boom(self, timeout_s=20.0):
            raise RuntimeError("simulated start failure")
        monkeypatch.setattr(chassis_host.EmbeddedChassis, "start", boom)
        r = c.post("/api/chassis/restart", json={"profile": "zi_shfqc_5q"}, headers=MUTATE)
        assert r.status_code == 409 and "simulated start failure" in r.json()["detail"]
        monkeypatch.setattr(chassis_host.EmbeddedChassis, "start", real_start)
        assert c.get("/api/lab/describe").json()["profile_name"] == before


def test_same_origin_websocket_is_accepted(tmp_path):
    c = TestClient(create_app(Settings(workspace=tmp_path, lab_target=None, admin_target=None, embedded_chassis=False,
                                       poll_interval_s=0.1)), base_url=LOCAL)
    with c.websocket_connect("ws://127.0.0.1/api/events", headers={"Origin": "http://127.0.0.1"}) as ws:
        assert '"ts"' in ws.receive_text()
