"""
Value-weighted portfolio returns, with weights that drift between rebalances.

Fama-French portfolios are formed once a year at the end of June and held for
twelve months. They are *not* rebalanced monthly. That single fact is the source
of the only genuinely subtle arithmetic in the construction, and getting it
wrong produces a return series that looks right and is not.

The asymmetry: weights drift on retx, returns accrue on ret
------------------------------------------------------------
Between rebalances a firm's weight moves with its **market capitalisation**,
which grows by price appreciation only. A dividend leaves the company and
reduces its market cap; it does not increase the holder's weight in the
portfolio. So weights drift on ``retx``, CRSP's return *excluding* dividends.

The portfolio's return, meanwhile, is what the holder actually earned, which
does include dividends. So returns accrue on ``ret``.

Using ``ret`` for both is the natural mistake and it compounds: it silently
overweights high-dividend firms month after month across the holding year, and
high dividend yield correlates with value. The error therefore lands
disproportionately on HML, the factor this project exists to reproduce.

Two distinct kinds of missing, handled differently
---------------------------------------------------
The two are separated deliberately, because conflating them is how a delisted
firm gets carried at a stale weight:

**Missing ``retx`` ends the position permanently.** Without an ex-dividend
return the weight cannot be drifted, so there is no defensible value to carry
forward; the firm is dropped from that month onward. Carrying it would silently
assume zero price change for a firm that has stopped trading, which is exactly
the survivorship error ``delisting.py`` exists to prevent.

**Missing ``ret`` excludes the firm from that month's return only.** Its weight
survives if ``retx`` is present, and it re-enters when a return reappears. In
CRSP the two are almost always missing together — a delisting removes both — so
this case is rare, but it is defined rather than accidental.

Delisting returns should already be folded into ``ret`` by ``delisting.py``
before this module sees the panel.

Everything here is a pure function of frames. No dates are parsed, no calendar
logic is applied; the caller supplies the months of the holding period in order.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def drifted_weights(
    formation_me: pd.Series,
    ex_dividend_returns: pd.DataFrame,
) -> pd.DataFrame:
    """
    The weight each firm carries in each month of the holding period.

    ``formation_me`` is market equity at formation, indexed by identifier.
    ``ex_dividend_returns`` is months x identifiers of ``retx``.

    The first month carries the formation weights unchanged — a portfolio formed
    at the end of June holds June's weights through July. Each subsequent month
    scales the previous weight by ``(1 + retx)``. Weights are returned
    unnormalised; the return calculation divides by their sum, so a firm
    dropping out shrinks the denominator rather than redistributing silently.
    """
    ids = [c for c in ex_dividend_returns.columns if c in formation_me.index]
    retx = ex_dividend_returns[ids]
    base = formation_me.loc[ids].astype(float)

    if (base < 0).any():
        raise ValueError("formation market equity cannot be negative")

    # Growth factor applied to reach month m is the product of (1+retx) over all
    # strictly earlier months, so month 0 carries the formation weights as-is.
    growth = (1.0 + retx.fillna(0.0)).shift(1).fillna(1.0).cumprod()
    weights = growth.mul(base, axis=1)

    # A firm with no retx observation in a month has left; it and every later
    # month are dropped rather than held at a stale weight.
    alive = retx.notna()
    alive = alive.cummin().astype(bool) if len(alive) else alive
    return weights.where(alive)


def value_weighted_return(
    formation_me: pd.Series,
    returns: pd.DataFrame,
    ex_dividend_returns: pd.DataFrame,
) -> pd.Series:
    """
    Monthly value-weighted return over a holding period.

    ``returns`` supplies ``ret`` (with dividends, and with delisting returns
    already compounded in); ``ex_dividend_returns`` supplies ``retx`` for the
    weight drift. Both are months x identifiers and must share an index.

    A month in which no firm has both a weight and a return yields NaN rather
    than 0.0 — an empty portfolio has no return, and 0.0 would be a fabricated
    observation that quietly enters the factor.
    """
    if not returns.index.equals(ex_dividend_returns.index):
        raise ValueError("returns and ex_dividend_returns must share a month index")

    weights = drifted_weights(formation_me, ex_dividend_returns)
    ids = list(weights.columns)
    ret = returns[ids]

    usable = weights.where(ret.notna())
    numerator = (usable * ret).sum(axis=1, min_count=1)
    denominator = usable.sum(axis=1, min_count=1)

    out = numerator / denominator
    return out.where(denominator > 0).rename("ret")


def portfolio_returns(
    assignments: pd.DataFrame,
    returns: pd.DataFrame,
    ex_dividend_returns: pd.DataFrame,
    *,
    weight_column: str = "me",
    portfolio_column: str = "portfolio",
) -> pd.DataFrame:
    """
    Value-weighted returns for every portfolio in an assignment, months x portfolios.

    ``assignments`` is the output of ``sorts.assign_2x3``: one row per firm with
    its formation market equity and its portfolio label. Portfolios appear as
    columns in sorted label order, so the output is stable across runs.
    """
    if portfolio_column not in assignments.columns:
        raise KeyError(f"assignments has no {portfolio_column!r} column")
    if weight_column not in assignments.columns:
        raise KeyError(f"assignments has no {weight_column!r} column")

    series: dict[str, pd.Series] = {}
    for label in sorted(assignments[portfolio_column].dropna().unique()):
        members = assignments[assignments[portfolio_column] == label]
        series[str(label)] = value_weighted_return(
            members[weight_column], returns, ex_dividend_returns
        )
    return pd.DataFrame(series, index=returns.index)


def equal_weighted_return(returns: pd.DataFrame) -> pd.Series:
    """
    Equal-weighted return, for diagnostics only.

    French publishes both, and the difference between them is a useful check
    that value weighting is actually happening: Project 02 recorded a case where
    an equal-weighted series was mistaken for a value-weighted one and matched
    published HML far worse. Never used to build a factor here.
    """
    return returns.mean(axis=1, skipna=True).rename("ret")
