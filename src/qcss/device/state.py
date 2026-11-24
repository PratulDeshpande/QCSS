"""DeviceState: maintains baseline parameters and advances drift, TLS, and bursts on the lab clock.

Without a ``dynamics`` block in the device file every parameter is static, so oracle
devices behave exactly as specified.
"""
from __future__ import annotations

import math

import numpy as np

from qcss.config.device import DeviceSpec
from qcss.device.bursts import BurstModel
from qcss.device.drift import LogNormalDrift, OneOverFNoise
from qcss.device.labclock import LabClock
from qcss.device.scenarios import InjectedBurst, Scenarios
from qcss.device.tls import TLSBath, TLSDefect


def _finite(**values: float) -> None:
    for name, v in values.items():
        if not math.isfinite(v):
            raise ValueError(f"{name} must be finite")


class DeviceState:
    def __init__(self, device: DeviceSpec, rng: np.random.Generator, lab_clock: LabClock | None = None) -> None:
        self.device = device
        self.clock = lab_clock if lab_clock is not None else LabClock()
        self.rng = rng
        self._rows = {q.qubit_index: i for i, q in enumerate(device.qubits)}
        self.scenarios = Scenarios(len(device.qubits))
        dyn = device.dynamics
        self.enabled = dyn is not None and dyn.enabled
        if not self.enabled:
            return
        assert dyn is not None
        self.t1_drifts = [LogNormalDrift(q.t1_us, sigma_ln=dyn.t1_sigma_ln, tau_s=dyn.t1_tau_s, rng=rng)
                          for q in device.qubits]
        self.f_noises = [OneOverFNoise(amplitude=dyn.flux_noise_ghz, f_lo_hz=1e-4, f_hi_hz=1e3, rng=rng)
                         for _ in device.qubits]
        self.tls_baths = [TLSBath((q.f_max_ghz - 0.5, q.f_max_ghz + 0.1), n_defects=dyn.tls_per_qubit, rng=rng)
                          for q in device.qubits]
        self.bursts = (BurstModel(chip_area_cm2=device.chip_area_cm2, rng=rng, chip_size_mm=device.chip_side_mm)
                       if dyn.bursts else None)
        self.qubit_coords = np.array([q.xy_mm for q in device.qubits], dtype=np.float64)

    def advance_time(self, dt_s: float) -> None:
        self.clock.advance(dt_s)
        self.scenarios.forget_old_bursts(self.clock.t_s)
        if not self.enabled or self.scenarios.frozen:
            return
        if self.bursts is not None:
            self.bursts.advance_to(self.clock.t_s)
        for d in self.t1_drifts:
            d.step(dt_s)
        for fn in self.f_noises:
            fn.step(dt_s)
        for tls in self.tls_baths:
            tls.step(dt_s)

    def snapshot(self) -> tuple[list[float], list[float]]:
        """Returns (effective_f01_ghz, effective_t1_ns) at the current lab time, scenarios included."""
        f, t1 = self._natural()
        t = self.clock.t_s
        out = [self.scenarios.apply(i, fi, ti, t) for i, (fi, ti) in enumerate(zip(f, t1, strict=True))]
        return [o[0] for o in out], [o[1] for o in out]

    def _natural(self) -> tuple[list[float], list[float]]:
        if not self.enabled:
            return [q.f_max_ghz for q in self.device.qubits], [q.t1_us * 1e3 for q in self.device.qubits]
        extra_gamma = (self.bursts.extra_gamma1_per_us(self.clock.t_s, self.qubit_coords)
                       if self.bursts is not None else np.zeros(len(self.device.qubits)))
        eff_f, eff_t1_ns = [], []
        for i, q in enumerate(self.device.qubits):
            f_eff = q.f_max_ghz + self.f_noises[i].step(0.0)
            eff_f.append(f_eff)
            gamma_tot = (1.0 / self.t1_drifts[i].step(0.0) + self.tls_baths[i].extra_gamma1_per_us(f_eff)
                         + float(extra_gamma[i]))
            eff_t1_ns.append(1e3 / gamma_tot)
        return eff_f, eff_t1_ns

    # ------------------------------------------------------------------ scenario controls (admin only)
    def _row(self, qubit_index: int) -> int:
        if qubit_index not in self._rows:
            raise KeyError(f"device has no qubit {qubit_index}")
        return self._rows[qubit_index]

    def kill_qubit(self, qubit_index: int) -> None:
        self.scenarios.dead.add(self._row(qubit_index))

    def revive_qubit(self, qubit_index: int) -> None:
        self.scenarios.dead.discard(self._row(qubit_index))

    def drift_step(self, qubit_index: int, df_ghz: float = 0.0, t1_factor: float = 1.0) -> None:
        _finite(df_ghz=df_ghz, t1_factor=t1_factor)
        if t1_factor <= 0:
            raise ValueError("t1_factor must be > 0")
        r = self._row(qubit_index)
        self.scenarios.f_offset_ghz[r] += df_ghz
        self.scenarios.t1_factor[r] *= t1_factor

    def tls_collision(self, qubit_index: int, g_mhz: float = 0.5, gamma_mhz: float = 1.0,
                      detuning_mhz: float = 0.0) -> None:
        """A defect drifts into resonance with the qubit where it sits now."""
        _finite(g_mhz=g_mhz, gamma_mhz=gamma_mhz, detuning_mhz=detuning_mhz)
        r = self._row(qubit_index)
        f_now = self.snapshot()[0][r]
        self.scenarios.tls.append((r, TLSDefect(f_ghz=f_now + 1e-3 * detuning_mhz, g_mhz=g_mhz,
                                                gamma_mhz=gamma_mhz, jump_mhz=0.0, switch_rate_hz=0.0)))

    def burst(self, qubit_index: int, peak_gamma_per_us: float = 2.0) -> None:
        """A cosmic-ray hit centred on the qubit, now (already past its ~10 us rise)."""
        _finite(peak_gamma_per_us=peak_gamma_per_us)
        self.scenarios.bursts.append(InjectedBurst(self._row(qubit_index), self.clock.t_s, peak_gamma_per_us))

    def freeze(self, frozen: bool) -> None:
        self.scenarios.frozen = frozen

    def clear_scenarios(self) -> None:
        self.scenarios = Scenarios(len(self.device.qubits), frozen=self.scenarios.frozen)

    # ------------------------------------------------------------------ persistence (plain data, no pickle)
    def to_dict(self) -> dict:
        """Everything that evolves, as JSON-ready data; the rest is rebuilt from the device file."""
        from dataclasses import asdict
        s = self.scenarios
        out: dict = {
            "clock_s": self.clock.t_s,
            "rng": self.rng.bit_generator.state,
            "scenarios": {"frozen": s.frozen, "dead": sorted(s.dead), "f_offset_ghz": list(s.f_offset_ghz),
                          "t1_factor": list(s.t1_factor), "tls": [[r, asdict(d)] for r, d in s.tls],
                          "bursts": [asdict(b) for b in s.bursts]},
        }
        if self.enabled:
            out["t1_ou"] = [d.ou.x for d in self.t1_drifts]
            out["f_ou"] = [[p.x for p in fn.parts] for fn in self.f_noises]
            out["tls_baths"] = [[asdict(d) for d in bath.defects] for bath in self.tls_baths]
            if self.bursts is not None:
                out["bursts"] = {"next_s": self.bursts._next_s, "arrivals": list(self.bursts.arrival_times_s),
                                 "events": [[e.t0_s, list(map(float, e.xy_mm)), e.peak_gamma_per_us]
                                            for e in self.bursts.events]}
        return out

    def load_dict(self, data: dict) -> None:
        """Restore what to_dict() saved into this freshly built state of the same device.

        Everything is parsed and checked into locals first, so a bad file leaves the state untouched.
        """
        from qcss.device.bursts import Burst
        n = len(self.device.qubits)

        def vec(xs: object, what: str) -> list[float]:
            out = [float(x) for x in xs]                    # type: ignore[attr-defined]
            if len(out) != n or not all(math.isfinite(x) for x in out):
                raise ValueError(f"saved {what} must be {n} finite numbers")
            return out

        clock_s = float(data["clock_s"])
        sc = data["scenarios"]
        dead = {int(r) for r in sc["dead"]}
        tls = [(int(r), TLSDefect(**d)) for r, d in sc["tls"]]
        injected = [InjectedBurst(**b) for b in sc["bursts"]]
        if not math.isfinite(clock_s) or not all(0 <= r < n for r in dead | {r for r, _ in tls}
                                                 | {b.row for b in injected}):
            raise ValueError("saved device state has a bad clock or qubit index")
        f_off, t1_fac = vec(sc["f_offset_ghz"], "f_offset_ghz"), vec(sc["t1_factor"], "t1_factor")
        if any(x <= 0 for x in t1_fac):
            raise ValueError("saved t1_factor must be > 0")
        t1_ou = f_ou = baths = burst_state = None
        if self.enabled:
            if "t1_ou" not in data:
                raise ValueError("saved device state has no drift (it was saved with dynamics off)")
            t1_ou = vec(data["t1_ou"], "t1_ou")
            f_ou = [[float(x) for x in xs] for xs in data["f_ou"]]
            baths = [[TLSDefect(**d) for d in defects] for defects in data["tls_baths"]]
            if len(f_ou) != n or len(baths) != n or any(len(xs) != len(fn.parts) for xs, fn in zip(f_ou, self.f_noises, strict=True)):
                raise ValueError("saved device state does not match this device")
            if self.bursts is not None and "bursts" in data:
                b = data["bursts"]
                next_s = None if b["next_s"] is None else float(b["next_s"])
                arrivals = [float(t) for t in b["arrivals"]]
                events = [Burst(float(t0), np.asarray(xy, dtype=np.float64), float(peak)) for t0, xy, peak in b["events"]]
                if (next_s is not None and not math.isfinite(next_s)) or not all(math.isfinite(t) for t in arrivals):
                    raise ValueError("saved burst times must be finite")
                burst_state = (next_s, arrivals, events)
        self.rng.bit_generator.state = data["rng"]      # raises before anything else changes if malformed
        self.clock.t_s = clock_s
        self.scenarios = Scenarios(n, frozen=bool(sc["frozen"]), dead=dead, f_offset_ghz=f_off, t1_factor=t1_fac,
                                   tls=tls, bursts=injected)
        if not self.enabled:
            return
        for d, x in zip(self.t1_drifts, t1_ou, strict=True):
            d.ou.x = x
        for fn, xs in zip(self.f_noises, f_ou, strict=True):
            for p, x in zip(fn.parts, xs, strict=True):
                p.x = x
        for bath, defects in zip(self.tls_baths, baths, strict=True):
            bath.defects = defects
        if burst_state is not None:
            self.bursts._next_s, self.bursts.arrival_times_s, self.bursts.events = burst_state
