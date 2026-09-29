"""
Step 5: attribute the gap to French, one construction choice at a time.

    python scripts/build_factors.py     # baseline first
    python scripts/attribution.py

Each variant rebuilds the BE/ME sort with exactly one thing changed and reports
how HML and SMB move against French's SIZ-vintage release, over the spec window
and the full sample. A variant that *improves* the fit is evidence about what
French does; one that worsens it prices the choice we made. Nothing is tuned to
the result: every variant is a published alternative or an explicit ablation,
and all of them are reported.

Two reference points frame the table rather than being variants of it:

* **vintage** — French's own CIZ release against his SIZ release. Two builds by
  the same author from the same firms differ by this much, so no replication
  should be expected to beat it.
* **baseline** — the shipped build.

Writes ``data/results/attribution/attribution.csv``.
"""

from __future__ import annotations

import sys
import time
from dataclasses import replace

import pandas as pd

from ffrep.config import Config
from ffrep.construct.formation import Conventions
from ffrep.evaluate.compare import fit
from ffrep.pipeline import build, load_inputs
from ffrep.reference.breakpoints import load_breakpoints
from ffrep.reference.published import load_published

WINDOWS = {"spec 1990-2020": ("1990-01", "2020-12"), "full 1963-2024": ("1963-07", "2024-12")}


def published_breakpoints(config: Config, years: range) -> dict:
    """French's own June size median and BE/ME 30th/70th, keyed like the build's override."""
    me = load_breakpoints(config.french_path("bp_me", "fiz202412")).values
    beme = load_breakpoints(config.french_path("bp_beme", "fiz202412")).values
    out = {}
    for year in years:
        june = pd.Timestamp(year=year, month=6, day=30)
        stamp = pd.Timestamp(year=year, month=12, day=31)
        if june in me.index and stamp in beme.index:
            out[(year, "beme")] = (float(me.loc[june, 50]), float(beme.loc[stamp, 30]), float(beme.loc[stamp, 70]))
    return out


def score(factors: pd.DataFrame, reference: pd.DataFrame, label: str) -> list[dict]:
    rows = []
    for series in ("HML", "SMB"):
        for window, (start, end) in WINDOWS.items():
            f = fit(factors[series].loc[start:end], reference[series].loc[start:end])
            rows.append({"variant": label, "series": series, "window": window,
                         "corr": f.corr, "te_bps": f.te_bps, "mean_diff_bps": f.mean_diff_bps, "n": f.n})
    return rows


def main() -> int:
    pd.set_option("display.width", 200)
    config = Config()
    out_dir = config.results / "attribution"
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    fiz = load_published(config, "fiz202412").factors
    current = load_published(config, "current").factors
    rows = score(current, fiz, "vintage: French CIZ vs French SIZ")

    fast = dict(sorts=("beme",), momentum=False, market=False)
    base_conventions = Conventions()

    print("baseline ...", flush=True)
    inputs = load_inputs(config)
    baseline = build(inputs, base_conventions, **fast)
    rows += score(baseline["factors"], fiz, "baseline (shipped)")

    variants = {
        "2-year Compustat requirement (FF 1993)": dict(conventions=replace(base_conventions, min_compustat_years=2)),
        "size breakpoint from each sort's NYSE sample": dict(conventions=replace(base_conventions, size_breakpoint_sample="sort")),
        "deferred taxes added in every year": dict(conventions=replace(base_conventions, deferred_taxes_through=None)),
        "no Moody's book equity (Compustat only)": dict(conventions=replace(base_conventions, moody_book_equity=False)),
        "French's published breakpoints (borrowed)": dict(breakpoints=published_breakpoints(config, range(1963, 2025))),
    }
    for label, change in variants.items():
        print(f"{label} ...", flush=True)
        result = build(inputs, change.get("conventions", base_conventions),
                       breakpoints=change.get("breakpoints"), **fast)
        rows += score(result["factors"], fiz, label)

    rebuilt_inputs = {
        "no delisting returns at all": dict(delisting=False),
        "delisting returns, but no terminal months (left join)": dict(terminal_rows=False),
        "no issuer-level (6-character) CUSIP links": dict(issuer_matches=False),
        "link on Compustat header CUSIP only": dict(compustat_securities=False, issuer_matches=False),
    }
    for label, kwargs in rebuilt_inputs.items():
        print(f"{label} ...", flush=True)
        result = build(load_inputs(config, **kwargs), base_conventions, **fast)
        rows += score(result["factors"], fiz, label)

    table = pd.DataFrame(rows)
    base = table[table["variant"] == "baseline (shipped)"].set_index(["series", "window"])
    table["d_corr"] = [r.corr - base.loc[(r.series, r.window), "corr"] for r in table.itertuples()]
    table["d_te_bps"] = [r.te_bps - base.loc[(r.series, r.window), "te_bps"] for r in table.itertuples()]
    table.to_csv(out_dir / "attribution.csv", index=False)

    for series in ("HML", "SMB"):
        print("\n" + "=" * 110)
        print(f"{series} vs French (SIZ vintage) — one change at a time")
        print("=" * 110)
        view = table[table["series"] == series].pivot_table(
            index="variant", columns="window", values=["corr", "te_bps", "d_corr"], sort=False)
        print(view.to_string(float_format=lambda x: f"{x:,.4f}"))
    print(f"\nwrote {out_dir}  ({time.time() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
