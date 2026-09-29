"""
Book equity tests.

Every hierarchy fallback is exercised with a row that forces it, and every
expected value is computable by hand. That matters more here than elsewhere:
the fallbacks fire on 3.5% of real firm-years but on almost the entire 1950s,
so a broken branch would look fine on a modern sample and delete the early
history.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ffrep.construct.book_equity import (
    BALANCE_SHEET_FIELDS,
    accounting_year,
    book_equity,
    deferred_taxes,
    drop_empty_records,
    for_formation_year,
    investment,
    latest_fiscal_year,
    operating_profitability,
    preferred_stock,
    stockholders_equity,
)

NAN = np.nan


#: Fiscal year end used by default in these fixtures. Deliberately before the
#: measured 1992 deferred-tax cutoff, so the hierarchy tests exercise the full
#: SE + DT - PS formula; the cutoff itself gets its own tests.
DEFAULT_DATADATE = "1990-12-31"


def funda(datadate: str = DEFAULT_DATADATE, **columns) -> pd.DataFrame:
    """A funda frame with every field NaN unless named."""
    fields = (
        "seq", "ceq", "pstk", "at", "lt", "mib",
        "pstkrv", "pstkl", "txditc", "txdb", "itcb",
        "revt", "cogs", "xsga", "xint",
    )
    n = max((len(v) for v in columns.values()), default=1)
    frame = pd.DataFrame({f: [NAN] * n for f in fields})
    frame["datadate"] = pd.to_datetime([datadate] * n)
    for name, values in columns.items():
        frame[name] = values
    return frame


class TestStockholdersEquity:
    def test_prefers_seq(self):
        f = funda(seq=[100.0], ceq=[70.0], pstk=[10.0], at=[500.0], lt=[380.0])
        assert stockholders_equity(f).iloc[0] == pytest.approx(100.0)

    def test_falls_back_to_common_plus_preferred_par(self):
        f = funda(seq=[NAN], ceq=[70.0], pstk=[10.0], at=[500.0], lt=[380.0])
        assert stockholders_equity(f).iloc[0] == pytest.approx(80.0)

    def test_missing_preferred_par_does_not_void_the_ceq_branch(self):
        """
        A firm with common equity and no preferred stock line has no preferred
        stock, not unknown preferred stock. Treating the blank as NaN would push
        it down to AT - LT for no reason.
        """
        f = funda(seq=[NAN], ceq=[70.0], pstk=[NAN], at=[500.0], lt=[380.0])
        assert stockholders_equity(f).iloc[0] == pytest.approx(70.0)

    def test_falls_back_to_assets_minus_liabilities(self):
        f = funda(seq=[NAN], ceq=[NAN], at=[500.0], lt=[380.0])
        assert stockholders_equity(f).iloc[0] == pytest.approx(120.0)

    def test_nan_when_nothing_is_available(self):
        f = funda(seq=[NAN], ceq=[NAN], at=[NAN], lt=[NAN])
        assert np.isnan(stockholders_equity(f).iloc[0])

    def test_assets_without_liabilities_is_not_usable(self):
        f = funda(seq=[NAN], ceq=[NAN], at=[500.0], lt=[NAN])
        assert np.isnan(stockholders_equity(f).iloc[0])

    def test_hierarchy_is_row_by_row(self):
        f = funda(
            seq=[100.0, NAN, NAN],
            ceq=[NAN, 70.0, NAN],
            pstk=[NAN, 10.0, NAN],
            at=[NAN, NAN, 500.0],
            lt=[NAN, NAN, 380.0],
        )
        assert list(stockholders_equity(f)) == pytest.approx([100.0, 80.0, 120.0])


class TestPreferredStock:
    def test_redemption_first(self):
        f = funda(pstkrv=[30.0], pstkl=[25.0], pstk=[20.0])
        assert preferred_stock(f).iloc[0] == pytest.approx(30.0)

    def test_then_liquidation(self):
        f = funda(pstkrv=[NAN], pstkl=[25.0], pstk=[20.0])
        assert preferred_stock(f).iloc[0] == pytest.approx(25.0)

    def test_then_par(self):
        f = funda(pstkrv=[NAN], pstkl=[NAN], pstk=[20.0])
        assert preferred_stock(f).iloc[0] == pytest.approx(20.0)

    def test_all_missing_is_zero_by_default(self):
        f = funda(pstkrv=[NAN], pstkl=[NAN], pstk=[NAN])
        assert preferred_stock(f).iloc[0] == 0.0

    def test_all_missing_can_be_left_unknown(self):
        f = funda(pstkrv=[NAN], pstkl=[NAN], pstk=[NAN])
        assert np.isnan(preferred_stock(f, missing_as_zero=False).iloc[0])

    def test_zero_preferred_is_not_treated_as_missing(self):
        f = funda(pstkrv=[0.0], pstkl=[25.0])
        assert preferred_stock(f).iloc[0] == 0.0


class TestDeferredTaxes:
    def test_prefers_the_combined_field(self):
        f = funda(txditc=[15.0], txdb=[9.0], itcb=[3.0])
        assert deferred_taxes(f).iloc[0] == pytest.approx(15.0)

    def test_reconstructs_from_components(self):
        f = funda(txditc=[NAN], txdb=[9.0], itcb=[3.0])
        assert deferred_taxes(f).iloc[0] == pytest.approx(12.0)

    def test_one_component_is_enough(self):
        f = funda(txditc=[NAN], txdb=[9.0], itcb=[NAN])
        assert deferred_taxes(f).iloc[0] == pytest.approx(9.0)

    def test_reconstruction_can_be_switched_off(self):
        f = funda(txditc=[NAN], txdb=[9.0], itcb=[3.0])
        assert deferred_taxes(f, from_components=False).iloc[0] == 0.0

    def test_nothing_available_is_zero_not_missing(self):
        """
        "If available" makes deferred taxes an addition when present, not a
        precondition for book equity to exist. NaN here would delete every firm
        without a deferred tax balance.
        """
        f = funda(txditc=[NAN], txdb=[NAN], itcb=[NAN], seq=[100.0])
        assert deferred_taxes(f).iloc[0] == 0.0
        assert book_equity(f).iloc[0] == pytest.approx(100.0)


class TestDeferredTaxCutoff:
    """
    The one convention in this module that contradicts French's stated
    definition, and the only one derived from his output rather than his words.
    """

    def test_added_through_the_cutoff_fiscal_year(self):
        f = funda("1992-12-31", seq=[100.0], txditc=[15.0])
        assert deferred_taxes(f).iloc[0] == pytest.approx(15.0)
        assert book_equity(f).iloc[0] == pytest.approx(115.0)

    def test_dropped_the_fiscal_year_after(self):
        f = funda("1993-12-31", seq=[100.0], txditc=[15.0])
        assert deferred_taxes(f).iloc[0] == 0.0
        assert book_equity(f).iloc[0] == pytest.approx(100.0)

    def test_cutoff_is_on_the_fiscal_year_end_not_the_formation_year(self):
        """A June-1993 fiscal year end is after the cutoff even though it is
        used at the June-1994 formation, one year before a December-1993 one."""
        assert deferred_taxes(funda("1993-06-30", txditc=[15.0])).iloc[0] == 0.0
        assert deferred_taxes(funda("1992-06-30", txditc=[15.0])).iloc[0] == pytest.approx(15.0)

    def test_none_applies_the_term_to_the_whole_history(self):
        f = funda("2020-12-31", seq=[100.0], txditc=[15.0])
        assert book_equity(f, deferred_taxes_through=None).iloc[0] == pytest.approx(115.0)

    def test_a_cutoff_without_datadate_raises_rather_than_silently_lapsing(self):
        """
        Silently skipping the cutoff is an 8-percentage-point error against
        French's published breakpoints that leaves no trace in the output.
        """
        f = pd.DataFrame({"seq": [100.0], "txditc": [15.0]})
        with pytest.raises(KeyError, match="datadate"):
            deferred_taxes(f)

    def test_opting_out_needs_no_datadate(self):
        f = pd.DataFrame({"seq": [100.0], "txditc": [15.0]})
        assert deferred_taxes(f, through_fiscal_year=None).iloc[0] == pytest.approx(15.0)


class TestBookEquity:
    def test_the_whole_formula(self):
        """BE = SE + DT - PS = 100 + 15 - 30 = 85."""
        f = funda(seq=[100.0], txditc=[15.0], pstkrv=[30.0])
        assert book_equity(f).iloc[0] == pytest.approx(85.0)

    def test_through_every_fallback_at_once(self):
        """SE = 500 - 380 = 120; DT = 9 + 3 = 12; PS = 20 (par). BE = 112."""
        f = funda(at=[500.0], lt=[380.0], txdb=[9.0], itcb=[3.0], pstk=[20.0])
        assert book_equity(f).iloc[0] == pytest.approx(112.0)

    def test_nan_when_stockholders_equity_is_unavailable(self):
        f = funda(txditc=[15.0], pstkrv=[30.0])
        assert np.isnan(book_equity(f).iloc[0])

    def test_non_positive_book_equity_is_returned_not_dropped(self):
        """
        French publishes a count of BE <= 0 firms alongside the BE/ME
        breakpoints, so they have to survive measurement to be counted. The
        exclusion belongs to the sort.
        """
        f = funda(seq=[10.0], pstkrv=[40.0])
        assert book_equity(f).iloc[0] == pytest.approx(-30.0)

    def test_conventions_are_switchable(self):
        f = funda(seq=[100.0], txdb=[9.0])
        assert book_equity(f).iloc[0] == pytest.approx(109.0)
        assert book_equity(f, deferred_taxes_from_components=False).iloc[0] == pytest.approx(100.0)

    def test_preferred_convention_changes_only_the_all_missing_rows(self):
        f = funda(seq=[100.0, 100.0], pstkrv=[30.0, NAN])
        strict = book_equity(f, preferred_missing_as_zero=False)
        assert strict.iloc[0] == pytest.approx(70.0)
        assert np.isnan(strict.iloc[1])


class TestOperatingProfitability:
    def test_the_formula(self):
        """(1000 - 600 - 150 - 50) / 100 = 2.0."""
        f = funda(seq=[100.0], revt=[1000.0], cogs=[600.0], xsga=[150.0], xint=[50.0])
        assert operating_profitability(f).iloc[0] == pytest.approx(2.0)

    def test_missing_expense_items_count_as_zero(self):
        """(1000 - 600) / 100 = 4.0 when only COGS is reported."""
        f = funda(seq=[100.0], revt=[1000.0], cogs=[600.0])
        assert operating_profitability(f).iloc[0] == pytest.approx(4.0)

    def test_requires_at_least_one_expense_item(self):
        """
        Revenue alone would score as pure profit. French's "at least one of"
        clause exists precisely to refuse that row.
        """
        f = funda(seq=[100.0], revt=[1000.0])
        assert np.isnan(operating_profitability(f).iloc[0])

    def test_requires_revenue(self):
        f = funda(seq=[100.0], cogs=[600.0])
        assert np.isnan(operating_profitability(f).iloc[0])

    def test_non_positive_book_equity_gives_nan_not_a_sign_flip(self):
        f = funda(seq=[10.0], pstkrv=[40.0], revt=[1000.0], cogs=[600.0])
        assert np.isnan(operating_profitability(f).iloc[0])

    def test_accepts_a_precomputed_book_equity(self):
        f = funda(revt=[1000.0], cogs=[600.0])
        be = pd.Series([200.0], index=f.index)
        assert operating_profitability(f, be).iloc[0] == pytest.approx(2.0)

    def test_minority_interest_is_in_the_denominator(self):
        """Review R14: profit 50, BE 100, minority interest 100 -> 50/200 = 0.25."""
        f = funda(revt=[50.0], cogs=[0.0], mib=[100.0])
        be = pd.Series([100.0], index=f.index)
        assert operating_profitability(f, be).iloc[0] == pytest.approx(0.25)

    def test_minority_interest_can_be_left_out_for_ablation(self):
        f = funda(revt=[50.0], cogs=[0.0], mib=[100.0])
        be = pd.Series([100.0], index=f.index)
        assert operating_profitability(
            f, be, include_minority_interest=False
        ).iloc[0] == pytest.approx(0.50)

    def test_positive_minority_interest_does_not_rescue_negative_book_equity(self):
        """RMW's sample requires positive BE; BE -10 plus MI 100 is still out."""
        f = funda(revt=[50.0], cogs=[0.0], mib=[100.0])
        be = pd.Series([-10.0], index=f.index)
        assert np.isnan(operating_profitability(f, be).iloc[0])


class TestInvestment:
    def test_year_over_year_asset_growth(self):
        f = pd.DataFrame({
            "gvkey": ["A", "A"],
            "datadate": pd.to_datetime(["2019-12-31", "2020-12-31"]),
            "at": [100.0, 125.0],
        })
        assert list(investment(f)) == pytest.approx([NAN, 0.25], nan_ok=True)

    def test_first_record_of_a_firm_has_none(self):
        f = pd.DataFrame({
            "gvkey": ["A"], "datadate": pd.to_datetime(["2020-12-31"]), "at": [100.0],
        })
        assert np.isnan(investment(f).iloc[0])

    def test_does_not_borrow_the_previous_firms_assets(self):
        f = pd.DataFrame({
            "gvkey": ["A", "B"],
            "datadate": pd.to_datetime(["2020-12-31", "2020-12-31"]),
            "at": [100.0, 500.0],
        })
        assert investment(f).isna().all()

    def test_result_follows_the_input_order_not_the_sorted_order(self):
        f = pd.DataFrame({
            "gvkey": ["A", "A"],
            "datadate": pd.to_datetime(["2020-12-31", "2019-12-31"]),
            "at": [125.0, 100.0],
        }, index=[7, 3])
        out = investment(f)
        assert list(out.index) == [7, 3]
        assert out.loc[7] == pytest.approx(0.25)
        assert np.isnan(out.loc[3])

    def test_requires_consecutive_fiscal_years(self):
        """Assets 100 in 2020 and 200 in 2023 are not 100% annual investment."""
        f = pd.DataFrame({
            "gvkey": ["A", "A"],
            "datadate": pd.to_datetime(["2020-12-31", "2023-12-31"]),
            "at": [100.0, 200.0],
        })
        assert investment(f).isna().all()

    def test_consecutive_across_a_fiscal_year_end_change(self):
        """December 2019 to June 2020 is a consecutive accounting year."""
        f = pd.DataFrame({
            "gvkey": ["A", "A"],
            "datadate": pd.to_datetime(["2019-12-31", "2020-06-30"]),
            "at": [100.0, 110.0],
        })
        assert investment(f).iloc[1] == pytest.approx(0.10)

    def test_non_positive_prior_assets_yield_nan(self):
        f = pd.DataFrame({
            "gvkey": ["A", "A"],
            "datadate": pd.to_datetime(["2019-12-31", "2020-12-31"]),
            "at": [0.0, 125.0],
        })
        assert np.isnan(investment(f).iloc[1])


class TestDropEmptyRecords:
    def test_removes_rows_with_no_balance_sheet_data(self):
        f = funda(seq=[100.0, NAN], lt=[NAN, NAN])
        assert len(drop_empty_records(f)) == 1

    def test_any_one_field_is_enough_to_keep_a_row(self):
        for field in BALANCE_SHEET_FIELDS:
            f = funda(**{field: [5.0]})
            assert len(drop_empty_records(f)) == 1, field

    def test_a_row_with_only_income_statement_data_is_dropped(self):
        f = funda(revt=[1000.0], cogs=[600.0])
        assert drop_empty_records(f).empty


class TestMissingColumns:
    def test_a_field_absent_from_the_extract_behaves_as_missing(self):
        """
        A narrower extract (or an older Compustat vintage) may not carry every
        field. Raising KeyError would make the hierarchy brittle in exactly the
        situation it exists for; the field is simply unavailable.
        """
        f = pd.DataFrame({
            "seq": [100.0], "pstkrv": [30.0],
            "datadate": pd.to_datetime(["1990-12-31"]),
        })
        assert book_equity(f).iloc[0] == pytest.approx(70.0)

    def test_stockholders_equity_survives_a_missing_assets_column(self):
        f = pd.DataFrame({"seq": [100.0]})
        assert stockholders_equity(f).iloc[0] == pytest.approx(100.0)


class TestAccountingYear:
    def test_is_the_year_the_fiscal_year_ends(self):
        f = pd.DataFrame({"datadate": pd.to_datetime(["2020-05-31", "2020-12-31"])})
        assert list(accounting_year(f)) == [2020, 2020]

    def test_ignores_compustat_fyear(self):
        """
        Compustat labels a May-2020 fiscal year end fyear 2019. Following that
        would match it to the June-2020 formation, one month after the books
        closed — lookahead.
        """
        f = pd.DataFrame({
            "datadate": pd.to_datetime(["2020-05-31"]), "fyear": [2019.0],
        })
        assert accounting_year(f).iloc[0] == 2020


class TestLatestFiscalYear:
    def test_keeps_the_last_fiscal_year_end_in_a_calendar_year(self):
        f = pd.DataFrame({
            "gvkey": ["A", "A"],
            "datadate": pd.to_datetime(["1969-04-30", "1969-12-31"]),
            "seq": [187.9, 191.8],
        })
        out = latest_fiscal_year(f)
        assert len(out) == 1
        assert out["seq"].iloc[0] == pytest.approx(191.8)

    def test_keeps_one_record_per_firm_per_year(self):
        f = pd.DataFrame({
            "gvkey": ["A", "A", "B"],
            "datadate": pd.to_datetime(["2019-12-31", "2020-12-31", "2020-12-31"]),
            "seq": [1.0, 2.0, 3.0],
        })
        assert len(latest_fiscal_year(f)) == 3

    def test_adds_the_accounting_year_column(self):
        f = pd.DataFrame({
            "gvkey": ["A"], "datadate": pd.to_datetime(["2020-05-31"]), "seq": [1.0],
        })
        assert latest_fiscal_year(f)["accounting_year"].iloc[0] == 2020


class TestForFormationYear:
    def test_takes_the_fiscal_year_ending_the_year_before_formation(self):
        f = pd.DataFrame({
            "gvkey": ["A", "A", "A"],
            "datadate": pd.to_datetime(["2018-12-31", "2019-12-31", "2020-12-31"]),
            "seq": [1.0, 2.0, 3.0],
        })
        out = for_formation_year(f, 2020)
        assert len(out) == 1
        assert out["seq"].iloc[0] == pytest.approx(2.0)

    def test_a_may_fiscal_year_end_waits_thirteen_months(self):
        """
        FYE May 2019 belongs to accounting year 2019, so it is used at the June
        2020 formation, not June 2019.
        """
        f = pd.DataFrame({
            "gvkey": ["A"], "datadate": pd.to_datetime(["2019-05-31"]), "seq": [1.0],
        })
        assert for_formation_year(f, 2019).empty
        assert len(for_formation_year(f, 2020)) == 1

    def test_accepts_an_already_deduplicated_frame(self):
        f = latest_fiscal_year(pd.DataFrame({
            "gvkey": ["A"], "datadate": pd.to_datetime(["2019-12-31"]), "seq": [1.0],
        }))
        assert len(for_formation_year(f, 2020)) == 1

    def test_deduplicates_when_given_a_raw_frame(self):
        f = pd.DataFrame({
            "gvkey": ["A", "A"],
            "datadate": pd.to_datetime(["2019-04-30", "2019-12-31"]),
            "seq": [1.0, 2.0],
        })
        out = for_formation_year(f, 2020)
        assert len(out) == 1
        assert out["seq"].iloc[0] == pytest.approx(2.0)
