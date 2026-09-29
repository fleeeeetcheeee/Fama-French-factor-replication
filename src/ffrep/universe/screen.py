"""
The CRSP universe screen: which securities are a "firm" for Fama-French.

This module is the answer to a question that sounds trivial and is not: given a
month of CRSP data, which rows are the cross-section? Getting it wrong does not
raise — it produces a universe that is plausible, well-formed and shifted, and
every factor built on top inherits the shift silently.

Two corrections here were each worth several percent of the NYSE median, and
both were found by comparing against French's published breakpoints rather than
by reading code.

Market equity is a *company* property, not a security property
--------------------------------------------------------------
A firm with two share classes appears as two PERMNOs under one PERMCO. Its size
is the sum, not either half. Treating each class as its own firm both
double-counts the firm and understates it, and the effect grew as multi-class
listings became common: correcting it moved June-2000 from -5.50% to -0.18%
against French's published median and June-2010 from -3.68% to -0.35%.

The combined value is assigned to the PERMNO with the largest market equity
within the PERMCO, which is the Fama-French convention and matters downstream
because Compustat book equity arrives at the company level.

Blank-check companies are not firms
-----------------------------------
CRSP tags SPACs with share code 11 — ordinary common shares — so they pass an
otherwise-correct filter. Through the 2021-22 SPAC wave this put up to 164
excess names into the NYSE cross-section and dragged the June-2022 median 18.6%
below French's. They are excluded by SIC 6799; see ``EXCLUDED_SIC_CODES`` in
``config.py`` for the evidence and the caveat.

What is deliberately *not* here
-------------------------------
No WRDS calls. Everything below is a pure transformation of a DataFrame, so the
screen is unit-testable against hand-built cross-sections with known answers.
The queries live in ``wrds_source.py``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ffrep.config import (
    COMMON_SHARE_CODES,
    EXCLUDED_SIC_CODES,
    LISTED_EXCHANGE_CODES,
    NYSE_EXCHANGE_CODES,
)

#: Columns a raw CRSP monthly cross-section must carry to be screenable.
REQUIRED_COLUMNS: tuple[str, ...] = (
    "permno",
    "permco",
    "date",
    "prc",
    "shrout",
    "shrcd",
    "exchcd",
)


def _require_columns(df: pd.DataFrame) -> None:
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise KeyError(
            f"cross-section is missing required column(s): {missing}. "
            f"Got: {sorted(df.columns)}"
        )


def market_equity(df: pd.DataFrame) -> pd.Series:
    """
    Market equity in $ millions, per security.

    ``prc`` is negated by CRSP when the closing value is a bid/ask midpoint
    rather than a trade, so the sign carries information about *quote quality*,
    never about value — taking the absolute value is required, not a
    convenience. ``shrout`` is in thousands, hence the 1,000 divisor.

    Verified exactly: this reproduces CRSP's own ``mthcap`` field on 1,419 of
    1,419 securities in the June-2022 NYSE cross-section.
    """
    return df["prc"].abs() * df["shrout"] / 1000.0


def apply_share_screen(
    df: pd.DataFrame,
    *,
    exchanges: tuple[int, ...] = LISTED_EXCHANGE_CODES,
) -> pd.DataFrame:
    """
    Restrict a raw CRSP cross-section to Fama-French-eligible securities.

    Applies, in order: ordinary common shares only, the requested exchanges,
    non-null price and shares outstanding, strictly positive market equity, and
    the blank-check exclusion. Adds a ``me`` column.

    Pass ``exchanges=NYSE_EXCHANGE_CODES`` to build the breakpoint universe;
    the default is the full NYSE+AMEX+NASDAQ population the breakpoints get
    applied to.
    """
    _require_columns(df)
    out = df.copy()

    out = out[out["shrcd"].isin(COMMON_SHARE_CODES)]
    out = out[out["exchcd"].isin(exchanges)]
    out = out[out["prc"].notna() & out["shrout"].notna()]

    if "siccd" in out.columns:
        # Fill rather than drop: a missing SIC is not evidence of a blank check,
        # and dropping would silently shrink the universe.
        sic = pd.to_numeric(out["siccd"], errors="coerce").fillna(-1).astype(int)
        out = out[~sic.isin(EXCLUDED_SIC_CODES)]

    out["me"] = market_equity(out)
    out = out[out["me"] > 0]
    return out.reset_index(drop=True)


def aggregate_to_company(df: pd.DataFrame) -> pd.DataFrame:
    """
    Collapse share classes to one row per company, per date.

    Market equity is summed across every PERMNO sharing a PERMCO, and the total
    is carried on the PERMNO that held the largest share of it. That surviving
    PERMNO is what later joins to Compustat, so which one wins is not cosmetic.

    Ties are broken by the lower PERMNO. An arbitrary rule is fine; a
    *nondeterministic* one is not, because it makes the whole build
    irreproducible — the same reasoning as Project 02's event-queue sequence
    counter.

    The primary security is kept as an **intact row**. ``groupby().first()``
    would not do that: it takes the first non-null value *per column*, so a
    primary class with a missing return or CUSIP silently inherits the other
    class's — a hybrid row describing no real security (review finding R21).
    """
    if "me" not in df.columns:
        raise KeyError("aggregate_to_company expects an 'me' column; run apply_share_screen first")
    if df.empty:
        return df.copy()

    ordered = df.sort_values(["date", "permco", "me", "permno"], ascending=[True, True, False, True])
    primary = ordered.drop_duplicates(subset=["date", "permco"], keep="first")
    totals = df.groupby(["date", "permco"], as_index=False)["me"].sum().rename(columns={"me": "me_company"})

    out = primary.merge(totals, on=["date", "permco"], how="left")
    out["me"] = out["me_company"]
    return out.drop(columns=["me_company"]).reset_index(drop=True)


def nyse_breakpoint_universe(df: pd.DataFrame) -> pd.DataFrame:
    """
    The NYSE-only, company-level cross-section that breakpoints are computed on.

    Convenience composition of the two steps above with the NYSE exchange
    filter, because doing them in the wrong order is a real error: screening
    after aggregating would sum a SPAC's market equity into a legitimate
    company's total before the SPAC was ever excluded.
    """
    return aggregate_to_company(apply_share_screen(df, exchanges=NYSE_EXCHANGE_CODES))


def full_universe(df: pd.DataFrame) -> pd.DataFrame:
    """The NYSE+AMEX+NASDAQ company-level cross-section the sorts are applied to."""
    return aggregate_to_company(apply_share_screen(df, exchanges=LISTED_EXCHANGE_CODES))
