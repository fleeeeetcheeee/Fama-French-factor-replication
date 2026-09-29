"""
Fama-French book equity, operating profitability and investment from Compustat.

Book equity is the numerator of BE/ME and the denominator of operating
profitability, so an error here lands on HML and RMW at the same time. It is
also the single most convention-laden quantity in the whole replication: the
published definition is three nested fallback hierarchies stated in one English
sentence, and every implementation choice inside it is invisible in the output.

The definition, as Davis, Fama and French (2000) state it
---------------------------------------------------------
"Book equity is stockholders' equity, plus balance sheet deferred taxes and
investment tax credit (if available), minus the book value of preferred stock.
Depending on availability, we use the redemption, liquidation, or par value (in
that order) to estimate the book value of preferred stock. Stockholders' equity
is the value reported by Moody's or COMPUSTAT, if it is available. If not, we
measure stockholders' equity as the book value of common equity plus the par
value of preferred stock, or the book value of assets minus total liabilities
(in that order)."

Which is::

    BE = SE + DT - PS

    SE = SEQ,  else CEQ + PSTK,  else AT - LT
    PS = PSTKRV,  else PSTKL,  else PSTK
    DT = TXDITC

How often each fallback actually fires, measured on this subscription's
``comp.funda`` (443,461 firm-years with any balance-sheet data, 1950-2026):

    SE = SEQ            95.79%          PS = PSTKRV      99.19%
    SE = CEQ + PSTK      0.74%          PS = PSTKL        0.12%
    SE = AT - LT         2.57%          PS = PSTK         0.51%
    SE unavailable       0.89%          PS unavailable    0.19%

The hierarchies look like defensive padding at those rates and are not. In the
1950s ``seq`` is missing on 98.7% of rows and ``at``/``lt`` on 0.4%/31.2%, so
``AT - LT`` carries essentially the entire decade; by 1970 ``seq`` is missing on
3.3%. Dropping the hierarchy would not degrade the early sample, it would delete
it.

Two conventions the published sentence does not settle
-------------------------------------------------------
Both are exposed as keyword arguments rather than hardcoded, so step 5 can
ablate them instead of arguing about them:

``deferred_taxes_from_components``
    "if available" is doing quiet work. ``TXDITC`` is missing on 9.7% of
    non-blank rows, and on 22,147 of those ``TXDB`` (deferred taxes) or ``ITCB``
    (investment tax credit) is present separately — which is exactly the sum
    ``TXDITC`` is meant to be. Reconstructing it uses the data French's sentence
    names; refusing to reconstruct it takes his sentence to mean the single
    field. Default is to reconstruct.

``preferred_missing_as_zero``
    When all three preferred-stock fields are missing, PS can be treated as
    zero (assume no preferred) or the firm can be dropped. This affects 824
    firm-years, 0.19%. The default is zero, matching the widely used WRDS
    sample program; the cost is that a firm with preferred stock and no
    reported par value gets an overstated BE.

The deferred tax term stops in 1993 — documented in his change notes
-------------------------------------------------------------------
His definition carries no date qualifier and his variable-definitions page
states none; his data-library change notes do (August 2016: deferred taxes are
no longer added "for fiscal years ending in 1993 or later", citing FASB 109).
This project first found the break in his published breakpoints and recorded
it as undocumented, which was wrong — corrected 2026-09-28. The measurement
below is independent confirmation of the documented rule. Adding deferred taxes fits formation
years through 1993 (mean absolute error 1.0-1.9% across every published
percentile) and misses badly after (8.7%); dropping them inverts that exactly.
Scanning the cutoff gives a clean single minimum at fiscal years ending 1992 —
see ``config.DEFERRED_TAX_LAST_FISCAL_YEAR`` for the table.

With the cutoff in place the whole 1975-2024 span comes in at 1.08% mean
absolute error and a median bias of -0.22%. The residual is dominated by the
CUSIP linkage, not by this: the years where linkage is near-complete (2016-2024,
match rate 97-98%) run at 0.6-1.6%, while 1963-1971 — where Compustat covers
55-78% of NYSE and French adds hand-collected Moody's book equity — run at
4-13%. (French publishes that Moody's file; ``reference/historical_be.py``
reads it and the formation join uses it where Compustat has no value.)

The reason is French's own: FASB 109 changed the treatment of deferred taxes
for fiscal years beginning after 15 December 1992, which is exactly where the
break lands in the data.

Minority interest (``MIB``) is not part of *book equity*: the published
definition does not mention it. It is part of the *operating-profitability
denominator* — French's August 2018 change note: "We now include minority
interest in the denominator" — so ``operating_profitability`` adds it there.

Which calendar year an annual record belongs to
------------------------------------------------
``datadate.year``, not Compustat's ``fyear``. They disagree on 13.3% of rows —
every fiscal year ending January through May, which Compustat labels with the
*previous* calendar year. French's rule is stated as "the fiscal year ending in
calendar year t-1", which is the year of the end date. The distinction is not
cosmetic in either direction: using ``fyear`` would match a May-1990 fiscal year
to a June-1990 formation, one month after the fiscal year closed and months
before the annual report existed. That is lookahead, of the same kind Project 01
exists to prevent.

A firm can have two fiscal year ends in one calendar year (900 such cases here,
from fiscal-calendar changes). French's wording says the *last* one.

A pandas trap
-------------
Compustat's total-assets field is named ``at``, which collides with
``DataFrame.at``, the scalar indexer. ``frame.at`` silently returns the indexer
rather than the column and fails later with an unrelated-looking
``AttributeError``. Every access in this module is ``frame["at"]``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ffrep.config import DEFERRED_TAX_LAST_FISCAL_YEAR

#: Fields that must all be missing for a Compustat row to carry no book-equity
#: information at all. 16.1% of ``INDL``/``STD`` rows are empty like this — they
#: are placeholder firm-years, not financial-format filers: only 32 of 85,112
#: have a populated ``indfmt='FS'`` row at the same gvkey and date.
BALANCE_SHEET_FIELDS: tuple[str, ...] = ("seq", "ceq", "at", "lt")

#: Components of operating profitability that are treated as zero when missing.
#: Revenue is not among them: French requires non-missing revenue and at least
#: one of these three.
PROFITABILITY_COMPONENTS: tuple[str, ...] = ("cogs", "xsga", "xint")


def _col(funda: pd.DataFrame, name: str) -> pd.Series:
    """A numeric column, or an all-NaN series if the extract omitted it."""
    if name not in funda.columns:
        return pd.Series(np.nan, index=funda.index, dtype=float)
    return pd.to_numeric(funda[name], errors="coerce")


def drop_empty_records(funda: pd.DataFrame) -> pd.DataFrame:
    """
    Remove firm-years with no balance-sheet data whatsoever.

    Done *before* the one-record-per-year selection rather than after. A blank
    row with a later ``datadate`` would otherwise win the "last fiscal year end
    in the calendar year" tie-break and displace a populated one, turning a
    usable firm-year into a missing one for reasons no downstream check would
    surface.
    """
    present = pd.concat([_col(funda, f).notna() for f in BALANCE_SHEET_FIELDS], axis=1)
    return funda.loc[present.any(axis=1)].copy()


def stockholders_equity(funda: pd.DataFrame) -> pd.Series:
    """
    SE, by French's hierarchy: ``SEQ``, else ``CEQ + PSTK``, else ``AT - LT``.

    The order is not arbitrary. ``SEQ`` is the reported total. ``CEQ + PSTK``
    rebuilds it from common equity plus preferred at par. ``AT - LT`` is the
    accounting identity and the last resort, because it silently absorbs
    minority interest and anything else sitting between liabilities and equity.
    """
    seq = _col(funda, "seq")
    ceq = _col(funda, "ceq")
    pstk = _col(funda, "pstk")
    total_assets = _col(funda, "at")
    liabilities = _col(funda, "lt")

    # CEQ + PSTK, but PSTK missing means "no preferred at par", not "unknown":
    # a firm with common equity and no preferred stock line should still get a
    # value here rather than falling through to AT - LT.
    ceq_branch = ceq + pstk.fillna(0.0)
    ceq_branch = ceq_branch.where(ceq.notna())

    at_lt_branch = total_assets - liabilities

    return seq.fillna(ceq_branch).fillna(at_lt_branch).rename("se")


def preferred_stock(
    funda: pd.DataFrame, *, missing_as_zero: bool = True
) -> pd.Series:
    """
    PS, by French's hierarchy: redemption, then liquidation, then par value.

    The order runs from the value the firm would actually have to pay to retire
    the preferred down to its nominal par, which is the most conservative
    estimate of what is owed to preferred holders and therefore not common
    equity.
    """
    ps = (
        _col(funda, "pstkrv")
        .fillna(_col(funda, "pstkl"))
        .fillna(_col(funda, "pstk"))
    )
    if missing_as_zero:
        ps = ps.fillna(0.0)
    return ps.rename("ps")


def deferred_taxes(
    funda: pd.DataFrame,
    *,
    from_components: bool = True,
    through_fiscal_year: int | None = DEFERRED_TAX_LAST_FISCAL_YEAR,
) -> pd.Series:
    """
    DT: balance sheet deferred taxes and investment tax credit, "if available".

    ``TXDITC`` is the combined field. When it is missing but ``TXDB`` or
    ``ITCB`` is present, ``from_components`` reconstructs the sum — the two
    components *are* what the combined field combines. Either way a firm with
    none of the three gets zero, not NaN: "if available" makes the term an
    addition when it exists rather than a requirement for BE to exist at all,
    and treating it as a requirement would delete every firm-year without a
    deferred tax balance.

    ``through_fiscal_year`` zeroes the term for fiscal years ending after it.
    That is not in French's stated definition; it is in his published numbers,
    and the default is the fiscal year the break was measured at. ``None``
    applies the term to the whole history, which is what the stated definition
    literally says and what the breakpoints reject from 1994 on.

    Applying a cutoff needs a ``datadate`` column, and its absence raises rather
    than silently defaulting to "add everywhere" — a silently un-applied cutoff
    is an 8-percentage-point error that leaves no trace.
    """
    dt = _col(funda, "txditc")
    if from_components:
        components = _col(funda, "txdb").fillna(0.0) + _col(funda, "itcb").fillna(0.0)
        available = _col(funda, "txdb").notna() | _col(funda, "itcb").notna()
        dt = dt.fillna(components.where(available))
    dt = dt.fillna(0.0)

    if through_fiscal_year is not None:
        if "datadate" not in funda.columns:
            raise KeyError(
                "deferred_taxes needs a 'datadate' column to apply the "
                f"through_fiscal_year={through_fiscal_year} cutoff; pass "
                "through_fiscal_year=None to add deferred taxes everywhere"
            )
        dt = dt.where(accounting_year(funda) <= through_fiscal_year, 0.0)

    return dt.rename("dt")


def book_equity(
    funda: pd.DataFrame,
    *,
    deferred_taxes_from_components: bool = True,
    deferred_taxes_through: int | None = DEFERRED_TAX_LAST_FISCAL_YEAR,
    preferred_missing_as_zero: bool = True,
) -> pd.Series:
    """
    ``BE = SE + DT - PS``, in $ millions, NaN where SE cannot be determined.

    Non-positive values are returned as-is rather than dropped. They are real —
    French publishes a count of them alongside the BE/ME breakpoints — and the
    exclusion belongs to the *sort*, in ``sorts.book_to_market``, not to the
    measurement. Dropping them here would make that published count
    unreproducible and hide a genuine check on this function.
    """
    se = stockholders_equity(funda)
    dt = deferred_taxes(
        funda,
        from_components=deferred_taxes_from_components,
        through_fiscal_year=deferred_taxes_through,
    )
    ps = preferred_stock(funda, missing_as_zero=preferred_missing_as_zero)
    return (se + dt - ps).rename("be")


def operating_profitability(
    funda: pd.DataFrame,
    book_equity_values: pd.Series | None = None,
    *,
    include_minority_interest: bool = True,
) -> pd.Series:
    """
    ``(REVT - COGS - XSGA - XINT) / (BE + MIB)``, the RMW sort variable.

    The denominator is book equity **plus minority interest**. French's August
    2018 change note: "We now include minority interest in the denominator", and
    his variable definitions now read "divided by the sum of book equity and
    minority interest". An earlier version divided by BE alone while pulling
    ``MIB`` and not using it — profit 50, BE 100 and minority interest 100 came
    out at 0.50 rather than 0.25 (review finding R14). Missing ``MIB`` counts as
    zero: most firms have no minority interest and Compustat leaves it blank.
    ``include_minority_interest=False`` restores the pre-2018 definition for
    ablation.

    French's data requirement is specific and asymmetric: revenue must be
    present, and *at least one* of the three expense items must be present.
    Missing items among those three are then treated as zero. A firm reporting
    revenue and nothing else would otherwise be scored as pure profit, which is
    why the "at least one" clause exists rather than a blanket fillna.

    Book equity must be positive — RMW's sample requires "(positive) book equity
    data for t-1" — and so must the denominator; otherwise the result is NaN
    rather than a sign-flipped profitability.
    """
    be = book_equity(funda) if book_equity_values is None else book_equity_values
    revenue = _col(funda, "revt")

    components = [_col(funda, name) for name in PROFITABILITY_COMPONENTS]
    any_component = pd.concat([c.notna() for c in components], axis=1).any(axis=1)
    expenses = sum(c.fillna(0.0) for c in components)

    profit = revenue - expenses
    profit = profit.where(revenue.notna() & any_component)

    minority = _col(funda, "mib").fillna(0.0) if include_minority_interest else 0.0
    denominator = be + minority
    denominator = denominator.where((be > 0) & (denominator > 0))
    return (profit / denominator).rename("op")


def investment(funda: pd.DataFrame, *, id_column: str = "gvkey") -> pd.Series:
    """
    Year-over-year growth in total assets, the CMA sort variable.

    ``(AT_t-1 - AT_t-2) / AT_t-2`` in French's notation: "the change in total
    assets from the fiscal year ending in year t-2 to the fiscal year ending in
    t-1, divided by t-2 total assets".

    The two records must be **consecutive fiscal years** — the previous record's
    accounting year exactly one less. A firm whose coverage skips a year does not
    get a growth rate: assets of 100 in 2020 and 200 in 2023 are 100% growth over
    three years, not one, and scoring it as annual investment puts the firm in
    the wrong CMA bucket. Expects one record per firm per accounting year
    (``latest_fiscal_year``); two in the same year are not consecutive either.
    """
    ordered = funda.sort_values([id_column, "datadate"])
    total_assets = _col(ordered, "at")
    year = accounting_year(ordered)
    grouped = ordered[id_column]
    previous = total_assets.groupby(grouped).shift(1)
    consecutive = (year - year.groupby(grouped).shift(1)) == 1
    growth = (total_assets - previous) / previous.where((previous > 0) & consecutive)
    return growth.reindex(funda.index).rename("inv")


def accounting_year(funda: pd.DataFrame) -> pd.Series:
    """
    The calendar year each fiscal year *ends* in — ``datadate.year``.

    Not ``fyear``. See the module docstring: they disagree on every January-to-
    May fiscal year end, 13.3% of rows, and ``fyear`` would introduce lookahead.
    """
    return pd.to_datetime(funda["datadate"]).dt.year.rename("accounting_year")


def latest_fiscal_year(
    funda: pd.DataFrame, *, id_column: str = "gvkey"
) -> pd.DataFrame:
    """
    One record per firm per calendar year: the last fiscal year end in it.

    French's wording is "the fiscal year ending in calendar year t-1", and 900
    firm-years here have two, from companies changing their fiscal calendar.
    Taking the last is both what the wording says and the only choice that does
    not use a superseded balance sheet.
    """
    out = funda.copy()
    out["accounting_year"] = accounting_year(out)
    out = out.sort_values([id_column, "accounting_year", "datadate"])
    return out.drop_duplicates(subset=[id_column, "accounting_year"], keep="last")


def for_formation_year(
    annual: pd.DataFrame, formation_year: int, *, id_column: str = "gvkey"
) -> pd.DataFrame:
    """
    The accounting records used to form portfolios in June of ``formation_year``.

    Which is the fiscal year ending in the calendar year before it. Because the
    latest such fiscal year end is December 31 of t-1, this rule guarantees at
    least the six-month gap in ``config.MIN_MONTHS_BETWEEN_FYE_AND_FORMATION``
    — that constant describes the consequence of this rule rather than imposing
    a second filter on top of it.
    """
    if "accounting_year" not in annual.columns:
        annual = latest_fiscal_year(annual, id_column=id_column)
    return annual.loc[annual["accounting_year"] == formation_year - 1].copy()
