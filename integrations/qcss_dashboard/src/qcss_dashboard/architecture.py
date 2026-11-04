"""The architecture map the Atlas view draws: QCSS's layers, what flows between them, and where each lives in code.

Written from the design notes and the code paths traced in src/qcss. Every node names the
packages and source lines it summarizes, so the dashboard can link each block to the code that implements it.
"""
from __future__ import annotations

from typing import Any

NODES: list[dict[str, Any]] = [
    {"id": "clients", "name": "Lab clients", "kind": "external", "view": "lab",
     "packages": ["integrations/qcss_qibolab", "platforms/", "Qibocal technician"],
     "summary": "Quark through Qibolab, Qibocal (the virtual technician), or any board client. They must not be able "
                "to tell QCSS from real hardware.",
     "detail": "Clients see only the lab link: DescribeDevice, calibration, jobs and results. Truth, tier and seeds "
               "never reach them (tests/integration/test_indistinguishability.py).",
     "sources": ["integrations/qcss_qibolab/src/qcss_qibolab/controller.py:22"]},
    {"id": "adapters", "name": "Adapters and faces", "kind": "layer", "view": "boards",
     "packages": ["qcss.adapters", "qcss.boards", "qcss.chassis", "qcss.cli"],
     "summary": "The wire: gRPC ControlService (lab link), the admin channel, instrument faults, the Qibosoq board face. "
                "Translation and error mapping only, no physics.",
     "detail": "Errors become google.rpc details (BadRequest field violations, PreconditionFailure). Bearer tokens are "
               "compared in constant time; non-loopback binds need TLS and a token.",
     "sources": ["src/qcss/adapters/grpc_server.py:31", "src/qcss/adapters/admin_server.py:25",
                 "src/qcss/boards/qibosoq.py:110"]},
    {"id": "runtime", "name": "Runtime", "kind": "layer", "view": "lab",
     "packages": ["qcss.runtime"],
     "summary": "Job lifecycle (queue, priority, backpressure, replay), the simulation context, the calibration store "
                "with epochs, persistence and instrument pacing. The only place subsystems are wired together.",
     "detail": "Jobs run in 1024-shot chunks; the producer stays at most 64 chunks ahead of the reader; results are "
               "retained for the 256 most recent jobs.",
     "sources": ["src/qcss/runtime/jobs.py:64", "src/qcss/runtime/runner.py:174",
                 "src/qcss/runtime/calibration_store.py:50"]},
    {"id": "compiler", "name": "Compiler and validator", "kind": "layer", "view": "program",
     "packages": ["qcss.ir"],
     "summary": "Job to Program IR: waveform synthesis, sweep expansion, channel bindings, frames, and the hardware "
                "rule validator (grids, memory, NCO, acquisitions, branch latency, saturation).",
     "detail": "A violation is reported with the job's field path, exactly as a real instrument driver would refuse "
               "the upload.",
     "sources": ["src/qcss/ir/compiler.py:87", "src/qcss/ir/validator.py:73"]},
    {"id": "router", "name": "Tier router", "kind": "layer", "view": "physics",
     "packages": ["qcss.physics.router", "qcss.physics.lifter"],
     "summary": "A planning dry run lifts every pulse to the gate it performs; the router then picks the cheapest tier "
                "that is still faithful (T0 surrogate, T1a stabilizer, T1b statevector, T2 Lindblad).",
     "detail": "Leakage above 0.03, overlapping pulses on a shared qubit, raw-trace readout, or more than 26 qubits "
               "decide the tier; T2 handles at most 4 qutrits.",
     "sources": ["src/qcss/runtime/runner.py:369", "src/qcss/physics/router.py:21"]},
    {"id": "executor", "name": "Shot executor", "kind": "layer", "view": "timing",
     "packages": ["qcss.feedback", "qcss.timing"],
     "summary": "One discrete-event timeline per shot, ordered by (tick, priority, sequence): plays, frame updates, "
                "acquisitions, branch decisions after the measured latency.",
     "detail": "Same-tick order: frame update < acquisition complete < branch decision < playback. No hidden reset "
               "between shots: the repetition delay is real relaxation.",
     "sources": ["src/qcss/feedback/executor.py:232", "src/qcss/timing/des.py:17"]},
    {"id": "render", "name": "Render (seam 1)", "kind": "seam", "view": "signal",
     "packages": ["qcss.signal"],
     "summary": "Programmed samples to what the qubit sees: NCO phase, the lab's IQ correction, the hidden mixer truth, "
                "LO leakage, flux-line distortion and predistortion. Output: Omega(t) in rad/ns and flux V(t).",
     "detail": "With ideal truth and correction the chain takes an exact fast path; otherwise image sidebands and "
               "flux tails appear exactly where a real lab would see them.",
     "sources": ["src/qcss/signal/port_renderer.py:23", "src/qcss/signal/mixer.py:46"]},
    {"id": "parameters", "name": "Parameters (seam 2)", "kind": "seam", "view": "chip",
     "packages": ["qcss.device"],
     "summary": "The hidden chip on the lab clock: T1 drift, 1/f flux noise, TLS defects, cosmic-ray bursts and admin "
                "scenarios, producing f01 and T1 per qubit per chunk.",
     "detail": "Lab time is wall time x time_scale; the chip state is saved and keeps ageing while the chassis is down.",
     "sources": ["src/qcss/device/state.py:18", "src/qcss/runtime/runner.py:268"]},
    {"id": "evolve", "name": "Evolve (seam 3)", "kind": "seam", "view": "physics",
     "packages": ["qcss.physics"],
     "summary": "The quantum state: qutrit Lindblad master equation (T2), statevector with quantum jumps (T1b), Stim "
                "stabilizer with Pauli-twirled noise (T1a), or a classical surrogate (T0).",
     "detail": "T2 solves H = Delta n + alpha/2 a+a+aa + Omega drive + J exchange with collapse operators for decay, "
               "thermal excitation and dephasing (QuTiP mesolve).",
     "sources": ["src/qcss/physics/lindblad_t2.py:100", "src/qcss/physics/statevector_t1b.py:1"]},
    {"id": "readout", "name": "Readout (seam 4)", "kind": "seam", "view": "readout",
     "packages": ["qcss.readout"],
     "summary": "True qubit level to resonator field to ADC trace (with T1 jumps and noise) to integrated IQ to a "
                "label, using the lab's discriminator when it has written one.",
     "detail": "Gate tiers use a surrogate whose confusion matrix is derived from the same physical model.",
     "sources": ["src/qcss/readout/resonator.py:39", "src/qcss/readout/model.py:57"]},
    {"id": "config", "name": "Config and core", "kind": "foundation", "view": "config",
     "packages": ["qcss.config", "qcss.core"],
     "summary": "YAML profiles and devices (Pydantic, frozen, extra fields forbidden), exact rational time base, seeded "
                "random streams, units and errors.",
     "detail": "Random streams are PCG64 keyed by (global seed, job key, domain, point, chunk): shots, readout, drift, "
               "jitter and Stim each get their own.",
     "sources": ["src/qcss/config/loader.py:13", "src/qcss/core/timebase.py:38", "src/qcss/core/seeding.py:17"]},
    {"id": "admin", "name": "Admin channel", "kind": "external", "view": "admin",
     "packages": ["qcss.adapters.admin_server", "proto/qcss/admin/v1"],
     "summary": "The operator's side door (own port and token): read the truth, inspect jobs, change mode, inject "
                "scenarios and instrument faults. This dashboard is an admin client.",
     "detail": "Calibration cannot be changed here: it belongs to the lab (compare-and-swap on the lab link).",
     "sources": ["src/qcss/adapters/admin_server.py:43"]},
]

EDGES: list[dict[str, str]] = [
    {"from": "clients", "to": "adapters", "label": "Job, calibration (gRPC / board protocol)"},
    {"from": "adapters", "to": "runtime", "label": "submit, stream results"},
    {"from": "runtime", "to": "compiler", "label": "plan: compile + validate"},
    {"from": "compiler", "to": "router", "label": "Program IR + waveforms"},
    {"from": "router", "to": "executor", "label": "tier + engine"},
    {"from": "executor", "to": "render", "label": "Play at tick t"},
    {"from": "parameters", "to": "evolve", "label": "f01, T1 now"},
    {"from": "render", "to": "evolve", "label": "Omega(t), V_flux(t)"},
    {"from": "evolve", "to": "readout", "label": "true level"},
    {"from": "readout", "to": "runtime", "label": "IQ, label, trace"},
    {"from": "config", "to": "runtime", "label": "profile, device"},
    {"from": "admin", "to": "parameters", "label": "scenarios, truth"},
    {"from": "admin", "to": "runtime", "label": "mode, inspect, faults"},
]

PIPELINE: list[dict[str, str]] = [
    {"id": "plan", "name": "Plan", "summary": "Pin calibration, expand sweeps, compile, validate, dry-run lift, route "
     "to a tier.", "source": "src/qcss/runtime/runner.py:369"},
    {"id": "render", "name": "Render", "summary": "Each Play becomes the drive the qubit sees (NCO, mixers, LO) or a "
     "distorted flux pulse.", "source": "src/qcss/feedback/executor.py:139"},
    {"id": "evolve", "name": "Evolve", "summary": "The chosen engine advances the state through the pulses and idle "
     "time, with the chip parameters of this moment.", "source": "src/qcss/feedback/executor.py:201"},
    {"id": "readout", "name": "Read out", "summary": "The measured level drives the resonator; the trace is "
     "integrated and discriminated.", "source": "src/qcss/readout/model.py:126"},
    {"id": "stream", "name": "Stream", "summary": "1024-shot chunks are paced to instrument time and streamed, "
     "resumable by sequence number.", "source": "src/qcss/runtime/runner.py:668"},
]


def architecture() -> dict[str, Any]:
    return {"nodes": NODES, "edges": EDGES, "pipeline": PIPELINE}
