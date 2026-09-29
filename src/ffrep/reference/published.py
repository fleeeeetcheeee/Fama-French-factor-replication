"""
French's published series, in the shape the bottom-up build produces.

The build labels every 2x3 portfolio set ``SL SM SH BL BM BH`` — size first,
then the low / middle / high third of the second characteristic — and indexes
by calendar month. French's files use a different name per sort ("SMALL LoBM",
"BIG HiOP", ...) and month-end dates. This module is the one place the two are
reconciled, so a comparison can never pair SmallGrowth with SmallValue by
misreading a label: the direction of every sort is fixed here once.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ffrep.config import Config
from ffrep.evaluate.compare import to_monthly
from ffrep.reference.parser import (
    SIX_BEME_PORTFOLIOS,
    SIX_INV_PORTFOLIOS,
    SIX_OP_PORTFOLIOS,
    SIX_PRIOR_PORTFOLIOS,
    load_factors,
    load_firm_counts,
    load_six_portfolios,
)

#: Build labels in French's reporting order, per sort, and the French column
#: each corresponds to. L is always the low third of the characteristic.
_ORDER = ("SL", "SM", "SH", "BL", "BM", "BH")
SORTS: dict[str, tuple[str, dict[str, str]]] = {
    "beme": ("portfolios_6_beme", SIX_BEME_PORTFOLIOS),
    "op": ("portfolios_6_op", SIX_OP_PORTFOLIOS),
    "inv": ("portfolios_6_inv", SIX_INV_PORTFOLIOS),
    "prior": ("portfolios_6_prior", SIX_PRIOR_PORTFOLIOS),
}


def _relabel(frame: pd.DataFrame, names: dict[str, str]) -> pd.DataFrame:
    """French's column order is the same for every sort: S-low, S-mid, S-high, B-..."""
    mapping = dict(zip(names.values(), _ORDER))
    return to_monthly(frame.rename(columns=mapping)[list(_ORDER)])


@dataclass
class Published:
    vintage: str
    factors: pd.DataFrame                 # Mkt-RF, SMB (3-factor), HML, RMW, CMA, SMB5, UMD, RF
    portfolios: dict[str, pd.DataFrame]   # sort -> months x SL..BH, value weighted
    counts: dict[str, pd.DataFrame]       # sort -> months x SL..BH


def load_published(config: Config, vintage: str = "fiz202412") -> Published:
    three = to_monthly(load_factors(config.french_path("factors_3", vintage)))
    five = to_monthly(load_factors(config.french_path("factors_5", vintage)))
    mom = to_monthly(load_factors(config.french_path("momentum", vintage)))

    factors = pd.DataFrame({
        "Mkt-RF": three["Mkt-RF"],
        "SMB": three["SMB"],
        "HML": three["HML"],
        "RF": three["RF"],
    })
    factors = factors.join(five[["RMW", "CMA"]], how="outer")
    factors["SMB5"] = five["SMB"]
    factors["HML5"] = five["HML"]
    factors = factors.join(mom.rename(columns={mom.columns[0]: "UMD"}), how="outer")

    portfolios, counts = {}, {}
    for sort, (key, names) in SORTS.items():
        path = config.french_path(key, vintage)
        portfolios[sort] = _relabel(load_six_portfolios(path, weighting="value", names=names), names)
        counts[sort] = _relabel(load_firm_counts(path, names=names), names)
    return Published(vintage=vintage, factors=factors, portfolios=portfolios, counts=counts)


@dataclass
class GlobalQ:
    factors: pd.DataFrame      # MKT (excess), ME, IA, ROE, EG, RF — decimal
    portfolios: pd.DataFrame   # months x "111".."233", value-weighted, decimal
    counts: pd.DataFrame       # months x "111".."233"


def load_global_q(config: Config) -> GlobalQ:
    """
    Hou-Xue-Zhang's published q5 factors and 18 benchmark portfolios.

    Both files are in percent and indexed by separate ``year``/``month``
    columns. Portfolio ranks are ascending — size 1 is small; I/A and ROE 1 are
    low — and are joined into the same ``"{size}{ia}{roe}"`` labels the build
    uses.
    """
    raw = pd.read_csv(config.global_q_path("factors"))
    index = pd.PeriodIndex.from_fields(year=raw["year"], month=raw["month"], freq="M").rename("month")
    factors = pd.DataFrame({
        "MKT": raw["R_MKT"].to_numpy(), "ME": raw["R_ME"].to_numpy(), "IA": raw["R_IA"].to_numpy(),
        "ROE": raw["R_ROE"].to_numpy(), "EG": raw["R_EG"].to_numpy(), "RF": raw["R_F"].to_numpy(),
    }, index=index) / 100.0

    ports = pd.read_csv(config.global_q_path("portfolios"))
    ports["month"] = pd.PeriodIndex.from_fields(year=ports["year"], month=ports["month"], freq="M")
    ports["label"] = (ports["rank_ME"].astype(str) + ports["rank_IA"].astype(str)
                      + ports["rank_ROE"].astype(str))
    returns = ports.pivot(index="month", columns="label", values="ret_vw") / 100.0
    counts = ports.pivot(index="month", columns="label", values="nstocks")
    return GlobalQ(factors=factors, portfolios=returns, counts=counts)
