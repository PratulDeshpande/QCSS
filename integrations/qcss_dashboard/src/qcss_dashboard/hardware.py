"""Hardware & Timing view: the profile turned into grids, budgets and a latency matrix, using QCSS's own helpers."""
from __future__ import annotations

from typing import Any

from qcss.config.device import DeviceSpec
from qcss.config.profile import HardwareProfile
from qcss.core.timebase import TimeBase
from qcss.feedback.latency import LatencyRouteError, lookup_latency, readout_tof_ticks
from qcss.ir.compiler import build_bindings

# Which profile fields each validator rule reads (src/qcss/ir/validator.py), for the rule explainer.
VALIDATOR_RULES: list[dict[str, Any]] = [
    {"rule": "plays", "source": "src/qcss/ir/validator.py:98",
     "checks": "start on the real-time grid, minimum duration, duration granularity, waveform length x ticks per "
               "sample equals the duration, |amplitude| <= 1",
     "fields": ["GeneratorSpec.rt_granularity_ticks", "GeneratorSpec.rt_min_duration_ticks",
                "GeneratorSpec.wave_min_samples", "GeneratorSpec.wave_granularity_samples"]},
    {"rule": "overlaps", "source": "src/qcss/ir/validator.py:133",
     "checks": "two plays on one generator at the same time", "fields": ["GeneratorSpec.overlap_policy"]},
    {"rule": "memory", "source": "src/qcss/ir/validator.py:150",
     "checks": "unique waveform samples and waveform count fit the generator memory",
     "fields": ["GeneratorSpec.wave_mem_samples", "GeneratorSpec.max_waveforms"]},
    {"rule": "frame ops", "source": "src/qcss/ir/validator.py:166",
     "checks": "NCO updates on the NCO grid, spaced enough, within the frequency range",
     "fields": ["GeneratorSpec.nco_grid_ticks", "GeneratorSpec.nco_min_spacing_ticks",
                "GeneratorSpec.nco_freq_range_hz"]},
    {"rule": "acquisitions", "source": "src/qcss/ir/validator.py:190",
     "checks": "mode supported, integration grid and maximum length, weights length, spacing, weight sets",
     "fields": ["AcquisitionSpec.modes", "AcquisitionSpec.integration_granularity_ticks",
                "AcquisitionSpec.max_square_integration_ticks", "AcquisitionSpec.max_weighted_integration_ticks",
                "AcquisitionSpec.min_acq_spacing_ticks", "AcquisitionSpec.max_weight_sets"]},
    {"rule": "branches", "source": "src/qcss/ir/validator.py:226",
     "checks": "register written before, latency route exists, decision after acq + ToF + integration + latency, "
               "arm length within the declared duration",
     "fields": ["FeedbackSpec.branch_equal_duration_required", "FeedbackSpec.max_condition_addresses",
                "LatencyEntry.latency_ticks"]},
    {"rule": "instruction budget", "source": "src/qcss/ir/validator.py:272",
     "checks": "about 2 instructions per play or acquisition plus waits fit the instruction memory",
     "fields": ["GeneratorSpec.instr_mem", "GeneratorSpec.max_wait_ticks_per_instr"]},
    {"rule": "saturation", "source": "src/qcss/ir/validator.py:288",
     "checks": "the summed, NCO-modulated I/Q of every port stays within full scale",
     "fields": ["PortSpec.full_scale_per_path", "PortSpec.saturation_policy"]},
]


def hardware_view(profile: HardwareProfile, device: DeviceSpec | None) -> dict[str, Any]:
    tb = TimeBase.from_clocks(profile.clock.tick_hz)
    tick_hz = float(tb.tick_hz)
    tick_ns = 1e9 / tick_hz
    bindings = build_bindings(profile, device)
    gens = []
    for g in profile.generators:
        tps = tb.ticks_per(g.sample_rate_hz)
        gens.append({
            "generator_id": g.generator_id, "port_id": g.port_id, "module_id": g.module_id,
            "is_readout": g.is_readout, "sample_rate_hz": float(g.sample_rate_hz), "ticks_per_sample": tps,
            "sample_ns": tps * tick_ns, "rt_grid_ticks": g.rt_granularity_ticks,
            "rt_grid_ns": g.rt_granularity_ticks * tick_ns, "min_duration_ns": g.rt_min_duration_ticks * tick_ns,
            "nco_grid_ns": g.nco_grid_ticks * tick_ns, "nco_range_hz": list(g.nco_freq_range_hz),
            "nco_freq_resolution_hz": g.nco_freq_resolution_hz, "nco_phase_steps": g.nco_phase_steps,
            "nco_latched": g.nco_latched, "wave_mem_samples": g.wave_mem_samples,
            "wave_mem_us": g.wave_mem_samples * tps * tick_ns / 1e3, "max_waveforms": g.max_waveforms,
            "instr_mem": g.instr_mem, "max_wait_ns": g.max_wait_ticks_per_instr * tick_ns,
            "overlap_policy": g.overlap_policy.value, "verified": g.provenance.verified,
            "channels": sorted(c for c, b in bindings.items() if b.generator_id == g.generator_id),
        })
    ports = [{"port_id": p.port_id, "kind": p.kind, "max_generators": p.max_generators,
              "full_scale": p.full_scale_per_path, "saturation_policy": p.saturation_policy.value,
              "lo_hz": p.lo_frequency_hz, "output_latency_ns": p.output_latency_ticks * tick_ns,
              "verified": p.provenance.verified,
              "generators": [g.generator_id for g in profile.generators if g.port_id == p.port_id]}
             for p in profile.ports]
    matrix = []
    for src in profile.generators:
        if not src.is_readout:
            continue
        for dst in profile.generators:
            try:
                lat, jit = lookup_latency(profile, src.generator_id, dst.generator_id, "bit")
                entry = {"latency_ticks": lat, "latency_ns": lat * tick_ns, "jitter_ticks": jit,
                         "routing": profile.routing(src.generator_id, dst.generator_id), "verified": None}
            except LatencyRouteError:
                entry = {"latency_ticks": None, "latency_ns": None, "jitter_ticks": None,
                         "routing": profile.routing(src.generator_id, dst.generator_id), "verified": False}
            matrix.append({"src": src.generator_id, "dst": dst.generator_id, **entry})
    tof = {}
    for cid, b in bindings.items():
        if b.kind.name == "READOUT":
            t = readout_tof_ticks(profile, device, b, tb)
            tof[cid] = {"ticks": t, "ns": t * tick_ns}
    a = profile.acquisition
    acq = {"modes": [m.value for m in a.modes], "max_states": a.max_discriminated_states,
           "integration_grid_ns": a.integration_granularity_ticks * tick_ns,
           "max_square_us": a.max_square_integration_ticks * tick_ns / 1e3,
           "max_weighted_us": a.max_weighted_integration_ticks * tick_ns / 1e3,
           "max_weight_sets": a.max_weight_sets, "min_spacing_ns": a.min_acq_spacing_ticks * tick_ns,
           "internal_tof_ns": a.internal_tof_ticks * tick_ns, "convention": a.integration_convention,
           "verified": a.provenance.verified}
    return {
        "profile_name": profile.profile_name, "vendor": profile.vendor, "tick_hz": tick_hz, "tick_ns": tick_ns,
        "tick_hz_exact": profile.clock.tick_hz, "generators": gens, "ports": ports, "acquisition": acq,
        "latency_matrix": matrix, "tof": tof, "rules": VALIDATOR_RULES,
        "feedback": {"branch_equal_duration_required": profile.feedback.branch_equal_duration_required,
                     "max_condition_addresses": profile.feedback.max_condition_addresses,
                     "latencies": [{"src": e.src, "dst": e.dst, "payload": e.payload, "routing": e.routing,
                                    "latency_ns": e.latency_ticks * tick_ns, "jitter_ns": e.jitter_ticks * tick_ns,
                                    "verified": e.provenance.verified} for e in profile.feedback.latencies]},
        "bindings": [{"channel_id": c, "kind": b.kind.name.lower(), "generator_id": b.generator_id,
                      "port_id": b.port_id, "frame_id": b.frame_id, "qubits": list(b.qubits)}
                     for c, b in sorted(bindings.items())],
    }
