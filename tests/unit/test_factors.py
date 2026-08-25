"""
Factor algebra tests.

Simple arithmetic with conventions that are easy to get backwards: the 1/3 for
SMB against the 1/2 for HML, and the neutral portfolios appearing in one and
not the other.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ffrep.construct.factors import (
    PORTFOLIO_LABELS,
    build_2x3_factors,
    second_sort_factor,
    size_factor,
    value_factor,
)


def six(**overrides) -> pd.DataFrame:
    base = {"SL": 1.0, "SM": 2.0, "SH": 3.0, "BL": 4.0, "BM": 5.0, "BH": 6.0}
    base.update(overrides)
    return pd.DataFrame({k: [v] for k, v in base.items()})


class TestSizeFactor:
    def test_hand_computed(self):
        """(1+2+3)/3 - (4+5+6)/3 = 2 - 5 = -3."""
        assert size_factor(six()).iloc[0] == pytest.approx(-3.0)

    def test_uses_all_three_value_groups(self):
        """
        Changing only the neutral portfolios must move SMB. If it does not, the
        implementation is averaging the extremes and carries a value tilt.
        """
        assert size_factor(six(SM=99.0)).iloc[0] != pytest.approx(size_factor(six()).iloc[0])

    def test_is_value_neutral_by_construction(self):
        """Adding a constant to every value group leaves SMB unchanged."""
        shifted = six(SL=2.0, SM=3.0, SH=4.0, BL=5.0, BM=6.0, BH=7.0)
        assert size_factor(shifted).iloc[0] == pytest.approx(size_factor(six()).iloc[0])

    def test_named_for_downstream_joins(self):
        assert size_factor(six()).name == "SMB"


class TestValueFactor:
    def test_hand_computed(self):
        """(3+6)/2 - (1+4)/2 = 4.5 - 2.5 = 2."""
        assert value_factor(six()).iloc[0] == pytest.approx(2.0)

    def test_excludes_the_neutral_portfolios(self):
        """Changing only SM and BM must leave HML untouched."""
        assert value_factor(six(SM=99.0, BM=-99.0)).iloc[0] == pytest.approx(
            value_factor(six()).iloc[0]
        )

    def test_is_size_neutral_by_construction(self):
        """Adding a constant to both small portfolios leaves HML unchanged."""
        assert value_factor(six(SL=2.0, SH=4.0)).iloc[0] == pytest.approx(
            value_factor(six()).iloc[0]
        )

    def test_denominator_is_two_not_three(self):
        """
        The most common slip. With SH=SL=BH=BL=0 and the neutrals nonzero, a
        1/3-based HML would be nonzero; a correct one is exactly zero.
        """
        flat = six(SL=0.0, SH=0.0, BL=0.0, BH=0.0, SM=10.0, BM=10.0)
        assert value_factor(flat).iloc[0] == pytest.approx(0.0)

    def test_named_for_downstream_joins(self):
        assert value_factor(six()).name == "HML"


class TestSecondSortFactor:
    def test_reuses_the_high_minus_low_shape_under_a_new_name(self):
        out = second_sort_factor(six(), "RMW")
        assert out.name == "RMW"
        assert out.iloc[0] == pytest.approx(2.0)


class TestBuild:
    def test_returns_both_factors(self):
        out = build_2x3_factors(six())
        assert list(out.columns) == ["SMB", "HML"]
        assert out["SMB"].iloc[0] == pytest.approx(-3.0)
        assert out["HML"].iloc[0] == pytest.approx(2.0)

    @pytest.mark.parametrize("label", PORTFOLIO_LABELS)
    def test_missing_any_portfolio_raises_naming_it(self, label):
        with pytest.raises(KeyError, match=label):
            build_2x3_factors(six().drop(columns=[label]))

    def test_preserves_the_index(self):
        months = pd.period_range("2020-01", periods=1, freq="M")
        frame = six().set_index(months)
        assert list(build_2x3_factors(frame).index) == list(months)
