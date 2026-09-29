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
    assign_bucket,
    breakpoints_from_nyse,
    nyse_size_breakpoint,
    nyse_value_breakpoints,
    size_bucket,
    value_bucket,
)


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
