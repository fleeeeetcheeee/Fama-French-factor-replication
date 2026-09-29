"""
The monthly-rebalanced factors: momentum (UMD) and the market (Rm).

Unlike the June sorts these are re-formed every month, so they are built
vectorised over the whole panel rather than one formation at a time.

Momentum, as French states it
-----------------------------
"The portfolios, which are formed monthly, are the intersections of 2 portfolios
formed on size (market equity, ME) and 3 portfolios formed on prior (2-12)
return. The monthly size breakpoint is the median NYSE market equity. The
monthly prior (2-12) return breakpoints are the 30th and 70th NYSE percentiles.
... To be included in a portfolio for month t (formed at the end of month t-1),
a stock must have a price for the end of month t-13 and a good return for t-2.
In addition, any missing returns from t-12 to t-3 must be -99.0, CRSP's code for
a missing price. Each included stock also must have ME for the end of month t-1."

The prior return is the compounded return over t-12 .. t-2 — eleven months,
skipping t-1, whose short-term reversal would otherwise contaminate the signal.

The -99 rule, approximated and said so
--------------------------------------
CRSP distinguishes *why* a return is missing: -99 means the price was missing
that month (the next return then spans both months, so compounding the returns
that exist is still exact), while -66/-77/-88 mean the security was not
properly trading. WRDS's Postgres ``msf`` stores all of them as NULL. The rule
is therefore approximated from what survives: a missing return is allowed when
the security *has* a row that month with a missing price (the -99 situation),
and disqualifying when the security has no row at all (not listed then).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ffrep.config import (
    LISTED_EXCHANGE_CODES,
    MOMENTUM_LOOKBACK_MONTHS,
    MOMENTUM_SKIP_MONTHS,
    NYSE_EXCHANGE_CODES,
    SIZE_BREAKPOINT_PERCENTILE,
    VALUE_BREAKPOINT_PERCENTILES,
)
from ffrep.construct.sorts import breakpoints_from_nyse, size_bucket, value_bucket
from ffrep.universe.screen import aggregate_to_company, apply_share_screen

#: Months in the prior-return window: t-12 .. t-2 inclusive.
PRIOR_WINDOW = MOMENTUM_LOOKBACK_MONTHS - MOMENTUM_SKIP_MONTHS


def company_panel(panel: pd.DataFrame, exchanges: tuple[int, ...] = LISTED_EXCHANGE_CODES) -> pd.DataFrame:
    """
    Every month's screened company cross-section at once.

    Equivalent to calling ``company_cross_section`` month by month, because
    ``msf`` stamps every security in a month with the same trading date — so
    aggregating on (date, PERMCO) is aggregating on (month, PERMCO).
    """
    return aggregate_to_company(apply_share_screen(panel, exchanges=exchanges))


def prior_returns(panel: pd.DataFrame) -> pd.DataFrame:
    """
    Prior (2-12) return for every (PERMNO, month s), where s is the formation
    month — the end of t-1 — so the window is s-11 .. s-1. NaN where French's
    inclusion rule is not met.

    Returned long: ``permno``, ``month`` (= s), ``prior``.
    """
    months = pd.period_range(panel["month"].min(), panel["month"].max(), freq="M", name="month")
    ret = panel.pivot(index="month", columns="permno", values="ret").reindex(months)
    present = panel.assign(one=1.0).pivot(index="month", columns="permno", values="one").reindex(months).notna()
    priced = panel.pivot(index="month", columns="permno", values="prc").reindex(months).notna()

    good = ret.notna()
    tolerable = good | (present & ~priced)                     # the -99 situation

    # A -100% month is log1p(-1) = -inf, which compounds correctly to a prior
    # return of exactly -100%; the warning it raises is not an error.
    with np.errstate(divide="ignore"):
        log_growth = np.log1p(ret.fillna(0.0))
    # Row s holds the sum over s-11 .. s-1: an 11-month window ending at s-1.
    window_sum = log_growth.rolling(PRIOR_WINDOW, min_periods=PRIOR_WINDOW).sum().shift(1)

    # t-12 .. t-3 is s-11 .. s-2: ten months ending at s-2.
    middle_ok = tolerable.astype(float).rolling(PRIOR_WINDOW - 1, min_periods=PRIOR_WINDOW - 1).min().shift(2) == 1.0
    recent_ok = good.shift(1, fill_value=False)                 # t-2 = s-1
    start_priced = priced.shift(MOMENTUM_LOOKBACK_MONTHS, fill_value=False)  # t-13 = s-12

    eligible = middle_ok & recent_ok & start_priced
    prior = np.expm1(window_sum).where(eligible)
    # pandas 3 keeps NaN when stacking, so ineligible pairs are dropped explicitly.
    return prior.stack().dropna().rename("prior").reset_index()


def momentum_portfolios(
    panel: pd.DataFrame,
    companies: pd.DataFrame | None = None,
    start: str | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Six value-weighted size x prior-return portfolios, rebalanced monthly.

    Returns (returns, counts), months t x ``SL``..``BH`` where ``L`` is the low
    30% of prior return (losers) and ``H`` the high 30% (winners). Weights are
    company ME at the end of t-1; returns are the primary security's
    delisting-adjusted return in t.
    """
    companies = company_panel(panel) if companies is None else companies
    prior = prior_returns(panel)
    formed = companies.merge(prior, on=["permno", "month"], how="left")
    if start is not None:
        formed = formed[formed["month"] >= pd.Period(start, "M") - 1]

    next_ret = panel[["permno", "month", "ret"]].copy()
    next_ret["month"] = next_ret["month"] - 1                  # align t's return to formation month s
    formed = formed.merge(next_ret.rename(columns={"ret": "ret_next"}), on=["permno", "month"], how="left")

    rows_ret, rows_cnt = {}, {}
    for s, group in formed.groupby("month", sort=True):
        nyse = group[group["exchcd"].isin(NYSE_EXCHANGE_CODES)]
        if len(nyse) < 10:
            continue
        size_bp = breakpoints_from_nyse(nyse["me"], (SIZE_BREAKPOINT_PERCENTILE,))[0]
        sample = group[group["prior"].notna() & (group["me"] > 0)]
        nyse_sample = sample[sample["exchcd"].isin(NYSE_EXCHANGE_CODES)]
        if len(nyse_sample) < 10:
            continue
        p30, p70 = breakpoints_from_nyse(nyse_sample["prior"], VALUE_BREAKPOINT_PERCENTILES)
        label = size_bucket(sample["me"], size_bp).astype(str) + value_bucket(sample["prior"], p30, p70).astype(str)
        held = sample.assign(portfolio=label.to_numpy())
        held = held[held["ret_next"].notna()]
        if held.empty:
            continue                                            # no month t observed yet
        weighted = (held["me"] * held["ret_next"]).groupby(held["portfolio"]).sum()
        weights = held["me"].groupby(held["portfolio"]).sum()
        rows_ret[s + 1] = weighted / weights
        rows_cnt[s + 1] = held.groupby("portfolio").size()

    labels = ["SL", "SM", "SH", "BL", "BM", "BH"]
    returns = pd.DataFrame(rows_ret).T.reindex(columns=labels)
    counts = pd.DataFrame(rows_cnt).T.reindex(columns=labels).fillna(0).astype(int)
    returns.index.name = counts.index.name = "month"
    return returns, counts


def market_return(panel: pd.DataFrame, start: str | None = None) -> pd.Series:
    """
    Value-weighted return on all screened listed common stocks.

    French: "value-weight return of all CRSP firms incorporated in the US and
    listed on the NYSE, AMEX, or NASDAQ that have a CRSP share code of 10 or 11
    at the beginning of month t, good shares and price data at the beginning of
    t, and good return data for t". Security level, weighted by ME at the end of
    t-1; the blank-check exclusion applies as it does everywhere else.
    """
    begin = apply_share_screen(panel)[["permno", "month", "me"]]
    realised = panel[["permno", "month", "ret"]].copy()
    realised["month"] = realised["month"] - 1
    both = begin.merge(realised, on=["permno", "month"]).dropna(subset=["ret"])
    if start is not None:
        both = both[both["month"] >= pd.Period(start, "M") - 1]
    num = (both["me"] * both["ret"]).groupby(both["month"]).sum()
    den = both["me"].groupby(both["month"]).sum()
    out = num / den
    out.index = out.index + 1
    out.index.name = "month"
    return out.rename("Mkt")
