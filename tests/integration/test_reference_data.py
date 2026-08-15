"""
Tests against the real downloaded reference files.

These skip cleanly when the data is absent so a fresh clone still runs green.
The synthetic fixtures prove the parsers handle the *format*; these prove they
handle the actual files, which is a different claim — Projects 01 and 02 both
recorded cases where a schema assumed from memory would have failed against
reality.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ffrep.reference import breakpoints as bp
from ffrep.reference import parser as fp
from tests.conftest import requires_real


class TestSixPortfolios:
    def test_finds_all_ten_stacked_tables(self, real_config):
        requires_real(real_config, "portfolios_6_beme")
        tables = fp.parse_tables(real_config.french_path("portfolios_6_beme"))
        assert len(tables) == 10

    def test_history_starts_in_july_1926(self, real_config):
        requires_real(real_config, "portfolios_6_beme")
        frame = fp.load_six_portfolios(
            real_config.french_path("portfolios_6_beme"), weighting="value"
        )
        assert frame.index[0] == pd.Timestamp("1926-07-31")
        assert len(frame) > 1150

    def test_returns_are_decimals_not_percent(self, real_config):
        """A monthly equity return outside +-100% would mean the /100 was missed."""
        requires_real(real_config, "portfolios_6_beme")
        frame = fp.load_six_portfolios(
            real_config.french_path("portfolios_6_beme"), weighting="value"
        )
        assert frame.abs().max().max() < 1.0

    def test_firm_counts_are_positive_integers(self, real_config):
        requires_real(real_config, "portfolios_6_beme")
        counts = fp.load_firm_counts(real_config.french_path("portfolios_6_beme"))
        recent = counts.loc[counts.index >= pd.Timestamp("2000-01-01")]
        assert (recent > 0).all().all()

    def test_small_portfolios_hold_far_more_firms_than_big(self, real_config):
        """
        The single most important fact for this project's feasibility: the small
        half of the market is where most *firms* live, even though the big half
        holds most of the *value*. A large-cap universe loses the majority of
        the cross-section by count.
        """
        requires_real(real_config, "portfolios_6_beme")
        counts = fp.load_firm_counts(real_config.french_path("portfolios_6_beme"))
        recent = counts.loc[counts.index >= pd.Timestamp("2015-01-01")]
        small = recent[["SmallGrowth", "SmallNeutral", "SmallValue"]].sum(axis=1)
        big = recent[["BigGrowth", "BigNeutral", "BigValue"]].sum(axis=1)
        assert (small > big).all()


class TestFactorAlgebraAgainstPublished:
    """
    The done criterion of this step: reproduce the published factors from
    French's own portfolios. Any error above the rounding floor is an error in
    the algebra, because there is nothing else in the path.
    """

    #: French publishes to two decimals in percent, so the half-ulp of his own
    #: reporting is exactly 0.5 bp. This is a floor, not a tolerance chosen to
    #: make a test pass — the same bound Project 02 landed on independently.
    ROUNDING_FLOOR_BPS = 0.5

    #: Slack for float64 representation only. The observed excess over the floor
    #: is ~8e-14 bps, i.e. 1e-17 in return terms, which is the arithmetic of
    #: summing six doubles and not a property of the data. Deliberately far too
    #: small to hide any accounting error: one basis point is 1e9 times this.
    FLOAT_EPSILON_BPS = 1e-9

    @pytest.fixture
    def series(self, real_config):
        requires_real(real_config, "portfolios_6_beme", "factors_3")
        portfolios = fp.load_six_portfolios(
            real_config.french_path("portfolios_6_beme"), weighting="value"
        )
        published = fp.load_factors(real_config.french_path("factors_3"))
        return portfolios, published

    def _gap_bps(self, mine, published):
        joined = pd.concat([mine, published], axis=1).dropna()
        return joined, (joined.iloc[:, 0] - joined.iloc[:, 1]).abs() * 1e4

    def test_hml_reproduced_to_the_rounding_floor(self, series):
        portfolios, published = series
        joined, gap = self._gap_bps(
            fp.construct_hml_from_portfolios(portfolios), published["HML"]
        )
        assert len(joined) > 1150
        assert gap.max() <= self.ROUNDING_FLOOR_BPS + self.FLOAT_EPSILON_BPS

    def test_smb_reproduced_to_the_rounding_floor(self, series):
        portfolios, published = series
        _, gap = self._gap_bps(
            fp.construct_smb_from_portfolios(portfolios), published["SMB"]
        )
        assert gap.max() <= self.ROUNDING_FLOOR_BPS + self.FLOAT_EPSILON_BPS

    def test_error_sits_exactly_on_french_rounding_not_merely_under_it(self, series):
        """
        The informative assertion, and the reason the bound is credible.

        An accounting bug — a wrong weight, a swapped leg, a misread column —
        would produce a *messy* error bound, not one that lands precisely on the
        half-ulp of French's own 2-decimal reporting. Hitting 0.5000 exactly is
        evidence that the only error in the path is his rounding. This is the
        same argument Project 02 made about its engine.
        """
        portfolios, published = series
        for name, mine in (
            ("HML", fp.construct_hml_from_portfolios(portfolios)),
            ("SMB", fp.construct_smb_from_portfolios(portfolios)),
        ):
            _, gap = self._gap_bps(mine, published[name])
            assert gap.max() == pytest.approx(
                self.ROUNDING_FLOOR_BPS, abs=self.FLOAT_EPSILON_BPS
            ), f"{name} max gap is {gap.max()}, not the rounding floor"

    def test_equal_weighted_would_have_been_wrong(self, real_config, series):
        """
        Control assertion. Project 02 measured this at 92 bps a month with a
        0.93 correlation — plausible enough to publish and entirely incorrect.
        Pinning it means the value/equal distinction cannot silently regress.
        """
        _, published = series
        equal = fp.load_six_portfolios(
            real_config.french_path("portfolios_6_beme"), weighting="equal"
        )
        wrong = fp.construct_hml_from_portfolios(equal)
        joined = pd.concat([wrong, published["HML"]], axis=1).dropna()
        gap = (joined.iloc[:, 0] - joined.iloc[:, 1]).abs() * 1e4
        assert gap.mean() > 50.0
        assert joined.iloc[:, 0].corr(joined.iloc[:, 1]) > 0.85


class TestRealBreakpoints:
    @pytest.mark.parametrize(
        "key,periodicity,count_columns",
        [
            ("bp_me", "monthly", ["n_firms"]),
            ("bp_beme", "annual", ["n_nonpositive", "n_positive"]),
            ("bp_op", "annual", ["n_firms"]),
            ("bp_inv", "annual", ["n_firms"]),
            ("bp_prior", "monthly", ["n_firms"]),
        ],
    )
    def test_each_file_parses_with_its_own_shape(
        self, real_config, key, periodicity, count_columns
    ):
        """
        The count-column width differs across these files and is not announced
        by a usable header. Getting it wrong shifts every percentile silently,
        so each shape is pinned explicitly.
        """
        requires_real(real_config, key)
        table = bp.load_breakpoints(real_config.french_path(key))
        assert table.periodicity == periodicity
        assert list(table.counts.columns) == count_columns
        assert list(table.values.columns) == list(range(5, 101, 5))

    def test_percentiles_are_monotone_across_the_row(self, real_config):
        """
        A percentile table must increase left to right in every period. This is
        the strongest available check that no column shift or misparse occurred,
        and it holds for all 1,207 monthly rows.
        """
        requires_real(real_config, "bp_me")
        values = bp.load_breakpoints(real_config.french_path("bp_me")).values
        differences = values.diff(axis=1).iloc[:, 1:]
        assert (differences.fillna(0) >= 0).all().all()

    def test_nyse_median_is_economically_plausible(self, real_config):
        """
        ME breakpoints are in $ millions. A recent NYSE median between $1bn and
        $20bn is a sanity bound wide enough to survive any market, but narrow
        enough to catch a units error of 10^3 or 10^6 — which is the realistic
        failure, since the file header says values are "divided by 1000000".
        """
        requires_real(real_config, "bp_me")
        table = bp.load_breakpoints(real_config.french_path("bp_me"))
        median = bp.percentile(table, 50)
        recent = median.loc[median.index >= pd.Timestamp("2020-01-01")]
        assert 1_000 < recent.mean() < 20_000

    def test_beme_breakpoints_cover_the_full_factor_history(self, real_config):
        requires_real(real_config, "bp_beme")
        table = bp.load_breakpoints(real_config.french_path("bp_beme"))
        assert table.values.index[0].year <= 1926
        assert table.values.index[-1].year >= 2025

    def test_profitability_and_investment_start_in_1963(self, real_config):
        """
        RMW and CMA cannot be built before Compustat coverage begins, and the
        breakpoint files say so directly. Worth pinning: it is a second, harder
        start-date constraint on the 5-factor extension.
        """
        requires_real(real_config, "bp_op", "bp_inv")
        for key in ("bp_op", "bp_inv"):
            table = bp.load_breakpoints(real_config.french_path(key))
            assert table.values.index[0].year == 1963


class TestFiveFactorAndMomentum:
    def test_five_factor_file_carries_rmw_and_cma(self, real_config):
        requires_real(real_config, "factors_5")
        frame = fp.load_factors(real_config.french_path("factors_5"))
        assert {"RMW", "CMA"} <= set(frame.columns)

    def test_five_factor_history_starts_in_1963(self, real_config):
        requires_real(real_config, "factors_5")
        frame = fp.load_factors(real_config.french_path("factors_5"))
        assert frame.index[0].year == 1963

    def test_momentum_file_loads(self, real_config):
        requires_real(real_config, "momentum")
        frame = fp.load_factors(real_config.french_path("momentum"))
        assert len(frame.columns) == 1
        assert frame.abs().max().max() < 1.0

    def test_five_factor_smb_differs_from_three_factor_smb(self, real_config):
        """
        A real and easy mistake. The 5-factor SMB averages the small-minus-big
        spread across all three 2x3 sorts (BE/ME, OP, INV); the 3-factor SMB
        uses only the BE/ME sort. They are different series with the same name.
        """
        requires_real(real_config, "factors_3", "factors_5")
        three = fp.load_factors(real_config.french_path("factors_3"))["SMB"]
        five = fp.load_factors(real_config.french_path("factors_5"))["SMB"]
        joined = pd.concat([three, five], axis=1).dropna()
        joined.columns = ["three", "five"]
        assert not joined["three"].equals(joined["five"])
        # Highly correlated but not identical — that is exactly what makes
        # confusing them dangerous rather than obvious.
        assert joined["three"].corr(joined["five"]) > 0.95
        assert (joined["three"] - joined["five"]).abs().max() > 1e-4


class TestCeilingAnalysis:
    """
    Step 1's result, pinned. These are the numbers the project's revised target
    rests on, so a change in them is a change in what the project is claiming.
    """

    @pytest.fixture
    def table(self, real_config):
        requires_real(real_config, "portfolios_6_beme", "factors_3")
        from ffrep.evaluate.ceiling import run

        return run(
            real_config.french_path("portfolios_6_beme"),
            real_config.french_path("factors_3"),
        )

    def test_covers_every_factor_and_window(self, table):
        assert len(table) == 6
        assert set(table["window"]) == {
            "full history", "spec 1990-2020", "free-data 2010.07+"
        }

    def test_big_only_hml_cannot_reach_the_spec_target(self, table):
        """
        The finding that reshapes the project. A universe without small caps
        tops out near 0.92, not 0.99 — and this is measured on French's *own*
        portfolios, so it is a bound on the data rather than on the
        implementation. No downstream care can beat it.
        """
        big_only = table[table["factor"] == "HML (big-only)"]
        assert (big_only["corr"] < 0.95).all()
        assert (big_only["corr"] > 0.85).all()

    def test_analytic_and_empirical_correlations_agree(self, table):
        """
        Computed by different routes — one from rho and the two spread
        volatilities, the other by correlating the realised series. Agreement is
        evidence the HML decomposition is right; disagreement would mean the
        algebra is wrong somewhere.
        """
        big_only = table[table["factor"] == "HML (big-only)"].dropna(
            subset=["analytic_corr"]
        )
        assert len(big_only) == 3
        for _, row in big_only.iterrows():
            assert row["corr"] == pytest.approx(row["analytic_corr"], abs=1e-3)

    def test_tracking_error_is_economically_large(self, table):
        """
        The correlation alone understates the problem. ~160 bps per month of
        tracking error against a factor whose own monthly standard deviation is
        around 300 bps is not a near miss.
        """
        big_only = table[table["factor"] == "HML (big-only)"]
        assert (big_only["TE_bps"] > 100).all()

    def test_both_size_halves_matter_roughly_equally(self, table):
        """
        Neither half of the market is redundant: dropping the small stocks and
        dropping the big ones cost about the same. That rules out the hopeful
        reading that HML is mostly a large-cap phenomenon a large-cap universe
        would capture.
        """
        big_only = table[table["factor"] == "HML (big-only)"]["corr"].mean()
        small_only = table[table["factor"] == "HML (small-only)"]["corr"].mean()
        assert abs(big_only - small_only) < 0.05
