"""Monthly security panel tests."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ffrep.universe.panel import company_cross_section, security_panel, wide


def msf(**overrides) -> pd.DataFrame:
    base = {
        "permno": [1, 1, 2],
        "permco": [10, 10, 20],
        "date": pd.to_datetime(["1990-05-31", "1990-06-29", "1990-06-29"]),
        "prc": [10.0, -11.0, 5.0],
        "shrout": [1000, 1000, 2000],
        "ret": [0.01, 0.10, 0.02],
        "retx": [0.01, 0.10, 0.02],
        "shrcd": [11, 11, 10],
        "exchcd": [1, 1, 3],
        "siccd": [2000, 2000, 3000],
    }
    base.update(overrides)
    return pd.DataFrame(base)


NO_EVENTS = pd.DataFrame({"permno": [], "date": pd.to_datetime([]), "dlret": [], "dlstcd": []})


class TestSecurityPanel:
    def test_month_is_the_calendar_month_not_the_trading_date(self):
        """1990-06-29 is June 1990; the key must not depend on the trading calendar."""
        p = security_panel(msf(), NO_EVENTS)
        assert set(p["month"]) == {pd.Period("1990-05"), pd.Period("1990-06")}

    def test_market_equity_uses_absolute_price(self):
        p = security_panel(msf(), NO_EVENTS)
        row = p[(p["permno"] == 1) & (p["month"] == pd.Period("1990-06"))].iloc[0]
        assert row["me"] == pytest.approx(11.0)

    def test_duplicate_security_months_raise(self):
        dup = pd.concat([msf(), msf().iloc[[0]]], ignore_index=True)
        with pytest.raises(ValueError, match="duplicate"):
            security_panel(dup, NO_EVENTS)

    def test_terminal_delisting_month_is_added_with_no_market_equity(self):
        events = pd.DataFrame({"permno": [2], "date": pd.to_datetime(["1990-07-10"]),
                               "dlret": [-0.5], "dlstcd": [560]})
        p = security_panel(msf(), events)
        row = p[(p["permno"] == 2) & (p["month"] == pd.Period("1990-07"))].iloc[0]
        assert row["ret"] == pytest.approx(-0.5)
        assert np.isnan(row["me"])


class TestCompanyCrossSection:
    def test_one_row_per_company_for_the_month(self):
        p = security_panel(msf(), NO_EVENTS)
        cs = company_cross_section(p, pd.Period("1990-06"))
        assert sorted(cs["permco"]) == [10, 20]

    def test_terminal_rows_never_enter_a_cross_section(self):
        """A delisted security has no price that month and must not be sorted."""
        events = pd.DataFrame({"permno": [2], "date": pd.to_datetime(["1990-07-10"]),
                               "dlret": [-0.5], "dlstcd": [560]})
        p = security_panel(msf(), events)
        assert company_cross_section(p, pd.Period("1990-07")).empty

    def test_exchange_filter_applies(self):
        p = security_panel(msf(), NO_EVENTS)
        cs = company_cross_section(p, pd.Period("1990-06"), exchanges=(1,))
        assert cs["permco"].tolist() == [10]


class TestWide:
    def test_missing_pairs_are_nan_and_order_is_preserved(self):
        p = security_panel(msf(), NO_EVENTS)
        months = pd.period_range("1990-05", "1990-07", freq="M")
        w = wide(p, "ret", months, pd.Index([2, 1]))
        assert list(w.columns) == [2, 1]
        assert list(w.index) == list(months)
        assert np.isnan(w.loc[pd.Period("1990-05"), 2])
        assert w.loc[pd.Period("1990-06"), 1] == pytest.approx(0.10)
        assert w.loc[pd.Period("1990-07")].isna().all()
