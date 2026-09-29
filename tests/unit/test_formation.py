"""
Formation-join tests, on a six-company world small enough to sort by hand.

    permco  exch    June ME  Dec ME   BE(FY1999)   BE/ME
      1     NYSE      100     100        10         0.10
      2     NYSE      200     100        20         0.20
      3     NYSE      300     100        30         0.30
      4     NYSE      400     100        40         0.40
      5     NASDAQ     50     100        80         0.80
      6     NASDAQ   1000     100        -5          --

NYSE June ME median ("lower") = 200, so 1, 2 and 5 are small. NYSE BE/ME
p30 = 0.10 and p70 = 0.30 ("lower" on four values picks the 1st and 3rd), so:
1 -> SL, 2 -> SM, 3 -> BM, 4 -> BH, 5 -> SH, and 6 is out of the value sort for
negative book equity — but *in* the investment sort, which does not require it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ffrep.construct.formation import (
    Conventions,
    annual_characteristics,
    build_formation,
    holding_months,
    holding_returns,
    run_annual_sorts,
    sort_2x3,
)
from ffrep.universe.links import compustat_candidates, crsp_candidates, link_candidates
from ffrep.universe.panel import security_panel

PERMCOS = [1, 2, 3, 4, 5, 6]
EXCH = [1, 1, 1, 1, 3, 3]
JUNE_ME = [100.0, 200.0, 300.0, 400.0, 50.0, 1000.0]
BE = [10.0, 20.0, 30.0, 40.0, 80.0, -5.0]


def world(monthly_ret: float = 0.01) -> dict:
    rows = []
    months = [pd.Period("1999-12")] + list(pd.period_range("2000-06", "2001-06", freq="M"))
    for i, permco in enumerate(PERMCOS):
        for m in months:
            me = 100.0 if m == pd.Period("1999-12") else JUNE_ME[i]
            rows.append({
                "permno": 100 + permco, "permco": permco,
                "date": m.to_timestamp(how="end").normalize(),
                "prc": me, "shrout": 1000.0,
                "ret": monthly_ret, "retx": monthly_ret,
                "shrcd": 11, "exchcd": EXCH[i], "siccd": 2000,
                "cusip": f"C{permco:07d}", "ncusip": None,
            })
    msf = pd.DataFrame(rows)
    funda = pd.DataFrame([
        {"gvkey": f"G{p}", "datadate": pd.Timestamp(f"{y}-12-31"), "cusip": f"C{p:07d}9",
         "seq": be if y == 1999 else 1.0, "at": 100.0 * (1 + 0.1 * p) if y == 1999 else 100.0,
         "lt": 50.0, "revt": 100.0, "cogs": 50.0}
        for p, be in zip(PERMCOS, BE) for y in (1998, 1999)
    ])
    events = pd.DataFrame({"permno": [], "date": pd.to_datetime([]), "dlret": [], "dlstcd": []})
    panel = security_panel(msf, events)
    candidates = link_candidates(crsp_candidates(msf), compustat_candidates(funda))
    return {"panel": panel, "funda": funda, "candidates": candidates, "msf": msf}


@pytest.fixture(scope="module")
def w():
    return world()


@pytest.fixture(scope="module")
def formation(w):
    chars = annual_characteristics(w["funda"])
    return build_formation(2000, w["panel"], w["candidates"], chars)


class TestJoin:
    def test_every_company_is_linked(self, formation):
        assert formation.frame["gvkey"].notna().all()

    def test_bm_uses_december_market_equity_not_june(self, formation):
        """Permco 4: BE 40 over December ME 100 = 0.40. June ME 400 would give 0.10."""
        assert formation.frame.loc[4, "beme"] == pytest.approx(0.40)

    def test_negative_book_equity_has_no_bm(self, formation):
        assert np.isnan(formation.frame.loc[6, "beme"])

    def test_samples_follow_frenchs_per_sort_requirements(self, formation):
        assert list(formation.samples["beme"]) == [1, 2, 3, 4, 5]
        assert list(formation.samples["op"]) == [1, 2, 3, 4, 5]
        assert list(formation.samples["inv"]) == [1, 2, 3, 4, 5, 6]

    def test_missing_december_market_equity_removes_the_firm_from_every_sort(self, w):
        panel = w["panel"]
        dropped = panel[~((panel["permco"] == 3) & (panel["month"] == pd.Period("1999-12")))]
        f = build_formation(2000, dropped, w["candidates"], annual_characteristics(w["funda"]))
        for sort in ("beme", "op", "inv"):
            assert 3 not in f.samples[sort]

    def test_two_year_compustat_rule_is_an_explicit_switch(self, w):
        """Every firm here has records for 1998 and 1999, so a 3-year rule empties the sort."""
        chars = annual_characteristics(w["funda"])
        two = build_formation(2000, w["panel"], w["candidates"], chars, Conventions(min_compustat_years=2))
        three = build_formation(2000, w["panel"], w["candidates"], chars, Conventions(min_compustat_years=3))
        assert len(two.samples["beme"]) == 5
        assert len(three.samples["beme"]) == 0


class TestSort:
    def test_hand_computed_assignment(self, formation):
        result = sort_2x3(formation, "beme")
        assert result.size_breakpoint == pytest.approx(200.0)
        assert result.breakpoints == pytest.approx((0.10, 0.30))
        assert result.assignments["portfolio"].to_dict() == {
            1: "SL", 2: "SM", 3: "BM", 4: "BH", 5: "SH",
        }

    def test_breakpoints_ignore_nasdaq_firms(self, formation):
        """Permco 5's BE/ME of 0.80 is NASDAQ; including it would move p70 above 0.30."""
        assert sort_2x3(formation, "beme").breakpoints[1] == pytest.approx(0.30)

    def test_size_breakpoint_sample_is_switchable(self, formation):
        nyse_all = sort_2x3(formation, "beme", Conventions(size_breakpoint_sample="nyse"))
        in_sort = sort_2x3(formation, "beme", Conventions(size_breakpoint_sample="sort"))
        # Same four NYSE firms in both here, so the same median.
        assert nyse_all.size_breakpoint == pytest.approx(in_sort.size_breakpoint)

    def test_investment_sort_keeps_the_negative_book_equity_firm(self, formation):
        assert 6 in sort_2x3(formation, "inv").assignments.index


class TestHolding:
    def test_twelve_months_july_to_june(self):
        months = holding_months(2000)
        assert (months[0], months[-1], len(months)) == (pd.Period("2000-07"), pd.Period("2001-06"), 12)

    def test_uniform_returns_give_uniform_portfolios(self, w, formation):
        returns, counts = holding_returns(w["panel"], sort_2x3(formation, "beme"), 2000)
        assert returns.shape == (12, 5)          # no big-growth firm in this world
        assert np.allclose(returns.to_numpy(), 0.01)
        assert counts.sum(axis=1).eq(5).all()


class TestRun:
    def test_missing_leg_is_reported_not_invented(self, w):
        """BL is empty in this world, so HML cannot be formed; the column is NaN."""
        chars = annual_characteristics(w["funda"])
        out = run_annual_sorts(w["panel"], w["candidates"], chars, range(2000, 2001), sorts=("beme",))
        assert out["returns"]["beme"]["BL"].isna().all()
        assert out["counts"]["beme"]["BL"].eq(0).all()
        assert out["diagnostics"].loc[2000, "linked_by_count"] == pytest.approx(1.0)


class TestConventions:
    def test_rejects_an_unknown_breakpoint_sample(self):
        with pytest.raises(ValueError):
            Conventions(size_breakpoint_sample="all")

    def test_rejects_zero_years(self):
        with pytest.raises(ValueError):
            Conventions(min_compustat_years=0)


class TestMoodyBookEquity:
    """
    French's hand-collected Moody's book equity fills firms Compustat does not
    reach. It must fill only gaps, never override Compustat, and it cannot
    create a profitability or investment value.
    """

    def moody(self, rows):
        return pd.DataFrame(rows, columns=["permno", "year", "be"])

    def unlinked(self, w):
        """Permco 2 loses its Compustat link."""
        return w["candidates"][w["candidates"]["permco"] != 2]

    def test_fills_a_company_compustat_does_not_reach(self, w):
        chars = annual_characteristics(w["funda"])
        f = build_formation(2000, w["panel"], self.unlinked(w), chars,
                            moody=self.moody([(102, 2000, 50.0)]))
        assert f.frame.loc[2, "be_source"] == "moody"
        assert f.frame.loc[2, "beme"] == pytest.approx(0.50)
        assert 2 in f.samples["beme"]

    def test_never_overrides_compustat(self, w):
        chars = annual_characteristics(w["funda"])
        f = build_formation(2000, w["panel"], w["candidates"], chars,
                            moody=self.moody([(102, 2000, 999.0)]))
        assert f.frame.loc[2, "be"] == pytest.approx(20.0)
        assert f.frame.loc[2, "be_source"] == "compustat"

    def test_uses_the_formation_years_manual_only(self, w):
        chars = annual_characteristics(w["funda"])
        f = build_formation(2000, w["panel"], self.unlinked(w), chars,
                            moody=self.moody([(102, 1999, 50.0), (102, 2001, 60.0)]))
        assert np.isnan(f.frame.loc[2, "be"])

    def test_moody_firm_enters_value_sort_but_not_profitability(self, w):
        chars = annual_characteristics(w["funda"])
        f = build_formation(2000, w["panel"], self.unlinked(w), chars,
                            moody=self.moody([(102, 2000, 50.0)]))
        assert 2 in f.samples["beme"]
        assert 2 not in f.samples["op"] and 2 not in f.samples["inv"]

    def test_can_be_switched_off(self, w):
        chars = annual_characteristics(w["funda"])
        f = build_formation(2000, w["panel"], self.unlinked(w), chars,
                            Conventions(moody_book_equity=False),
                            moody=self.moody([(102, 2000, 50.0)]))
        assert 2 not in f.samples["beme"]
