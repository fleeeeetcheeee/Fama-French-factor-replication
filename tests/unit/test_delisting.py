"""
Delisting-return tests.

The asymmetry is what matters: distress delistings are far more common than
triumphant ones, so an omission here biases the value leg specifically. These
tests pin the sign, the compounding, and the boundaries of the performance-code
range — an off-by-one at 519/520 or 584/585 changes which firms get -30%.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ffrep.config import PERFORMANCE_DELISTING_CODES, SHUMWAY_DELISTING_RETURN
from ffrep.universe.delisting import (
    apply_delisting_returns,
    compound_delisting,
    impute_delisting_return,
)


class TestImputation:
    def test_present_returns_are_never_overwritten(self):
        out = impute_delisting_return(pd.Series([-0.5, 0.2]), pd.Series([500, 574]))
        assert list(out) == pytest.approx([-0.5, 0.2])

    def test_zero_is_a_value_not_a_gap(self):
        """0.0 must survive; treating it as missing would silently apply -30%."""
        out = impute_delisting_return(pd.Series([0.0]), pd.Series([500]))
        assert out.iloc[0] == 0.0

    @pytest.mark.parametrize("code", [500, 520, 550, 584])
    def test_performance_codes_get_shumway(self, code):
        out = impute_delisting_return(pd.Series([np.nan]), pd.Series([code]))
        assert out.iloc[0] == pytest.approx(SHUMWAY_DELISTING_RETURN)

    @pytest.mark.parametrize("code", [100, 200, 300, 519, 585, 600])
    def test_non_performance_codes_get_zero(self, code):
        """Mergers and voluntary moves: the holder was generally made whole."""
        out = impute_delisting_return(pd.Series([np.nan]), pd.Series([code]))
        assert out.iloc[0] == 0.0

    def test_range_boundaries_are_exact(self):
        assert 519 not in PERFORMANCE_DELISTING_CODES
        assert 520 in PERFORMANCE_DELISTING_CODES
        assert 584 in PERFORMANCE_DELISTING_CODES
        assert 585 not in PERFORMANCE_DELISTING_CODES

    def test_missing_code_with_missing_return_is_not_penalised(self):
        out = impute_delisting_return(pd.Series([np.nan]), pd.Series([np.nan]))
        assert out.iloc[0] == 0.0

    def test_imputed_value_is_a_loss(self):
        assert SHUMWAY_DELISTING_RETURN < 0

    def test_input_is_not_mutated(self):
        dlret = pd.Series([np.nan, 0.1])
        impute_delisting_return(dlret, pd.Series([500, 200]))
        assert dlret.isna().iloc[0]


class TestCompounding:
    def test_compounds_rather_than_sums(self):
        """(1-0.5)(1-0.3)-1 = -0.65, not -0.80."""
        out = compound_delisting(pd.Series([-0.5]), pd.Series([-0.3]))
        assert out.iloc[0] == pytest.approx(-0.65)

    def test_missing_holding_return_yields_the_delisting_return(self):
        out = compound_delisting(pd.Series([np.nan]), pd.Series([-0.3]))
        assert out.iloc[0] == pytest.approx(-0.3)

    def test_missing_delisting_return_yields_the_holding_return(self):
        out = compound_delisting(pd.Series([0.1]), pd.Series([np.nan]))
        assert out.iloc[0] == pytest.approx(0.1)

    def test_both_missing_stays_missing(self):
        """0.0 here would be a fabricated observation, not a neutral one."""
        out = compound_delisting(pd.Series([np.nan]), pd.Series([np.nan]))
        assert pd.isna(out.iloc[0])

    def test_total_loss_is_representable(self):
        out = compound_delisting(pd.Series([0.05]), pd.Series([-1.0]))
        assert out.iloc[0] == pytest.approx(-1.0)


class TestApplyToPanel:
    def panel(self):
        return pd.DataFrame({
            "permno": [1, 2, 3],
            "date": [pd.Timestamp("2022-06-30")] * 3,
            "ret": [0.10, -0.50, 0.02],
        })

    def test_rows_without_an_event_are_untouched(self):
        events = pd.DataFrame({"permno": [2], "date": [pd.Timestamp("2022-06-30")],
                               "dlret": [np.nan], "dlstcd": [500]})
        out = apply_delisting_returns(self.panel(), events)
        assert out.set_index("permno").loc[1, "ret"] == pytest.approx(0.10)
        assert out.set_index("permno").loc[3, "ret"] == pytest.approx(0.02)

    def test_event_row_is_compounded_with_the_imputed_value(self):
        events = pd.DataFrame({"permno": [2], "date": [pd.Timestamp("2022-06-30")],
                               "dlret": [np.nan], "dlstcd": [500]})
        out = apply_delisting_returns(self.panel(), events)
        assert out.set_index("permno").loc[2, "ret"] == pytest.approx(0.5 * 0.7 - 1.0)

    def test_adjustment_stays_auditable(self):
        """dlret/dlstcd survive onto the output so the change can be traced."""
        events = pd.DataFrame({"permno": [2], "date": [pd.Timestamp("2022-06-30")],
                               "dlret": [np.nan], "dlstcd": [500]})
        out = apply_delisting_returns(self.panel(), events)
        row = out.set_index("permno").loc[2]
        assert row["dlret"] == pytest.approx(SHUMWAY_DELISTING_RETURN)
        assert row["dlstcd"] == 500

    def test_row_count_is_preserved(self):
        events = pd.DataFrame({"permno": [2], "date": [pd.Timestamp("2022-06-30")],
                               "dlret": [-0.2], "dlstcd": [574]})
        assert len(apply_delisting_returns(self.panel(), events)) == 3

    def test_no_events_at_all_is_a_no_op(self):
        events = pd.DataFrame({"permno": [], "date": [], "dlret": [], "dlstcd": []})
        out = apply_delisting_returns(self.panel(), events)
        assert list(out["ret"]) == pytest.approx([0.10, -0.50, 0.02])

    def test_event_on_a_different_date_does_not_apply(self):
        events = pd.DataFrame({"permno": [2], "date": [pd.Timestamp("2022-07-29")],
                               "dlret": [np.nan], "dlstcd": [500]})
        out = apply_delisting_returns(self.panel(), events)
        assert out.set_index("permno").loc[2, "ret"] == pytest.approx(-0.50)

    def test_requires_a_ret_column(self):
        with pytest.raises(KeyError, match="ret"):
            apply_delisting_returns(
                self.panel().drop(columns=["ret"]),
                pd.DataFrame({"permno": [], "date": [], "dlret": [], "dlstcd": []}),
            )
