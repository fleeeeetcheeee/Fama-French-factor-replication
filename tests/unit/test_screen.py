"""
Universe screen tests.

Every cross-section here is small enough to verify by hand. That is deliberate:
the failure mode this module guards against is not a crash but a plausible
wrong answer, and only a case whose correct output you already know can catch
one.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ffrep.config import (
    COMMON_SHARE_CODES,
    EXCLUDED_SIC_CODES,
    NYSE_EXCHANGE_CODES,
)
from ffrep.universe.screen import (
    REQUIRED_COLUMNS,
    aggregate_to_company,
    apply_share_screen,
    full_universe,
    market_equity,
    nyse_breakpoint_universe,
)

JUNE = pd.Timestamp("2022-06-30")


def cross_section(**overrides) -> pd.DataFrame:
    """A four-security cross-section with sane defaults, overridable per column."""
    base = {
        "permno": [1, 2, 3, 4],
        "permco": [10, 20, 30, 40],
        "date": [JUNE] * 4,
        "prc": [10.0, 20.0, 30.0, 40.0],
        "shrout": [1000, 1000, 1000, 1000],
        "shrcd": [11, 11, 11, 11],
        "exchcd": [1, 1, 1, 1],
        "siccd": [2834, 3711, 7372, 1311],
    }
    base.update(overrides)
    return pd.DataFrame(base)


class TestMarketEquity:
    def test_units_are_millions(self):
        # 10 dollars x 1,000 thousand shares = $10m.
        df = cross_section()
        assert market_equity(df).iloc[0] == pytest.approx(10.0)

    def test_negative_price_is_a_quote_flag_not_a_value(self):
        """CRSP negates prc for bid/ask midpoints. Sign must not reach the answer."""
        df = cross_section(prc=[-10.0, 20.0, 30.0, 40.0])
        assert market_equity(df).iloc[0] == pytest.approx(10.0)

    def test_matches_hand_computation_across_the_row(self):
        df = cross_section(prc=[1.5, -2.5, 100.0, 0.25], shrout=[2000, 400, 10, 8000])
        assert list(market_equity(df)) == pytest.approx([3.0, 1.0, 1.0, 2.0])


class TestShareScreen:
    def test_keeps_only_ordinary_common_shares(self):
        # 18 = REIT, 44 = closed-end fund: French excludes both by name, and
        # CRSP's coding already excludes them via share code.
        df = cross_section(shrcd=[11, 18, 44, 10])
        assert set(apply_share_screen(df)["permno"]) == {1, 4}

    @pytest.mark.parametrize("code", COMMON_SHARE_CODES)
    def test_both_common_codes_survive(self, code):
        df = cross_section(shrcd=[code] * 4)
        assert len(apply_share_screen(df)) == 4

    def test_excludes_blank_check_companies(self):
        """The SPAC leak: share code 11, NYSE-listed, and not a firm."""
        df = cross_section(siccd=[2834, 6799, 3711, 6799])
        assert set(apply_share_screen(df)["permno"]) == {1, 3}

    @pytest.mark.parametrize("sic", EXCLUDED_SIC_CODES)
    def test_every_excluded_sic_is_actually_excluded(self, sic):
        df = cross_section(siccd=[sic] * 4)
        assert apply_share_screen(df).empty

    def test_missing_sic_is_kept_not_dropped(self):
        """A missing SIC is not evidence of a blank check."""
        df = cross_section(siccd=[None, 2834, 3711, 1311])
        assert 1 in set(apply_share_screen(df)["permno"])

    def test_survives_absent_sic_column(self):
        df = cross_section().drop(columns=["siccd"])
        assert len(apply_share_screen(df)) == 4

    def test_nyse_filter_is_narrower_than_listed(self):
        df = cross_section(exchcd=[1, 2, 3, 1])
        assert len(apply_share_screen(df)) == 4
        nyse = apply_share_screen(df, exchanges=NYSE_EXCHANGE_CODES)
        assert set(nyse["permno"]) == {1, 4}

    def test_drops_null_price_and_shares(self):
        df = cross_section(prc=[10.0, None, 30.0, 40.0], shrout=[1000, 1000, None, 1000])
        assert set(apply_share_screen(df)["permno"]) == {1, 4}

    def test_drops_zero_market_equity(self):
        df = cross_section(prc=[0.0, 20.0, 30.0, 40.0])
        assert 1 not in set(apply_share_screen(df)["permno"])

    @pytest.mark.parametrize("col", REQUIRED_COLUMNS)
    def test_missing_required_column_raises_naming_it(self, col):
        df = cross_section().drop(columns=[col])
        with pytest.raises(KeyError, match=col):
            apply_share_screen(df)


class TestCompanyAggregation:
    def test_share_classes_sum_to_one_company(self):
        """Two classes, one firm: $10m + $40m = $50m, not two firms."""
        df = cross_section(permco=[10, 10, 30, 40], prc=[10.0, 40.0, 30.0, 40.0])
        out = aggregate_to_company(apply_share_screen(df))
        assert len(out) == 3
        assert out.set_index("permco").loc[10, "me"] == pytest.approx(50.0)

    def test_total_is_assigned_to_the_largest_class(self):
        """Which PERMNO survives decides what joins to Compustat later."""
        df = cross_section(permco=[10, 10, 30, 40], prc=[10.0, 40.0, 30.0, 40.0])
        out = aggregate_to_company(apply_share_screen(df))
        assert out.set_index("permco").loc[10, "permno"] == 2

    def test_ties_break_deterministically_on_lower_permno(self):
        df = cross_section(permco=[10, 10, 30, 40], prc=[25.0, 25.0, 30.0, 40.0])
        out = aggregate_to_company(apply_share_screen(df))
        assert out.set_index("permco").loc[10, "permno"] == 1

    def test_reordering_input_does_not_change_output(self):
        df = cross_section(permco=[10, 10, 30, 40], prc=[10.0, 40.0, 30.0, 40.0])
        a = aggregate_to_company(apply_share_screen(df))
        b = aggregate_to_company(apply_share_screen(df.iloc[::-1].reset_index(drop=True)))
        pd.testing.assert_frame_equal(
            a.sort_values("permco").reset_index(drop=True),
            b.sort_values("permco").reset_index(drop=True),
        )

    def test_total_market_equity_is_conserved(self):
        df = cross_section(permco=[10, 10, 10, 40])
        screened = apply_share_screen(df)
        out = aggregate_to_company(screened)
        assert out["me"].sum() == pytest.approx(screened["me"].sum())

    def test_dates_are_kept_separate(self):
        july = pd.Timestamp("2022-07-29")
        df = cross_section(permco=[10, 10, 10, 10], date=[JUNE, JUNE, july, july])
        out = aggregate_to_company(apply_share_screen(df))
        assert len(out) == 2

    def test_primary_row_is_kept_intact_not_assembled_from_classes(self):
        """
        Review R21. The larger class (permno 2) has no return and no CUSIP; the
        smaller one returned -30%. The survivor must be permno 2's own row —
        missing return, missing CUSIP — not permno 2 wearing permno 1's -30%.
        """
        df = cross_section(permco=[10, 10, 30, 40], prc=[10.0, 40.0, 30.0, 40.0])
        df["ret"] = [-0.30, float("nan"), 0.01, 0.02]
        df["cusip"] = ["11111111", None, "33333333", "44444444"]
        row = aggregate_to_company(apply_share_screen(df)).set_index("permco").loc[10]
        assert row["permno"] == 2
        assert pd.isna(row["ret"])
        assert pd.isna(row["cusip"])
        assert row["me"] == pytest.approx(50.0)

    def test_requires_me_column(self):
        with pytest.raises(KeyError, match="me"):
            aggregate_to_company(cross_section())

    def test_empty_input_is_not_an_error(self):
        empty = apply_share_screen(cross_section(shrcd=[44] * 4))
        assert aggregate_to_company(empty).empty


class TestComposition:
    def test_screen_runs_before_aggregation(self):
        """
        A SPAC sharing a PERMCO must not contribute its size to the survivor.

        Aggregating first would fold permno 2's $40m into permco 10's total and
        then never look at its SIC again.
        """
        df = cross_section(permco=[10, 10, 30, 40], prc=[10.0, 40.0, 30.0, 40.0],
                           siccd=[2834, 6799, 3711, 1311])
        out = nyse_breakpoint_universe(df)
        assert out.set_index("permco").loc[10, "me"] == pytest.approx(10.0)

    def test_nyse_universe_is_a_subset_of_the_full_universe(self):
        df = cross_section(exchcd=[1, 2, 3, 1])
        assert set(nyse_breakpoint_universe(df)["permno"]) <= set(full_universe(df)["permno"])

    def test_full_universe_spans_three_exchanges(self):
        df = cross_section(exchcd=[1, 2, 3, 1])
        assert len(full_universe(df)) == 4
