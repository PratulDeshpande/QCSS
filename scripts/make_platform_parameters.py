"""Write a QCSS platform's starting parameters.json: the calibration a lab has from its last cooldown.

The values are close to the chip but not right (frequencies off by up to a few hundred kHz,
pi amplitudes off by a few percent), as a lab finds its records after warming up and cooling
down again. The discriminator is fitted from simulated |0> and |1> shots, as the last
single-shot classification would have left it. Qibocal (the virtual technician) then
calibrates the platform properly; QCSS itself never writes calibration at run time.

    python scripts/make_platform_parameters.py platforms/qcss_qblox_5q --profile qblox_cluster_5q \
        --device transmon_5q --seed 2026
"""
from __future__ import annotations

import argparse
import asyncio
import json
import pathlib
import sys

import numpy as np

from qcss.cli import _resolve_device_path, _resolve_profile_path
from qcss.config.loader import load_device, load_profile
from qcss.core.ndarray import from_proto, to_proto
from qcss.readout.discriminator import fit_binary_discriminator
from qcss.runtime.runner import SimulationContext, create_simulation_runner
from qcss.v1 import job_pb2

PI_NS, REL_SIGMA, READOUT_NS = 40, 0.2, 2000


class Convention:
    """How the platform's instrument turns a 40 ns Gaussian and a 2 us readout into samples and IQ.

    cluster:  QcssController, Qibolab's own envelope sampled at the sequencer rate, IQ summed;
    qibosoq:  Qibolab's RFSoC driver on a qibosoq board, QICK's Gaussian (sigma * sqrt(2)) in whole
              16-sample fabric cycles, IQ the window mean (the sum over the decimated samples).
    """

    def __init__(self, board: str, ctx: SimulationContext) -> None:
        gen = ctx.profile.generators[0]
        self.board = board
        self.sr_gsps = float(gen.sample_rate_hz) / 1e9
        tick_hz = float(ctx.profile.clock.tick_hz)
        gran = ctx.profile.acquisition.integration_granularity_ticks
        self.ticks_per_sample = round(tick_hz / float(gen.sample_rate_hz))
        self.readout_ticks = round(READOUT_NS * 1e-9 * tick_hz / gran) * gran
        if board == "qibosoq":
            self.n = round(PI_NS * self.sr_gsps / 16) * 16
            self.iq_divisor = self.readout_ticks / gran
        else:
            self.n = round(PI_NS * self.sr_gsps)
            self.iq_divisor = 1.0

    def envelope(self) -> np.ndarray:
        x = np.arange(self.n)
        if self.board == "qibosoq":
            si = self.n * REL_SIGMA * np.sqrt(2)                    # qibosoq: n / (1 / rel_sigma) * sqrt(2)
            return np.exp(-(x - (self.n / 2 - 0.5)) ** 2 / (2 * si ** 2))
        return np.exp(-0.5 * ((x - (self.n - 1) / 2) / (REL_SIGMA * self.n)) ** 2)

    def pi_amplitude(self, rabi_rad_ns: float) -> float:
        return float(np.pi / (rabi_rad_ns * self.envelope().sum() / self.sr_gsps))


def fitted_discriminator(ctx: SimulationContext, conv: Convention, q: int, pi_amp: float) -> tuple[float, float]:
    """(iq_angle, threshold) in Qibolab's convention, from 2000 simulated shots each of |0> and |1>."""
    j = job_pb2.Job(num_shots=2000, repetition_delay_ticks=round(300e-6 * float(ctx.profile.clock.tick_hz)))
    env = pi_amp * conv.envelope()
    j.waveform_library["pi"].CopyFrom(job_pb2.Waveform(
        shape=job_pb2.WAVEFORM_SHAPE_ARBITRARY, samples=to_proto(env.astype(np.complex128)), length_samples=conv.n))
    for k, play in enumerate((False, True)):
        ins = j.program_points.add(indices=[k]).main.instructions
        if play:
            ins.add(start_tick=0, play=job_pb2.Play(channel_id=f"xy_q{q}", waveform_id="pi", amplitude=1.0))
        ins.add(start_tick=conv.n * conv.ticks_per_sample, acquire=job_pb2.Acquire(
            channel_id=f"ro_q{q}", integration_ticks=conv.readout_ticks, mode=job_pb2.ACQUISITION_MODE_INTEGRATED,
            result_key="z"))
    runner = create_simulation_runner(ctx.profile, ctx.device, ctx.tb, context=ctx)

    async def go():
        return [c async for c in runner("cooldown", j, asyncio.Event())]
    z: dict[int, list] = {0: [], 1: []}
    for c in asyncio.run(go()):
        z[c.sweep_point[0]].append(from_proto(c.acquisitions[0].iq))
    disc = fit_binary_discriminator(np.concatenate(z[0]) / conv.iq_divisor, np.concatenate(z[1]) / conv.iq_divisor)
    return -disc.rotation_rad, disc.threshold          # Qibolab rotates by +iq_angle (QCSS by -rotation)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("platform_dir", type=pathlib.Path)
    ap.add_argument("--profile", default="qblox_cluster_5q")
    ap.add_argument("--device", default="transmon_5q")
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--board", choices=["cluster", "qibosoq"], default="cluster",
                    help="how the platform's instrument samples pulses and reports IQ")
    args = ap.parse_args(argv)
    rng = np.random.default_rng(args.seed)
    prof = load_profile(_resolve_profile_path(args.profile))
    d_path = _resolve_device_path(args.device)
    assert d_path is not None
    dev = load_device(d_path)
    ctx = SimulationContext(prof, dev, global_seed=args.seed, tier_policy="T1B")
    conv = Convention(args.board, ctx)
    configs: dict[str, dict] = {}
    single: dict[str, dict] = {}
    for qc in ctx.calibration.snapshot().qubits:
        q, d = qc.qubit_index, ctx.qdef[qc.qubit_index]
        pi_amp = conv.pi_amplitude(d.rabi_rad_ns)                               # what a pi pulse should be
        iq_angle, threshold = fitted_discriminator(ctx, conv, q, pi_amp)
        configs[f"{q}/drive"] = {"kind": "iq", "frequency": round(qc.drive_frequency_hz + rng.uniform(-3e5, 3e5))}
        configs[f"{q}/probe"] = {"kind": "iq", "frequency": round(qc.readout_frequency_hz)}
        configs[f"{q}/acquisition"] = {"kind": "acquisition", "delay": 0.0, "smearing": 0.0,
                                       "threshold": threshold, "iq_angle": iq_angle, "kernel": None}
        configs[f"{q}/flux"] = {"kind": "dc", "offset": 0.0}
        amp = round(pi_amp * (1 + rng.uniform(-0.03, 0.03)), 6)
        gauss = {"kind": "gaussian", "rel_sigma": REL_SIGMA}
        single[str(q)] = {
            "RX": [[f"{q}/drive", {"kind": "pulse", "duration": PI_NS, "amplitude": amp, "envelope": gauss,
                                   "relative_phase": 0.0}]],
            "RX90": [[f"{q}/drive", {"kind": "pulse", "duration": PI_NS, "amplitude": round(amp / 2, 6),
                                     "envelope": gauss, "relative_phase": 0.0}]],
            "MZ": [[f"{q}/acquisition", {
                "kind": "readout", "acquisition": {"kind": "acquisition", "duration": READOUT_NS},
                "probe": {"kind": "pulse", "duration": READOUT_NS, "amplitude": 0.1,
                          "envelope": {"kind": "rectangular"}, "relative_phase": 0.0}}]],
        }
    two = {}
    for c in dev.couplers:                                  # a CZ per coupled pair: flux on the higher qubit
        low, high = sorted(c.qubit_pair, key=lambda q: ctx.qdef[q].f01_ghz)
        two[f"{min(low, high)}-{max(low, high)}"] = {"CZ": [
            [f"{high}/flux", {"kind": "pulse", "duration": 60, "amplitude": 0.3, "envelope": {"kind": "rectangular"},
                              "relative_phase": 0.0}],
            [f"{low}/drive", {"kind": "virtualz", "phase": 0.0}],
            [f"{high}/drive", {"kind": "virtualz", "phase": 0.0}]]}
    params = {"settings": {"nshots": 1024, "relaxation_time": 300_000}, "configs": configs,
              "native_gates": {"single_qubit": single, "two_qubit": two, "coupler": {}}}
    args.platform_dir.mkdir(parents=True, exist_ok=True)
    (args.platform_dir / "parameters.json").write_text(json.dumps(params, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.platform_dir / 'parameters.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
