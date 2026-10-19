"""Weighted integration of ADC traces with vendor convention support and validation."""
from __future__ import annotations

import numpy as np


class WeightedIntegrator:
    """Performs weighted integration Z = sum_n s[n] conj(w[n]) dt over the acquisition window."""

    def __init__(self, convention: str = "sum") -> None:
        if convention not in ("sum", "mean"):
            raise ValueError(f"Unknown integration convention '{convention}', must be 'sum' or 'mean'")
        self.convention = convention

    def integrate(
        self,
        traces: np.ndarray,
        weights: np.ndarray,
        start_sample: int = 0,
        integration_length: int | None = None,
        dt_ns: float = 1.0,
    ) -> np.ndarray:
        """Integrate traces with weights.

        Args:
            traces: Complex ADC traces of shape (shots, samples) or (samples,).
            weights: Complex integration weights of shape (weight_samples,).
            start_sample: Starting sample index in trace for the acquisition window.
            integration_length: Expected integration duration in samples. If provided,
                validates len(weights) == integration_length (RO-09).
            dt_ns: ADC sample period in nanoseconds.

        Returns:
            Integrated complex values of shape (shots,) or scalar if 1D trace.
        """
        weights = np.asarray(weights, dtype=np.complex128)
        if integration_length is not None and len(weights) != integration_length:
            raise ValueError(
                f"Weight length mismatch: weights has {len(weights)} samples, "
                f"but integration_length is {integration_length} samples (RO-09)"
            )

        n_w = len(weights)
        is_1d = traces.ndim == 1
        tr = traces[None, :] if is_1d else traces

        if start_sample + n_w > tr.shape[1]:
            raise ValueError(
                f"Acquisition window [{start_sample}, {start_sample + n_w}) exceeds trace length {tr.shape[1]}"
            )

        window = tr[:, start_sample:start_sample + n_w]
        # Z = sum_n s[n] conj(w[n]) dt
        z = window @ np.conj(weights) * dt_ns

        if self.convention == "mean":
            z = z / float(n_w)

        return z[0] if is_1d else z
