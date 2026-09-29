"""
q-factor tests: quarterly book equity, the announcement-date gate, and the
18-portfolio algebra. Each ROE case is one firm and a handful of quarters.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ffrep.qfactor.construct import LABELS, q_factors
from ffrep.qfactor.quarterly import quarterly_book_equity, quarterly_roe, roe_as_of


def fundq(rows) -> pd.DataFrame:
    cols = ["gvkey", "datadate", "fyearq", "fqtr", "rdq", "ibq", "seqq"]
    frame = pd.DataFrame(rows, columns=cols)
    frame["datadate"] = pd.to_datetime(frame["datadate"])
    frame["rdq"] = pd.to_datetime(frame["rdq"])
    return frame


QUARTERS = fundq([
    ("A", "2000-03-31", 2000, 1, "2000-04-20", 10.0, 100.0),
    ("A", "2000-06-30", 2000, 2, "2000-07-20", 12.0, 110.0),
    ("A", "2000-09-30", 2000, 3, "2000-10-20", 15.0, 120.0),
])


class TestQuarterlyBookEquity:
    def test_hierarchy_and_preferred(self):
        f = pd.DataFrame({
            "seqq": [100.0, np.nan, np.nan],
            "ceqq": [np.nan, 80.0, np.nan],
            "pstkq": [5.0, 5.0, np.nan],
            "atq": [np.nan, np.nan, 300.0],
            "ltq": [np.nan, np.nan, 250.0],
            "txditcq": [2.0, np.nan, np.nan],
            "pstkrq": [7.0, np.nan, np.nan],
        })
        # 100 + 2 - 7 ;  (80 + 5) - 5 ;  300 - 250
        assert list(quarterly_book_equity(f)) == pytest.approx([95.0, 80.0, 50.0])


class TestQuarterlyRoe:
    def test_earnings_over_last_quarters_book_equity(self):
        roe = quarterly_roe(QUARTERS).set_index("datadate")["roe"]
        assert roe.loc["2000-06-30"] == pytest.approx(12.0 / 100.0)
        assert roe.loc["2000-09-30"] == pytest.approx(15.0 / 110.0)

    def test_first_quarter_has_no_lagged_book_equity(self):
        assert pd.Timestamp("2000-03-31") not in set(quarterly_roe(QUARTERS)["datadate"])

    def test_skipped_quarter_breaks_the_lag(self):
        gap = QUARTERS.drop(index=1)
        assert pd.Timestamp("2000-09-30") not in set(quarterly_roe(gap)["datadate"])

    def test_announcement_before_quarter_end_is_not_trusted(self):
        bad = QUARTERS.copy()
        bad.loc[2, "rdq"] = pd.Timestamp("2000-09-15")
        assert pd.Timestamp("2000-09-30") not in set(quarterly_roe(bad)["datadate"])

    def test_pre_1972_quarter_without_rdq_waits_four_months(self):
        old = fundq([
            ("B", "1968-03-31", 1968, 1, None, 1.0, 50.0),
            ("B", "1968-06-30", 1968, 2, None, 2.0, 55.0),
        ])
        roe = quarterly_roe(old)
        assert roe["available"].iloc[0] == pd.Timestamp("1968-10-30")

    def test_post_1972_quarter_without_rdq_is_unusable(self):
        new = QUARTERS.copy()
        new.loc[2, "rdq"] = pd.NaT
        assert pd.Timestamp("2000-09-30") not in set(quarterly_roe(new)["datadate"])


class TestRoeAsOf:
    def requests(self, *months):
        return pd.DataFrame({"gvkey": ["A"] * len(months),
                             "month": [pd.Period(m, "M") for m in months]})

    def test_uses_the_latest_announced_quarter(self):
        roe = quarterly_roe(QUARTERS)
        got = roe_as_of(roe, self.requests("2000-07", "2000-09", "2000-10"))
        # July: Q2 announced 07-20 -> 12/100. September: still Q2. October: Q3 -> 15/110.
        assert list(got) == pytest.approx([0.12, 0.12, 15.0 / 110.0])

    def test_nothing_before_the_first_announcement(self):
        got = roe_as_of(quarterly_roe(QUARTERS), self.requests("2000-06"))
        assert np.isnan(got.iloc[0])

    def test_stale_earnings_are_dropped_not_carried(self):
        """Q3 ended 2000-09-30; by May 2001 it is over six months old."""
        got = roe_as_of(quarterly_roe(QUARTERS), self.requests("2001-03", "2001-05"))
        assert got.iloc[0] == pytest.approx(15.0 / 110.0)
        assert np.isnan(got.iloc[1])

    def test_result_follows_request_order(self):
        roe = quarterly_roe(QUARTERS)
        req = self.requests("2000-10", "2000-07")
        req.index = [5, 3]
        got = roe_as_of(roe, req)
        assert list(got.index) == [5, 3]
        assert got.loc[3] == pytest.approx(0.12)


class TestQFactorAlgebra:
    def test_hand_computed(self):
        """Return = 1 if small else 0, plus 10 x IA rank, plus 100 x ROE rank."""
        values = {lab: (1.0 if lab[0] == "1" else 0.0) + 10 * int(lab[1]) + 100 * int(lab[2]) for lab in LABELS}
        f = q_factors(pd.DataFrame([values]))
        assert f.loc[0, "ME"] == pytest.approx(1.0)
        assert f.loc[0, "IA"] == pytest.approx(-20.0)     # low minus high: 10 - 30
        assert f.loc[0, "ROE"] == pytest.approx(200.0)    # high minus low: 300 - 100

    def test_a_missing_portfolio_voids_every_factor_it_enters(self):
        values = {lab: 0.01 for lab in LABELS}
        values["132"] = np.nan                      # small, high I/A, *middle* ROE
        f = q_factors(pd.DataFrame([values]))
        assert np.isnan(f.loc[0, "ME"]) and np.isnan(f.loc[0, "IA"])
        assert f.loc[0, "ROE"] == pytest.approx(0.0)   # middle-ROE legs never enter R_ROE

    def test_eighteen_labels_in_global_q_rank_order(self):
        assert len(LABELS) == 18
        assert LABELS[0] == "111" and LABELS[-1] == "233"
