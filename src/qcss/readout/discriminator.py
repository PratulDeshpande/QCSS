"""State discrimination from integrated IQ points (Binary and Multistate)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class BinaryDiscriminator:
    """Binary state discriminator: rotates IQ plane then thresholds on real axis (Qblox convention)."""
    threshold: float
    rotation_rad: float = 0.0

    def classify(self, z: np.ndarray) -> np.ndarray:
        """Classify integrated IQ points into binary states (0 or 1)."""
        z_arr = np.asarray(z, dtype=np.complex128)
        rotated = z_arr * np.exp(-1j * self.rotation_rad)
        return (rotated.real > self.threshold).astype(np.int32)


@dataclass
class MultistateDiscriminator:
    """Multistate discriminator for up to 4 states using minimum Mahalanobis/Euclidean distance (ZI convention)."""
    centroids: np.ndarray  # complex centroids of shape (n_states,)
    sigma: float = 1.0

    def classify(self, z: np.ndarray) -> np.ndarray:
        """Classify integrated points to the nearest centroid."""
        z_arr = np.asarray(z, dtype=np.complex128)
        # Distances: shape (shots, n_states)
        diffs = abs(z_arr[:, None] - self.centroids[None, :])
        return np.argmin(diffs, axis=1).astype(np.int32)


def fit_binary_discriminator(z0: np.ndarray, z1: np.ndarray) -> BinaryDiscriminator:
    """Fit optimal rotation and threshold from simulated calibration shots of |0> and |1>."""
    m0 = np.mean(z0)
    m1 = np.mean(z1)
    diff = m1 - m0
    rotation = float(np.angle(diff))

    u0 = (z0 * np.exp(-1j * rotation)).real
    u1 = (z1 * np.exp(-1j * rotation)).real
    threshold = float(0.5 * (np.mean(u0) + np.mean(u1)))
    return BinaryDiscriminator(threshold=threshold, rotation_rad=rotation)


def fit_multistate_discriminator(z_by_state: dict[int, np.ndarray]) -> MultistateDiscriminator:
    """Fit centroids and variance from calibration shots of each level."""
    max_state = max(z_by_state.keys())
    centroids = np.zeros(max_state + 1, dtype=np.complex128)
    variances = []
    for s, z in z_by_state.items():
        c = np.mean(z)
        centroids[s] = c
        variances.append(np.var(z))

    sigma = float(np.sqrt(np.mean(variances))) if variances else 1.0
    return MultistateDiscriminator(centroids=centroids, sigma=sigma)
