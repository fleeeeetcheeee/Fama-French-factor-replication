"""
The universe layer against live CRSP, validated on French's published breakpoints.

This is the acceptance test for `ffrep.universe`. The unit tests prove the screen
does what it says on hand-built data; only this proves that what it says is the
*right* screen, and it does so against an external reference we did not produce.

Opt-in: set FFREP_WRDS_TESTS=1 and WRDS_USERNAME. Skips otherwise.

Two facts these lock in, both bought expensively (LOG.md, 2026-08-25):

* Excluding SIC 6799 is what reconciles the NYSE universe with French's. Without
  it June-2022 is 18.6% adrift on the median and 154 firms too many.
* Market equity aggregates to the PERMCO. Without it, June-2000 is 5.5% adrift.

The tolerances are deliberately loose relative to what we measured — the point
is to catch a regression that reintroduces a structural error, not to freeze a
CRSP vintage. French's files are built from the 202606 database and ours ends
2024-12-31, so exact agreement is not available at any tolerance.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ffrep.config import Config, NYSE_EXCHANGE_CODES
from ffrep.reference.breakpoints import load_breakpoints, percentile
from ffrep.universe.screen import (
    aggregate_to_company,
    apply_share_screen,
    market_equity,
    nyse_breakpoint_universe,
)
from ffrep.universe.wrds_source import ExtractWindow, fetch_monthly_stock
from tests.conftest import requires_real

#: June cross-sections spanning four decades, including both sides of the SPAC wave.
CHECK_DATES = ["1990-06", "2000-06", "2010-06", "2015-06", "2018-06", "2022-06"]


@pytest.fixture(scope="module")
def june_cross_sections(wrds_db):
    """Every June cross-section we check, pulled in one round trip."""
    years = sorted({int(d[:4]) for d in CHECK_DATES})
    frames = [
        fetch_monthly_stock(wrds_db, ExtractWindow(f"{y}-06-01", f"{y}-06-30"))
        for y in years
    ]
    df = pd.concat(frames, ignore_index=True)
    df["ym"] = df["date"].dt.strftime("%Y-%m")
    return df


@pytest.fixture(scope="module")
def french_me():
    """French's published NYSE median and firm counts. Config() is cheap, so
    this builds its own rather than depending on the function-scoped fixture."""
    config = Config()
    requires_real(config, "bp_me")
    table = load_breakpoints(config.french_path("bp_me"))
    return percentile(table, 50), table.counts["n_firms"]


def _month_end(ym: str) -> pd.Timestamp:
    return pd.Timestamp(ym + "-01") + pd.offsets.MonthEnd(0)


class TestAgainstPublishedBreakpoints:
    @pytest.mark.parametrize("ym", CHECK_DATES)
    def test_nyse_median_tracks_french(self, june_cross_sections, french_me, ym):
        median, _ = french_me
        universe = nyse_breakpoint_universe(june_cross_sections[june_cross_sections.ym == ym])
        gap = universe["me"].median() / median[_month_end(ym)] - 1
        assert abs(gap) < 0.05, f"{ym}: NYSE median is {gap:+.2%} from French's published value"

    @pytest.mark.parametrize("ym", CHECK_DATES)
    def test_nyse_firm_count_tracks_french(self, june_cross_sections, french_me, ym):
        _, counts = french_me
        universe = nyse_breakpoint_universe(june_cross_sections[june_cross_sections.ym == ym])
        published = counts[_month_end(ym)]
        assert abs(len(universe) - published) <= 30, (
            f"{ym}: {len(universe)} firms against French's {published:.0f}"
        )

    def test_full_percentile_curve_tracks_french(self, june_cross_sections, french_me):
        """
        The median alone can agree while the distribution is wrong. June 2022 was
        within 18.6% at the median and 37.3% at the 20th percentile before the
        SIC 6799 exclusion.
        """
        config = Config()
        requires_real(config, "bp_me")
        table = load_breakpoints(config.french_path("bp_me"))
        universe = nyse_breakpoint_universe(
            june_cross_sections[june_cross_sections.ym == "2022-06"]
        )
        published = table.values.loc[_month_end("2022-06")]
        for pct in (10, 20, 30, 50, 70, 90):
            mine = universe["me"].quantile(pct / 100)
            gap = mine / published[pct] - 1
            assert abs(gap) < 0.06, f"p{pct}: {gap:+.2%} from French"


class TestScreenComponentsMatter:
    """Each guards a correction that was worth several percent when it was missing."""

    def test_dropping_blank_checks_moves_2022_materially(self, june_cross_sections, french_me):
        median, _ = french_me
        raw = june_cross_sections[june_cross_sections.ym == "2022-06"]
        published = median[_month_end("2022-06")]

        with_spacs = raw[raw.shrcd.isin([10, 11]) & raw.exchcd.isin(NYSE_EXCHANGE_CODES)].copy()
        with_spacs["me"] = market_equity(with_spacs)
        with_spacs = aggregate_to_company(with_spacs[with_spacs.me > 0])

        corrected = nyse_breakpoint_universe(raw)

        assert abs(with_spacs["me"].median() / published - 1) > 0.10
        assert abs(corrected["me"].median() / published - 1) < 0.05

    def test_blank_check_exclusion_is_nearly_inert_before_2010(self, june_cross_sections):
        """It must not be a patch that buys 2022 at the cost of history."""
        raw = june_cross_sections[june_cross_sections.ym == "1990-06"]
        screened = apply_share_screen(raw, exchanges=NYSE_EXCHANGE_CODES)
        unscreened = raw[raw.shrcd.isin([10, 11]) & raw.exchcd.isin(NYSE_EXCHANGE_CODES)]
        assert len(unscreened) - len(screened) < 20

    def test_company_aggregation_moves_the_median(self, june_cross_sections, french_me):
        median, _ = french_me
        raw = june_cross_sections[june_cross_sections.ym == "2000-06"]
        published = median[_month_end("2000-06")]

        securities = apply_share_screen(raw, exchanges=NYSE_EXCHANGE_CODES)
        companies = aggregate_to_company(securities)

        assert len(companies) < len(securities)
        assert abs(companies["me"].median() / published - 1) < abs(
            securities["me"].median() / published - 1
        )


class TestMarketEquityAgainstCrsp:
    def test_matches_crsps_own_market_cap_field(self, wrds_db):
        """
        prc x shrout / 1000 must reproduce CIZ's `mthcap` exactly. This is the
        check that eliminated measurement as a suspect for the 2022 gap.
        """
        ciz = wrds_db.raw_sql(
            """
            select permno, mthprc, shrout, mthcap
            from crsp.msf_v2
            where mthcaldt between '2022-06-01' and '2022-06-30'
              and sharetype='NS' and securitytype='EQTY' and securitysubtype='COM'
              and usincflg='Y' and issuertype in ('ACOR','CORP')
              and primaryexch='N' and conditionaltype='RW' and tradingstatusflg='A'
              and mthprc is not null and shrout is not null and mthcap > 0
            """
        )
        mine = ciz["mthprc"].abs() * ciz["shrout"] / 1000.0
        theirs = ciz["mthcap"] / 1000.0
        assert len(ciz) > 1000
        assert ((mine / theirs - 1).abs() < 1e-3).all()


class TestFormatEquivalence:
    def test_siz_and_ciz_agree_on_the_nyse_universe(self, wrds_db, june_cross_sections):
        """
        Justifies building on SIZ: the formats are interchangeable here, so the
        choice goes to fidelity with the published recipe rather than to data.

        The blank-check exclusion is applied to both sides — CIZ has no
        structural field for it either, so it must be done by SIC in both cases.
        """
        ciz = wrds_db.raw_sql(
            """
            select permno, permco, siccd, mthcap
            from crsp.msf_v2
            where mthcaldt between '2022-06-01' and '2022-06-30'
              and sharetype='NS' and securitytype='EQTY' and securitysubtype='COM'
              and usincflg='Y' and issuertype in ('ACOR','CORP')
              and primaryexch='N' and conditionaltype='RW' and tradingstatusflg='A'
              and mthprc is not null and shrout is not null and mthcap > 0
              and (siccd is null or siccd <> 6799)
            """
        )
        ciz["me"] = ciz["mthcap"] / 1000.0
        ciz_companies = ciz.groupby("permco")["me"].sum()

        siz = june_cross_sections[june_cross_sections.ym == "2022-06"]
        siz_companies = nyse_breakpoint_universe(siz)["me"]

        # 2-3% apart, not identical, and the reason is worth keeping: CIZ's
        # `siccd` is the current header classification while `msenames.siccd` is
        # the point-in-time name-record value, so the two formats disagree about
        # roughly 20 firms' industry codes. That is an argument *for* SIZ, whose
        # SIC travels with the name record rather than with today's view.
        assert abs(ciz_companies.median() / siz_companies.median() - 1) < 0.05
        assert abs(len(ciz_companies) - len(siz_companies)) <= 30


class TestDerivedBreakpoints:
    """
    Can we derive NYSE breakpoints instead of borrowing French's published files?

    This is the test that decides whether the README's "breakpoints are borrowed,
    not derived" limitation stands. Measured over 544 months and every percentile
    French reports: median error -0.000%, mean absolute error 0.51%, 85.7% of
    (month, percentile) pairs within 1%. See LOG.md, 2026-08-25.

    Tolerances here are per-month and looser than that aggregate, because a
    single month can sit in the tail of the distribution without indicating a
    regression.
    """

    @pytest.mark.parametrize("ym", ["1970-06", "1990-06", "2010-06"])
    def test_derived_median_matches_french(self, june_cross_sections, french_me, ym):
        from ffrep.construct.sorts import nyse_size_breakpoint

        median, _ = french_me
        if ym not in set(june_cross_sections.ym):
            pytest.skip(f"{ym} not in the pulled cross-sections")
        universe = nyse_breakpoint_universe(june_cross_sections[june_cross_sections.ym == ym])
        derived = nyse_size_breakpoint(universe["me"])
        gap = derived / median[_month_end(ym)] - 1
        assert abs(gap) < 0.03, f"{ym}: derived NYSE median is {gap:+.2%} from French's"

    def test_derived_percentile_curve_matches_french(self, june_cross_sections, french_me):
        """
        The full curve, not just the median — a size breakpoint can agree while
        the tails are wrong, and the tails are where the error concentrates
        (mean absolute error is 1.08% at p5 against 0.39% at p50).
        """
        from ffrep.construct.sorts import breakpoints_from_nyse

        config = Config()
        requires_real(config, "bp_me")
        table = load_breakpoints(config.french_path("bp_me"))
        universe = nyse_breakpoint_universe(
            june_cross_sections[june_cross_sections.ym == "1990-06"]
        )
        published = table.values.loc[_month_end("1990-06")]

        pcts = (10, 30, 50, 70, 90)
        derived = breakpoints_from_nyse(universe["me"], pcts)
        for pct, mine in zip(pcts, derived):
            gap = mine / published[pct] - 1
            assert abs(gap) < 0.04, f"p{pct}: derived breakpoint is {gap:+.2%} from French's"

    def test_derived_breakpoints_are_monotone(self, june_cross_sections):
        """A sanity invariant that holds regardless of how well we match French."""
        from ffrep.construct.sorts import breakpoints_from_nyse

        universe = nyse_breakpoint_universe(
            june_cross_sections[june_cross_sections.ym == "2010-06"]
        )
        derived = breakpoints_from_nyse(universe["me"], tuple(range(5, 100, 5)))
        assert all(b > a for a, b in zip(derived, derived[1:]))

    def test_size_breakpoint_splits_nyse_in_half(self, june_cross_sections):
        """
        Self-consistency: by construction the NYSE median must put half of NYSE
        on each side. Catches an inverted inequality in the bucket assignment
        that a comparison against French could mask.
        """
        from ffrep.construct.sorts import nyse_size_breakpoint, size_bucket

        universe = nyse_breakpoint_universe(
            june_cross_sections[june_cross_sections.ym == "2010-06"]
        )
        buckets = size_bucket(universe["me"], nyse_size_breakpoint(universe["me"]))
        share_small = (buckets == "S").mean()
        assert abs(share_small - 0.5) < 0.01
