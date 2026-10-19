"""Statistical assertion helpers with 5-sigma tolerance policy."""
from __future__ import annotations

import numpy as np
from scipy import stats


def assert_binomial(
    successes: int,
    n: int,
    p_expected: float,
    k: float = 5.0,
    delta_model: float = 0.0,
) -> None:
    """Assert empirical success rate matches p_expected within 5-sigma + model tolerance."""
    p_hat = successes / n
    if 0.02 < p_expected < 0.98:
        tol = k * np.sqrt(p_expected * (1.0 - p_expected) / n) + delta_model
        assert abs(p_hat - p_expected) <= tol, (
            f"p_hat={p_hat:.5f} vs {p_expected:.5f} +/- {tol:.5f}"
        )
    else:  # Wilson score interval at ~5 sigma for extreme probabilities
        ci = stats.binomtest(successes, n).proportion_ci(confidence_level=1.0 - 5.7e-7, method="wilson")
        assert ci.low - delta_model <= p_expected <= ci.high + delta_model, (
            f"p_hat={p_hat:.5f}, ci=[{ci.low:.5f}, {ci.high:.5f}], p_expected={p_expected:.5f}"
        )


def assert_hist_matches(counts_a: np.ndarray, counts_b: np.ndarray, alpha: float = 1e-4) -> None:
    """Assert two histograms match via chi-square test."""
    table = np.vstack([counts_a, counts_b])
    table = table[:, table.sum(axis=0) > 0]
    _, p, _, expected = stats.chi2_contingency(table)
    assert (expected >= 5).all(), "too few counts per bin for chi-square"
    assert p > alpha, f"distributions differ (p={p:.2e})"
