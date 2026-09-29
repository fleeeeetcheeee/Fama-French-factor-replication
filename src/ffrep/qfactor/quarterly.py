"""
Quarterly ROE, and the date each quarter's earnings became public.

Hou, Xue and Zhang's ROE factor is re-sorted every month on the most recently
*announced* quarterly earnings, which makes it the one factor here whose
point-in-time correctness rests on a filing date rather than a calendar rule.
Definitions follow the global-q.org technical document (July 2026):

    ROE  = IBQ / BE lagged one quarter
    BEQ  = SE + TXDITCQ - PS
    SE   = SEQQ, else CEQQ + PSTKQ, else ATQ - LTQ
    PS   = PSTKRQ, else PSTKQ

"Earnings data in Compustat quarterly files are used in the months immediately
after the most recent public quarterly earnings announcement dates (item RDQ)
... we require the end of the fiscal quarter that corresponds to its most
recently announced quarterly earnings to be within six months prior to the
portfolio formation." The 2015 paper adds that the announcement must fall after
the fiscal quarter end.

Before 1972 announcement dates are largely missing, and HXZ (2019) substitute
"the most recent quarterly earnings from the fiscal quarter ending at least four
months prior to the portfolio formation month". That rule is applied to pre-1972
quarters without an ``rdq``; from 1972 on a quarter without one is not used.

Simplification, stated rather than hidden: HXZ also fill missing quarterly book
equity from the annual file (fourth quarters) and by clean-surplus imputation
from dividends and share counts. Neither is implemented here, so this ROE
covers fewer firm-quarters than theirs — a coverage gap measured in the
comparison against global-q's published portfolio counts, not assumed away.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: HXZ (2019) back-fill rule for quarters without an announcement date.
PRE_RDQ_LAG_MONTHS = 4

#: From 1972 on, HXZ (2015) require a real announcement date.
RDQ_REQUIRED_FROM = pd.Timestamp("1972-01-01")

#: A quarter's earnings are stale once its fiscal quarter ended more than this
#: long before formation.
MAX_STALENESS_MONTHS = 6


def _col(frame: pd.DataFrame, name: str) -> pd.Series:
    if name not in frame.columns:
        return pd.Series(np.nan, index=frame.index, dtype=float)
    return pd.to_numeric(frame[name], errors="coerce")


def quarterly_book_equity(fundq: pd.DataFrame) -> pd.Series:
    """The quarterly Davis-Fama-French book equity, per the technical document."""
    ceq_branch = (_col(fundq, "ceqq") + _col(fundq, "pstkq").fillna(0.0)).where(_col(fundq, "ceqq").notna())
    se = _col(fundq, "seqq").fillna(ceq_branch).fillna(_col(fundq, "atq") - _col(fundq, "ltq"))
    ps = _col(fundq, "pstkrq").fillna(_col(fundq, "pstkq")).fillna(0.0)
    return (se + _col(fundq, "txditcq").fillna(0.0) - ps).rename("beq")


def quarterly_roe(fundq: pd.DataFrame) -> pd.DataFrame:
    """
    One row per (GVKEY, fiscal quarter): ROE, and the date it became usable.

    The lagged book equity must come from the *immediately preceding* fiscal
    quarter — a firm whose previous record is two quarters back gets no ROE,
    for the same reason annual investment requires consecutive years.
    """
    q = fundq.dropna(subset=["gvkey", "datadate", "fyearq", "fqtr"]).copy()
    q = q.sort_values(["gvkey", "fyearq", "fqtr", "datadate"])
    q = q.drop_duplicates(subset=["gvkey", "fyearq", "fqtr"], keep="last")
    q["beq"] = quarterly_book_equity(q)
    q["quarter"] = q["fyearq"].astype(int) * 4 + q["fqtr"].astype(int)

    grouped = q.groupby("gvkey")
    lag_beq = grouped["beq"].shift(1)
    consecutive = (q["quarter"] - grouped["quarter"].shift(1)) == 1
    lag_beq = lag_beq.where(consecutive & (lag_beq > 0))

    q["roe"] = _col(q, "ibq") / lag_beq

    datadate = pd.to_datetime(q["datadate"])
    rdq = pd.to_datetime(q["rdq"]) if "rdq" in q.columns else pd.Series(pd.NaT, index=q.index)
    announced = rdq.where(rdq > datadate)
    backfill = (datadate + pd.DateOffset(months=PRE_RDQ_LAG_MONTHS)).where(
        rdq.isna() & (datadate < RDQ_REQUIRED_FROM)
    )
    q["available"] = announced.fillna(backfill)

    out = q.loc[q["roe"].notna() & q["available"].notna(), ["gvkey", "datadate", "available", "roe"]]
    return out.reset_index(drop=True)


def roe_as_of(roe: pd.DataFrame, requests: pd.DataFrame) -> pd.Series:
    """
    The ROE each (GVKEY, formation month) would have used.

    ``requests`` carries ``gvkey`` and ``month`` (the formation month s, i.e.
    the end of t-1). A quarter qualifies if it became available on or before the
    last day of s, and the *most recent* qualifying quarter is used — provided
    its fiscal quarter ended within six months of formation; a stale latest
    quarter yields NaN rather than falling back to an older one.

    Returned aligned to ``requests.index``.
    """
    left = requests[["gvkey", "month"]].copy()
    left["_row"] = np.arange(len(left))
    left["asof"] = left["month"].dt.to_timestamp(how="end").dt.normalize()
    left = left.sort_values("asof")

    right = roe.sort_values("available")[["gvkey", "available", "datadate", "roe"]]
    right = right.rename(columns={"available": "asof_key"})
    matched = pd.merge_asof(
        left, right, left_on="asof", right_on="asof_key", by="gvkey", direction="backward"
    )
    fresh = matched["datadate"] >= matched["asof"] - pd.DateOffset(months=MAX_STALENESS_MONTHS)
    values = matched["roe"].where(fresh)
    out = pd.Series(np.nan, index=range(len(left)))
    out.iloc[matched["_row"].to_numpy()] = values.to_numpy()
    out.index = requests.index
    return out.rename("roe")
