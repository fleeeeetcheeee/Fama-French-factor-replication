"""
Step 1 — the ceiling on a truncated-universe replication.

Answers, from French's published data alone and before any firm-level data is
assembled: how well can an HML built without small-cap stocks possibly track the
real one? If that bound is well below 0.99, no amount of care downstream reaches
0.99, and the project's target has to be reconsidered rather than pursued.

    python scripts/ceiling_analysis.py
"""

from __future__ import annotations

import sys

import pandas as pd

from ffrep.config import Config
from ffrep.evaluate.ceiling import run


def main() -> int:
    pd.set_option("display.width", 200)
    config = Config()

    for key in ("portfolios_6_beme", "factors_3"):
        if not config.french_path(key).exists():
            print(
                f"missing {config.french_path(key)}\n"
                f"Run: python scripts/fetch_reference_data.py"
            )
            return 1

    table = run(
        config.french_path("portfolios_6_beme"), config.french_path("factors_3")
    )

    print("Ceiling on a truncated-universe HML replication")
    print("=" * 96)
    print(table.to_string(index=False))
    print()
    print(
        "corr           empirical correlation with French's published factor\n"
        "beta           slope of published ~ constructed\n"
        "mean_gap_bps   mean(constructed - published), basis points per month\n"
        "TE_bps         standard deviation of that gap\n"
        "analytic_corr  the closed form, from rho and the two spread volatilities"
    )

    config.results.mkdir(parents=True, exist_ok=True)
    destination = config.results / "ceiling_analysis.csv"
    table.to_csv(destination, index=False)
    print(f"\nwritten to {destination}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
