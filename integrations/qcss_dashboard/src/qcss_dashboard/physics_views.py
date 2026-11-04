"""Chip, readout and signal-chain views. Every curve is computed by QCSS's own physics code, never re-derived here."""
from __future__ import annotations

from typing import Any

import numpy as np

from qcss.config.device import DeviceSpec
from qcss.config.profile import HardwareProfile
from qcss.device.state import DeviceState
from qcss.physics.transmon import (
    df01_dphi_ghz,
    f01_ghz,
    nbar_from_excited_population,
    nbar_from_temperature,
    thermal_populations,
    zz_second_order_ghz,
)
from qcss.readout.model import SurrogateReadout
from qcss.runtime.runner import SimulationContext
from qcss.signal.filters import FluxLineModel
from qcss.signal.mixer import IQCorrection, IQImpairment, apply_mixer
from qcss.signal.predistortion import QbloxRTP


def _ds(n: int, max_pts: int = 400) -> np.ndarray:
    """Indices that downsample a length-n series to at most max_pts points (keeps the last one)."""
    if n <= max_pts:
        return np.arange(n)
    return np.unique(np.linspace(0, n - 1, max_pts).round().astype(int))


def _c(z: np.ndarray) -> dict[str, list[float]]:
    return {"re": np.real(z).tolist(), "im": np.imag(z).tolist()}


# ------------------------------------------------------------------ chip (the hidden truth)
def chip_view(device: DeviceSpec, hours: float = 24.0, steps: int = 96, seed: int = 1) -> dict[str, Any]:
    qubits = []
    for q in device.qubits:
        f01 = float(f01_ghz(q.phi_offset, q.f_max_ghz, q.ec_ghz, q.d_asym))
        if q.t_eff_mk is not None:
            nbar = nbar_from_temperature(f01, q.t_eff_mk)
        elif q.p_excited:
            nbar = nbar_from_excited_population(q.p_excited)
        else:
            nbar = 0.0
        phi = np.linspace(-0.6, 0.6, 241)
        gamma_phi = max(0.0, 1.0 / q.t2_star_us - 1.0 / (2.0 * q.t1_us))
        r = device.resonator(q.qubit_index)
        res = None
        if r is not None:
            res = {"f_r_ghz": r.f_r_ghz, "kappa_mhz": r.kappa_mhz, "pulls_mhz": list(r.pulls_mhz),
                   "chi_mhz": (r.pulls_mhz[1] - r.pulls_mhz[0]) / 2, "eta": r.eta, "photons": r.readout_photons,
                   "cable_delay_ns": r.cable_delay_ns,
                   "dressed_ghz": [r.f_r_ghz + p * 1e-3 for p in r.pulls_mhz]}
        qubits.append({
            "qubit_index": q.qubit_index, "f_max_ghz": q.f_max_ghz, "ec_ghz": q.ec_ghz, "d_asym": q.d_asym,
            "phi_offset": q.phi_offset, "f01_ghz": f01, "f12_ghz": f01 - q.ec_ghz, "alpha_ghz": -q.ec_ghz,
            "df_dphi_ghz": float(df01_dphi_ghz(q.phi_offset, q.f_max_ghz, q.ec_ghz, q.d_asym)),
            "t1_us": q.t1_us, "t2_star_us": q.t2_star_us, "gamma_phi_per_us": gamma_phi,
            "t_phi_us": (1.0 / gamma_phi) if gamma_phi > 0 else None, "nbar": nbar,
            "thermal_populations": thermal_populations(nbar).tolist(), "rabi_max_ghz": q.rabi_max_ghz,
            "xy_mm": list(q.xy_mm), "verified": q.provenance.verified, "resonator": res,
            "flux_curve": {"phi": phi.tolist(),
                           "f01_ghz": np.asarray(f01_ghz(phi, q.f_max_ghz, q.ec_ghz, q.d_asym)).tolist()},
        })
    idx = {q.qubit_index: i for i, q in enumerate(device.qubits)}
    couplers = []
    for c in device.couplers:
        a, b = c.qubit_pair
        qa, qb = qubits[idx[a]], qubits[idx[b]]
        j_ghz = c.j_mhz * 1e-3
        zz = float(zz_second_order_ghz(j_ghz, qa["f01_ghz"], qb["f01_ghz"], qa["alpha_ghz"], qb["alpha_ghz"]))
        couplers.append({"qubit_pair": [a, b], "j_mhz": c.j_mhz,
                         "cz_time_ns": 1.0 / (2.0 * np.sqrt(2.0) * c.j_mhz * 1e6) * 1e9,
                         "zz_khz": zz * 1e6, "detuning_mhz": (qa["f01_ghz"] - qb["f01_ghz"]) * 1e3})

    # Drift: QCSS's own DeviceState advanced on a lab clock, exactly what a chassis does between jobs.
    state = DeviceState(device, np.random.default_rng(seed))
    t_h = np.linspace(0.0, hours, steps)
    f_tr: list[list[float]] = [[] for _ in device.qubits]
    t1_tr: list[list[float]] = [[] for _ in device.qubits]
    bursts: list[dict[str, Any]] = []
    seen_bursts: set[float] = set()
    prev = 0.0
    for t in t_h:
        state.advance_time((t - prev) * 3600.0)
        prev = t
        f_eff, t1_eff = state.snapshot()
        for i, q in enumerate(device.qubits):
            f_tr[i].append(f_eff[i] - (q.f_max_ghz - qubits[i]["f01_ghz"]))
            t1_tr[i].append(t1_eff[i] / 1e3)
        if state.enabled and state.bursts is not None:
            for e in state.bursts.events:
                if e.t0_s not in seen_bursts:
                    seen_bursts.add(e.t0_s)
                    bursts.append({"t_hours": e.t0_s / 3600.0, "xy_mm": [float(x) for x in e.xy_mm],
                                   "peak_gamma_per_us": e.peak_gamma_per_us})
    tls: list[list[dict[str, Any]]] = []
    tls_curves: list[dict[str, Any]] = []
    for i, q in enumerate(qubits):
        if state.enabled:
            bath = state.tls_baths[i]
            tls.append([{"f_ghz": d.f_ghz, "g_mhz": d.g_mhz, "gamma_mhz": d.gamma_mhz} for d in bath.defects])
            f = np.linspace(q["f01_ghz"] - 0.6, q["f01_ghz"] + 0.15, 600)
            extra = np.array([bath.extra_gamma1_per_us(x) for x in f])
            base = 1.0 / q["t1_us"]
            tls_curves.append({"f_ghz": f.tolist(), "t1_limit_us": (1.0 / (base + extra)).tolist()})
        else:
            tls.append([])
            tls_curves.append({"f_ghz": [], "t1_limit_us": []})
    dyn = device.dynamics
    return {
        "device_name": device.device_name, "chip_side_mm": device.chip_side_mm, "chip_area_cm2": device.chip_area_cm2,
        "qubits": qubits, "couplers": couplers, "tls": tls, "tls_curves": tls_curves,
        "dynamics": dyn.model_dump(mode="json") if dyn is not None else None,
        "faults": device.faults.model_dump(mode="json") if device.faults is not None else None,
        "m_fast": device.m_fast,
        "drift": {"t_hours": t_h.tolist(), "f01_ghz": f_tr, "t1_us": t1_tr, "bursts": bursts,
                  "enabled": state.enabled, "seed": seed},
    }


# ------------------------------------------------------------------ readout
def readout_view(profile: HardwareProfile, device: DeviceSpec, qubit: int = 0, shots: int = 300,
                 seed: int = 1, integration_ns: float = 1000.0) -> dict[str, Any]:
    if not 10.0 <= integration_ns <= 20_000.0:
        raise ValueError("integration_ns must be between 10 and 20000")
    if not 1 <= shots <= 2000:
        raise ValueError("shots must be between 1 and 2000")
    ctx = SimulationContext(profile, device)
    cid = f"ro_q{qubit}"
    if cid not in ctx.bindings:
        raise ValueError(f"no readout channel for qubit {qubit} (device {device.device_name})")
    b = ctx.bindings[cid]
    snap = ctx.calibration.snapshot([])
    phys = ctx._physical_readout(cid, snap, frozenset())
    if phys is None:
        raise ValueError(f"qubit {qubit} has no resonator in device {device.device_name}")
    rng = np.random.default_rng(seed)
    n = max(1, round(integration_ns / phys.dt))
    t1_ns = ctx.qdef[qubit].t1_ns
    p = phys.ro.p
    base = phys._base(n)                                     # mean resonator field alpha(t) per level
    w, disc = phys._calibration(n)
    i_ds = _ds(n)
    mean_field = {str(m): {"re": np.real(base[m][i_ds]).tolist(), "im": np.imag(base[m][i_ds]).tolist(),
                           "photons": (np.abs(base[m][i_ds]) ** 2).tolist()} for m in range(3)}
    clouds: dict[str, list[list[float]]] = {}
    labels: dict[str, list[int]] = {}
    for m in range(3):
        r = phys.acquire(np.full(shots, m), n, t1_ns, rng)
        clouds[str(m)] = [[float(z.real), float(z.imag)] for z in r.iq]
        labels[str(m)] = r.labels.astype(int).tolist()
    drive = np.full(n, phys.amp, dtype=np.complex128)
    examples = phys.ro.traces(np.array([0, 1, 1]), drive, t1_ns, rng, base=base)
    e_ds = _ds(examples.shape[1])
    conf = SurrogateReadout(phys, profile.acquisition.max_discriminated_states)._model(n, float(f"{t1_ns:.3g}")).c
    # Steady-state reflection vs probe detuning (resonator spectroscopy), per qubit level.
    det = np.linspace(-6, 6, 241) * p.kappa_rad_ns
    mags, phases = {}, {}
    for m, pull in enumerate(p.pulls_rad_ns):
        alpha_ss = np.sqrt(p.kappa_rad_ns) * phys.amp / (1j * (p.drive_detuning_rad_ns + det + pull)
                                                          + p.kappa_rad_ns / 2)
        bref = -phys.amp + np.sqrt(p.kappa_rad_ns) * alpha_ss
        mags[str(m)] = (np.abs(bref) / phys.amp).tolist()
        phases[str(m)] = np.angle(bref).tolist()
    # Separation SNR vs integration length (the reason readout takes ~1 us).
    snr = []
    for frac in (0.1, 0.2, 0.35, 0.5, 0.75, 1.0, 1.5):
        k = max(2, round(n * frac))
        z0 = phys.acquire(np.zeros(120, dtype=int), k, t1_ns, rng).iq
        z1 = phys.acquire(np.ones(120, dtype=int), k, t1_ns, rng).iq
        sigma = float(np.sqrt((np.var(z0) + np.var(z1)) / 2)) or 1e-30
        snr.append({"integration_ns": k * phys.dt, "snr": float(abs(np.mean(z1) - np.mean(z0)) / sigma)})
    disc_info: dict[str, Any] = {"kind": type(disc).__name__}
    for attr in ("threshold", "rotation_rad"):
        if hasattr(disc, attr):
            disc_info[attr] = float(getattr(disc, attr))
    if hasattr(disc, "centroids"):
        disc_info["centroids"] = [[float(np.real(c)), float(np.imag(c))] for c in disc.centroids]   # type: ignore[attr-defined]
    return {
        "qubit": qubit, "channel_id": cid, "generator_id": b.generator_id, "adc_dt_ns": phys.dt,
        "window_samples": len(i_ds), "integration_ns": n * phys.dt, "t_ns": (i_ds * phys.dt).tolist(),
        "tof_ns": phys.tof_samples * phys.dt, "delay_ns": phys.delay_samples * phys.dt,
        "kappa_mhz": p.kappa_rad_ns / (2 * np.pi) * 1e3, "chi_mhz": (p.pulls_rad_ns[1] - p.pulls_rad_ns[0]) / 2
        / (2 * np.pi) * 1e3, "eta": p.eta, "drive_amplitude": phys.amp, "t1_us": t1_ns / 1e3,
        "mean_field": mean_field, "clouds": clouds, "labels": labels,
        "weights": _c(w[i_ds]), "discriminator": disc_info, "confusion": np.asarray(conf).tolist(),
        "example_traces": {"t_ns": (e_ds * phys.dt).tolist(),
                           "traces": [_c(tr[e_ds]) for tr in examples], "levels": [0, 1, 1]},
        "spectroscopy": {"freq_mhz": (det / (2 * np.pi) * 1e3).tolist(), "mag": mags, "phase": phases},
        "snr_vs_integration": snr,
    }


# ------------------------------------------------------------------ signal chain
def signal_view(params: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    mx = params.get("mixer")
    if mx is not None:
        t = mx.get("truth", {})
        c = mx.get("correction", {})
        truth = IQImpairment(t.get("gain_i", 1.0), t.get("gain_q", 1.0), t.get("phase_rad", 0.0),
                             t.get("dc_i", 0.0), t.get("dc_q", 0.0))
        corr = IQCorrection(c.get("dc_i", 0.0), c.get("dc_q", 0.0), c.get("gain_ratio", 1.0) or 1.0,
                            c.get("phase_rad", 0.0))
        fs, f_if, n = 1e9, float(mx.get("if_hz", 100e6)), 1000
        k = np.arange(n)
        m_if = 0.5 * np.exp(2j * np.pi * f_if * k / fs)                # a pure single-sideband tone
        x = apply_mixer(m_if, truth, corr)
        spec = np.fft.fftshift(np.fft.fft(x * np.hanning(n))) / n
        freqs = np.fft.fftshift(np.fft.fftfreq(n, 1 / fs))
        sig = abs(np.mean(x * np.exp(-2j * np.pi * f_if * k / fs)))
        img = abs(np.mean(x * np.exp(2j * np.pi * f_if * k / fs)))
        lo = abs(np.mean(x)) if f_if != 0 else 0.0
        db = (lambda v: float(20 * np.log10(max(v, 1e-12) / max(sig, 1e-30))))
        sel = slice(0, 120)
        out["mixer"] = {"mu": _c(np.array([truth.mu])), "nu": _c(np.array([truth.nu])),
                        "image_dbc": db(img), "lo_dbc": db(lo), "if_hz": f_if,
                        "spectrum": {"f_mhz": (freqs / 1e6).tolist(),
                                     "db": (20 * np.log10(np.abs(spec) + 1e-12)).tolist()},
                        "iq_in": _c(m_if[sel]), "iq_out": _c(x[sel])}
    fl = params.get("flux")
    if fl is not None:
        fs = float(fl.get("fs_hz", 1e9))
        n = int(fl.get("samples", 2000))
        if not 10 <= n <= 20_000:
            raise ValueError("flux samples must be between 10 and 20000")
        step = np.ones(n)
        terms = [tuple(map(float, tt)) for tt in fl.get("exp_terms", [])]
        bias = fl.get("bias_tee_tau_s")
        line = FluxLineModel(fs, terms, bias_tee_tau_s=bias)                  # type: ignore[arg-type]
        truth = line(step)
        pre = QbloxRTP(fs)
        stages = [(float(a), float(tau)) for a, tau in fl.get("predistortion", [])]
        pre.configure(stages, fl.get("inverse_highpass_tau_s"), None)
        pred = pre(step)
        line.reset()
        combined = line(pred)
        i = _ds(n)
        out["flux"] = {"t_ns": (i / fs * 1e9).tolist(), "ideal": step[i].tolist(), "truth": truth[i].tolist(),
                       "predistorted": pred[i].tolist(), "combined": combined[i].tolist(),
                       "residual_max": float(np.max(np.abs(combined - 1.0)))}
    return out
