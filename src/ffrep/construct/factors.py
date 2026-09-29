"""
Factor algebra: six portfolios into SMB and HML.

The arithmetic is simple and the conventions are not. Both factors are
*averages of averages*, and the grouping matters:

    SMB = 1/3 (SL + SM + SH) - 1/3 (BL + BM + BH)
    HML = 1/2 (SH + BH)      - 1/2 (SL + BL)

HML averages across the size halves, so it is neutral to size by construction;
SMB averages across the value thirds, so it is neutral to value. Note the
asymmetry in the denominators — three value groups but two size groups — which
follows from the 2x3 design and is the most common place to put a 1/2 where a
1/3 belongs. The neutral (M) portfolios appear in SMB and are absent from HML;
dropping them from SMB, or including them in HML, are both silent errors that
still produce a plausible series.

This same shape produces RMW from a size x operating-profitability sort and CMA
from a size x investment sort, which is why the algebra is parameterised rather
than written three times.

Verified separately: ``evaluate/ceiling.py`` reproduces published HML and SMB
from French's own six portfolios to 0.5 bps — the half-ulp of his two-decimal
reporting — so this arithmetic is known correct against the published series.
Over portfolios built here from CRSP and Compustat, the same algebra gives an
HML that correlates 0.995 with French's over 1990-2020 (``scripts/build_factors.py``).
"""

from __future__ import annotations

import pandas as pd

#: The six 2x3 portfolio labels, in the order French reports them.
PORTFOLIO_LABELS: tuple[str, ...] = ("SL", "SM", "SH", "BL", "BM", "BH")

#: Which labels are small, and which carry the high/low leg of the second sort.
SMALL = ("SL", "SM", "SH")
BIG = ("BL", "BM", "BH")
HIGH = ("SH", "BH")
LOW = ("SL", "BL")


def _leg(returns: pd.DataFrame, labels: tuple[str, ...]) -> pd.Series:
    """
    Equal-weighted average of the named portfolios, NaN if any one is missing.

    ``skipna=False`` is the point. pandas' default mean skips a missing leg and
    averages the rest, which silently redefines the factor: with SmallValue
    missing, "HML" becomes BigValue alone minus the growth average — a different
    series under the same name (review finding R13). A month in which a
    prescribed leg cannot be computed has no factor return.
    """
    return returns[list(labels)].mean(axis=1, skipna=False)


def _require(returns: pd.DataFrame, labels: tuple[str, ...]) -> None:
    missing = [label for label in labels if label not in returns.columns]
    if missing:
        raise KeyError(
            f"portfolio returns are missing {missing}; expected all of {list(PORTFOLIO_LABELS)}"
        )


def size_factor(returns: pd.DataFrame) -> pd.Series:
    """
    SMB: average of the three small portfolios minus the three big.

    All three value groups participate, including neutral. Averaging only the
    extremes would leave a value tilt in a factor whose entire purpose is to be
    value-neutral.
    """
    _require(returns, PORTFOLIO_LABELS)
    return (_leg(returns, SMALL) - _leg(returns, BIG)).rename("SMB")


def value_factor(returns: pd.DataFrame) -> pd.Series:
    """
    HML: average of the two high-BE/ME portfolios minus the two low.

    Two, not three — the neutral portfolios are excluded entirely. Averaging
    across both size halves is what makes HML size-neutral, and is exactly the
    decomposition step 1 exploited to measure the large-cap ceiling at 0.92.
    """
    _require(returns, PORTFOLIO_LABELS)
    return (_leg(returns, HIGH) - _leg(returns, LOW)).rename("HML")


def second_sort_factor(returns: pd.DataFrame, name: str) -> pd.Series:
    """
    The high-minus-low factor from any 2x3 sort, under a caller-supplied name.

    RMW is this over a size x operating-profitability sort (robust minus weak);
    CMA is this over size x investment, with the sign reversed by the caller
    because *conservative* investment is the low-investment leg.
    """
    return value_factor(returns).rename(name)


def build_2x3_factors(returns: pd.DataFrame) -> pd.DataFrame:
    """Both factors from one set of six portfolio return series."""
    return pd.DataFrame({"SMB": size_factor(returns), "HML": value_factor(returns)})
