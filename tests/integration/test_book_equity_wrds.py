"""
Book equity against live Compustat, validated on French's published breakpoints.

The acceptance test for `ffrep.construct.book_equity`. The unit tests prove each
hierarchy fallback does what it says on hand-built rows; only this proves the
assembled definition is French's, and it does so against a file we did not
produce.

What is being exercised is wider than the accounting: BE/ME also depends on the
CUSIP linkage standing in for CRSP/Compustat Merged and on the December-market-
equity convention. The tolerances below are therefore set by the linkage, not by
the formula — the firm-count shortfall is a linkage cost and is asserted as a
bound rather than pretended away.

The sharpest assertion here is the deferred-tax cutoff: French's stated
definition adds balance-sheet deferred taxes unconditionally, and his published
breakpoints require them to stop after fiscal 1992. That is a finding, not a
citation, so it is pinned with a test that fails if either side of the break
regresses.

Opt-in: set FFREP_WRDS_TESTS=1 and WRDS_USERNAME. Skips otherwise.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ffrep.config import Config, DEFERRED_TAX_LAST_FISCAL_YEAR
from ffrep.construct.book_equity import (
    book_equity,
    deferred_taxes,
    drop_empty_records,
    latest_fiscal_year,
    operating_profitability,
    preferred_stock,
    stockholders_equity,
)
from ffrep.reference.breakpoints import load_breakpoints
from ffrep.universe.linker import CusipLinker
from ffrep.universe.screen import nyse_breakpoint_universe
from ffrep.universe.wrds_source import ExtractWindow, fetch_cusip_history, fetch_fundamentals

#: Two windows, chosen for what each can prove. 1989-1998 straddles the deferred
#: tax break; 2015-2024 is where the CUSIP linkage is near-complete (97-98%), so
#: a miss there cannot be blamed on linkage.
ACCOUNTING_YEARS = list(range(1989, 1999)) + list(range(2015, 2025))

PERCENTILES: tuple[int, ...] = tuple(range(5, 100, 5))


@pytest.fixture(scope="module")
def fundamentals(wrds_db):
    """Compustat annual records for the checked accounting years."""
    window = ExtractWindow(f"{min(ACCOUNTING_YEARS)}-01-01", f"{max(ACCOUNTING_YEARS)}-12-31")
    return latest_fiscal_year(drop_empty_records(fetch_fundamentals(wrds_db, window)))


@pytest.fixture(scope="module")
def december_nyse(wrds_db, fundamentals):
    """NYSE December cross-sections, linked to Compustat on CUSIP."""
    years = ", ".join(f"'{y}-12-31'" for y in ACCOUNTING_YEARS)
    raw = wrds_db.raw_sql(
        f"""
        select a.permno, a.permco, a.date, a.prc, a.shrout,
               b.shrcd, b.exchcd, b.siccd, b.cusip, b.ncusip
        from crsp.msf a
        join crsp.msenames b
          on a.permno = b.permno and b.namedt <= a.date and a.date <= b.nameendt
        where b.exchcd in (1, 31)
          and extract(month from a.date) = 12
          and extract(year from a.date) in ({', '.join(str(y) for y in ACCOUNTING_YEARS)})
        """,
        date_cols=["date"],
    )
    universe = nyse_breakpoint_universe(raw)
    universe["year"] = universe["date"].dt.year
    identifiers = (
        fundamentals[["gvkey", "cusip"]].dropna(subset=["cusip"]).drop_duplicates("cusip")
    )
    linker = CusipLinker(historical=fetch_cusip_history(wrds_db))
    return linker.link(universe, identifiers).dropna(subset=["gvkey"])


@pytest.fixture(scope="module")
def published():
    config = Config()
    if not config.french_path("bp_beme").exists():
        pytest.skip("BE-ME_Breakpoints not downloaded; run scripts/fetch_reference_data.py")
    return load_breakpoints(config.french_path("bp_beme"))


def cross_section(fundamentals, december_nyse, values: pd.Series, formation_year: int):
    """BE/ME for formation year t, from a supplied book-equity series."""
    frame = fundamentals.assign(v=values).dropna(subset=["v"])
    lookup = frame.set_index(["gvkey", "accounting_year"])["v"]
    group = december_nyse[december_nyse["year"] == formation_year - 1]
    found = lookup.reindex(
        pd.MultiIndex.from_arrays([group["gvkey"], [formation_year - 1] * len(group)])
    ).to_numpy()
    return pd.Series(found / group["me"].to_numpy()).dropna()


def mean_absolute_error(section: pd.Series, published, formation_year: int) -> float:
    """Mean |error| across every percentile French publishes, in percent."""
    stamp = pd.Timestamp(year=formation_year, month=12, day=31)
    row = published.values.loc[stamp]
    positive = section[section > 0].to_numpy()
    mine = np.quantile(positive, [p / 100 for p in PERCENTILES], method="lower")
    errors = [
        100 * (m / row[p] - 1) for p, m in zip(PERCENTILES, mine) if row.get(p, 0) > 0
    ]
    return float(np.abs(errors).mean())


CHECK_YEARS = [1990, 1993, 1996, 2016, 2019, 2022, 2024]


class TestAgainstPublishedBreakpoints:
    @pytest.mark.parametrize("t", CHECK_YEARS)
    def test_beme_percentiles_track_french(self, fundamentals, december_nyse, published, t):
        section = cross_section(fundamentals, december_nyse, book_equity(fundamentals), t)
        error = mean_absolute_error(section, published, t)
        assert error < 4.0, f"formation {t}: mean |error| across percentiles is {error:.2f}%"

    @pytest.mark.parametrize("t", CHECK_YEARS)
    def test_median_beme_tracks_french(self, fundamentals, december_nyse, published, t):
        section = cross_section(fundamentals, december_nyse, book_equity(fundamentals), t)
        positive = section[section > 0].to_numpy()
        mine = np.quantile(positive, 0.5, method="lower")
        theirs = published.values.loc[pd.Timestamp(year=t, month=12, day=31), 50]
        assert abs(mine / theirs - 1) < 0.04, f"formation {t}: median BE/ME {mine:.3f} vs {theirs:.3f}"

    @pytest.mark.parametrize("t", [2016, 2019, 2022, 2024])
    def test_negative_book_equity_count_tracks_french(
        self, fundamentals, december_nyse, published, t
    ):
        """
        French publishes a separate count of NYSE firms with BE <= 0. It is an
        independent check on the sign of book equity: the percentiles are
        computed only from positive values, so a systematic sign error would
        leave them intact and move this count.

        Only checked where the CUSIP linkage is near-complete — before then the
        count is dominated by firms we never matched.
        """
        section = cross_section(fundamentals, december_nyse, book_equity(fundamentals), t)
        stamp = pd.Timestamp(year=t, month=12, day=31)
        mine = int((section <= 0).sum())
        theirs = int(published.counts.loc[stamp, "n_nonpositive"])
        assert abs(mine - theirs) <= 12, f"formation {t}: {mine} firms with BE <= 0 vs {theirs}"

    @pytest.mark.parametrize("t", [2019, 2022, 2024])
    def test_firm_count_shortfall_is_bounded_by_the_linkage(
        self, fundamentals, december_nyse, published, t
    ):
        """
        We are always short of French, and the shortfall is the CUSIP linkage,
        not the accounting. Asserted as a bound so a regression that starts
        losing firms is caught, and stated as a shortfall so it is not mistaken
        for agreement.
        """
        section = cross_section(fundamentals, december_nyse, book_equity(fundamentals), t)
        stamp = pd.Timestamp(year=t, month=12, day=31)
        shortfall = int(published.counts.loc[stamp, "n_positive"]) - int((section > 0).sum())
        assert 0 <= shortfall <= 80, f"formation {t}: {shortfall} NYSE firms short of French"


class TestDeferredTaxCutoff:
    """
    The finding this layer turns on: French's stated book-equity definition adds
    balance-sheet deferred taxes unconditionally, and his published breakpoints
    show him stopping after fiscal 1992.
    """

    def _variants(self, fundamentals):
        se = stockholders_equity(fundamentals)
        dt = deferred_taxes(fundamentals, through_fiscal_year=None)
        ps = preferred_stock(fundamentals)
        year = fundamentals["accounting_year"]
        return {
            "always": se + dt - ps,
            "never": se - ps,
            "shipped": se + dt.where(year <= DEFERRED_TAX_LAST_FISCAL_YEAR, 0.0) - ps,
        }

    @pytest.mark.parametrize("t", [1990, 1993])
    def test_before_the_break_deferred_taxes_must_be_added(
        self, fundamentals, december_nyse, published, t
    ):
        v = self._variants(fundamentals)
        with_dt = mean_absolute_error(
            cross_section(fundamentals, december_nyse, v["always"], t), published, t)
        without = mean_absolute_error(
            cross_section(fundamentals, december_nyse, v["never"], t), published, t)
        assert with_dt < without / 3, (
            f"formation {t}: adding deferred taxes gives {with_dt:.2f}%, "
            f"omitting them {without:.2f}%"
        )

    @pytest.mark.parametrize("t", [1996, 2016, 2022])
    def test_after_the_break_deferred_taxes_must_not_be_added(
        self, fundamentals, december_nyse, published, t
    ):
        v = self._variants(fundamentals)
        with_dt = mean_absolute_error(
            cross_section(fundamentals, december_nyse, v["always"], t), published, t)
        without = mean_absolute_error(
            cross_section(fundamentals, december_nyse, v["never"], t), published, t)
        assert without < with_dt / 3, (
            f"formation {t}: omitting deferred taxes gives {without:.2f}%, "
            f"adding them {with_dt:.2f}%"
        )

    @pytest.mark.parametrize("t", [1990, 1993, 1996, 2016, 2022])
    def test_the_shipped_default_picks_the_right_side_of_the_break(
        self, fundamentals, december_nyse, published, t
    ):
        v = self._variants(fundamentals)
        shipped = mean_absolute_error(
            cross_section(fundamentals, december_nyse, v["shipped"], t), published, t)
        others = [
            mean_absolute_error(
                cross_section(fundamentals, december_nyse, v[k], t), published, t)
            for k in ("always", "never")
        ]
        assert shipped <= min(others) + 1e-9, f"formation {t}: shipped {shipped:.2f}%, best other {min(others):.2f}%"

    def test_the_shipped_default_matches_the_measured_cutoff(self):
        assert DEFERRED_TAX_LAST_FISCAL_YEAR == 1992


class TestYearLabel:
    def test_a_published_row_is_stamped_with_the_formation_year(
        self, fundamentals, december_nyse, published
    ):
        """
        BE for the fiscal year ending in 1995 over December-1995 market equity
        matches French's 1996 row, not his 1995 one. Getting this backwards
        shifts every breakpoint by a year and still produces a full, plausible
        table.
        """
        section = cross_section(fundamentals, december_nyse, book_equity(fundamentals), 1996)
        right = mean_absolute_error(section, published, 1996)
        wrong = mean_absolute_error(section, published, 1995)
        assert right < wrong / 3, f"formation-year {right:.2f}% vs accounting-year {wrong:.2f}%"


class TestOperatingProfitabilityShareTheDefinition:
    def test_profitability_uses_the_same_book_equity(self, fundamentals):
        """
        RMW's denominator is BE, so the deferred-tax cutoff moves it too. This
        pins that they are not allowed to drift apart.
        """
        shipped = book_equity(fundamentals)
        assert operating_profitability(fundamentals).equals(
            operating_profitability(fundamentals, shipped)
        )
