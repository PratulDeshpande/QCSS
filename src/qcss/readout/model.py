"""Readout models used by the runtime (fault seam 4). Each error is counted exactly once.

* PhysicalReadout (pulse-level tiers): true level -> resonator traces with T1 jumps, ToF and
  eta-calibrated noise -> weighted integration over the ADC window that starts at the
  acquisition delay -> the discriminator the OS configured (rotation + threshold), or an
  auto-calibrated one. No confusion matrix anywhere on this path (RO-01).
* SurrogateReadout (gate-level tiers): true level -> confusion matrix -> label, with IQ drawn
  consistently with the label. The confusion matrix is DERIVED from the physical model by
  simulated calibration shots, so the fast tiers report the same readout error as T2.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from qcss.config.device import ResonatorSpec
from qcss.readout.discriminator import BinaryDiscriminator, MultistateDiscriminator
from qcss.readout.phenomenological import PhenomenologicalReadout
from qcss.readout.resonator import DispersiveReadout, ResonatorParams, drive_amplitude_for_photons

TWO_PI = 2 * np.pi


@dataclass(frozen=True)
class ReadoutDrive:
    """The probe tone a board played itself (QICK): the hardware view of the ADC window.

    ``scale`` multiplies the drive that gives the resonator its nominal photon number; the window starts
    ``offset_samples`` after the tone began (negative: before), and the tone lasts ``drive_samples``.
    The window is summed as captured, with no matched filter. ``phase_rad`` is the tone's phase: it turns
    what comes back, not the noise.
    """
    scale: float
    offset_samples: int
    drive_samples: int
    phase_rad: float = 0.0


# The probe amplitude (fraction of full scale) that gives a resonator its nominal photon number
# (ResonatorSpec.readout_photons); photons grow as the square of the amplitude. Not from a datasheet.
NOMINAL_TONE_AMPLITUDE = 0.5


def tone_drive(amplitude: float, offset_samples: int, drive_samples: int, phase_rad: float = 0.0) -> ReadoutDrive:
    """The ReadoutDrive of a probe tone played at ``amplitude`` (fraction of full scale) and ``phase_rad``."""
    return ReadoutDrive(amplitude / NOMINAL_TONE_AMPLITUDE, int(offset_samples), int(drive_samples), float(phase_rad))


@dataclass(frozen=True)
class AcquireResult:
    labels: np.ndarray            # uint8, one per shot
    iq: np.ndarray                # complex, one integrated point per shot
    traces: np.ndarray | None     # complex (shots, samples) for raw-trace acquisitions


class PhysicalReadout:
    def __init__(self, spec: ResonatorSpec, adc_dt_ns: float, tof_ns: float, max_states: int = 2,
                 convention: str = "sum", readout_frequency_hz: float | None = None,
                 delay_ns: float | None = None, os_rotation_rad: float | None = None,
                 os_threshold: float | None = None) -> None:
        self.spec = spec
        self.dt = adc_dt_ns
        self.max_states = max_states
        self.convention = convention
        kappa = TWO_PI * spec.kappa_mhz * 1e-3
        pulls = tuple(TWO_PI * x * 1e-3 for x in spec.pulls_mhz)
        if readout_frequency_hz is None:                       # dressed midpoint between |0> and |1>
            det = -(pulls[0] + pulls[1]) / 2
        else:
            det = TWO_PI * (spec.f_r_ghz * 1e9 - readout_frequency_hz) * 1e-9
        self.tof_samples = round(tof_ns / adc_dt_ns)
        self.delay_samples = round((tof_ns if delay_ns is None else delay_ns) / adc_dt_ns)
        self.ro = DispersiveReadout(ResonatorParams(kappa_rad_ns=kappa, pulls_rad_ns=pulls,
                                                    drive_detuning_rad_ns=det, eta=spec.eta,
                                                    tof_samples=self.tof_samples, dt_ns=adc_dt_ns))
        chi = (pulls[1] - pulls[0]) / 2
        self.amp = drive_amplitude_for_photons(spec.readout_photons, kappa, chi)
        self.os_disc = (BinaryDiscriminator(os_threshold, os_rotation_rad or 0.0)
                        if os_threshold is not None else None)
        self._bases: dict[int, np.ndarray] = {}
        self._cals: dict[int, tuple[np.ndarray, object]] = {}
        self._driven: dict[tuple[int, int, int], np.ndarray] = {}

    def _base(self, n: int) -> np.ndarray:
        if n not in self._bases:
            drive = np.full(n, self.amp, dtype=np.complex128)
            self._bases[n] = np.stack([self.ro.mean_field(m, drive) for m in range(3)])
        return self._bases[n]

    def _window(self, traces: np.ndarray, n: int) -> np.ndarray:
        s = self.delay_samples
        win = np.zeros((traces.shape[0], n), dtype=np.complex128)
        avail = traces[:, s:s + n]
        win[:, :avail.shape[1]] = avail
        return win

    def _integrate(self, win: np.ndarray, w: np.ndarray) -> np.ndarray:
        z = win @ np.conj(w) * self.dt
        return z / len(w) if self.convention == "mean" else z

    def _calibration(self, n: int) -> tuple[np.ndarray, object]:
        """Matched-filter weights and auto discriminator from noiseless mean traces."""
        if n not in self._cals:
            self._cals[n] = self._calibrate(n)
        return self._cals[n]

    def _calibrate(self, n: int) -> tuple[np.ndarray, object]:
        base = self._base(n)
        mean_b = -self.amp + np.sqrt(self.ro.p.kappa_rad_ns) * base          # reflection, per level
        rec = np.zeros((3, n + self.tof_samples), dtype=np.complex128)
        rec[:, self.tof_samples:] = mean_b
        win = self._window(rec, n)
        w = win[1] - win[0]
        w = w / max(np.max(np.abs(w)), 1e-30)                             # Qblox weights live in [-1, 1]
        z = self._integrate(win, w)
        if self.max_states <= 2:
            d = z[1] - z[0]
            rot = float(np.angle(d))
            disc = BinaryDiscriminator(threshold=float(np.real((z[0] + z[1]) / 2 * np.exp(-1j * rot))),
                                       rotation_rad=rot)
        else:
            disc = MultistateDiscriminator(centroids=z[:min(self.max_states, 3)])
        return w, disc

    def acquire(self, levels: np.ndarray, n: int, t1_ns: float, rng: np.random.Generator,
                weights: np.ndarray | None = None, want_trace: bool = False,
                drive: ReadoutDrive | None = None) -> AcquireResult:
        levels = np.asarray(levels, dtype=np.intp)
        if drive is not None:
            return self._acquire_driven(levels, n, t1_ns, rng, drive, want_trace)
        base = self._base(n)
        tone = np.full(n, self.amp, dtype=np.complex128)
        traces = self.ro.traces(levels, tone, t1_ns, rng, base=base)
        w_auto, disc_auto = self._calibration(n)
        w = w_auto if weights is None else np.asarray(weights, dtype=np.complex128)
        z = self._integrate(self._window(traces, n), w)
        disc = self.os_disc if self.os_disc is not None else disc_auto
        labels = disc.classify(z).astype(np.uint8)                  # type: ignore[union-attr]
        return AcquireResult(labels, z, traces if want_trace else None)

    def _acquire_driven(self, levels: np.ndarray, n: int, t1_ns: float, rng: np.random.Generator,
                        drive: ReadoutDrive, want_trace: bool) -> AcquireResult:
        pre = max(0, -drive.offset_samples)              # the record starts this long before the tone
        start = drive.offset_samples + pre
        m = max(1, start + n - self.tof_samples)         # drive samples the record needs to cover the window
        key = (m, pre, drive.drive_samples)
        if key not in self._driven:                      # unit-amplitude mean fields: the model is linear
            d = np.zeros(m, dtype=np.complex128)
            d[pre:pre + drive.drive_samples] = self.amp
            self._driven[key] = np.stack([self.ro.mean_field(lv, d) for lv in range(3)])
        c = drive.scale * np.exp(1j * drive.phase_rad)          # the model is linear in the drive
        base = self._driven[key] * c
        d = np.zeros(m, dtype=np.complex128)
        d[pre:pre + drive.drive_samples] = self.amp * c
        win = self.ro.traces(levels, d, t1_ns, rng, base=base)[:, start:start + n]
        z = win.sum(axis=1) * self.dt
        if self.convention == "mean":
            z = z / n
        if self.os_disc is not None:
            disc: object = self.os_disc
        else:                                            # the noiseless levels 0 and 1, split halfway
            rec = np.zeros((2, m + self.tof_samples), dtype=np.complex128)
            rec[:, self.tof_samples:] = -d + np.sqrt(self.ro.p.kappa_rad_ns) * base[:2]
            z01 = rec[:, start:start + n].sum(axis=1) * self.dt
            rot = float(np.angle(z01[1] - z01[0]))
            disc = BinaryDiscriminator(float(np.real((z01[0] + z01[1]) / 2 * np.exp(-1j * rot))), rot)
        labels = disc.classify(z).astype(np.uint8)       # type: ignore[attr-defined]
        return AcquireResult(labels, z, win if want_trace else None)


class SurrogateReadout:
    CAL_SHOTS = 2000

    def __init__(self, physical: PhysicalReadout | None, max_states: int = 2, sigma: float = 0.05) -> None:
        self.physical = physical
        self.max_states = max_states
        self.sigma = sigma
        self._models: dict[tuple[int, float], PhenomenologicalReadout] = {}

    def _model(self, n: int, t1_ns: float) -> PhenomenologicalReadout:
        key = (n, t1_ns)
        if key not in self._models:
            self._models[key] = self._derive(n, t1_ns)
        return self._models[key]

    def _derive(self, n: int, t1_ns: float) -> PhenomenologicalReadout:
        n_labels = min(self.max_states, 3)
        if self.physical is None:                                      # no resonator data: ideal readout
            conf = np.zeros((3, n_labels))
            for lvl in range(3):
                conf[lvl, min(lvl, n_labels - 1)] = 1.0
            return PhenomenologicalReadout(conf, np.arange(n_labels).astype(complex), self.sigma)
        rng = np.random.default_rng(20_260_419)                      # calibration is part of setup
        levels = np.repeat(np.arange(3), self.CAL_SHOTS)
        res = self.physical.acquire(levels, n, t1_ns, rng)          # T1 decay during the window -> P(0|1)
        conf = np.zeros((3, n_labels))
        mu = np.zeros(n_labels, dtype=complex)
        for lvl in range(3):
            lab = res.labels[levels == lvl]
            conf[lvl] = np.bincount(np.minimum(lab, n_labels - 1), minlength=n_labels)[:n_labels] / len(lab)
        for k in range(n_labels):
            sel = res.labels == k
            mu[k] = res.iq[sel].mean() if np.any(sel) else res.iq[levels == k].mean()
        spread = float(np.sqrt(np.mean([np.var(np.real(res.iq[levels == lv])) for lv in range(2)])))
        return PhenomenologicalReadout(conf, mu, max(spread, 1e-12))

    def acquire(self, levels: np.ndarray, n: int, t1_ns: float, rng: np.random.Generator,
                weights: np.ndarray | None = None, want_trace: bool = False,
                drive: ReadoutDrive | None = None) -> AcquireResult:
        if drive is not None and self.physical is not None:     # a board-played tone: the window as captured
            return self.physical.acquire(levels, n, t1_ns, rng, weights, want_trace, drive=drive)
        t1_key = float(min(t1_ns, 1e18))
        if self.physical is not None:
            t1_key = float(f"{t1_key:.3g}")                        # drifted T1s share a calibration
        labels, iq = self._model(n, t1_key).sample(np.asarray(levels), rng, want_iq=True)
        assert iq is not None                                      # want_iq=True always returns IQ
        return AcquireResult(labels.astype(np.uint8), iq, None)
