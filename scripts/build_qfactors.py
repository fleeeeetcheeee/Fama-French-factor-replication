"""
Step 6: the Hou-Xue-Zhang q-factors bottom-up, then spanning tests both ways.

    python scripts/build_factors.py       # the FF side first
    python scripts/build_qfactors.py

The q-factors are scored against global-q.org's published series and 18
benchmark portfolios (returns and firm counts). The spanning tests are then run
on the published series — the literature's own numbers, which this project
should reproduce — and on the series built here, which it should agree with.

Quarterly book equity is imputed as HXZ do — fourth quarters from the annual
file, then clean surplus backward and forward (``qfactor/quarterly.py``) —
which is what makes their 1967-71 extension reachable: without it only ~10% of
their firms had a usable ROE before 1972. Series are scored from January 1967,
their published start, and from 1972, their 2015 start; both the published and
the bottom-up spanning tests use the same months.

Writes ``data/results/qfactors/``.
"""

from __future__ import annotations

import sys
import time

import pandas as pd

from ffrep.config import Config
from ffrep.construct.book_equity import book_equity, drop_empty_records
from ffrep.construct.formation import annual_characteristics
from ffrep.construct.monthly import company_panel
from ffrep.evaluate.compare import fit_table
from ffrep.evaluate.spanning import spanning
from ffrep.pipeline import LAST_MONTH, load_inputs
from ffrep.qfactor.construct import q_factors, q_portfolios
from ffrep.qfactor.quarterly import crsp_shares_by_gvkey, quarterly_roe
from ffrep.reference.published import load_global_q, load_published
from ffrep.store import read_extract

#: January 1967, HXZ's published start, is held by the June 1966 formation.
FIRST_FORMATION_YEAR = 1966

WINDOWS = {
    "1967-2024": ("1967-01", "2024-12"),
    "1967-1971": ("1967-01", "1971-12"),
    "1972-2024": ("1972-01", "2024-12"),
    "spec 1990-2020": ("1990-01", "2020-12"),
}

#: The common sample for every spanning regression, published and bottom-up.
SPANNING_WINDOW = slice("1967-01", "2024-12")


def main() -> int:
    pd.set_option("display.width", 200)
    config = Config()
    out_dir = config.results / "qfactors"
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print("loading ...", flush=True)
    inputs = load_inputs(config)
    characteristics = annual_characteristics(inputs.funda)
    annual = drop_empty_records(inputs.funda)
    annual_be = annual.assign(be=book_equity(annual, deferred_taxes_through=None))[["gvkey", "datadate", "be"]]
    roe = quarterly_roe(
        read_extract(config, "comp_fundq"),
        annual_be=annual_be,
        crsp_shares=crsp_shares_by_gvkey(inputs.panel, inputs.candidates),
    )
    companies = company_panel(inputs.panel)
    print(f"  {len(roe):,} firm-quarters with a usable ROE ({time.time() - t0:.0f}s)", flush=True)

    print("sorting 2 x 3 x 3 monthly ...", flush=True)
    years = range(FIRST_FORMATION_YEAR, int(LAST_MONTH[:4]) + 1)
    portfolios, counts = q_portfolios(inputs.panel, companies, inputs.candidates,
                                      characteristics, roe, years)
    cut = pd.Period(LAST_MONTH, "M")
    portfolios, counts = portfolios.loc[:cut], counts.loc[:cut]
    ours = q_factors(portfolios)
    print(f"  done ({time.time() - t0:.0f}s)", flush=True)

    ff_bottom_up = pd.read_csv(config.results / "bottom_up" / "factors.csv", index_col=0)
    ff_bottom_up.index = pd.PeriodIndex(ff_bottom_up.index, freq="M", name="month")
    ours["MKT"] = ff_bottom_up["Mkt-RF"].reindex(ours.index)

    portfolios.to_csv(out_dir / "portfolios_18.csv")
    counts.to_csv(out_dir / "counts_18.csv")
    ours.to_csv(out_dir / "q_factors.csv")

    gq = load_global_q(config)
    table = fit_table(ours, gq.factors, WINDOWS, {"ME": "ME", "IA": "IA", "ROE": "ROE", "MKT": "MKT"})
    table.to_csv(out_dir / "comparison.csv", index=False)
    print("\n" + "=" * 100)
    print("q-FACTORS vs global-q.org")
    print("=" * 100)
    cols = ["series", "window", "n", "corr", "slope", "mean_diff_bps", "te_bps"]
    print(table[cols].to_string(index=False, float_format=lambda x: f"{x:,.4f}"))

    window = slice("1967-01", "2024-12")
    ratio = counts.loc[window].sum() / gq.counts.loc[window].sum()
    port_fit = fit_table(portfolios, gq.portfolios, {"1967-2024": ("1967-01", "2024-12")})
    port_fit["count_ratio"] = port_fit["series"].map(ratio)
    port_fit.to_csv(out_dir / "portfolio_comparison.csv", index=False)
    print("\n18 benchmark portfolios, 1967-2024: return corr, TE (bps) and firm-count ratio")
    print(port_fit[["series", "corr", "te_bps", "count_ratio"]].to_string(
        index=False, float_format=lambda x: f"{x:,.3f}"))

    # --- spanning tests, both directions ------------------------------------
    french = load_published(config, "fiz202412").factors
    ff5_pub = french[["Mkt-RF", "SMB5", "HML", "RMW", "CMA"]]
    ff6_pub = ff5_pub.join(french["UMD"])
    q_pub = gq.factors[["MKT", "ME", "IA", "ROE"]]

    ff5_ours = ff_bottom_up[["Mkt-RF", "SMB5", "HML", "RMW", "CMA"]]
    ff6_ours = ff5_ours.join(ff_bottom_up["UMD"])
    q_ours = ours[["MKT", "ME", "IA", "ROE"]]

    span = SPANNING_WINDOW
    cases = [
        ("published: q on FF5", gq.factors[["ME", "IA", "ROE"]], ff5_pub),
        ("published: q on FF6", gq.factors[["ME", "IA", "ROE"]], ff6_pub),
        ("published: FF on q", french[["SMB5", "HML", "RMW", "CMA", "UMD"]], q_pub),
        ("bottom-up: q on FF5", ours[["ME", "IA", "ROE"]], ff5_ours),
        ("bottom-up: q on FF6", ours[["ME", "IA", "ROE"]], ff6_ours),
        ("bottom-up: FF on q", ff_bottom_up[["SMB5", "HML", "RMW", "CMA", "UMD"]], q_ours),
    ]
    alphas, joint = [], []
    for name, targets, model in cases:
        a, j = spanning(targets.loc[span], model.loc[span], name=name)
        alphas.append(a)
        joint.append(j)
    alphas = pd.concat(alphas, ignore_index=True)
    joint = pd.DataFrame(joint)
    alphas.to_csv(out_dir / "spanning_alphas.csv", index=False)
    joint.to_csv(out_dir / "spanning_grs.csv", index=False)

    print("\n" + "=" * 100)
    print("SPANNING — monthly alpha (%) with Newey-West t, 1967-2024")
    print("=" * 100)
    print(alphas.to_string(index=False, float_format=lambda x: f"{x:,.3f}"))
    print("\nGRS (all target factors jointly):")
    print(joint.to_string(index=False, float_format=lambda x: f"{x:,.4f}"))
    print(f"\nwrote {out_dir}  ({time.time() - t0:.0f}s total)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
