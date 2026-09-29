"""
OLS with Newey-West standard errors, and the GRS test.

Written out in numpy rather than imported from statsmodels, following Project
02's precedent: the portfolio standard requires being able to derive these on a
whiteboard, and a dependency you cannot reproduce is a dependency you cannot
defend in an interview.

Newey-West matters here specifically. Factor returns are heteroskedastic (vol
clusters) and monthly overlapping-information effects induce autocorrelation, so
plain OLS standard errors are biased **downward** — they make alphas look more
significant than they are. Reporting a t-statistic of 2.4 that is really 1.6 is
the difference between a finding and nothing.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats


@dataclass(frozen=True)
class OLSResult:
    """Coefficients, robust standard errors, and fit for a single regression."""

    params: pd.Series
    std_errors: pd.Series
    t_stats: pd.Series
    p_values: pd.Series
    r_squared: float
    n_obs: int
    lags: int

    @property
    def alpha(self) -> float:
        """The intercept — for a factor regression, the unexplained mean return."""
        return float(self.params.iloc[0])

    @property
    def alpha_t(self) -> float:
        return float(self.t_stats.iloc[0])

    def summary(self) -> str:
        rows = [
            f"{name:>16s}  {p: 10.6f}  ({self.std_errors[name]:.6f})  "
            f"t={self.t_stats[name]: 7.3f}  p={self.p_values[name]:.4f}"
            for name, p in self.params.items()
        ]
        head = (
            f"OLS, Newey-West({self.lags})  n={self.n_obs}  "
            f"R2={self.r_squared:.6f}"
        )
        return "\n".join([head, *rows])


def newey_west_lags(n_obs: int) -> int:
    """
    The standard automatic bandwidth, `floor(4 (n/100)^(2/9))`.

    From Newey-West (1994). Fixed by a rule rather than chosen by hand, because
    picking the lag length after seeing which choice makes a t-statistic clear
    2.0 is a specification search.
    """
    return int(np.floor(4.0 * (n_obs / 100.0) ** (2.0 / 9.0)))


def ols(
    y: pd.Series,
    X: pd.DataFrame,
    *,
    add_constant: bool = True,
    lags: int | None = None,
) -> OLSResult:
    """
    Regress `y` on `X` with Newey-West heteroskedasticity- and
    autocorrelation-consistent standard errors.

    Rows with any missing value are dropped pairwise across y and X, so the
    caller does not have to pre-align series with different histories — which is
    the normal case here, since factors start in different decades.
    """
    frame = pd.concat([y.rename("__y__"), X], axis=1).dropna()
    if frame.empty:
        raise ValueError("no overlapping non-null observations between y and X")

    y_vec = frame["__y__"].to_numpy(dtype=float)
    design = frame.drop(columns="__y__")

    names = list(design.columns)
    matrix = design.to_numpy(dtype=float)
    if add_constant:
        matrix = np.column_stack([np.ones(len(matrix)), matrix])
        names = ["alpha", *names]

    n, k = matrix.shape
    if n <= k:
        raise ValueError(f"need more observations than regressors; got n={n}, k={k}")

    xtx_inv = np.linalg.pinv(matrix.T @ matrix)
    beta = xtx_inv @ matrix.T @ y_vec
    residuals = y_vec - matrix @ beta

    if lags is None:
        lags = newey_west_lags(n)

    # Newey-West meat matrix: S = G0 + sum_l w_l (G_l + G_l'), with Bartlett
    # weights w_l = 1 - l/(L+1). The weights are what guarantee S stays positive
    # semi-definite; an unweighted truncated sum does not, and can hand back a
    # negative variance.
    scaled = matrix * residuals[:, None]
    meat = scaled.T @ scaled
    for lag in range(1, lags + 1):
        gamma = scaled[lag:].T @ scaled[:-lag]
        weight = 1.0 - lag / (lags + 1.0)
        meat += weight * (gamma + gamma.T)

    covariance = xtx_inv @ meat @ xtx_inv
    std_errors = np.sqrt(np.maximum(np.diag(covariance), 0.0))

    with np.errstate(divide="ignore", invalid="ignore"):
        t_stats = np.where(std_errors > 0, beta / std_errors, np.nan)
    p_values = 2.0 * (1.0 - stats.norm.cdf(np.abs(t_stats)))

    centred = y_vec - y_vec.mean()
    total_ss = float(centred @ centred)
    resid_ss = float(residuals @ residuals)
    r_squared = 1.0 - resid_ss / total_ss if total_ss > 0 else np.nan

    index = pd.Index(names, name="term")
    return OLSResult(
        params=pd.Series(beta, index=index),
        std_errors=pd.Series(std_errors, index=index),
        t_stats=pd.Series(t_stats, index=index),
        p_values=pd.Series(p_values, index=index),
        r_squared=r_squared,
        n_obs=n,
        lags=lags,
    )


@dataclass(frozen=True)
class GRSResult:
    """Gibbons-Ross-Shanken (1989) test that a set of alphas is jointly zero."""

    statistic: float
    p_value: float
    n_obs: int
    n_assets: int
    n_factors: int


def grs_test(returns: pd.DataFrame, factors: pd.DataFrame) -> GRSResult:
    """
    Test H0: every intercept in `returns ~ factors` is zero.

        F = (T/N) * ((T - N - K) / (T - K - 1))
            * a' Σ⁻¹ a / (1 + μ' Ω⁻¹ μ)   ~  F(N, T - N - K)

    where `a` is the vector of intercepts, `Σ` the residual covariance, and
    `μ`, `Ω` the factor mean vector and covariance.

    This is the right test when asking whether one factor model *spans* another:
    testing each alpha separately and counting how many clear t=2 ignores that
    the residuals are heavily cross-correlated, and overstates the evidence.

    Two normalisations, deliberately different. `Σ` is the unbiased residual
    covariance, over `T - K - 1`. `Ω` is the *unadjusted* factor covariance,
    over `T` — the one that appears in the OLS intercept variance
    `σ²(1 + μ'Ω⁻¹μ)/T`. With one test asset the statistic is then exactly the
    squared OLS t-statistic of its intercept, which the tests assert. Using the
    `T - 1` sample covariance for `Ω` misses that identity by a small amount
    (review finding R22).

    Assets and factors are aligned by **row index only**. An earlier version
    concatenated both frames and re-selected columns by name, so an asset that
    shared a factor's name was counted twice and a one-asset, one-factor test
    became a two-by-two one (also R22).
    """
    for label, frame in (("returns", returns), ("factors", factors)):
        if frame.columns.duplicated().any():
            raise ValueError(f"{label} has duplicate column names: {list(frame.columns)}")
        if not frame.index.is_unique:
            raise ValueError(f"{label} has a duplicated row index")

    common = returns.dropna().index.intersection(factors.dropna().index, sort=False)
    if len(common) == 0:
        raise ValueError("no overlapping observations between returns and factors")

    asset_block = returns.loc[common].to_numpy(dtype=float)
    factor_block = factors.loc[common].to_numpy(dtype=float)

    T, N = asset_block.shape
    K = factor_block.shape[1]
    if T - N - K <= 0:
        raise ValueError(
            f"GRS needs T > N + K; got T={T}, N={N}, K={K}. "
            f"Too few periods for {N} test assets."
        )

    design = np.column_stack([np.ones(T), factor_block])
    if np.linalg.matrix_rank(design) < K + 1:
        raise ValueError("factors are collinear (or constant); the regression is not identified")

    coefficients = np.linalg.solve(design.T @ design, design.T @ asset_block)
    alphas = coefficients[0]
    residuals = asset_block - design @ coefficients

    sigma = residuals.T @ residuals / (T - K - 1)
    if np.linalg.matrix_rank(sigma) < N:
        raise ValueError("residual covariance is singular; test assets are linearly dependent")

    factor_means = factor_block.mean(axis=0)
    centred = factor_block - factor_means
    omega = centred.T @ centred / T

    sharpe_term = float(factor_means @ np.linalg.solve(omega, factor_means))
    alpha_term = float(alphas @ np.linalg.solve(sigma, alphas))

    statistic = (T / N) * ((T - N - K) / (T - K - 1)) * alpha_term / (1.0 + sharpe_term)
    p_value = float(stats.f.sf(statistic, N, T - N - K))

    return GRSResult(
        statistic=float(statistic),
        p_value=p_value,
        n_obs=T,
        n_assets=N,
        n_factors=K,
    )
