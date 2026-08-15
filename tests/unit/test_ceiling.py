"""
Tests for the step-1 ceiling analysis.

The load-bearing test is `test_analytic_matches_empirical`: the closed form and
the measured correlation are computed by completely different routes, so their
agreement is real evidence that the HML decomposition is right rather than a
tautology.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ffrep.evaluate.ceiling import analytic_ceiling, compare


def _spreads(rho: float, sigma_s: float, sigma_b: float, n: int = 4000, seed: int = 0):
    """Two correlated spread series with known rho and volatilities."""
    rng = np.random.default_rng(seed)
    z1 = rng.normal(size=n)
    z2 = rho * z1 + np.sqrt(1.0 - rho**2) * rng.normal(size=n)
    index = pd.date_range("1990-01-31", periods=n, freq="ME")
    return (
        pd.Series(sigma_s * z1, index=index, name="small"),
        pd.Series(sigma_b * z2, index=index, name="big"),
    )


class TestAnalyticCeiling:
    def test_matches_empirical_correlation(self):
        """
        The formula and a direct correlation of the same two series must agree.
        They are computed by different routes — one from sigmas and rho, the
        other from the realised series — so agreement is a genuine check.
        """
        small, big = _spreads(rho=0.6, sigma_s=0.037, sigma_b=0.041)
        hml = 0.5 * (small + big)
        assert analytic_ceiling(small, big) == pytest.approx(float(big.corr(hml)), abs=1e-6)

    def test_perfectly_correlated_equal_vol_spreads_give_ceiling_one(self):
        """If the two halves move identically, deleting one costs nothing."""
        small, big = _spreads(rho=1.0, sigma_s=0.04, sigma_b=0.04)
        assert analytic_ceiling(small, big) == pytest.approx(1.0, abs=1e-6)

    def test_ceiling_rises_with_correlation(self):
        """
        The economic content: the ceiling is set by how much the small-cap and
        large-cap value spreads co-move, which is a property of the market, not
        of anyone's data budget.
        """
        ceilings = [
            analytic_ceiling(*_spreads(rho=r, sigma_s=0.04, sigma_b=0.04, seed=1))
            for r in (0.0, 0.3, 0.6, 0.9)
        ]
        assert ceilings == sorted(ceilings)

    def test_uncorrelated_equal_vol_gives_one_over_sqrt_two(self):
        """Closed form: with rho=0 and equal vols the ceiling is 1/sqrt(2)."""
        small, big = _spreads(rho=0.0, sigma_s=0.04, sigma_b=0.04, n=20000, seed=2)
        assert analytic_ceiling(small, big) == pytest.approx(1 / np.sqrt(2), abs=0.01)

    def test_a_dominant_big_leg_pushes_the_ceiling_up(self):
        """If the big spread carries most of the variance, losing small hurts less."""
        quiet_small = analytic_ceiling(*_spreads(rho=0.5, sigma_s=0.01, sigma_b=0.05, seed=3))
        loud_small = analytic_ceiling(*_spreads(rho=0.5, sigma_s=0.05, sigma_b=0.01, seed=3))
        assert quiet_small > loud_small


class TestCompare:
    def test_identical_series_give_perfect_agreement(self):
        index = pd.date_range("2010-01-31", periods=100, freq="ME")
        series = pd.Series(np.random.default_rng(0).normal(scale=0.03, size=100), index=index)
        result = compare(series, series, name="x", window="all")
        assert result.correlation == pytest.approx(1.0)
        assert result.mean_gap_bps == pytest.approx(0.0, abs=1e-9)
        assert result.tracking_error_bps == pytest.approx(0.0, abs=1e-9)
        assert result.beta == pytest.approx(1.0)

    def test_window_bounds_are_applied(self):
        index = pd.date_range("2000-01-31", periods=240, freq="ME")
        rng = np.random.default_rng(4)
        a = pd.Series(rng.normal(size=240), index=index)
        b = pd.Series(rng.normal(size=240), index=index)
        result = compare(
            a, b, name="x", window="w", start=pd.Timestamp("2010-01-01")
        )
        assert result.n_obs == 120

    def test_gap_is_reported_in_basis_points(self):
        index = pd.date_range("2010-01-31", periods=50, freq="ME")
        # Deliberately non-constant: a flat series makes the correlation 0/0.
        base = pd.Series(
            np.random.default_rng(6).normal(scale=0.03, size=50), index=index
        )
        shifted = base + 0.0005  # 5 bps a month
        result = compare(shifted, base, name="x", window="all")
        assert result.mean_gap_bps == pytest.approx(5.0)

    def test_raises_when_the_window_is_empty(self):
        index = pd.date_range("2010-01-31", periods=12, freq="ME")
        series = pd.Series(1.0, index=index)
        with pytest.raises(ValueError, match="no overlapping"):
            compare(
                series, series, name="x", window="w",
                start=pd.Timestamp("2030-01-01"),
            )
