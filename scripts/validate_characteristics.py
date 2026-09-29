"""
Score the sort characteristics against French's published NYSE breakpoints.

    python scripts/validate_characteristics.py

Closes the log's open item 9: operating profitability and investment were
implemented and hand-tested, but never scored and recorded against
``OP_Breakpoints`` and ``INV_Breakpoints`` the way BE/ME was. This scores all
three as the *formation join* produces them — linked through ``links.resolve``,
restricted to each sort's own sample, NYSE firms only — so what is validated is
the input the portfolios are actually built from, not a side calculation.

BE/ME is scored in percent (relative error, it is positive by construction);
OP and INV in percentage points, because both cross zero and a relative error
near zero measures the denominator rather than the fit.

Scored against the SIZ-vintage (``fiz202412``) files. French's OP definition
has included minority interest in the denominator since August 2018, so both
vintages here carry it; the pre-2018 definition is shown for contrast.
"""

from __future__ import annotations

import sys
from dataclasses import replace

import numpy as np
import pandas as pd

from ffrep.config import Config
from ffrep.construct.formation import Conventions, annual_characteristics, build_formation
from ffrep.pipeline import load_inputs
from ffrep.reference.breakpoints import load_breakpoints

PERCENTILES = tuple(range(5, 100, 5))
YEARS = range(1964, 2025)
SCORE_FROM = 1975


def sections(inputs, conventions: Conventions) -> dict[int, dict[str, pd.Series]]:
    chars = annual_characteristics(inputs.funda, conventions)
    out = {}
    for year in YEARS:
        f = build_formation(year, inputs.panel, inputs.candidates, chars, conventions)
        frame = f.frame
        out[year] = {
            "beme": frame.loc[f.samples["beme"]].query("nyse")["beme"],
            "op": frame.loc[f.samples["op"]].query("nyse")["op"] * 100.0,
            "inv": frame.loc[f.samples["inv"]].query("nyse")["inv"] * 100.0,
        }
    return out


def score(data: dict, key: str, table, *, relative: bool) -> pd.DataFrame:
    rows = []
    for year, parts in data.items():
        stamp = pd.Timestamp(year=year, month=12, day=31)
        if stamp not in table.values.index:
            continue
        values = parts[key].dropna().to_numpy()
        if len(values) < 50:
            continue
        mine = np.quantile(values, [p / 100 for p in PERCENTILES], method="lower")
        published = table.values.loc[stamp, list(PERCENTILES)].to_numpy(dtype=float)
        errors = 100 * (mine / published - 1) if relative else mine - published
        count_col = "n_positive" if "n_positive" in table.counts.columns else "n_firms"
        rows.append({"year": year, "mean_abs": np.nanmean(np.abs(errors)),
                     "bias": np.nanmedian(errors), "n": len(values),
                     "fr_n": int(table.counts.loc[stamp, count_col])})
    frame = pd.DataFrame(rows).set_index("year")
    frame["dn"] = frame["n"] - frame["fr_n"]
    return frame


def main() -> int:
    pd.set_option("display.width", 200)
    config = Config()
    inputs = load_inputs(config)
    tables = {k: load_breakpoints(config.french_path(f"bp_{k}", "fiz202412")) for k in ("beme", "op", "inv")}

    shipped = sections(inputs, Conventions())
    pre2018 = sections(inputs, replace(Conventions(), op_minority_interest=False))

    results = {
        "BE/ME (%)": score(shipped, "beme", tables["beme"], relative=True),
        "OP, BE + MI denominator (pp)  [shipped]": score(shipped, "op", tables["op"], relative=False),
        "OP, BE-only denominator (pp)": score(pre2018, "op", tables["op"], relative=False),
        "INV (pp)": score(shipped, "inv", tables["inv"], relative=False),
    }
    summary = []
    for label, frame in results.items():
        w = frame.loc[SCORE_FROM:]
        summary.append({"characteristic": label, "years": len(w), "mean_abs_err": w["mean_abs"].mean(),
                        "median_bias": w["bias"].median(), "median_count_diff": w["dn"].median(),
                        "worst_count_diff": w["dn"].abs().max()})
    summary = pd.DataFrame(summary)
    print(f"NYSE breakpoints, every 5th percentile p5-p95, formation {SCORE_FROM}-2024, vs French (SIZ vintage)")
    print(summary.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))

    for label in ("OP, BE + MI denominator (pp)  [shipped]", "INV (pp)"):
        frame = results[label]
        decade = frame.groupby(frame.index // 10 * 10).agg(
            mean_abs=("mean_abs", "mean"), bias=("bias", "median"), dn=("dn", "median"))
        print(f"\n{label}, by decade:")
        print(decade.to_string(float_format=lambda x: f"{x:,.3f}"))

    out = config.results / "characteristics"
    out.mkdir(parents=True, exist_ok=True)
    summary.to_csv(out / "breakpoint_validation.csv", index=False)
    for label, frame in results.items():
        stem = label.split(" (")[0].split(",")[0].replace("/", "").lower()
        frame.to_csv(out / f"breakpoints_{stem}{'_pre2018' if 'BE-only' in label else ''}.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
