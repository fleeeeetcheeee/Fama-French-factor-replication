"""
Step 1 — how good can a truncated-universe replication possibly be?

The point of doing this first
-----------------------------
Before any firm-level data existed, this asked how well an HML built from large
caps alone — the only universe free data could supply — tracks French's HML,
using French's *own* large-cap portfolios. The answer (0.92 over 1926-2026,
0.88 over 1990-2020) was computable from published data alone and settled that
a large-cap-only replication could not reach the 0.99 criterion.

What it is and is not. It is the measured correlation of one specific
construction — French's big-stock value spread — with his factor, over a given
sample. It is *not* a mathematical upper bound on every possible large-cap
construction, and the earlier wording that "no implementation can beat it"
overstated it (corrected 2026-09-28, after the 2026-09-09 review). With WRDS
access the question became moot: the bottom-up build uses the full CRSP
universe and reaches 0.995 over 1990-2020.

The decomposition it rests on
-----------------------------
HML is the average of two spreads, one within each size half::

    HML = 1/2 (SmallValue + BigValue) - 1/2 (SmallGrowth + BigGrowth)
        = 1/2 [ (SmallValue - SmallGrowth) + (BigValue - BigGrowth) ]
        = 1/2 [ small spread + big spread ]

So an HML built from big stocks only is exactly the `big spread` term, and its
correlation with true HML follows from how the two spreads co-move and their
relative volatilities::

                             σ_B + ρ σ_S
    corr(B, 1/2(S + B)) = ----------------------------
                          sqrt(σ_S² + 2ρ σ_S σ_B + σ_B²)

which is worth deriving rather than only measuring, because it says the
correlation is set by ρ — and ρ is a property of the market, not of anyone's
data budget.

SMB gets the same treatment, where the answer is expected to be far worse: SMB
*is* the small-minus-big spread, so a universe with no small stocks does not
approximate it, it deletes it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ffrep.evaluate.regression import OLSResult, ols
from ffrep.reference import parser as fp

#: The first month reachable when book equity comes from SEC XBRL rather than
#: Compustat. See LOG.md: the Financial Statement Data Sets begin 2009q1, so the
#: first June formation with genuinely-known book equity is June 2010.
FREE_DATA_START = pd.Timestamp("2010-07-31")

#: The window the spec's done criterion asks for.
SPEC_WINDOW = (pd.Timestamp("1990-01-31"), pd.Timestamp("2020-12-31"))


@dataclass(frozen=True)
class CeilingResult:
    """One truncated factor measured against the published series."""

    name: str
    window: str
    n_obs: int
    correlation: float
    #: Annualised mean of (truncated - published), in basis points per month.
    mean_gap_bps: float
    tracking_error_bps: float
    regression: OLSResult

    @property
    def beta(self) -> float:
        return float(self.regression.params.iloc[1])

    def as_row(self) -> dict[str, object]:
        return {
            "factor": self.name,
            "window": self.window,
            "n": self.n_obs,
            "corr": round(self.correlation, 4),
            "beta": round(self.beta, 4),
            "R2": round(self.regression.r_squared, 4),
            "mean_gap_bps": round(self.mean_gap_bps, 2),
            "TE_bps": round(self.tracking_error_bps, 2),
        }


def analytic_ceiling(small_spread: pd.Series, big_spread: pd.Series) -> float:
    """
    The closed form above, evaluated on the two realised spread series.

    Computed alongside the empirical correlation so the two can be compared: if
    they disagree, the decomposition is wrong somewhere, which is a much more
    useful signal than a single number that looks plausible.
    """
    joined = pd.concat([small_spread, big_spread], axis=1).dropna()
    s, b = joined.iloc[:, 0], joined.iloc[:, 1]

    sigma_s, sigma_b = float(s.std(ddof=1)), float(b.std(ddof=1))
    rho = float(s.corr(b))

    numerator = sigma_b + rho * sigma_s
    denominator = np.sqrt(sigma_s**2 + 2 * rho * sigma_s * sigma_b + sigma_b**2)
    return float(numerator / denominator)


def compare(
    constructed: pd.Series,
    published: pd.Series,
    *,
    name: str,
    window: str,
    start: pd.Timestamp | None = None,
    end: pd.Timestamp | None = None,
) -> CeilingResult:
    """Measure one constructed series against the published one over a window."""
    joined = pd.concat(
        [constructed.rename("mine"), published.rename("published")], axis=1
    ).dropna()
    if start is not None:
        joined = joined[joined.index >= start]
    if end is not None:
        joined = joined[joined.index <= end]
    if joined.empty:
        raise ValueError(f"no overlapping observations for {name} in {window}")

    gap = joined["mine"] - joined["published"]

    return CeilingResult(
        name=name,
        window=window,
        n_obs=len(joined),
        correlation=float(joined["mine"].corr(joined["published"])),
        mean_gap_bps=float(gap.mean() * 1e4),
        tracking_error_bps=float(gap.std(ddof=1) * 1e4),
        regression=ols(joined["published"], joined[["mine"]]),
    )


def run(portfolios_path: Path | str, factors_path: Path | str) -> pd.DataFrame:
    """
    The full step-1 analysis, from French's published files only.

    Returns one row per (factor, truncation, window).
    """
    portfolios = fp.load_six_portfolios(portfolios_path, weighting="value")
    published = fp.load_factors(factors_path)

    small_value_spread = portfolios["SmallValue"] - portfolios["SmallGrowth"]
    big_value_spread = portfolios["BigValue"] - portfolios["BigGrowth"]

    small_leg = portfolios[["SmallValue", "SmallNeutral", "SmallGrowth"]].mean(axis=1)
    big_leg = portfolios[["BigValue", "BigNeutral", "BigGrowth"]].mean(axis=1)

    candidates = {
        # HML with the small half of the market deleted — what an S&P-500-sized
        # universe forces.
        ("HML", "big-only"): (big_value_spread, published["HML"]),
        # The mirror image, for contrast: a small-only universe.
        ("HML", "small-only"): (small_value_spread, published["HML"]),
        # SMB cannot survive the same truncation; measuring it makes the point
        # quantitative rather than rhetorical.
        ("SMB", "big-only"): (big_leg - big_leg, published["SMB"]),
    }

    windows: dict[str, tuple[pd.Timestamp | None, pd.Timestamp | None]] = {
        "full history": (None, None),
        "spec 1990-2020": SPEC_WINDOW,
        "free-data 2010.07+": (FREE_DATA_START, None),
    }

    rows: list[dict[str, object]] = []
    for (factor, truncation), (constructed, reference) in candidates.items():
        if factor == "SMB" and truncation == "big-only":
            # A big-only universe has no small leg at all, so SMB is identically
            # zero. Correlation is undefined rather than low; report the fact
            # instead of a number that invites misreading.
            continue
        for window_name, (start, end) in windows.items():
            result = compare(
                constructed,
                reference,
                name=f"{factor} ({truncation})",
                window=window_name,
                start=start,
                end=end,
            )
            rows.append(result.as_row())

    frame = pd.DataFrame(rows)

    # The analytic check, on the same windows.
    analytic = []
    for window_name, (start, end) in windows.items():
        s, b = small_value_spread, big_value_spread
        if start is not None:
            s, b = s[s.index >= start], b[b.index >= start]
        if end is not None:
            s, b = s[s.index <= end], b[b.index <= end]
        analytic.append(
            {
                "factor": "HML (big-only)",
                "window": window_name,
                "analytic_corr": round(analytic_ceiling(s, b), 4),
                "rho(small,big)": round(float(s.corr(b)), 4),
                "sigma_small_bps": round(float(s.std(ddof=1)) * 1e4, 1),
                "sigma_big_bps": round(float(b.std(ddof=1)) * 1e4, 1),
            }
        )

    return frame.merge(
        pd.DataFrame(analytic), on=["factor", "window"], how="left"
    )
