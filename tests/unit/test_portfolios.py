"""
Portfolio-return tests.

The drift arithmetic is the only genuinely subtle part of the construction, so
the cases here are two-firm portfolios whose answers are computable by hand, and
several of them exist specifically to prove that a *wrong* convention would give
a different answer.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ffrep.construct.portfolios import (
    drifted_weights,
    equal_weighted_return,
    portfolio_returns,
    value_weighted_return,
)

MONTHS = pd.period_range("2020-07", periods=3, freq="M")


def panel(**cols) -> pd.DataFrame:
    return pd.DataFrame(cols, index=MONTHS)


class TestDrift:
    def test_first_month_carries_formation_weights(self):
        """A portfolio formed at end of June holds June's weights through July."""
        w = drifted_weights(pd.Series({"a": 100.0, "b": 300.0}),
                            panel(a=[0.5, 0.0, 0.0], b=[0.0, 0.0, 0.0]))
        assert w.iloc[0]["a"] == pytest.approx(100.0)
        assert w.iloc[0]["b"] == pytest.approx(300.0)

    def test_weight_grows_by_one_plus_retx(self):
        w = drifted_weights(pd.Series({"a": 100.0}), panel(a=[0.10, 0.20, 0.0]))
        assert list(w["a"]) == pytest.approx([100.0, 110.0, 132.0])

    def test_drift_compounds_rather_than_summing(self):
        w = drifted_weights(pd.Series({"a": 100.0}), panel(a=[0.10, 0.10, 0.0]))
        assert w["a"].iloc[2] == pytest.approx(121.0)  # not 120.0

    def test_missing_retx_ends_the_position_permanently(self):
        """A firm that stops trading must not be carried at a stale weight."""
        w = drifted_weights(pd.Series({"a": 100.0}), panel(a=[0.0, np.nan, 0.0]))
        assert not pd.isna(w["a"].iloc[0])
        assert pd.isna(w["a"].iloc[1])
        assert pd.isna(w["a"].iloc[2])

    def test_negative_formation_market_equity_raises(self):
        with pytest.raises(ValueError, match="negative"):
            drifted_weights(pd.Series({"a": -1.0}), panel(a=[0.0, 0.0, 0.0]))

    def test_firms_absent_from_the_return_panel_are_ignored(self):
        w = drifted_weights(pd.Series({"a": 100.0, "ghost": 50.0}),
                            panel(a=[0.0, 0.0, 0.0]))
        assert list(w.columns) == ["a"]


class TestValueWeightedReturn:
    def test_equal_weights_give_the_simple_average(self):
        r = value_weighted_return(
            pd.Series({"a": 100.0, "b": 100.0}),
            panel(a=[0.10, 0.0, 0.0], b=[0.0, 0.0, 0.0]),
            panel(a=[0.0, 0.0, 0.0], b=[0.0, 0.0, 0.0]),
        )
        assert r.iloc[0] == pytest.approx(0.05)

    def test_weights_by_market_equity(self):
        """3:1 weights on returns of 10% and 0% give 7.5%, not 5%."""
        r = value_weighted_return(
            pd.Series({"a": 300.0, "b": 100.0}),
            panel(a=[0.10, 0.0, 0.0], b=[0.0, 0.0, 0.0]),
            panel(a=[0.0, 0.0, 0.0], b=[0.0, 0.0, 0.0]),
        )
        assert r.iloc[0] == pytest.approx(0.075)

    def test_drift_uses_retx_not_ret(self):
        """
        The asymmetry, stated as a number.

        Both firms start at weight 100. Firm 'a' returns 20% in month 1, all of
        it dividend: ret 0.20, retx 0.00. Its market cap has not grown, so its
        month-2 weight must stay 100 and the month-2 portfolio return must be
        the equal-weighted 0.05. Drifting on ret would push a's weight to 120
        and the answer to roughly 0.0545.
        """
        me = pd.Series({"a": 100.0, "b": 100.0})
        ret = panel(a=[0.20, 0.10, 0.0], b=[0.0, 0.0, 0.0])
        retx = panel(a=[0.00, 0.10, 0.0], b=[0.0, 0.0, 0.0])

        correct = value_weighted_return(me, ret, retx)
        assert correct.iloc[1] == pytest.approx(0.05)

        # Using ret for the drift — the natural mistake — gives a different number.
        wrong = value_weighted_return(me, ret, ret)
        assert wrong.iloc[1] == pytest.approx(120 * 0.10 / 220)
        assert wrong.iloc[1] != pytest.approx(correct.iloc[1])

    def test_dividend_heavy_firm_is_not_progressively_overweighted(self):
        """
        The error compounds across a holding year, which is why it matters.
        Twelve months of pure-dividend return must leave the weight unchanged.
        """
        months = pd.period_range("2020-07", periods=12, freq="M")
        me = pd.Series({"a": 100.0, "b": 100.0})
        retx = pd.DataFrame({"a": [0.0] * 12, "b": [0.0] * 12}, index=months)
        w = drifted_weights(me, retx)
        assert w["a"].iloc[-1] == pytest.approx(100.0)

    def test_missing_return_removes_a_firm_from_that_month(self):
        r = value_weighted_return(
            pd.Series({"a": 100.0, "b": 100.0}),
            panel(a=[np.nan, 0.0, 0.0], b=[0.20, 0.0, 0.0]),
            panel(a=[0.0, 0.0, 0.0], b=[0.0, 0.0, 0.0]),
        )
        assert r.iloc[0] == pytest.approx(0.20)

    def test_empty_month_is_nan_not_zero(self):
        """0.0 would be a fabricated observation entering the factor."""
        r = value_weighted_return(
            pd.Series({"a": 100.0}),
            panel(a=[np.nan, np.nan, np.nan]),
            panel(a=[0.0, 0.0, 0.0]),
        )
        assert pd.isna(r.iloc[0])

    def test_mismatched_indices_raise(self):
        other = pd.DataFrame({"a": [0.0]}, index=pd.period_range("2021-01", periods=1, freq="M"))
        with pytest.raises(ValueError, match="month index"):
            value_weighted_return(pd.Series({"a": 1.0}), panel(a=[0.0, 0.0, 0.0]), other)


class TestPortfolioReturns:
    def assignments(self) -> pd.DataFrame:
        return pd.DataFrame(
            {"me": [100.0, 100.0, 200.0], "portfolio": ["SL", "SL", "BH"]},
            index=["a", "b", "c"],
        )

    def test_one_column_per_portfolio_in_sorted_order(self):
        out = portfolio_returns(
            self.assignments(),
            panel(a=[0.10, 0.0, 0.0], b=[0.0, 0.0, 0.0], c=[0.30, 0.0, 0.0]),
            panel(a=[0.0, 0.0, 0.0], b=[0.0, 0.0, 0.0], c=[0.0, 0.0, 0.0]),
        )
        assert list(out.columns) == ["BH", "SL"]

    def test_each_portfolio_is_weighted_within_itself(self):
        out = portfolio_returns(
            self.assignments(),
            panel(a=[0.10, 0.0, 0.0], b=[0.0, 0.0, 0.0], c=[0.30, 0.0, 0.0]),
            panel(a=[0.0, 0.0, 0.0], b=[0.0, 0.0, 0.0], c=[0.0, 0.0, 0.0]),
        )
        assert out.loc[MONTHS[0], "SL"] == pytest.approx(0.05)
        assert out.loc[MONTHS[0], "BH"] == pytest.approx(0.30)

    def test_missing_portfolio_column_raises(self):
        with pytest.raises(KeyError, match="portfolio"):
            portfolio_returns(
                self.assignments().drop(columns=["portfolio"]),
                panel(a=[0.0, 0.0, 0.0]), panel(a=[0.0, 0.0, 0.0]),
            )

    def test_missing_weight_column_raises(self):
        with pytest.raises(KeyError, match="me"):
            portfolio_returns(
                self.assignments().drop(columns=["me"]),
                panel(a=[0.0, 0.0, 0.0]), panel(a=[0.0, 0.0, 0.0]),
            )


class TestEqualWeighted:
    def test_is_a_plain_mean(self):
        out = equal_weighted_return(panel(a=[0.10, 0.0, 0.0], b=[0.30, 0.0, 0.0]))
        assert out.iloc[0] == pytest.approx(0.20)

    def test_differs_from_value_weighted_when_sizes_differ(self):
        """The diagnostic that catches an equal-weighted series mistaken for VW."""
        ret = panel(a=[0.10, 0.0, 0.0], b=[0.30, 0.0, 0.0])
        retx = panel(a=[0.0, 0.0, 0.0], b=[0.0, 0.0, 0.0])
        vw = value_weighted_return(pd.Series({"a": 900.0, "b": 100.0}), ret, retx)
        assert vw.iloc[0] != pytest.approx(equal_weighted_return(ret).iloc[0])


class TestMissingKindsAreDistinct:
    """
    The two kinds of missing are handled differently and the difference is
    deliberate, so it is pinned rather than left to whatever the code happens
    to do.
    """

    def test_missing_retx_ends_the_position_but_missing_ret_does_not(self):
        me = pd.Series({"a": 100.0, "b": 100.0})

        # 'a' loses ret in month 1 but keeps retx: excluded from month 1 only,
        # and back in month 2.
        ret = panel(a=[0.0, np.nan, 0.40], b=[0.0, 0.20, 0.0])
        retx = panel(a=[0.0, 0.0, 0.0], b=[0.0, 0.0, 0.0])
        r = value_weighted_return(me, ret, retx)
        assert r.iloc[1] == pytest.approx(0.20)   # only 'b' contributes
        assert r.iloc[2] == pytest.approx(0.20)   # 'a' is back: (0.40+0)/2

    def test_missing_retx_removes_the_firm_even_when_ret_is_present(self):
        me = pd.Series({"a": 100.0, "b": 100.0})
        ret = panel(a=[0.0, 0.40, 0.40], b=[0.0, 0.0, 0.0])
        retx = panel(a=[0.0, np.nan, 0.0], b=[0.0, 0.0, 0.0])
        r = value_weighted_return(me, ret, retx)
        # 'a' has a return but no drift basis, so it is gone from month 1 on.
        assert r.iloc[1] == pytest.approx(0.0)
        assert r.iloc[2] == pytest.approx(0.0)
