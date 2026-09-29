"""
How close is a constructed series to a published one?

The done criterion is a correlation, and the spec also asks for the R² of a
regression on the published series. Neither is enough alone: two series can
correlate at 0.99 while one runs at 1.3 times the other's volatility, or with a
persistent 10 bp monthly drift. So every comparison reports the slope and the
tracking error beside the correlation, in basis points per month.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Fit:
    n: int
    corr: float
    r2: float
    slope: float             # published = a + slope * ours
    mean_diff_bps: float     # mean(ours - published)
    te_bps: float            # std(ours - published), monthly
    max_abs_diff_bps: float
    first: str
    last: str


def to_monthly(frame: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    """Index a French or global-q series by calendar month, like the build."""
    out = frame.copy()
    if not isinstance(out.index, pd.PeriodIndex):
        out.index = pd.DatetimeIndex(out.index).to_period("M")
    out.index.name = "month"
    return out


def fit(ours: pd.Series, published: pd.Series) -> Fit:
    both = pd.concat([ours.rename("ours"), published.rename("pub")], axis=1).dropna()
    if len(both) < 3:
        raise ValueError(f"only {len(both)} overlapping months")
    x, y = both["ours"].to_numpy(), both["pub"].to_numpy()
    diff = x - y
    corr = float(np.corrcoef(x, y)[0, 1])
    slope = float(np.cov(x, y, ddof=1)[0, 1] / np.var(x, ddof=1))
    return Fit(
        n=len(both),
        corr=corr,
        r2=corr**2,
        slope=slope,
        mean_diff_bps=float(diff.mean() * 1e4),
        te_bps=float(diff.std(ddof=1) * 1e4),
        max_abs_diff_bps=float(np.abs(diff).max() * 1e4),
        first=str(both.index.min()),
        last=str(both.index.max()),
    )


def fit_table(
    ours: pd.DataFrame,
    published: pd.DataFrame,
    windows: dict[str, tuple[str, str]],
    columns: dict[str, str] | None = None,
) -> pd.DataFrame:
    """
    One row per (series, window). ``columns`` maps our column to the published
    one where the names differ (UMD vs Mom, say).
    """
    columns = columns or {c: c for c in ours.columns if c in published.columns}
    rows = []
    for mine, theirs in columns.items():
        for label, (start, end) in windows.items():
            a = ours[mine].loc[start:end]
            b = published[theirs].loc[start:end]
            try:
                rows.append({"series": mine, "window": label, **asdict(fit(a, b))})
            except ValueError:
                continue
    return pd.DataFrame(rows)
