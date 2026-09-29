"""
Steps 3-4: build every factor bottom-up and score it against French.

    python scripts/extract_wrds.py      # once; needs WRDS
    python scripts/build_factors.py

Scored against two releases of French's library (see ``FRENCH_VINTAGES``):

* ``fiz202412`` — the last release built from the legacy SIZ files, which are
  the files this build reads. Like-for-like, and the primary reference.
* ``current`` — built from CIZ since January 2025, with a different monthly
  return definition. French's two releases agree with each other at
  HML correlation 0.9991 over 1990-2020, which is the scale of difference a
  vintage change alone produces.

The done criterion is HML correlation > 0.99 over 1990-01 to 2020-12.

Writes ``data/results/bottom_up/``: the factors, the six-portfolio returns and
firm counts per sort, per-year diagnostics, and the comparison table.
"""

from __future__ import annotations

import sys
import time

import pandas as pd

from ffrep.config import Config
from ffrep.evaluate.compare import fit_table
from ffrep.pipeline import build, load_inputs
from ffrep.reference.published import load_published
from ffrep.store import read_manifest

WINDOWS = {
    "spec 1990-2020": ("1990-01", "2020-12"),
    "full 1963-2024": ("1963-07", "2024-12"),
    "1963-1989": ("1963-07", "1989-12"),
    "2021-2024": ("2021-01", "2024-12"),
}

#: Our factor -> French's column.
FACTOR_MAP = {"Mkt-RF": "Mkt-RF", "SMB": "SMB", "HML": "HML", "RMW": "RMW",
              "CMA": "CMA", "SMB5": "SMB5", "UMD": "UMD"}


def main() -> int:
    pd.set_option("display.width", 200)
    config = Config()
    out_dir = config.results / "bottom_up"
    out_dir.mkdir(parents=True, exist_ok=True)

    t0 = time.time()
    print("loading extracts and building the panel ...", flush=True)
    inputs = load_inputs(config)
    print(f"  {len(inputs.panel):,} security-months, {len(inputs.candidates):,} link candidates "
          f"({time.time() - t0:.0f}s)", flush=True)

    print("building factors ...", flush=True)
    result = build(inputs)
    print(f"  done ({time.time() - t0:.0f}s)", flush=True)

    published = {v: load_published(config, v) for v in ("fiz202412", "current")}
    factors = result["factors"].copy()
    factors["Mkt-RF"] = factors["Mkt"] - published["fiz202412"].factors["RF"].reindex(factors.index)

    factors.to_csv(out_dir / "factors.csv")
    for sort, frame in result["portfolios"].items():
        frame.to_csv(out_dir / f"portfolios_{sort}.csv")
        result["counts"][sort].to_csv(out_dir / f"counts_{sort}.csv")
    result["diagnostics"].to_csv(out_dir / "diagnostics.csv")

    tables = []
    for vintage, pub in published.items():
        t = fit_table(factors, pub.factors, WINDOWS, FACTOR_MAP)
        t.insert(0, "reference", vintage)
        tables.append(t)
    table = pd.concat(tables, ignore_index=True)
    table.to_csv(out_dir / "comparison.csv", index=False)

    show = ["reference", "series", "window", "n", "corr", "r2", "slope", "mean_diff_bps", "te_bps"]
    print("\n" + "=" * 100)
    print("FACTORS vs FRENCH")
    print("=" * 100)
    print(table[show].to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

    spec = table[(table["reference"] == "fiz202412") & (table["series"] == "HML")
                 & (table["window"] == "spec 1990-2020")].iloc[0]
    verdict = "MET" if spec["corr"] > 0.99 else "NOT MET"
    print(f"\nDone criterion — HML corr > 0.99 over 1990-2020 vs the SIZ-vintage reference: "
          f"{spec['corr']:.4f}  ({verdict})")

    # Portfolio-level fit and firm counts: where any factor gap actually lives.
    print("\n" + "=" * 100)
    print("SIX PORTFOLIOS vs FRENCH (fiz202412), 1990-2020: return corr, TE, and firm-count ratio")
    print("=" * 100)
    ref = published["fiz202412"]
    rows = []
    for sort in result["portfolios"]:
        ours = result["portfolios"][sort]
        t = fit_table(ours, ref.portfolios[sort], {"spec": WINDOWS["spec 1990-2020"]})
        ratio = (result["counts"][sort].loc["1990-01":"2020-12"].sum()
                 / ref.counts[sort].loc["1990-01":"2020-12"].sum())
        for _, r in t.iterrows():
            rows.append({"sort": sort, "portfolio": r["series"], "corr": r["corr"],
                         "te_bps": r["te_bps"], "count_ratio": ratio[r["series"]]})
    print(pd.DataFrame(rows).to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

    print("\nHML and SMB correlation with French (fiz202412), by decade:")
    ref_f = published["fiz202412"].factors
    decades = []
    for start in range(1960, 2030, 10):
        lo, hi = f"{max(start, 1963)}-{'07' if start == 1960 else '01'}", f"{min(start + 9, 2024)}-12"
        row = {"decade": f"{start}s"}
        for s_ in ("HML", "SMB", "RMW", "CMA", "UMD"):
            row[s_] = factors[s_].loc[lo:hi].corr(ref_f[s_].loc[lo:hi])
        decades.append(row)
    decades = pd.DataFrame(decades)
    decades.to_csv(out_dir / "correlation_by_decade.csv", index=False)
    print(decades.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

    diag = result["diagnostics"]
    print("\nlink coverage of the June cross-section, by decade (count / market equity):")
    by_decade = diag.groupby(diag.index // 10 * 10)[["linked_by_count", "linked_by_me",
                                                     "ambiguous_permcos", "ambiguous_gvkeys",
                                                     "be_from_moody"]].mean()
    print(by_decade.to_string(float_format=lambda x: f"{x:,.3f}"))

    manifest = read_manifest(config)
    print("\ninputs:", {k: v["sha256"][:12] for k, v in manifest.items()})
    print(f"\nwrote {out_dir}  ({time.time() - t0:.0f}s total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
