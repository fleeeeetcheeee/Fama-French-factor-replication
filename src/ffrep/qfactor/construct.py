"""
The Hou-Xue-Zhang q-factors from a monthly 2 x 3 x 3 sort.

From the global-q.org technical document (July 2026):

    size    NYSE median market equity, end of June of year t, held for a year
    I/A     annual change in total assets over lagged assets, fiscal year
            ending in t-1; NYSE 30th/70th percentiles, end of June, held a year
    ROE     most recently announced quarterly earnings over one-quarter-lagged
            book equity; NYSE 30th/70th percentiles, re-sorted every month

"Taking the intersections of the two size, three I/A, and three Roe groups, we
form 18 portfolios. Monthly value-weighted portfolio returns are calculated for
the current month, and the portfolios are rebalanced monthly." The sample
excludes financial firms (SIC 6000-6999) and firms with negative book equity;
the market factor excludes neither.

    R_ME  = mean of the 9 small portfolios  - mean of the 9 big
    R_IA  = mean of the 6 low-I/A portfolios - mean of the 6 high-I/A
    R_ROE = mean of the 6 high-ROE portfolios - mean of the 6 low-ROE

Two differences from the FF sorts are worth naming because they are easy to
carry over by habit: the sorts are *independent* three-way intersections, and
the value weights are last month's market equity every month (a monthly
rebalance), not June weights drifted through the year.

Portfolios are labelled ``"{size}{ia}{roe}"`` with global-q's ascending ranks —
``"132"`` is small, high-I/A, middle-ROE — so they compare directly against the
published benchmark portfolios.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ffrep.config import NYSE_EXCHANGE_CODES, VALUE_BREAKPOINT_PERCENTILES
from ffrep.construct.formation import build_formation, holding_months
from ffrep.construct.sorts import assign_bucket, breakpoints_from_nyse
from ffrep.qfactor.quarterly import roe_as_of

#: Financial firms, excluded from the q-factor sample.
FINANCIAL_SIC = (6000, 6999)

LABELS: tuple[str, ...] = tuple(f"{s}{i}{r}" for s in "12" for i in "123" for r in "123")


def _terciles(values: pd.Series, nyse: pd.Series) -> pd.Series:
    p30, p70 = breakpoints_from_nyse(values[nyse], VALUE_BREAKPOINT_PERCENTILES)
    return assign_bucket(values, (p30, p70), ("1", "2", "3"))


@dataclass(frozen=True)
class QConventions:
    """
    Choices the global-q document leaves open, as switches the build can ablate.

    ``size_breakpoint_sample``
        ``"sample"`` takes the NYSE median from the NYSE firms in the q-factor
        sample (non-financial, positive book equity, with I/A); ``"nyse"`` from
        every NYSE company, the population of French's size breakpoint. HXZ:
        "we use the median NYSE market equity to split NYSE, Amex, and NASDAQ
        stocks" — either reading fits the sentence.
    ``annual_be_screen``
        Apply the negative-book-equity exclusion to annual book equity for the
        fiscal year ending in t-1. The ROE sort separately requires positive
        lagged quarterly book equity, so ``False`` still excludes firms whose
        quarterly book equity is negative.
    """

    size_breakpoint_sample: str = "sample"
    annual_be_screen: bool = True

    def __post_init__(self) -> None:
        if self.size_breakpoint_sample not in ("sample", "nyse"):
            raise ValueError(f"size_breakpoint_sample must be 'sample' or 'nyse', got {self.size_breakpoint_sample!r}")


def annual_groups(formation, conventions: QConventions = QConventions()) -> pd.DataFrame:
    """
    Size and I/A groups for the year, from the June formation cross-section.

    Sample: positive June ME, non-missing I/A, not a financial firm, and — with
    ``annual_be_screen`` — positive book equity. The I/A breakpoints come from
    the NYSE firms in that sample; the size breakpoint per
    ``conventions.size_breakpoint_sample``.
    """
    frame = formation.frame
    sic = pd.to_numeric(frame.get("siccd"), errors="coerce")
    financial = sic.between(*FINANCIAL_SIC)
    keep = (frame["me"] > 0) & frame["inv"].notna() & ~financial
    if conventions.annual_be_screen:
        keep &= frame["be"] > 0
    sample = frame[keep]
    nyse = sample["nyse"]
    if nyse.sum() < 10:
        return pd.DataFrame(columns=["gvkey", "size", "ia"])
    size_population = sample.loc[nyse, "me"] if conventions.size_breakpoint_sample == "sample" else formation.nyse_june_me
    size_bp = breakpoints_from_nyse(size_population, (50,))[0]
    return pd.DataFrame({
        "gvkey": sample["gvkey"],
        "size": assign_bucket(sample["me"], (size_bp,), ("1", "2")),
        "ia": _terciles(sample["inv"], nyse),
    })


def q_portfolios(
    panel: pd.DataFrame,
    companies: pd.DataFrame,
    candidates: pd.DataFrame,
    characteristics: pd.DataFrame,
    roe: pd.DataFrame,
    years: range,
    conventions: QConventions = QConventions(),
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    The 18 benchmark portfolios, months x ``LABELS``: returns and firm counts.

    ``companies`` is the screened company panel (``monthly.company_panel``),
    which supplies each month's ME weights and exchange; ``roe`` is the output
    of ``quarterly.quarterly_roe``.
    """
    ret_lookup = panel.set_index(["permno", "month"])["ret"]
    by_month = {m: g.set_index("permco") for m, g in companies.groupby("month")}
    rets, cnts = {}, {}

    for year in years:
        groups = annual_groups(build_formation(year, panel, candidates, characteristics), conventions)
        if groups.empty:
            continue
        months = holding_months(year)
        requests = []
        for t in months:
            cs = by_month.get(t - 1)
            if cs is None:
                continue
            members = groups.join(cs[["permno", "me", "exchcd"]], how="inner")
            members = members[members["me"] > 0]
            requests.append(members.assign(month=t - 1, t=t))
        if not requests:
            continue
        stacked = pd.concat(requests)
        stacked["roe"] = roe_as_of(roe, stacked[["gvkey", "month"]]).to_numpy()
        stacked = stacked[stacked["roe"].notna()]
        keys = pd.MultiIndex.from_arrays([stacked["permno"], stacked["t"]])
        stacked["ret"] = ret_lookup.reindex(keys).to_numpy()

        for t, month in stacked.groupby("t"):
            nyse = month["exchcd"].isin(NYSE_EXCHANGE_CODES)
            if nyse.sum() < 10:
                continue
            label = month["size"] + month["ia"] + _terciles(month["roe"], nyse)
            held = month.assign(label=label)
            held = held[held["ret"].notna()]
            if held.empty:
                continue
            weight = held.groupby("label")["me"].sum()
            rets[t] = (held["me"] * held["ret"]).groupby(held["label"]).sum() / weight
            cnts[t] = held.groupby("label").size()

    returns = pd.DataFrame(rets).T.reindex(columns=list(LABELS)).sort_index()
    counts = pd.DataFrame(cnts).T.reindex(columns=list(LABELS)).fillna(0).astype(int).sort_index()
    returns.index.name = counts.index.name = "month"
    return returns, counts


def q_factors(portfolios: pd.DataFrame) -> pd.DataFrame:
    """
    R_ME, R_IA and R_ROE from the 18 portfolios. A month missing any
    constituent portfolio has no factor return (the same no-reweighting rule as
    ``factors.py``).
    """
    def leg(predicate) -> pd.Series:
        cols = [c for c in LABELS if predicate(c)]
        return portfolios[cols].mean(axis=1, skipna=False)

    return pd.DataFrame({
        "ME": leg(lambda c: c[0] == "1") - leg(lambda c: c[0] == "2"),
        "IA": leg(lambda c: c[1] == "1") - leg(lambda c: c[1] == "3"),
        "ROE": leg(lambda c: c[2] == "3") - leg(lambda c: c[2] == "1"),
    })
