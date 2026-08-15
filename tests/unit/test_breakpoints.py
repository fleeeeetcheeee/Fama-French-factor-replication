"""
Tests for the NYSE breakpoint parser.

The assertion that carries the most weight is `test_two_count_shape_does_not_
shift_percentiles`: the ME and BE-ME files differ by one leading column, and
guessing wrong produces a complete, well-formed table in which every percentile
is mislabelled. Nothing crashes; the size sort just quietly uses the 45th
percentile where it meant the median.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ffrep.reference import breakpoints as bp


class TestMEBreakpoints:
    def test_single_count_column_detected(self, me_breakpoints_file):
        table = bp.load_breakpoints(me_breakpoints_file)
        assert list(table.counts.columns) == ["n_firms"]
        assert table.counts.iloc[0, 0] == 500

    def test_monthly_periodicity_and_month_end_index(self, me_breakpoints_file):
        table = bp.load_breakpoints(me_breakpoints_file)
        assert table.periodicity == "monthly"
        assert list(table.values.index) == [
            pd.Timestamp("2026-01-31"),
            pd.Timestamp("2026-02-28"),
        ]

    def test_twenty_percentiles_from_5_to_100(self, me_breakpoints_file):
        table = bp.load_breakpoints(me_breakpoints_file)
        assert list(table.values.columns) == list(range(5, 101, 5))
        assert len(table.values.columns) == 20

    def test_percentiles_land_in_the_right_columns(self, me_breakpoints_file):
        """
        The fixture's first row is 1.0, 2.0, ... 20.0 in order, so the nth
        percentile must equal n/5. Any column shift breaks this immediately.
        """
        table = bp.load_breakpoints(me_breakpoints_file)
        row = table.values.loc[pd.Timestamp("2026-01-31")]
        for pct in range(5, 101, 5):
            assert row[pct] == pytest.approx(pct / 5.0)

    def test_median_is_the_fiftieth(self, me_breakpoints_file):
        table = bp.load_breakpoints(me_breakpoints_file)
        assert bp.percentile(table, 50).iloc[0] == pytest.approx(10.0)


class TestBEMEBreakpoints:
    def test_two_count_columns_detected(self, beme_breakpoints_file):
        table = bp.load_breakpoints(beme_breakpoints_file)
        assert list(table.counts.columns) == ["n_nonpositive", "n_positive"]
        assert table.counts.loc[pd.Timestamp("2026-12-31"), "n_nonpositive"] == 70
        assert table.counts.loc[pd.Timestamp("2026-12-31"), "n_positive"] == 1015

    def test_annual_periodicity_and_year_end_index(self, beme_breakpoints_file):
        table = bp.load_breakpoints(beme_breakpoints_file)
        assert table.periodicity == "annual"
        assert list(table.values.index) == [
            pd.Timestamp("2025-12-31"),
            pd.Timestamp("2026-12-31"),
        ]

    def test_two_count_shape_does_not_shift_percentiles(self, beme_breakpoints_file):
        """
        The fixture's 2025 row runs 0.10, 0.20, ... 2.00, so the nth percentile
        is n/50. If the parser assumed one count column, every value would be
        off by one position and this fails on the first assertion.
        """
        table = bp.load_breakpoints(beme_breakpoints_file)
        row = table.values.loc[pd.Timestamp("2025-12-31")]
        for pct in range(5, 101, 5):
            assert row[pct] == pytest.approx(pct / 50.0)

    def test_the_thirty_seventy_split_used_by_hml(self, beme_breakpoints_file):
        table = bp.load_breakpoints(beme_breakpoints_file)
        assert bp.percentile(table, 30).loc[pd.Timestamp("2025-12-31")] == pytest.approx(0.60)
        assert bp.percentile(table, 70).loc[pd.Timestamp("2025-12-31")] == pytest.approx(1.40)


class TestPercentileGuard:
    def test_rejects_percentiles_french_does_not_publish(self, me_breakpoints_file):
        """
        Silently interpolating a breakpoint is a quiet departure from the
        published protocol, which is exactly what this project exists to avoid.
        """
        table = bp.load_breakpoints(me_breakpoints_file)
        with pytest.raises(ValueError, match="every 5th percentile"):
            bp.percentile(table, 33)

    def test_accepts_every_published_percentile(self, me_breakpoints_file):
        table = bp.load_breakpoints(me_breakpoints_file)
        for pct in bp.PERCENTILES:
            assert not bp.percentile(table, pct).empty


class TestMalformedInput:
    def test_raises_on_a_file_with_no_data_rows(self, tmp_path):
        path = tmp_path / "empty.csv"
        path.write_text("Just a preamble.\n\nCopyright 2026\n")
        with pytest.raises(ValueError, match="no data rows"):
            bp.load_breakpoints(path)

    def test_raises_on_ragged_rows(self, tmp_path):
        path = tmp_path / "ragged.csv"
        path.write_text(
            "Preamble\n\n"
            "202601,   500,    1.0,    2.0\n"
            "202602,   510,    2.0\n"
        )
        with pytest.raises(ValueError, match="ragged"):
            bp.load_breakpoints(path)

    def test_raises_when_too_few_percentile_columns(self, tmp_path):
        path = tmp_path / "short.csv"
        path.write_text("Preamble\n\n202601,   500,    1.0,    2.0\n")
        with pytest.raises(ValueError, match="fewer than"):
            bp.load_breakpoints(path)
