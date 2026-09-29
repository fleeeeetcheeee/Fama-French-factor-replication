"""
Characteristics and bucket assignment: the 2x3 sort.

This is where a Fama-French replication goes silently wrong. Nothing here can
crash on a plausible input; it can only return the wrong bucket, and a wrong
bucket produces a factor that correlates 0.9 with the real one and is not it.

Three specific errors this module is shaped to prevent
------------------------------------------------------
**Using June market equity in the BE/ME ratio.** The size sort uses ME at the
end of June of year t. The *denominator of BE/ME* uses ME at the end of December
of t-1. They are different numbers six months apart, and swapping them mixes a
stale numerator with a fresh denominator, shifting every firm's value rank.
``construct/formation.py`` carries them as separate columns (``me``, ``me_dec``)
and computes BE/ME from ``me_dec`` only.

**The inequality at the breakpoint.** A firm exactly at the 30th percentile
belongs in the low bucket, not the middle. With continuous data exact ties are
near-measure-zero and the empirical cost is negligible, but the convention is
pinned by tests so it cannot drift silently.

**Keeping non-positive book equity.** BE/ME is not meaningful when BE <= 0 and
French drops those firms from the value sort entirely. ``formation.py`` excludes
them rather than letting them sort into the growth bucket, which is where a
naive ratio would put them.

Breakpoints are NYSE-only, applied to everything
------------------------------------------------
The asymmetry is the entire point of the design and is argued at length in
``reference/breakpoints.py``. This module takes breakpoints as *given values*
and does not care where they came from, so French's published files and
breakpoints derived from our own NYSE screen are interchangeable inputs.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ffrep.config import (
    BREAKPOINT_QUANTILE_METHOD,
    SIZE_BREAKPOINT_PERCENTILE,
    VALUE_BREAKPOINT_PERCENTILES,
)

#: Size buckets. Small is at or below the NYSE median.
SIZE_LABELS: tuple[str, str] = ("S", "B")

#: Value buckets, low to high book-to-market: growth, neutral, value.
VALUE_LABELS: tuple[str, str, str] = ("L", "M", "H")


def assign_bucket(
    values: pd.Series,
    edges: tuple[float, ...],
    labels: tuple[str, ...],
) -> pd.Series:
    """
    Assign each value to a bucket, lower edges inclusive.

    A value equal to an edge falls in the *lower* bucket: with edges (30, 70)
    and labels ("L", "M", "H"), exactly 30 is "L" and exactly 70 is "M". NaN
    values yield NaN rather than a default bucket, because a firm that cannot be
    sorted must not silently become growth.
    """
    if len(labels) != len(edges) + 1:
        raise ValueError(
            f"need one more label than edge; got {len(edges)} edges and {len(labels)} labels"
        )
    if any(b <= a for a, b in zip(edges, edges[1:])):
        raise ValueError(f"edges must be strictly increasing; got {edges}")

    # np.searchsorted with side="left" puts a value equal to an edge below it,
    # which is the inclusive-lower-edge convention above.
    codes = np.searchsorted(np.asarray(edges, dtype=float), values.to_numpy(dtype=float), side="left")
    out = pd.Series([labels[c] for c in codes], index=values.index, dtype="object")
    return out.where(values.notna())


def size_bucket(me: pd.Series, nyse_median: float) -> pd.Series:
    """Small at or below the NYSE median, big above it."""
    return assign_bucket(me, (float(nyse_median),), SIZE_LABELS).rename("size")


def value_bucket(beme: pd.Series, p30: float, p70: float) -> pd.Series:
    """Growth / neutral / value on the NYSE 30th and 70th BE/ME percentiles."""
    return assign_bucket(beme, (float(p30), float(p70)), VALUE_LABELS).rename("value")


def breakpoints_from_nyse(
    nyse_values: pd.Series,
    percentiles: tuple[int, ...],
    *,
    method: str = BREAKPOINT_QUANTILE_METHOD,
) -> tuple[float, ...]:
    """
    Compute breakpoints from an NYSE-only cross-section.

    The alternative to borrowing French's published files, and the reason that
    limitation can be downgraded from a constraint to a choice.

    ``method`` defaults to ``"lower"``, which was selected by scoring all five
    numpy conventions against French's published breakpoints over 1960-1989
    rather than assumed — see ``BREAKPOINT_QUANTILE_METHOD`` in ``config.py``
    for the table. Over 544 months and every percentile he reports, derived
    breakpoints carry a median error of -0.000% and a mean absolute error of
    0.51%, with 85.7% of pairs inside 1%.
    """
    clean = nyse_values.dropna().to_numpy(dtype=float)
    if clean.size == 0:
        raise ValueError("cannot compute breakpoints from an empty NYSE cross-section")
    qs = np.quantile(clean, [p / 100.0 for p in percentiles], method=method)
    return tuple(float(q) for q in np.atleast_1d(qs))


def nyse_size_breakpoint(nyse_me: pd.Series) -> float:
    """The NYSE median market equity."""
    return breakpoints_from_nyse(nyse_me, (SIZE_BREAKPOINT_PERCENTILE,))[0]


def nyse_value_breakpoints(nyse_beme: pd.Series) -> tuple[float, float]:
    """The NYSE 30th and 70th BE/ME percentiles."""
    p30, p70 = breakpoints_from_nyse(nyse_beme, VALUE_BREAKPOINT_PERCENTILES)
    return p30, p70
