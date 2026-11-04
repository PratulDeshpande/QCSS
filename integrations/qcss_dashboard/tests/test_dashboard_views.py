"""Every view's numbers come from QCSS's own code: hardware rules, chip physics, readout, signal chain, explain runs."""
from __future__ import annotations

import json
import pathlib

import numpy as np
import pytest

from qcss.config.loader import load_device, load_profile
from qcss.runtime.runner import SimulationContext
from qcss_dashboard.hardware import hardware_view
from qcss_dashboard.physics_views import chip_view, readout_view, signal_view
from qcss_dashboard.sandbox import explain

PROFILE = load_profile("src/qcss/config/profiles/qblox_cluster_5q.yaml")
QICK = load_profile("src/qcss/config/profiles/qick_zcu216_5q.yaml")
DEVICE = load_device("src/qcss/config/devices/transmon_5q.yaml")
RABI = json.loads(pathlib.Path("examples/jobs/rabi_amplitude_q0.json").read_text())


def test_hardware_view_reports_grids_latencies_and_bindings():
    hw = hardware_view(PROFILE, DEVICE)
    assert hw["tick_hz"] == 1e9
    gen = hw["generators"][0]
    assert gen["ticks_per_sample"] >= 1 and gen["sample_ns"] > 0
    assert any(b["channel_id"] == "xy_q0" for b in hw["bindings"])
    lat = {(e["src"], e["dst"]): e for e in hw["latency_matrix"]}
    assert all(e["latency_ticks"] is None or e["latency_ticks"] > 0 for e in lat.values())
    assert hw["tof"]["ro_q0"]["ticks"] > 0


def test_hardware_view_of_qick_shows_its_fractional_tick():
    hw = hardware_view(QICK, DEVICE)
    assert hw["tick_hz"] == pytest.approx(34.4064e9)
    assert {g["ticks_per_sample"] for g in hw["generators"]} >= {5}


def test_chip_view_tunes_frequency_with_flux_and_drifts_over_time():
    chip = chip_view(DEVICE, hours=6.0, steps=12, seed=4)
    q0 = chip["qubits"][0]
    ctx = SimulationContext(PROFILE, DEVICE)
    assert q0["f01_ghz"] == pytest.approx(ctx.qdef[0].f01_ghz)
    assert max(q0["flux_curve"]["f01_ghz"]) == pytest.approx(DEVICE.qubits[0].f_max_ghz, rel=1e-6)
    assert len(chip["drift"]["t_hours"]) == 12
    t1 = np.asarray(chip["drift"]["t1_us"][0])
    assert t1.std() > 0                                   # dynamics on: T1 wanders
    assert chip["tls"][0] and all("f_ghz" in d for d in chip["tls"][0])
    assert len(chip["couplers"]) == len(DEVICE.couplers)


def test_readout_view_separates_levels_and_has_a_stochastic_confusion_matrix():
    ro = readout_view(PROFILE, DEVICE, qubit=0, shots=200, seed=2)
    conf = np.asarray(ro["confusion"])
    assert np.allclose(conf.sum(axis=1), 1.0)
    assert conf[0, 0] > 0.8 and conf[1, 1] > 0.6
    c0, c1 = (np.mean(np.asarray(ro["clouds"][k]), axis=0) for k in ("0", "1"))
    assert np.linalg.norm(c1 - c0) > 0
    assert len(ro["mean_field"]["0"]["re"]) == ro["window_samples"]
    assert len(ro["spectroscopy"]["freq_mhz"]) == len(ro["spectroscopy"]["mag"]["0"])


def test_signal_view_mixer_image_matches_the_imbalance_and_cancels_when_corrected():
    ideal = signal_view({"mixer": {}})["mixer"]
    assert ideal["image_dbc"] < -100
    off = signal_view({"mixer": {"truth": {"gain_q": 1.1, "phase_rad": 0.05}}})["mixer"]
    expected = 10 * np.log10(((0.1) ** 2 + 0.05 ** 2) / 4)
    assert off["image_dbc"] == pytest.approx(expected, abs=1.5)


def test_signal_view_flux_predistortion_flattens_the_step_response():
    v = signal_view({"flux": {"exp_terms": [[0.1, 50e-9]], "predistortion": [[0.1, 50e-9]]}})["flux"]
    truth, combined = np.asarray(v["truth"]), np.asarray(v["combined"])
    assert abs(truth[0] - 1.1) < 0.02 and abs(truth[-1] - 1.0) < 0.01
    assert np.max(np.abs(combined - 1.0)) < 0.02


def test_explain_runs_a_job_through_every_stage():
    out = explain(PROFILE, DEVICE, RABI, tier="T2", seed=1, shots=50, point=6)
    assert out["valid"] and out["plan"]["tier"] == "T2"
    kinds = [o["kind"] for o in out["program"]["ops"]]
    assert "play" in kinds and "acquire" in kinds
    assert "pi" in out["waveforms"]
    assert out["shot"]["timeline"] and out["shot"]["segments"]
    pops = out["state"]["populations"][0]
    assert sum(pops) == pytest.approx(1.0, abs=1e-6)
    assert len(out["state"]["trajectory"]["t_ns"]) > 2
    assert out["results"]["points"] and 0 <= out["results"]["points"][0]["p1"]["q0"] <= 1


def test_explain_lifts_gates_for_gate_tiers():
    out = explain(PROFILE, DEVICE, RABI, tier="T1B", seed=1, shots=20, point=10)
    ev = out["lift"][0]
    assert ev["qubits"] == [0] and 0 <= ev["leakage"] < 1 and len(ev["unitary"]) == 2


def test_explain_reports_hardware_violations_with_field_paths():
    bad = json.loads(json.dumps(RABI))
    bad["main"]["instructions"][1]["startTick"] = "3"                    # inside the pulse, off any sane grid
    bad["main"]["instructions"][1]["acquire"]["integrationTicks"] = "7"  # not on the integration grid
    out = explain(PROFILE, DEVICE, bad, tier="T1B", seed=1, shots=10)
    assert not out["valid"] and out["violations"]
    assert all("path" in v and "description" in v for v in out["violations"])
