"""
Tests for the hand-rolled OLS, Newey-West, and GRS implementations.

Every one of these is checked against an answer derived independently — a known
data-generating process, a closed form, or a degenerate case with an obvious
result — rather than against whatever the code happened to return the first time.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ffrep.evaluate.regression import grs_test, newey_west_lags, ols


@pytest.fixture
def exact_line():
    """y = 2 + 3x exactly: coefficients are known, R2 is 1, residuals are 0."""
    x = pd.Series(np.arange(1.0, 51.0), name="x")
    y = 2.0 + 3.0 * x
    return y.rename("y"), x.to_frame()


class TestOLS:
    def test_recovers_known_coefficients(self, exact_line):
        y, X = exact_line
        result = ols(y, X)
        assert result.params["alpha"] == pytest.approx(2.0)
        assert result.params["x"] == pytest.approx(3.0)

    def test_perfect_fit_gives_r_squared_one(self, exact_line):
        y, X = exact_line
        assert ols(y, X).r_squared == pytest.approx(1.0)

    def test_zero_residuals_give_zero_standard_errors(self, exact_line):
        y, X = exact_line
        result = ols(y, X)
        assert result.std_errors.max() == pytest.approx(0.0, abs=1e-9)

    def test_no_constant_when_suppressed(self, exact_line):
        y, X = exact_line
        result = ols(y, X, add_constant=False)
        assert "alpha" not in result.params.index
        assert list(result.params.index) == ["x"]

    def test_recovers_coefficients_with_noise(self):
        rng = np.random.default_rng(0)
        n = 4000
        x1 = pd.Series(rng.normal(size=n), name="x1")
        x2 = pd.Series(rng.normal(size=n), name="x2")
        y = pd.Series(1.5 + 0.8 * x1 - 0.4 * x2 + rng.normal(scale=0.5, size=n), name="y")

        result = ols(y, pd.concat([x1, x2], axis=1))
        assert result.params["alpha"] == pytest.approx(1.5, abs=0.05)
        assert result.params["x1"] == pytest.approx(0.8, abs=0.05)
        assert result.params["x2"] == pytest.approx(-0.4, abs=0.05)

    def test_matches_numpy_lstsq_on_coefficients(self):
        """
        Newey-West changes the standard errors, never the point estimates.
        Pinning that against an independent solver catches an error in the
        normal equations that a self-consistent test would miss.
        """
        rng = np.random.default_rng(7)
        n = 500
        X = pd.DataFrame(rng.normal(size=(n, 3)), columns=["a", "b", "c"])
        y = pd.Series(rng.normal(size=n), name="y")

        result = ols(y, X)
        design = np.column_stack([np.ones(n), X.to_numpy()])
        expected, *_ = np.linalg.lstsq(design, y.to_numpy(), rcond=None)
        np.testing.assert_allclose(result.params.to_numpy(), expected, rtol=1e-9)

    def test_drops_rows_with_missing_values(self):
        y = pd.Series([1.0, 2.0, np.nan, 4.0, 5.0], name="y")
        X = pd.DataFrame({"x": [1.0, 2.0, 3.0, np.nan, 5.0]})
        assert ols(y, X).n_obs == 3

    def test_raises_on_no_overlap(self):
        y = pd.Series([1.0, 2.0], index=[0, 1], name="y")
        X = pd.DataFrame({"x": [1.0, 2.0]}, index=[2, 3])
        with pytest.raises(ValueError, match="no overlapping"):
            ols(y, X)

    def test_raises_when_fewer_observations_than_regressors(self):
        y = pd.Series([1.0, 2.0], name="y")
        X = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, 4.0]})
        with pytest.raises(ValueError, match="more observations"):
            ols(y, X)


class TestNeweyWest:
    def test_lag_rule_matches_the_published_formula(self):
        for n in (100, 200, 500, 1200):
            assert newey_west_lags(n) == int(np.floor(4.0 * (n / 100.0) ** (2.0 / 9.0)))

    def test_zero_lags_reduces_to_white_standard_errors(self):
        """With L=0 the Bartlett sum is empty, so this must equal the plain
        heteroskedasticity-robust sandwich."""
        rng = np.random.default_rng(3)
        n = 300
        X = pd.DataFrame(rng.normal(size=(n, 1)), columns=["x"])
        y = pd.Series(rng.normal(size=n), name="y")

        result = ols(y, X, lags=0)
        design = np.column_stack([np.ones(n), X.to_numpy()])
        beta = np.linalg.pinv(design.T @ design) @ design.T @ y.to_numpy()
        resid = y.to_numpy() - design @ beta
        bread = np.linalg.pinv(design.T @ design)
        scaled = design * resid[:, None]
        expected = np.sqrt(np.diag(bread @ (scaled.T @ scaled) @ bread))
        np.testing.assert_allclose(result.std_errors.to_numpy(), expected, rtol=1e-10)

    def test_widens_standard_errors_on_autocorrelated_residuals(self):
        """
        The reason Newey-West is used at all. With positively autocorrelated
        errors, OLS standard errors are biased downward — they make an alpha
        look more significant than it is.
        """
        rng = np.random.default_rng(11)
        n = 2000
        errors = np.zeros(n)
        for t in range(1, n):
            errors[t] = 0.8 * errors[t - 1] + rng.normal()

        x = pd.Series(rng.normal(size=n), name="x")
        y = pd.Series(errors, name="y")

        naive = ols(y, x.to_frame(), lags=0)
        robust = ols(y, x.to_frame())
        assert robust.std_errors["alpha"] > naive.std_errors["alpha"]

    def test_variance_stays_non_negative_under_bartlett_weights(self):
        rng = np.random.default_rng(23)
        for seed_shift in range(5):
            n = 120
            x = pd.Series(rng.normal(size=n), name="x")
            y = pd.Series(rng.normal(size=n) * (1 + seed_shift), name="y")
            assert (ols(y, x.to_frame()).std_errors >= 0).all()


class TestGRS:
    def test_zero_alphas_give_a_small_statistic(self):
        """Returns generated with no pricing error must not reject."""
        rng = np.random.default_rng(5)
        n = 600
        factor = pd.Series(rng.normal(scale=0.04, size=n), name="Mkt")
        returns = pd.DataFrame(
            {
                f"a{i}": 1.2 * factor.to_numpy() + rng.normal(scale=0.02, size=n)
                for i in range(4)
            }
        )
        result = grs_test(returns, factor.to_frame())
        assert result.p_value > 0.05

    def test_large_alphas_reject(self):
        rng = np.random.default_rng(5)
        n = 600
        factor = pd.Series(rng.normal(scale=0.04, size=n), name="Mkt")
        returns = pd.DataFrame(
            {
                f"a{i}": 0.05 + 1.2 * factor.to_numpy() + rng.normal(scale=0.02, size=n)
                for i in range(4)
            }
        )
        result = grs_test(returns, factor.to_frame())
        assert result.p_value < 0.01

    def test_reports_its_dimensions(self):
        rng = np.random.default_rng(9)
        n = 200
        factors = pd.DataFrame(rng.normal(size=(n, 2)), columns=["f1", "f2"])
        returns = pd.DataFrame(rng.normal(size=(n, 3)), columns=["a", "b", "c"])
        result = grs_test(returns, factors)
        assert (result.n_obs, result.n_assets, result.n_factors) == (200, 3, 2)

    def test_raises_when_too_few_periods(self):
        rng = np.random.default_rng(13)
        factors = pd.DataFrame(rng.normal(size=(6, 2)), columns=["f1", "f2"])
        returns = pd.DataFrame(rng.normal(size=(6, 5)), columns=list("abcde"))
        with pytest.raises(ValueError, match="T > N \\+ K"):
            grs_test(returns, factors)


class TestGRSIdentities:
    """
    Review R22. GRS has two exact properties an implementation can be checked
    against without trusting it: it cannot depend on column names, and with a
    single test asset it equals the squared OLS t-statistic of the intercept.
    """

    @staticmethod
    def sample(seed: int = 7, T: int = 120):
        rng = np.random.default_rng(seed)
        f = rng.normal(0.005, 0.04, T)
        y = 0.003 + 0.9 * f + rng.normal(0, 0.02, T)
        idx = pd.RangeIndex(T)
        return pd.DataFrame({"asset": y}, index=idx), pd.DataFrame({"mkt": f}, index=idx)

    def test_renaming_an_asset_to_the_factors_name_changes_nothing(self):
        assets, factors = self.sample()
        before = grs_test(assets, factors)
        after = grs_test(assets.rename(columns={"asset": "mkt"}), factors)
        assert (after.n_assets, after.n_factors) == (1, 1)
        assert after.statistic == pytest.approx(before.statistic, rel=1e-12)

    def test_single_asset_statistic_is_the_squared_intercept_t(self):
        assets, factors = self.sample()
        T = len(assets)
        X = np.column_stack([np.ones(T), factors["mkt"].to_numpy()])
        y = assets["asset"].to_numpy()
        beta = np.linalg.solve(X.T @ X, X.T @ y)
        resid = y - X @ beta
        s2 = resid @ resid / (T - 2)
        t_alpha = beta[0] / np.sqrt(s2 * np.linalg.inv(X.T @ X)[0, 0])
        assert grs_test(assets, factors).statistic == pytest.approx(t_alpha**2, rel=1e-10)

    def test_rows_missing_in_either_frame_are_dropped_from_both(self):
        assets, factors = self.sample()
        holed = assets.copy()
        holed.iloc[5, 0] = np.nan
        a = grs_test(holed, factors)
        b = grs_test(assets.drop(index=5), factors.drop(index=5))
        assert a.n_obs == len(assets) - 1
        assert a.statistic == pytest.approx(b.statistic, rel=1e-12)

    def test_duplicate_column_names_are_rejected(self):
        assets, factors = self.sample()
        doubled = pd.concat([assets, assets], axis=1)
        with pytest.raises(ValueError, match="duplicate"):
            grs_test(doubled, factors)

    def test_collinear_factors_are_rejected(self):
        assets, factors = self.sample()
        with pytest.raises(ValueError, match="collinear"):
            grs_test(assets, factors.assign(twice=2 * factors["mkt"]))

    def test_linearly_dependent_assets_are_rejected(self):
        assets, factors = self.sample()
        with pytest.raises(ValueError, match="singular"):
            grs_test(assets.assign(copy=assets["asset"] * 2.0), factors)
