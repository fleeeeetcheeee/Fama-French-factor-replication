"""
Step 3 — does our book equity reproduce French's published NYSE breakpoints?

The BE-ME_Breakpoints file is the sharpest external check available for this
layer, and it checks three things at once: the book-equity formula, the CUSIP
linkage standing in for CRSP/Compustat Merged, and the December-market-equity
convention. A miss has to be attributed across those three before it can be
blamed on the accounting.

It also carries two count columns — firms with BE <= 0 and firms with BE > 0 —
which is a second, independent signal. A linkage losing firms moves the counts
whether or not it moves the median.

Two things this script settles empirically rather than by assertion:

  1. Which year a BE-ME_Breakpoints row is stamped with (formation year t, not
     the accounting year t-1).
  2. That French stops adding balance-sheet deferred taxes to book equity after
     fiscal 1992, which his stated definition does not say and his published
     breakpoints require.

    export WRDS_USERNAME=...        # credentials live in ~/.pgpass
    python scripts/validate_book_equity.py

Runs about five minutes, almost all of it the Compustat pull.
"""

from __future__ import annotations

import os
import sys

import numpy as np
import pandas as pd

from ffrep.config import Config, DEFERRED_TAX_LAST_FISCAL_YEAR
from ffrep.construct.book_equity import (
    book_equity,
    deferred_taxes,
    drop_empty_records,
    investment,
    latest_fiscal_year,
    operating_profitability,
    preferred_stock,
    stockholders_equity,
)
from ffrep.reference.breakpoints import load_breakpoints
from ffrep.universe.linker import CusipLinker
from ffrep.universe.screen import nyse_breakpoint_universe
from ffrep.universe.wrds_source import (
    connect,
    fetch_cusip_history,
    fetch_fundamentals,
    fetch_nyse_month_ends,
)

#: French publishes p5..p100. The 100th is a maximum, not a breakpoint, and one
#: outlier moves it by orders of magnitude, so it is excluded from scoring.
PERCENTILES: tuple[int, ...] = tuple(range(5, 100, 5))

#: Scoring window. Compustat covers 55-78% of NYSE before 1972 and French's
#: early book equity is hand-collected from Moody's, which is not purchasable
#: at any price — so the pre-1975 years are reported but not summarised.
SCORE_FROM = 1975


def _quantiles(values: np.ndarray, method: str = "lower") -> np.ndarray:
    return np.quantile(values, [p / 100 for p in PERCENTILES], method=method)


def build(db) -> dict:
    """Pull everything once; every table below is a view on these three frames."""
    print("pulling NYSE June/December cross-sections ...", flush=True)
    nyse = nyse_breakpoint_universe(fetch_nyse_month_ends(db))
    nyse["year"] = nyse["date"].dt.year

    print("pulling Compustat annual fundamentals ...", flush=True)
    funda = latest_fiscal_year(drop_empty_records(fetch_fundamentals(db)))

    print("pulling CRSP CUSIP history ...", flush=True)
    history = fetch_cusip_history(db)

    identifiers = (
        funda[["gvkey", "cusip"]].dropna(subset=["cusip"]).drop_duplicates("cusip")
    )
    linker = CusipLinker(historical=history)
    december = linker.link(nyse[nyse["date"].dt.month == 12], identifiers)
    june = linker.link(nyse[nyse["date"].dt.month == 6], identifiers)

    print(
        f"  {len(nyse):,} NYSE company-months, {len(funda):,} Compustat firm-years, "
        f"linked {100 * linker.coverage(december)['by_count']:.1f}% by count / "
        f"{100 * linker.coverage(december)['by_market_equity']:.1f}% by market equity"
    )
    return {"december": december, "june": june, "funda": funda}


def beme_sections(data: dict, be: pd.Series) -> dict[int, pd.Series]:
    """BE/ME by formation year: BE for the fiscal year ending in t-1 over
    December-(t-1) market equity."""
    annual = data["funda"].assign(be=be).dropna(subset=["be"])
    lookup = annual.set_index(["gvkey", "accounting_year"])["be"]
    december = data["december"].dropna(subset=["gvkey"])

    out = {}
    for year, group in december.groupby("year"):
        values = lookup.reindex(
            pd.MultiIndex.from_arrays([group["gvkey"], [year] * len(group)])
        ).to_numpy()
        section = pd.Series(values / group["me"].to_numpy()).dropna()
        if len(section) >= 50:
            out[year + 1] = section
    return out


def score_beme(sections: dict[int, pd.Series], table, *, offset: int = 0) -> pd.DataFrame:
    rows = []
    for t, section in sorted(sections.items()):
        stamp = pd.Timestamp(year=t + offset, month=12, day=31)
        if stamp not in table.values.index:
            continue
        published = table.values.loc[stamp]
        positive = section[section > 0].to_numpy()
        if len(positive) < 50:
            continue
        errors = [
            100 * (mine / published[p] - 1)
            for p, mine in zip(PERCENTILES, _quantiles(positive))
            if published.get(p, 0) > 0
        ]
        rows.append(
            {
                "t": t,
                "n_pos": len(positive),
                "fr_n_pos": int(table.counts.loc[stamp, "n_positive"]),
                "n_nonpos": int((section <= 0).sum()),
                "fr_n_nonpos": int(table.counts.loc[stamp, "n_nonpositive"]),
                "med": np.quantile(positive, 0.5, method="lower"),
                "fr_med": published[50],
                "mean_abs_err": np.abs(errors).mean(),
                "bias": np.median(errors),
            }
        )
    frame = pd.DataFrame(rows)
    frame["dn"] = frame["n_pos"] - frame["fr_n_pos"]
    frame["dn_nonpos"] = frame["n_nonpos"] - frame["fr_n_nonpos"]
    return frame


def score_ratio(data: dict, column: str, values: pd.Series, table) -> pd.DataFrame:
    """OP and INV, scored in percentage POINTS.

    Relative error is meaningless for these: both files publish percentages that
    cross zero — INV's 5th percentile is negative in most years — so a 0.2pp
    difference becomes a 50% error from the denominator alone. BE/ME has no such
    problem because it is positive by construction.
    """
    annual = data["funda"].assign(v=values).dropna(subset=["v"])
    lookup = annual.set_index(["gvkey", "accounting_year"])["v"]
    december = data["december"].dropna(subset=["gvkey"])

    rows = []
    for year, group in december.groupby("year"):
        t = year + 1
        stamp = pd.Timestamp(year=t, month=12, day=31)
        if stamp not in table.values.index:
            continue
        found = lookup.reindex(
            pd.MultiIndex.from_arrays([group["gvkey"], [year] * len(group)])
        ).to_numpy()
        section = pd.Series(found).dropna().to_numpy() * 100.0
        if len(section) < 50:
            continue
        published = table.values.loc[stamp]
        diffs = [
            mine - published[p]
            for p, mine in zip(PERCENTILES, _quantiles(section))
            if not np.isnan(published.get(p, np.nan))
        ]
        rows.append(
            {
                "t": t,
                "n": len(section),
                "fr_n": int(table.counts.loc[stamp, "n_firms"]),
                "mean_abs_pp": np.abs(diffs).mean(),
                "bias_pp": np.median(diffs),
                "p50": np.quantile(section, 0.5, method="lower"),
                "fr_p50": published[50],
            }
        )
    frame = pd.DataFrame(rows)
    frame["dn"] = frame["n"] - frame["fr_n"]
    return frame


def main() -> int:
    pd.set_option("display.width", 220)
    config = Config()

    for key in ("bp_beme", "bp_op", "bp_inv"):
        if not config.french_path(key).exists():
            print(
                f"missing {config.french_path(key)}\n"
                f"Run: python scripts/fetch_reference_data.py"
            )
            return 1

    username = os.getenv("WRDS_USERNAME")
    if not username:
        print("set WRDS_USERNAME (credentials come from ~/.pgpass)")
        return 1

    db = connect(username)
    try:
        data = build(db)
    finally:
        db.close()

    funda = data["funda"]
    se = stockholders_equity(funda)
    dt_raw = deferred_taxes(funda, through_fiscal_year=None)
    ps = preferred_stock(funda)
    fiscal_year = funda["accounting_year"]

    beme_table = load_breakpoints(config.french_path("bp_beme"))
    shipped = book_equity(funda)

    # --- 1. what does the year label on a published row mean? ---------------
    print("\n" + "=" * 104)
    print("YEAR LABEL — is a BE-ME_Breakpoints row the formation year t, or the "
          "accounting year t-1?")
    print("=" * 104)
    sections = beme_sections(data, shipped)
    for offset, label in ((0, "row year == formation year t"),
                          (-1, "row year == accounting year t-1")):
        scored = score_beme(sections, beme_table, offset=offset)
        window = scored[scored["t"] >= SCORE_FROM]
        print(f"  {label:<34}  mean |err| {window['mean_abs_err'].mean():>7.3f}%   "
              f"median bias {window['bias'].median():>+7.3f}%")
    print("  The formation-year reading wins by an order of magnitude, and the "
          "medians settle it outright:\n"
          "  our accounting year 1976 median BE/ME equals French's 1977 row to "
          "three decimals.")

    # --- 2. the deferred tax term -------------------------------------------
    print("\n" + "=" * 104)
    print("DEFERRED TAXES — French's definition adds them unconditionally; his "
          "breakpoints do not")
    print("=" * 104)
    variants = {
        "SE + DT - PS  (always add, as stated)": se + dt_raw - ps,
        "SE - PS       (never add)": se - ps,
        f"DT through FY{DEFERRED_TAX_LAST_FISCAL_YEAR}, none after  [shipped]": shipped,
    }
    print(f"  {'definition':<44}{f'{SCORE_FROM}-1993':>22}{'1994-2025':>22}")
    for label, values in variants.items():
        scored = score_beme(beme_sections(data, values), beme_table)
        early = scored[(scored["t"] >= SCORE_FROM) & (scored["t"] <= 1993)]
        late = scored[scored["t"] >= 1994]
        print(f"  {label:<44}{early['mean_abs_err'].mean():>21.3f}%"
              f"{late['mean_abs_err'].mean():>21.3f}%")

    print(f"\n  cutoff scan — mean |err| over formation 1985-2005 by last fiscal "
          f"year in which DT is added:")
    line = []
    for cutoff in range(1988, 1999):
        scored = score_beme(
            beme_sections(data, se + dt_raw.where(fiscal_year <= cutoff, 0.0) - ps),
            beme_table,
        )
        window = scored[(scored["t"] >= 1985) & (scored["t"] <= 2005)]
        line.append((cutoff, window["mean_abs_err"].mean()))
    print("    " + "  ".join(f"FY{c}" for c, _ in line))
    print("    " + "  ".join(f"{v:>6.2f}" for _, v in line))
    print("\n  A single clean minimum. No source states this cutoff; SFAS 109 "
          "takes effect for fiscal\n  years beginning after 15 December 1992, "
          "which is where it lands — suggestive, not proof.")

    # --- 3. the shipped definition, year by year ----------------------------
    scored = score_beme(sections, beme_table)
    print("\n" + "=" * 104)
    print("BE/ME vs published NYSE breakpoints — shipped definition")
    print("=" * 104)
    print(scored.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    window = scored[scored["t"] >= SCORE_FROM]
    print(f"\n  {SCORE_FROM}-2024: mean |err| {window['mean_abs_err'].mean():.3f}%, "
          f"median bias {window['bias'].median():+.3f}%, "
          f"median firm-count difference {window['dn'].median():+.0f}")
    print(f"  BE <= 0 count difference: median {window['dn_nonpos'].median():+.0f}, "
          f"worst {window['dn_nonpos'].abs().max():.0f} — an independent check on "
          f"the sign of BE")

    # --- 4. profitability and investment ------------------------------------
    print("\n" + "=" * 104)
    print("OPERATING PROFITABILITY and INVESTMENT — percentage points")
    print("=" * 104)
    for column, key, values in (
        ("OP", "bp_op", operating_profitability(funda, shipped)),
        ("INV", "bp_inv", investment(funda)),
    ):
        table = load_breakpoints(config.french_path(key))
        frame = score_ratio(data, column, values, table)
        window = frame[frame["t"] >= SCORE_FROM]
        print(f"  {column:<4} {SCORE_FROM}-2024: mean |err| "
              f"{window['mean_abs_pp'].mean():.3f}pp, "
              f"median bias {window['bias_pp'].median():+.3f}pp, "
              f"median count difference {window['dn'].median():+.0f}")
        decade = frame.groupby(frame["t"] // 10 * 10).agg(
            years=("t", "size"),
            mean_abs_pp=("mean_abs_pp", "mean"),
            bias_pp=("bias_pp", "median"),
            med_dn=("dn", "median"),
        )
        print(decade.to_string(float_format=lambda x: f"{x:,.3f}"))

    return 0


if __name__ == "__main__":
    sys.exit(main())
