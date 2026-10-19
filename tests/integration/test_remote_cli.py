"""`qcss remote ...` and scripts/remote_smoke.py against a real server, as the second laptop runs them."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Iterator

import pytest
from click.testing import CliRunner
from google.protobuf import json_format

from qcss.cli import app
from tests.conftest import REPO_ROOT
from tests.integration.test_grpc_end_to_end import _can_connect_loopback
from tests.integration.test_remote_client import TOKEN, _ServerThread, pi_job


@pytest.fixture(scope="module")
def server() -> Iterator[_ServerThread]:
    if not _can_connect_loopback():
        pytest.skip("Loopback socket connection not permitted in current sandbox environment")
    with _ServerThread() as s:
        yield s


def _remote(server, *args: str):
    return CliRunner().invoke(app, ["remote", *args, "--target", server.addr, "--token", TOKEN])


def test_ping_reports_serving(server):
    r = _remote(server, "ping")
    assert r.exit_code == 0, r.output
    assert "SERVING" in r.output


def test_describe_lists_channels(server):
    r = _remote(server, "describe")
    assert r.exit_code == 0, r.output
    assert "xy_q0" in r.output and "ro_q0" in r.output


def test_properties_prints_coherence_and_readout(server):
    r = _remote(server, "properties")
    assert r.exit_code == 0, r.output
    assert "T1" in r.output and "P(0|1)" in r.output


def test_run_prints_counts_and_saves_json(server, tmp_path):
    job = tmp_path / "pi.json"
    job.write_text(json_format.MessageToJson(pi_job(shots=100)))
    out = tmp_path / "res.json"
    r = _remote(server, "run", str(job), "-o", str(out))
    assert r.exit_code == 0, r.output
    saved = json.loads(out.read_text())
    assert saved["state"] == "JOB_STATE_COMPLETED"
    assert sum(saved["counts"].values()) == 100


def test_run_of_a_sweep_reports_counts_per_sweep_point(server, tmp_path):
    out = tmp_path / "rabi.json"
    r = _remote(server, "run", str(REPO_ROOT / "examples" / "jobs" / "rabi_amplitude_q0.json"), "-s", "50",
                "-o", str(out))
    assert r.exit_code == 0, r.output
    assert "point [10]" in r.output
    per_point = json.loads(out.read_text())["counts_per_point"]
    assert len(per_point) == 11
    assert all(sum(p["counts"].values()) == 50 for p in per_point)


def test_run_shows_field_violations_and_fails(server, tmp_path):
    bad = pi_job()
    bad.main.instructions[0].play.channel_id = "xy_q99"
    job = tmp_path / "bad.json"
    job.write_text(json_format.MessageToJson(bad))
    r = _remote(server, "run", str(job))
    assert r.exit_code != 0
    assert "INVALID_ARGUMENT" in r.output and "main.instructions" in r.output


def test_wrong_token_fails_cleanly(server):
    r = CliRunner().invoke(app, ["remote", "describe", "--target", server.addr, "--token", "nope"])
    assert r.exit_code != 0
    assert "UNAUTHENTICATED" in r.output


def test_smoke_script_passes_every_step(server, tmp_path):
    report = tmp_path / "smoke.json"
    proc = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "remote_smoke.py"), "--target", server.addr,
                           "--token", TOKEN, "--report", str(report)],
                          capture_output=True, text=True, timeout=600, check=False, cwd=REPO_ROOT,
                          env={**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    steps = json.loads(report.read_text())["steps"]
    assert len(steps) == 10
    assert all(s["status"] == "PASS" for s in steps), steps
