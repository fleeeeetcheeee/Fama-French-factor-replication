"""Tests for the stacked-table French CSV parser."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ffrep.reference import parser as fp


class TestParseTables:
    def test_finds_every_table(self, six_portfolio_file):
        tables = fp.parse_tables(six_portfolio_file)
        assert len(tables) == 4

    def test_classifies_periodicity_by_date_width(self, six_portfolio_file):
        tables = fp.parse_tables(six_portfolio_file)
        periodicities = [t.periodicity for t in tables]
        assert periodicities == ["monthly", "monthly", "annual", "monthly"]

    def test_title_is_the_preceding_non_empty_line(self, six_portfolio_file):
        titles = [t.title for t in fp.parse_tables(six_portfolio_file)]
        assert titles[0] == "Average Value Weighted Returns -- Monthly"
        assert titles[1] == "Average Equal Weighted Returns -- Monthly"

    def test_ignores_the_copyright_footer(self, six_portfolio_file):
        for table in fp.parse_tables(six_portfolio_file):
            assert not table.data.empty
            assert table.data.notna().any().any()


class TestLoadSixPortfolios:
    def test_renames_to_unambiguous_labels(self, six_portfolio_file):
        frame = fp.load_six_portfolios(six_portfolio_file, weighting="value")
        assert list(frame.columns) == [
            "SmallGrowth", "SmallNeutral", "SmallValue",
            "BigGrowth", "BigNeutral", "BigValue",
        ]

    def test_small_lobm_is_growth_not_value(self, six_portfolio_file):
        """
        The renaming is the test. "SMALL LoBM" is *low* book-to-market, i.e.
        small-cap growth. Reading it as value inverts HML's sign, which produces
        a factor that looks fine and is backwards.
        """
        frame = fp.load_six_portfolios(six_portfolio_file, weighting="value")
        # SMALL LoBM held 1.00 in 202601 — it must land in SmallGrowth.
        assert frame.loc[pd.Timestamp("2026-01-31"), "SmallGrowth"] == pytest.approx(0.01)
        assert frame.loc[pd.Timestamp("2026-01-31"), "SmallValue"] == pytest.approx(0.03)

    def test_percent_converted_to_decimal(self, six_portfolio_file):
        frame = fp.load_six_portfolios(six_portfolio_file, weighting="value")
        assert frame.loc[pd.Timestamp("2026-01-31"), "BigValue"] == pytest.approx(0.06)

    def test_missing_sentinel_becomes_nan(self, six_portfolio_file):
        frame = fp.load_six_portfolios(six_portfolio_file, weighting="value")
        assert np.isnan(frame.loc[pd.Timestamp("2026-03-31"), "SmallNeutral"])

    def test_indexed_by_month_end(self, six_portfolio_file):
        frame = fp.load_six_portfolios(six_portfolio_file, weighting="value")
        assert list(frame.index) == [
            pd.Timestamp("2026-01-31"),
            pd.Timestamp("2026-02-28"),
            pd.Timestamp("2026-03-31"),
        ]

    def test_weighting_is_required(self, six_portfolio_file):
        with pytest.raises(TypeError):
            fp.load_six_portfolios(six_portfolio_file)

    def test_rejects_unknown_weighting(self, six_portfolio_file):
        with pytest.raises(ValueError, match="weighting must be"):
            fp.load_six_portfolios(six_portfolio_file, weighting="cap")

    def test_equal_weighted_is_a_different_table(self, six_portfolio_file):
        """
        Control assertion, carried over from Project 02. The two tables have
        identical column names and sit adjacent in the file; reading the wrong
        one silently produces a plausible, incorrect factor.
        """
        value = fp.load_six_portfolios(six_portfolio_file, weighting="value")
        equal = fp.load_six_portfolios(six_portfolio_file, weighting="equal")
        assert not value.equals(equal)
        assert equal.loc[pd.Timestamp("2026-01-31"), "SmallGrowth"] == pytest.approx(0.10)

    def test_annual_table_is_reachable_and_distinct(self, six_portfolio_file):
        annual = fp.load_six_portfolios(
            six_portfolio_file, weighting="value", periodicity="annual"
        )
        assert len(annual) == 1
        assert annual.index[0] == pd.Timestamp("2026-12-31")


class TestFindTable:
    def test_raises_when_match_is_not_unique(self, six_portfolio_file):
        """
        Strictness is the feature. "Returns" alone matches both the value- and
        equal-weighted monthly tables, and a lenient parser would pick one.
        """
        with pytest.raises(ValueError, match="found 2"):
            fp.find_table(six_portfolio_file, title_contains=("Returns",))

    def test_raises_when_nothing_matches(self, six_portfolio_file):
        with pytest.raises(ValueError, match="found 0"):
            fp.find_table(six_portfolio_file, title_contains=("Nonexistent",))


class TestFirmCounts:
    def test_loads_counts_unscaled(self, six_portfolio_file):
        """Counts are counts — they must not go through the percent conversion."""
        counts = fp.load_firm_counts(six_portfolio_file)
        assert counts.loc[pd.Timestamp("2026-01-31"), "SmallGrowth"] == 100
        assert counts.loc[pd.Timestamp("2026-01-31"), "BigValue"] == 60


class TestFactorAlgebra:
    def test_hml_matches_its_definition(self, six_portfolio_file):
        frame = fp.load_six_portfolios(six_portfolio_file, weighting="value")
        hml = fp.construct_hml_from_portfolios(frame)
        # 202601: 1/2(0.03 + 0.06) - 1/2(0.01 + 0.04) = 0.045 - 0.025 = 0.02
        assert hml.loc[pd.Timestamp("2026-01-31")] == pytest.approx(0.02)

    def test_hml_ignores_the_neutral_portfolios(self, six_portfolio_file):
        frame = fp.load_six_portfolios(six_portfolio_file, weighting="value")
        before = fp.construct_hml_from_portfolios(frame)
        perturbed = frame.copy()
        perturbed[["SmallNeutral", "BigNeutral"]] += 0.5
        after = fp.construct_hml_from_portfolios(perturbed)
        pd.testing.assert_series_equal(before, after)

    def test_smb_matches_its_definition(self, six_portfolio_file):
        frame = fp.load_six_portfolios(six_portfolio_file, weighting="value")
        smb = fp.construct_smb_from_portfolios(frame)
        # 202601: mean(0.01,0.02,0.03) - mean(0.04,0.05,0.06) = 0.02 - 0.05
        assert smb.loc[pd.Timestamp("2026-01-31")] == pytest.approx(-0.03)

    def test_smb_uses_all_six_unlike_hml(self, six_portfolio_file):
        """SMB does depend on the neutral portfolios; HML does not."""
        frame = fp.load_six_portfolios(six_portfolio_file, weighting="value")
        before = fp.construct_smb_from_portfolios(frame)
        perturbed = frame.copy()
        perturbed["SmallNeutral"] += 0.5
        after = fp.construct_smb_from_portfolios(perturbed)
        assert not before.equals(after)

    def test_raises_on_missing_columns(self):
        with pytest.raises(ValueError, match="missing"):
            fp.construct_hml_from_portfolios(pd.DataFrame({"SmallValue": [0.1]}))


class TestLoadFactors:
    def test_reads_the_published_series(self, factors_file):
        frame = fp.load_factors(factors_file)
        assert list(frame.columns) == ["Mkt-RF", "SMB", "HML", "RF"]
        assert frame.loc[pd.Timestamp("2026-01-31"), "HML"] == pytest.approx(0.01)

    def test_raises_when_periodicity_is_ambiguous(self, six_portfolio_file):
        with pytest.raises(ValueError, match="expected exactly one"):
            fp.load_factors(six_portfolio_file)
