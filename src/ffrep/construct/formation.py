"""
The formation join: CRSP cross-sections + Compustat characteristics -> portfolios.

This is the seam the project log carried as open item 10. Everything upstream is
a validated component — the universe screen, the delisting adjustment, book
equity, the derived breakpoints — and everything downstream is the 2x3 algebra.
This module is what joins them, once a year at the end of June:

    June t        company cross-section: size, and the value weights
    December t-1  company cross-section: the BE/ME denominator
    FY ending t-1 Compustat: book equity, profitability, investment
                  (linked PERMCO -> GVKEY through ``links.resolve``)

then holds the resulting portfolios from July t to June t+1 with weights that
drift on ``retx`` (``portfolios.py``).

Each sort has its own sample, stated by French and followed literally
----------------------------------------------------------------------
"SMB, HML, RMW, and CMA for July of year t to June of t+1 include all NYSE,
AMEX, and NASDAQ stocks for which we have market equity data for December of
t-1 and June of t, (positive) book equity data for t-1 (for SMB, HML, and RMW),
non-missing revenues and at least one of the following: cost of goods sold,
selling, general and administrative expenses, or interest expense for t-1 (for
SMB and RMW), and total assets data for t-2 and t-1 (for SMB and CMA)."

So CMA does *not* require positive book equity, and every sort requires
December market equity even though only BE/ME uses it. Both are easy to get
wrong by writing one sample filter for all three sorts.

Conventions the published text leaves open
------------------------------------------
Gathered in ``Conventions`` as explicit switches rather than hardcoded, so the
gap attribution can ablate each one and report what it is worth, instead of
arguing about it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ffrep.config import (
    DEFERRED_TAX_LAST_FISCAL_YEAR,
    NYSE_EXCHANGE_CODES,
    SIZE_BREAKPOINT_PERCENTILE,
    VALUE_BREAKPOINT_PERCENTILES,
)
from ffrep.construct.book_equity import (
    book_equity,
    drop_empty_records,
    investment,
    latest_fiscal_year,
    operating_profitability,
)
from ffrep.construct.portfolios import drifted_weights, portfolio_returns
from ffrep.construct.sorts import breakpoints_from_nyse, size_bucket, value_bucket
from ffrep.universe.links import Resolution, resolve
from ffrep.universe.panel import company_cross_section, wide

#: The three annual 2x3 sorts and the characteristic each sorts on.
SORT_VARIABLES: dict[str, str] = {"beme": "beme", "op": "op", "inv": "inv"}


@dataclass(frozen=True)
class Conventions:
    """
    Every construction choice the published protocol does not pin down.

    ``min_compustat_years``
        Records a firm must have on Compustat, counting the one used. Fama and
        French (1993) required two, "to avoid the survival bias inherent in the
        way COMPUSTAT adds firms"; French's current web description states no
        such rule. 1 applies none.
    ``size_breakpoint_sample``
        ``"nyse"`` takes the median of every NYSE company in June — the
        population of French's published ``ME_Breakpoints``. ``"sort"`` takes
        it from the NYSE firms in each sort's own sample.
    ``deferred_taxes_through`` / ``op_minority_interest``
        The book-equity and profitability definitions, as in ``book_equity.py``.
    ``moody_book_equity``
        Fill book equity from French's hand-collected Moody's file where
        Compustat has none. French: book equity "is constructed from Compustat
        data or collected from the Moody's Industrial, Financial, and Utilities
        manuals". Only used when the build is given that file.
    """

    min_compustat_years: int = 1
    size_breakpoint_sample: str = "nyse"
    deferred_taxes_through: int | None = DEFERRED_TAX_LAST_FISCAL_YEAR
    op_minority_interest: bool = True
    moody_book_equity: bool = True

    def __post_init__(self) -> None:
        if self.size_breakpoint_sample not in ("nyse", "sort"):
            raise ValueError(f"size_breakpoint_sample must be 'nyse' or 'sort', got {self.size_breakpoint_sample!r}")
        if self.min_compustat_years < 1:
            raise ValueError("min_compustat_years counts the record used, so it is at least 1")


def annual_characteristics(funda: pd.DataFrame, conventions: Conventions = Conventions()) -> pd.DataFrame:
    """
    One row per (GVKEY, accounting year): BE, OP, INV and years on Compustat.

    ``accounting_year`` is the calendar year the fiscal year *ends* in, and the
    last such fiscal year end when a firm has two — see ``book_equity.py``.
    """
    annual = latest_fiscal_year(drop_empty_records(funda))
    annual = annual.sort_values(["gvkey", "datadate"]).reset_index(drop=True)
    annual["be"] = book_equity(annual, deferred_taxes_through=conventions.deferred_taxes_through)
    annual["op"] = operating_profitability(
        annual, annual["be"], include_minority_interest=conventions.op_minority_interest
    )
    annual["inv"] = investment(annual)
    annual["years_on_compustat"] = annual.groupby("gvkey").cumcount() + 1
    return annual[["gvkey", "accounting_year", "datadate", "be", "op", "inv", "years_on_compustat"]]


@dataclass
class Formation:
    """One June's cross-section, joined and ready to sort."""

    year: int
    frame: pd.DataFrame           # indexed by PERMCO
    nyse_june_me: pd.Series       # every NYSE company's June ME (the ME_Breakpoints population)
    resolution: Resolution
    samples: dict[str, pd.Index] = field(default_factory=dict)


def build_formation(
    year: int,
    panel: pd.DataFrame,
    candidates: pd.DataFrame,
    characteristics: pd.DataFrame,
    conventions: Conventions = Conventions(),
    moody: pd.DataFrame | None = None,
) -> Formation:
    """
    Join the June t and December t-1 cross-sections to fiscal-year t-1
    accounting, and define each sort's sample.

    ``moody`` is French's historical book equity (``permno``, ``year``,
    ``be``); where Compustat supplies no book equity, the value for the June
    formation year is taken for the company's primary security. The source of
    every book equity is recorded in ``be_source``.
    """
    june_month = pd.Period(f"{year}-06", "M")
    june = company_cross_section(panel, june_month).set_index("permco")
    december = company_cross_section(panel, pd.Period(f"{year - 1}-12", "M")).set_index("permco")
    nyse = company_cross_section(panel, june_month, exchanges=NYSE_EXCHANGE_CODES)

    frame = june[["permno", "me", "exchcd"] + (["siccd"] if "siccd" in june.columns else [])].copy()
    frame["me_dec"] = december["me"].reindex(frame.index)
    frame["nyse"] = frame["exchcd"].isin(NYSE_EXCHANGE_CODES)

    accounts = characteristics.loc[characteristics["accounting_year"] == year - 1].set_index("gvkey")
    resolution = resolve(candidates, frame["me"], accounts.index)
    frame["gvkey"] = resolution.links.reindex(frame.index)
    frame = frame.join(accounts[["be", "op", "inv", "years_on_compustat"]], on="gvkey")
    frame["be_source"] = np.where(frame["be"].notna(), "compustat", None)

    if moody is not None and conventions.moody_book_equity:
        available = moody.loc[moody["year"] == year].set_index("permno")["be"]
        filled = frame["be"].isna() & frame["permno"].isin(available.index)
        frame.loc[filled, "be"] = frame.loc[filled, "permno"].map(available)
        frame.loc[filled, "be_source"] = "moody"

    positive_be = frame["be"] > 0
    frame["beme"] = (frame["be"] / frame["me_dec"]).where(positive_be & (frame["me_dec"] > 0))

    # The Compustat-history rule guards against Compustat's backfill; it has no
    # meaning for a Moody's-only firm, which is admitted on its own record.
    seasoned = (frame["years_on_compustat"] >= conventions.min_compustat_years) | (frame["be_source"] == "moody")
    base = (frame["me"] > 0) & (frame["me_dec"] > 0) & seasoned
    samples = {
        "beme": frame.index[base & frame["beme"].notna()],
        "op": frame.index[base & positive_be & frame["op"].notna()],
        "inv": frame.index[base & frame["inv"].notna()],
    }
    return Formation(
        year=year,
        frame=frame,
        nyse_june_me=nyse.set_index("permco")["me"],
        resolution=resolution,
        samples=samples,
    )


@dataclass
class SortResult:
    """One 2x3 sort: assignments plus the breakpoints that produced them."""

    assignments: pd.DataFrame     # indexed by PERMCO: permno, me, value, portfolio
    size_breakpoint: float
    breakpoints: tuple[float, float]


def sort_2x3(
    formation: Formation,
    sort: str,
    conventions: Conventions = Conventions(),
    *,
    override: tuple[float, float, float] | None = None,
) -> SortResult:
    """
    Size x characteristic, on NYSE breakpoints applied to the sort's whole sample.

    Labels follow the generic ``SL`` ... ``BH`` layout of ``factors.py``: ``L``
    is the low 30% of the characteristic (growth, weak, conservative), ``H`` the
    high 30% (value, robust, aggressive).

    ``override`` supplies (size, p30, p70) from elsewhere — French's published
    breakpoint files — in place of the ones derived from our NYSE cross-section,
    which is how the attribution prices "derived versus borrowed" breakpoints.
    """
    variable = SORT_VARIABLES[sort]
    sample = formation.frame.loc[formation.samples[sort]]
    nyse_sample = sample[sample["nyse"]]

    if override is not None:
        size_bp, p30, p70 = override
    else:
        if conventions.size_breakpoint_sample == "nyse":
            size_bp = breakpoints_from_nyse(formation.nyse_june_me, (SIZE_BREAKPOINT_PERCENTILE,))[0]
        else:
            size_bp = breakpoints_from_nyse(nyse_sample["me"], (SIZE_BREAKPOINT_PERCENTILE,))[0]
        p30, p70 = breakpoints_from_nyse(nyse_sample[variable], VALUE_BREAKPOINT_PERCENTILES)

    out = pd.DataFrame({
        "permno": sample["permno"],
        "me": sample["me"],
        "value": sample[variable],
        "size": size_bucket(sample["me"], size_bp),
        "bucket": value_bucket(sample[variable], p30, p70),
    })
    out["portfolio"] = out["size"].astype(str) + out["bucket"].astype(str)
    return SortResult(assignments=out, size_breakpoint=size_bp, breakpoints=(p30, p70))


def holding_months(year: int) -> pd.PeriodIndex:
    """July of the formation year through June of the next: twelve months."""
    return pd.period_range(f"{year}-07", f"{year + 1}-06", freq="M")


def holding_returns(
    panel: pd.DataFrame, result: SortResult, year: int
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Value-weighted monthly returns of the six portfolios over the holding year,
    and the number of firms contributing to each month's return.
    """
    months = holding_months(year)
    members = result.assignments.set_index("permno")
    permnos = pd.Index(members.index.unique())
    ret = wide(panel, "ret", months, permnos)
    retx = wide(panel, "retx", months, permnos)

    returns = portfolio_returns(members, ret, retx)

    counts = {}
    for label, group in members.groupby("portfolio"):
        weights = drifted_weights(group["me"], retx)
        counts[label] = (weights.notna() & ret[weights.columns].notna()).sum(axis=1)
    return returns, pd.DataFrame(counts, index=months)


def run_annual_sorts(
    panel: pd.DataFrame,
    candidates: pd.DataFrame,
    characteristics: pd.DataFrame,
    years: range,
    conventions: Conventions = Conventions(),
    sorts: tuple[str, ...] = ("beme", "op", "inv"),
    *,
    breakpoints: dict | None = None,
    moody: pd.DataFrame | None = None,
) -> dict:
    """
    Every formation year in ``years``: portfolio returns, firm counts, and a
    per-year diagnostics table (sample sizes, breakpoints, link coverage).

    ``breakpoints`` optionally maps (year, sort) to (size, p30, p70) overrides;
    missing keys fall back to derived breakpoints.
    """
    returns = {s: [] for s in sorts}
    counts = {s: [] for s in sorts}
    diagnostics = []

    for year in years:
        formation = build_formation(year, panel, candidates, characteristics, conventions, moody)
        frame = formation.frame
        linked = frame["gvkey"].notna()
        row = {
            "year": year,
            "n_june": len(frame),
            "linked_by_count": float(linked.mean()) if len(frame) else np.nan,
            "linked_by_me": float(frame.loc[linked, "me"].sum() / frame["me"].sum()) if len(frame) else np.nan,
            "ambiguous_permcos": formation.resolution.ambiguous_permcos,
            "ambiguous_gvkeys": formation.resolution.ambiguous_gvkeys,
            "be_from_moody": int((frame["be_source"] == "moody").sum()),
            "nyse_median_me": float(np.quantile(formation.nyse_june_me, 0.5, method="lower")),
        }
        for sort in sorts:
            if len(formation.samples[sort]) == 0:
                continue
            override = (breakpoints or {}).get((year, sort))
            result = sort_2x3(formation, sort, conventions, override=override)
            r, c = holding_returns(panel, result, year)
            returns[sort].append(r)
            counts[sort].append(c)
            row[f"n_{sort}"] = len(result.assignments)
            row[f"{sort}_p30"], row[f"{sort}_p70"] = result.breakpoints
            row[f"{sort}_size_bp"] = result.size_breakpoint
        diagnostics.append(row)

    labels = ["SL", "SM", "SH", "BL", "BM", "BH"]
    out = {
        "returns": {s: pd.concat(v).reindex(columns=labels) for s, v in returns.items() if v},
        "counts": {s: pd.concat(v).reindex(columns=labels).fillna(0).astype(int) for s, v in counts.items() if v},
        "diagnostics": pd.DataFrame(diagnostics).set_index("year"),
    }
    return out
