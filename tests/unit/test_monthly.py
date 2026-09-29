"""
Momentum and market tests.

The momentum world is ten NYSE firms with constant monthly returns 0.1% x i and
market equity $100m x i. Prior returns are then ordered by i, and with the
"lower" quantile convention on ten values the breakpoints land on actual firms:

    size median  -> 5th firm  (ME 500): i <= 5 small
    prior p30    -> 3rd firm:            i <= 3 losers  (L)
    prior p70    -> 7th firm:            i >= 8 winners (H)

so SL = {1,2,3}, SM = {4,5}, BM = {6,7}, BH = {8,9,10}, and SL's value-weighted
next-month return is (100 x .001 + 200 x .002 + 300 x .003) / 600 = 0.0023333.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ffrep.construct.monthly import market_return, momentum_portfolios, prior_returns
from ffrep.evaluate.compare import fit, fit_table, to_monthly
from ffrep.universe.panel import security_panel

MONTHS = pd.period_range("2000-01", "2001-04", freq="M")
NO_EVENTS = pd.DataFrame({"permno": [], "date": pd.to_datetime([]), "dlret": [], "dlstcd": []})


def raw(n_firms: int = 10, months=MONTHS, **overrides) -> pd.DataFrame:
    rows = []
    for i in range(1, n_firms + 1):
        for m in months:
            rows.append({
                "permno": i, "permco": i, "date": m.to_timestamp(how="end").normalize(),
                "prc": 100.0 * i, "shrout": 1000.0, "ret": 0.001 * i, "retx": 0.001 * i,
                "shrcd": 11, "exchcd": 1, "siccd": 2000,
            })
    return pd.DataFrame(rows)


def panel(frame: pd.DataFrame | None = None) -> pd.DataFrame:
    return security_panel(raw() if frame is None else frame, NO_EVENTS)


class TestPriorReturns:
    def test_eleven_month_window_skipping_the_last(self):
        p = prior_returns(panel()).set_index(["permno", "month"])["prior"]
        assert p.loc[(1, pd.Period("2001-01"))] == pytest.approx(1.001**11 - 1)

    def test_needs_a_price_thirteen_months_back(self):
        """The first formation month with a t-13 price is 2001-01 (2000-01 + 12)."""
        p = prior_returns(panel())
        assert p["month"].min() == pd.Period("2001-01")

    def test_missing_price_month_is_tolerated_like_crsp_minus_99(self):
        frame = raw(1)
        hole = frame["date"] == pd.Timestamp("2000-06-30")
        frame.loc[hole, ["prc", "ret", "retx"]] = np.nan
        p = prior_returns(panel(frame)).set_index(["permno", "month"])["prior"]
        assert p.loc[(1, pd.Period("2001-01"))] == pytest.approx(1.001**10 - 1)

    def test_absent_month_is_not_tolerated(self):
        """No row at all means the security was not listed: -88, not -99."""
        frame = raw(1)
        frame = frame[frame["date"] != pd.Timestamp("2000-06-30")]
        p = prior_returns(panel(frame)).set_index(["permno", "month"])["prior"]
        assert (1, pd.Period("2001-01")) not in p.index

    def test_needs_a_good_return_at_t_minus_two(self):
        frame = raw(1)
        frame.loc[frame["date"] == pd.Timestamp("2000-12-31"), "ret"] = np.nan
        p = prior_returns(panel(frame)).set_index(["permno", "month"])["prior"]
        assert (1, pd.Period("2001-01")) not in p.index


class TestMomentumPortfolios:
    def test_hand_computed_assignment_and_return(self):
        returns, counts = momentum_portfolios(panel())
        first = pd.Period("2001-02")
        assert returns.loc[first, "SL"] == pytest.approx(1.4 / 600)
        assert counts.loc[first].to_dict() == {"SL": 3, "SM": 2, "SH": 0, "BL": 0, "BM": 2, "BH": 3}
        assert np.isnan(returns.loc[first, "SH"])

    def test_portfolio_month_is_the_month_after_formation(self):
        returns, _ = momentum_portfolios(panel())
        assert list(returns.index) == list(pd.period_range("2001-02", "2001-04", freq="M"))


class TestMarket:
    def test_weights_are_last_months_market_equity(self):
        """ME 100 and 200 at t-1, returns 0.1% and 0.2% at t -> (0.1 + 0.4)/300 = 0.00166..."""
        mkt = market_return(panel(raw(2)))
        assert mkt.loc[pd.Period("2000-02")] == pytest.approx(0.5 / 300)
        assert pd.Period("2000-01") not in mkt.index


class TestCompare:
    def test_identical_series_fit_exactly(self):
        s = pd.Series([0.01, -0.02, 0.03, 0.0], index=pd.period_range("2000-01", periods=4, freq="M"))
        f = fit(s, s)
        assert (f.corr, f.slope, f.te_bps) == pytest.approx((1.0, 1.0, 0.0))

    def test_scaled_series_has_perfect_correlation_but_a_wrong_slope(self):
        """Why correlation alone is not enough: half the volatility, corr 1.0."""
        s = pd.Series([0.01, -0.02, 0.03, 0.0], index=pd.period_range("2000-01", periods=4, freq="M"))
        f = fit(0.5 * s, s)
        assert f.corr == pytest.approx(1.0)
        assert f.slope == pytest.approx(2.0)
        assert f.te_bps > 0

    def test_french_month_end_index_aligns_with_periods(self):
        idx = pd.to_datetime(["2000-01-31", "2000-02-29", "2000-03-31"])
        published = to_monthly(pd.DataFrame({"HML": [0.01, 0.02, 0.03]}, index=idx))
        ours = pd.DataFrame({"HML": [0.01, 0.02, 0.03]}, index=pd.period_range("2000-01", periods=3, freq="M"))
        table = fit_table(ours, published, {"all": ("2000-01", "2000-03")})
        assert table.loc[0, "n"] == 3
        assert table.loc[0, "corr"] == pytest.approx(1.0)
