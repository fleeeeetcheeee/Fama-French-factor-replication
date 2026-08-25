"""
Linker tests.

The CUSIP fallback is a permanent limitation of this replication, so its
behaviour is pinned rather than left to a merge call: truncation to 8
characters, determinism when a PERMNO reaches two GVKEYs, and a coverage
report that quotes both count and market-equity weight.
"""

from __future__ import annotations

import pandas as pd
import pytest

from ffrep.universe.linker import (
    CUSIP_MATCH_LENGTH,
    CcmLinker,
    CusipLinker,
    normalise_cusip,
)


class TestNormalise:
    def test_truncates_compustat_nine_to_crsp_eight(self):
        assert normalise_cusip(pd.Series(["123456789"])).iloc[0] == "12345678"

    def test_upper_cases_and_strips(self):
        assert normalise_cusip(pd.Series([" 00abc123 "])).iloc[0] == "00ABC123"

    def test_empty_becomes_missing(self):
        assert pd.isna(normalise_cusip(pd.Series([""])).iloc[0])

    def test_null_survives_as_null(self):
        assert pd.isna(normalise_cusip(pd.Series([None])).iloc[0])

    def test_match_length_is_the_issue_level_cusip(self):
        assert CUSIP_MATCH_LENGTH == 8


class TestCusipLinker:
    crsp = pd.DataFrame({
        "permno": [1, 2, 3],
        "cusip": ["12345678", "87654321", "99999999"],
        "me": [100.0, 50.0, 25.0],
    })
    comp = pd.DataFrame({"gvkey": ["A", "B"], "cusip": ["123456789", "876543210"]})

    def test_matches_across_the_length_difference(self):
        out = CusipLinker().link(self.crsp, self.comp)
        assert list(out["gvkey"])[:2] == ["A", "B"]

    def test_unmatched_is_null_not_dropped(self):
        """Losing the row would hide the gap this project exists to measure."""
        out = CusipLinker().link(self.crsp, self.comp)
        assert len(out) == 3
        assert pd.isna(out.set_index("permno").loc[3, "gvkey"])

    def test_historical_cusips_widen_the_match(self):
        hist = pd.DataFrame({"permno": [3], "cusip": ["99999999"], "ncusip": ["12345678"]})
        out = CusipLinker(historical=hist).link(self.crsp, self.comp)
        assert out.set_index("permno").loc[3, "gvkey"] == "A"

    def test_ambiguous_link_resolves_deterministically(self):
        hist = pd.DataFrame({"permno": [1, 1], "cusip": ["12345678", "87654321"],
                             "ncusip": [None, None]})
        a = CusipLinker(historical=hist).link(self.crsp, self.comp)
        b = CusipLinker(historical=hist).link(self.crsp.iloc[::-1].reset_index(drop=True), self.comp)
        assert a.set_index("permno").loc[1, "gvkey"] == b.set_index("permno").loc[1, "gvkey"]

    def test_one_row_per_permno_survives(self):
        hist = pd.DataFrame({"permno": [1, 1], "cusip": ["12345678", "87654321"],
                             "ncusip": [None, None]})
        out = CusipLinker(historical=hist).link(self.crsp, self.comp)
        assert out["permno"].is_unique

    def test_requires_a_cusip_column(self):
        with pytest.raises(KeyError, match="cusip"):
            CusipLinker().link(self.crsp.drop(columns=["cusip"]), self.comp)

    def test_is_named_for_traceability(self):
        assert CusipLinker().name == "cusip"


class TestCoverage:
    def test_count_and_weight_are_reported_separately(self):
        """
        They answer different questions and can differ by several points; a
        value-weighted factor cares about the second.
        """
        linked = pd.DataFrame({"gvkey": ["A", "B", None], "me": [100.0, 50.0, 25.0]})
        cov = CusipLinker().coverage(linked)
        assert cov["by_count"] == pytest.approx(2 / 3)
        assert cov["by_market_equity"] == pytest.approx(150 / 175)

    def test_weight_is_omitted_without_market_equity(self):
        cov = CusipLinker().coverage(pd.DataFrame({"gvkey": ["A", None]}))
        assert "by_market_equity" not in cov

    def test_zero_total_market_equity_does_not_divide_by_zero(self):
        cov = CusipLinker().coverage(pd.DataFrame({"gvkey": [None], "me": [0.0]}))
        assert cov["by_market_equity"] == 0.0


class TestCcmLinker:
    def test_raises_loudly_rather_than_degrading_silently(self):
        with pytest.raises(NotImplementedError, match="crsp_a_ccm"):
            CcmLinker().link(pd.DataFrame(), pd.DataFrame())

    def test_error_names_the_alternative_and_its_measured_cost(self):
        with pytest.raises(NotImplementedError, match="92.9%"):
            CcmLinker().link(pd.DataFrame(), pd.DataFrame())
