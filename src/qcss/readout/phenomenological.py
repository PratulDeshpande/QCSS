"""Fast-tier readout: true state -> confusion matrix -> reported label (error counted ONCE).

If the OS asked for IQ, draw IQ from the REPORTED label's cloud, restricted to that label's
decision region (rejection sampling), so IQ and label are always consistent.
"""
from __future__ import annotations

import numpy as np


class PhenomenologicalReadout:
    def __init__(self, confusion: np.ndarray, centroids: np.ndarray, sigma: float) -> None:
        self.c = np.asarray(confusion, dtype=np.float64)          # rows: true state, cols: reported
        if not np.allclose(self.c.sum(axis=1), 1.0):
            raise ValueError("confusion-matrix rows must sum to 1")
        self.mu = np.asarray(centroids, dtype=np.complex128)        # one complex centroid per label
        self.sigma = float(sigma)                                  # per-quadrature std

    def _label_of(self, z: np.ndarray) -> np.ndarray:              # nearest-centroid regions
        return np.argmin(np.abs(z[:, None] - self.mu[None, :]), axis=1)

    def sample(self, true_states: np.ndarray, rng: np.random.Generator, want_iq: bool = True):
        true_states = np.asarray(true_states, dtype=np.intp)
        u = rng.random(len(true_states))
        cdf = np.cumsum(self.c[true_states], axis=1)
        labels = (u[:, None] > cdf).sum(axis=1).astype(np.uint8)
        if not want_iq:
            return labels, None
        iq = np.empty(len(labels), dtype=np.complex128)
        todo = np.arange(len(labels))
        while todo.size:
            z = self.mu[labels[todo]] + self.sigma * (
                rng.standard_normal(todo.size) + 1j * rng.standard_normal(todo.size)
            )
            ok = self._label_of(z) == labels[todo]
            iq[todo[ok]] = z[ok]
            todo = todo[~ok]
        return labels, iq.astype(np.complex64)
