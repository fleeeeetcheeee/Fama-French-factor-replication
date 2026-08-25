"""
Sort tests.

The 2x3 assignment cannot crash on plausible input — it can only return the
wrong bucket. Every case here has an answer computable in your head.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ffrep.config import BREAKPOINT_QUANTILE_METHOD
from ffrep.construct.sorts import (
    SIZE_LABELS,
    VALUE_LABELS,
    assign_2x3,
    assign_bucket,
    book_to_market,
    breakpoints_from_nyse,
    FormationInputs,
    nyse_size_breakpoint,
    nyse_value_breakpoints,
    size_bucket,
    value_bucket,
)


def inputs(**overrides) -> FormationInputs:
    base = {
        "me_june": pd.Series({1: 100.0, 2: 50.0, 3: 10.0}),
        "me_december": pd.Series({1: 80.0, 2: 40.0, 3: 8.0}),
        "book_equity": pd.Series({1: 40.0, 2: 40.0, 3: 8.0}),
    }
    base.update(overrides)
    return FormationInputs(**base)


class TestFormationInputs:
    def test_rejects_non_series(self):
        with pytest.raises(TypeError, match="me_june"):
            FormationInputs(me_june=[1, 2], me_december=pd.Series(), book_equity=pd.Series())

    def test_sortable_is_the_intersection(self):
        i = inputs(book_equity=pd.Series({1: 40.0, 2: 40.0}))
        assert list(i.sortable) == [1, 2]

    def test_nan_excludes_a_firm_from_sortable(self):
        i = inputs(me_december=pd.Series({1: 80.0, 2: np.nan, 3: 8.0}))
        assert list(i.sortable) == [1, 3]


class TestBookToMarket:
    def test_uses_december_market_equity_not_june(self):
        """
        The single most consequential convention in the module. Firm 1 has
        BE 40, December ME 80, June ME 100: BE/ME is 0.5, not 0.4.
        """
        assert book_to_market(inputs()).loc[1] == pytest.approx(0.5)

    def test_swapping_june_for_december_would_change_the_answer(self):
        """Guards the previous test against being vacuously true."""
        swapped = FormationInputs(
            me_june=inputs().me_december,
            me_december=inputs().me_june,
            book_equity=inputs().book_equity,
        )
        assert book_to_market(swapped).loc[1] != pytest.approx(0.5)

    def test_non_positive_book_equity_is_dropped(self):
        i = inputs(book_equity=pd.Series({1: 40.0, 2: 0.0, 3: -5.0}))
        assert list(book_to_market(i).index) == [1]

    def test_non_positive_market_equity_is_dropped(self):
        i = inputs(me_december=pd.Series({1: 80.0, 2: 0.0, 3: 8.0}))
        assert 2 not in book_to_market(i).index


class TestAssignBucket:
    def test_lower_edge_is_inclusive(self):
        """A value exactly at an edge belongs to the bucket below it."""
        out = assign_bucket(pd.Series([30.0, 70.0]), (30.0, 70.0), ("L", "M", "H"))
        assert list(out) == ["L", "M"]

    def test_values_below_between_and_above(self):
        out = assign_bucket(pd.Series([10.0, 50.0, 90.0]), (30.0, 70.0), ("L", "M", "H"))
        assert list(out) == ["L", "M", "H"]

    def test_nan_stays_nan_rather_than_defaulting(self):
        """A firm that cannot be sorted must not silently become growth."""
        out = assign_bucket(pd.Series([np.nan]), (30.0,), ("L", "H"))
        assert pd.isna(out.iloc[0])

    def test_label_count_must_exceed_edge_count_by_one(self):
        with pytest.raises(ValueError, match="one more label"):
            assign_bucket(pd.Series([1.0]), (1.0, 2.0), ("A", "B"))

    def test_edges_must_be_strictly_increasing(self):
        with pytest.raises(ValueError, match="increasing"):
            assign_bucket(pd.Series([1.0]), (70.0, 30.0), ("L", "M", "H"))


class TestBuckets:
    def test_small_is_at_or_below_the_median(self):
        out = size_bucket(pd.Series([49.0, 50.0, 51.0]), 50.0)
        assert list(out) == ["S", "S", "B"]

    def test_value_thirds(self):
        out = value_bucket(pd.Series([0.1, 0.5, 0.9]), 0.3, 0.7)
        assert list(out) == ["L", "M", "H"]

    def test_labels_are_the_documented_ones(self):
        assert SIZE_LABELS == ("S", "B")
        assert VALUE_LABELS == ("L", "M", "H")


class TestAssign2x3:
    def test_produces_concatenated_labels(self):
        out = assign_2x3(inputs(), nyse_size_breakpoint=50.0, nyse_value_breakpoints=(0.6, 0.9))
        assert out.loc[1, "portfolio"] == "BL"

    def test_weight_column_is_june_market_equity(self):
        """Value weighting uses June ME, never December."""
        out = assign_2x3(inputs(), nyse_size_breakpoint=50.0, nyse_value_breakpoints=(0.6, 0.9))
        assert out.loc[1, "me"] == pytest.approx(100.0)

    def test_unsortable_firms_are_dropped_not_defaulted(self):
        i = inputs(book_equity=pd.Series({1: 40.0, 2: -1.0, 3: 8.0}))
        out = assign_2x3(i, nyse_size_breakpoint=50.0, nyse_value_breakpoints=(0.6, 0.9))
        assert 2 not in out.index

    def test_every_row_gets_one_of_the_six_labels(self):
        out = assign_2x3(inputs(), nyse_size_breakpoint=50.0, nyse_value_breakpoints=(0.6, 0.9))
        assert set(out["portfolio"]) <= {"SL", "SM", "SH", "BL", "BM", "BH"}


class TestBreakpointDerivation:
    def test_median_of_a_known_series(self):
        assert nyse_size_breakpoint(pd.Series([1.0, 2.0, 3.0])) == pytest.approx(2.0)

    def test_thirty_seventy_of_a_uniform_series(self):
        p30, p70 = nyse_value_breakpoints(pd.Series(np.arange(0, 101, dtype=float)))
        assert p30 == pytest.approx(30.0)
        assert p70 == pytest.approx(70.0)

    def test_ignores_missing_values(self):
        """Two survivors under the 'lower' convention give the lower of them."""
        assert nyse_size_breakpoint(pd.Series([1.0, np.nan, 3.0])) == pytest.approx(1.0)

    def test_default_method_is_lower(self):
        """
        Selected by scoring all five numpy conventions against French's published
        breakpoints over 1960-1989, not assumed. 'lower' is unbiased to four
        decimals where 'linear' carries a +0.0886% median error.
        """
        assert BREAKPOINT_QUANTILE_METHOD == "lower"

    def test_lower_returns_an_actual_observation(self):
        """
        This is what makes the inclusive-lower-edge bucket rule coherent: the
        breakpoint is some firm's real market equity, and that firm belongs at
        or below it.
        """
        values = pd.Series([10.0, 25.0, 33.0, 47.0])
        bp = breakpoints_from_nyse(values, (50,))[0]
        assert bp in set(values)

    def test_method_is_overridable_and_the_choice_matters(self):
        """Guards the default against being a distinction without a difference."""
        values = pd.Series([1.0, 3.0])
        assert breakpoints_from_nyse(values, (50,), method="lower")[0] == pytest.approx(1.0)
        assert breakpoints_from_nyse(values, (50,), method="higher")[0] == pytest.approx(3.0)
        assert breakpoints_from_nyse(values, (50,), method="linear")[0] == pytest.approx(2.0)

    def test_breakpoints_are_monotone_in_percentile(self):
        values = pd.Series(np.arange(1, 201, dtype=float))
        out = breakpoints_from_nyse(values, tuple(range(5, 100, 5)))
        assert all(b >= a for a, b in zip(out, out[1:]))

    def test_empty_cross_section_raises(self):
        with pytest.raises(ValueError, match="empty"):
            breakpoints_from_nyse(pd.Series(dtype=float), (50,))
