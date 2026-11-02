"""Unit tests for QCSS CLI commands using Click CliRunner."""
from __future__ import annotations

import json

import pytest
from click.testing import CliRunner

from qcss.cli import app


@pytest.fixture
def cli_runner():
    return CliRunner()


def test_cli_help(cli_runner):
    result = cli_runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "QCSS: Hardware-in-the-loop" in result.output
    assert "profile" in result.output
    assert "device" in result.output
    assert "validate" in result.output
    assert "run" in result.output
    assert "serve" in result.output


def test_cli_profile_list(cli_runner):
    result = cli_runner.invoke(app, ["profile", "list"])
    assert result.exit_code == 0
    assert "qblox_cluster_5q" in result.output
    assert "zi_shfqc_5q" in result.output


def test_cli_profile_show(cli_runner):
    result = cli_runner.invoke(app, ["profile", "show", "qblox_cluster_5q"])
    assert result.exit_code == 0
    assert "Profile: qblox_cluster_5q" in result.output
    assert "Vendor:  qblox" in result.output
    assert "Generators" in result.output
    assert "Feedback Latencies" in result.output


def test_cli_device_show(cli_runner):
    result = cli_runner.invoke(app, ["device", "show", "transmon_5q"])
    assert result.exit_code == 0
    assert "Device: transmon_5q" in result.output
    assert "Qubits" in result.output
    assert "Couplers" in result.output
    assert "Resonators" in result.output


def test_cli_validate_and_run(cli_runner, tmp_path):
    job_dict = {
        "job_key": "cli_test_job",
        "num_shots": 20,
        "repetition_delay_ticks": 200_000,
        "requested_tier": "FIDELITY_TIER_T0_SURROGATE",
        "waveform_library": {
            "g1": {
                "shape": "WAVEFORM_SHAPE_GAUSSIAN",
                "length_samples": 20,
                "sigma_samples": 5.0,
            }
        },
        "main": {
            "instructions": [
                {
                    "start_tick": 0,
                    "play": {
                        "channel_id": "xy_q0",
                        "waveform_id": "g1",
                        "amplitude": 0.8,
                    },
                },
                {
                    "start_tick": 40,
                    "acquire": {
                        "channel_id": "ro_q0",
                        "integration_ticks": 500,
                        "mode": "ACQUISITION_MODE_DISCRIMINATED",
                        "register_index": 0,
                        "result_key": "q0",
                    },
                },
            ]
        },
    }

    job_file = tmp_path / "test_job.json"
    job_file.write_text(json.dumps(job_dict), encoding="utf-8")

    # Validate
    val_res = cli_runner.invoke(app, ["validate", str(job_file), "-p", "qblox_cluster_5q"])
    assert val_res.exit_code == 0
    assert "is VALID" in val_res.output

    # Run
    out_file = tmp_path / "results.json"
    run_res = cli_runner.invoke(app, ["run", str(job_file), "-p", "qblox_cluster_5q", "-s", "15", "-o", str(out_file)])
    assert run_res.exit_code == 0
    assert "Simulation completed" in run_res.output
    assert "Key 'q0'" in run_res.output
    assert out_file.exists()

    res_data = json.loads(out_file.read_text(encoding="utf-8"))
    assert res_data["num_shots"] == 15
    assert "q0" in res_data["acquisitions"]
    assert len(res_data["acquisitions"]["q0"]["states"]) == 15

    # Run with T1B statevector tier
    out_t1b = tmp_path / "results_t1b.json"
    run_t1b = cli_runner.invoke(app, ["run", str(job_file), "-p", "test_ideal_1q", "-t", "T1B", "-s", "10", "-o", str(out_t1b)])
    assert run_t1b.exit_code == 0
    assert "Simulation completed" in run_t1b.output

    # Run with T1A stabilizer tier using a Clifford gate
    job_t1a_dict = {
        "job_key": "cli_clifford_job",
        "num_shots": 10,
        "requested_tier": "FIDELITY_TIER_T1A_STABILIZER",
        "waveform_library": {"x": {"shape": "WAVEFORM_SHAPE_SQUARE", "length_samples": 20}},
        "main": {
            "instructions": [
                {"start_tick": 0, "play": {"channel_id": "xy_q0", "waveform_id": "x", "duration_ticks": 20, "amplitude": 0.5}},
                {"start_tick": 30, "acquire": {"channel_id": "ro_q0", "integration_ticks": 500, "mode": "ACQUISITION_MODE_DISCRIMINATED", "register_index": 0, "result_key": "q0"}},
            ]
        },
    }
    job_t1a_file = tmp_path / "clifford_job.json"
    job_t1a_file.write_text(json.dumps(job_t1a_dict), encoding="utf-8")

    out_t1a = tmp_path / "results_t1a.json"
    run_t1a = cli_runner.invoke(app, ["run", str(job_t1a_file), "-p", "test_ideal_1q", "-t", "T1A", "-s", "10", "-o", str(out_t1a)])
    assert run_t1a.exit_code == 0
    assert "Simulation completed" in run_t1a.output

    # Non-Clifford pulse on T1A should be rejected by router
    run_non_cliff = cli_runner.invoke(app, ["run", str(job_file), "-p", "test_ideal_1q", "-t", "T1A"])
    assert run_non_cliff.exit_code == 1
    assert "Tier routing failed" in run_non_cliff.output


def test_technician_request_queues_a_calibration_and_prints_its_eta(tmp_path):
    from click.testing import CliRunner as Runner
    result = Runner().invoke(app, ["technician", "request", "--requests-dir", str(tmp_path), "--scope", "device"])
    assert result.exit_code == 0, result.output
    assert "accepted" in result.output and "expected" in result.output
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_technician_request_refuses_an_unknown_scope(tmp_path):
    from click.testing import CliRunner as Runner
    result = Runner().invoke(app, ["technician", "request", "--requests-dir", str(tmp_path), "--scope", "q42"])
    assert result.exit_code != 0 and "q42" in result.output


def test_the_technician_commands_exist_when_the_cli_runs_as_a_module():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "qcss.cli", "technician", "--help"], capture_output=True, text=True,
                       check=False)
    assert r.returncode == 0, r.stderr
    assert "request" in r.stdout and "run" in r.stdout


def test_a_timed_fault_without_a_duration_is_a_usage_error():
    r = CliRunner().invoke(app, ["admin", "fault", "hang", "--count", "3"])
    assert r.exit_code == 2 and "--duration" in r.output


def test_a_technician_env_entry_without_an_equals_sign_is_a_usage_error(tmp_path):
    r = CliRunner().invoke(app, ["technician", "run", "--platforms-dir", str(tmp_path), "--platform", "p",
                                 "--reports", str(tmp_path / "rep"), "--requests-dir", str(tmp_path / "req"),
                                 "--env", "QCSS_ADDRESS"])
    assert r.exit_code == 2 and "QCSS_ADDRESS" in r.output and "NAME=VALUE" in r.output
