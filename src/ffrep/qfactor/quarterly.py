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

Missing book equity is imputed as HXZ describe, in their order
-----------------------------------------------------------------
Quarterly balance sheets are sparse before 1972 — book equity exists for 5-30%
of firm-quarters in 1963-1970 while earnings exist for 87-97% — so without
imputation almost no firm has an ROE before HXZ's 1972 start. Their document:

1. "We first use quarterly book equity from Compustat quarterly files. We then
   supplement the coverage for fiscal quarter four with book equity from
   Compustat annual files."
2. "If available, we backward impute beginning-of-quarter book equity as
   end-of-quarter book equity minus quarterly earnings plus quarterly dividends."
3. Otherwise forward: ``BEQ_t = BEQ_{t-j} + IBQ_{t-j+1..t} - DVQ_{t-j+1..t}``,
   ``1 <= j <= 4`` — "We do not use prior book equity from more than four
   quarters ago."

Quarterly dividends are dividends per share (``DVPSXQ``) times beginning-of-
quarter shares, adjusted for splits within the quarter by the ratio of
``AJEXQ``; zero when ``DVPSXQ`` is zero. Shares come from ``CSHOQ`` and, where
that is missing (58% of firm-quarters before 1972), from CRSP's shares
outstanding for the linked company — HXZ use the same two sources. A dividend
that cannot be computed leaves the imputation undone rather than guessed.

All quarter arithmetic runs on a complete per-firm quarter grid, so "the
previous quarter" is always the calendar-consecutive one, never merely the
previous record.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

#: Portfolios held from this month on use announced earnings (HXZ 2015). Before
#: it — HXZ's 2019 extension back to 1967 — every quarter counts as usable
#: ``PRE_RDQ_LAG_MONTHS`` after its end, announcement date or not: "we use the
#: most recent quarterly earnings from the fiscal quarter ending at least four
#: months prior to the portfolio formation month." The switch is keyed to the
#: portfolio month, not the quarter, so a 1971 quarter without an ``rdq`` does
#: not keep qualifying in 1972.
RDQ_REQUIRED_FROM = pd.Period("1972-01", "M")

#: The pre-1972 availability lag, in months after the fiscal quarter end.
PRE_RDQ_LAG_MONTHS = 4

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


#: How far back the forward imputation may reach, in quarters.
MAX_FORWARD_QUARTERS = 4


def _dedupe(fundq: pd.DataFrame) -> pd.DataFrame:
    q = fundq.dropna(subset=["gvkey", "datadate", "fyearq", "fqtr"]).copy()
    q = q.sort_values(["gvkey", "fyearq", "fqtr", "datadate"])
    q = q.drop_duplicates(subset=["gvkey", "fyearq", "fqtr"], keep="last")
    q["quarter"] = q["fyearq"].astype(int) * 4 + q["fqtr"].astype(int)
    return q.reset_index(drop=True)


def _grid(q: pd.DataFrame, columns: list[str]) -> pd.DataFrame:
    """``columns`` on a complete (gvkey, quarter) grid spanning each firm's records."""
    spans = q.groupby("gvkey")["quarter"].agg(["min", "max"])
    lengths = (spans["max"] - spans["min"] + 1).to_numpy()
    gvkeys = np.repeat(spans.index.to_numpy(), lengths)
    starts = np.repeat(spans["min"].to_numpy(), lengths)
    offsets = np.arange(lengths.sum()) - np.repeat(np.cumsum(lengths) - lengths, lengths)
    index = pd.MultiIndex.from_arrays([gvkeys, starts + offsets], names=["gvkey", "quarter"])
    return q.set_index(["gvkey", "quarter"])[columns].reindex(index)


def lagged_book_equity(q: pd.DataFrame, *, impute: bool = True) -> pd.Series:
    """
    Book equity at the end of the previous fiscal quarter, for each row of ``q``.

    ``q`` carries ``gvkey``, ``quarter``, ``beq`` (reported, Q4 already filled
    from the annual file), ``ibq`` and ``dvq``. With ``impute=False`` only the
    reported previous-quarter value is used.
    """
    g = _grid(q, ["beq", "ibq", "dvq"])
    by_firm = g.groupby(level="gvkey")
    lag = by_firm["beq"].shift(1)
    if impute:
        backward = g["beq"] - g["ibq"] + g["dvq"]
        lag = lag.fillna(backward)
        # BE[t-1] = BE[t-1-j] + (IBQ - DVQ) summed over quarters t-j .. t-1.
        flow_by_firm = (g["ibq"] - g["dvq"]).groupby(level="gvkey")
        accumulated = pd.Series(0.0, index=g.index)
        for j in range(1, MAX_FORWARD_QUARTERS + 1):
            accumulated = accumulated + flow_by_firm.shift(j)
            lag = lag.fillna(by_firm["beq"].shift(j + 1) + accumulated)
    keys = pd.MultiIndex.from_arrays([q["gvkey"], q["quarter"]])
    return pd.Series(lag.reindex(keys).to_numpy(), index=q.index, name="lag_beq")


def quarterly_dividends(q: pd.DataFrame) -> pd.Series:
    """
    ``DVPSXQ`` x beginning-of-quarter shares, split-adjusted: millions of $.

    Beginning-of-quarter shares are the previous quarter's ``shares`` scaled by
    ``AJEXQ[t-1] / AJEXQ[t]`` — a 2-for-1 split during the quarter doubles them.
    Zero dividends per share means zero dividends whatever the share count.
    """
    g = _grid(q, ["dvpsxq", "shares", "ajexq"])
    by_firm = g.groupby(level="gvkey")
    ratio = (by_firm["ajexq"].shift(1) / g["ajexq"]).where(g["ajexq"] > 0)
    begin_shares = by_firm["shares"].shift(1) * ratio.fillna(1.0)
    dv = (g["dvpsxq"] * begin_shares).where(g["dvpsxq"] != 0, 0.0)
    dv = dv.where(g["dvpsxq"].notna())
    keys = pd.MultiIndex.from_arrays([q["gvkey"], q["quarter"]])
    return pd.Series(dv.reindex(keys).to_numpy(), index=q.index, name="dvq")


def quarterly_roe(
    fundq: pd.DataFrame,
    *,
    annual_be: pd.DataFrame | None = None,
    crsp_shares: pd.DataFrame | None = None,
    impute: bool = True,
) -> pd.DataFrame:
    """
    One row per (GVKEY, fiscal quarter): ROE, and the date it became usable.

    ``annual_be`` (``gvkey``, ``datadate``, ``be``) fills fourth-quarter book
    equity; ``crsp_shares`` (``gvkey``, ``month``, ``shares`` in millions) fills
    missing ``CSHOQ`` for the dividend calculation. ``impute=False`` reproduces
    the reported-data-only ROE, for ablation.
    """
    q = _dedupe(fundq)
    q["beq"] = quarterly_book_equity(q)

    if annual_be is not None:
        annual = annual_be.dropna(subset=["be"]).drop_duplicates(["gvkey", "datadate"], keep="last")
        q4 = q.merge(annual[["gvkey", "datadate", "be"]], on=["gvkey", "datadate"], how="left")["be"].to_numpy()
        q["beq"] = q["beq"].fillna(pd.Series(q4, index=q.index).where(q["fqtr"] == 4))

    q["shares"] = _col(q, "cshoq")
    if crsp_shares is not None:
        month = pd.to_datetime(q["datadate"]).dt.to_period("M")
        fallback = pd.DataFrame({"gvkey": q["gvkey"], "month": month}).merge(
            crsp_shares, on=["gvkey", "month"], how="left")["shares"].to_numpy()
        q["shares"] = q["shares"].fillna(pd.Series(fallback, index=q.index))
    q["dvpsxq"] = _col(q, "dvpsxq")
    q["ajexq"] = _col(q, "ajexq")
    q["ibq"] = _col(q, "ibq")
    q["dvq"] = quarterly_dividends(q)

    lag = lagged_book_equity(q, impute=impute)
    q["roe"] = q["ibq"] / lag.where(lag > 0)

    datadate = pd.to_datetime(q["datadate"])
    rdq = pd.to_datetime(q["rdq"]) if "rdq" in q.columns else pd.Series(pd.NaT, index=q.index)
    q["available"] = rdq.where(rdq > datadate)
    q["available_lagged"] = datadate + pd.DateOffset(months=PRE_RDQ_LAG_MONTHS)

    out = q.loc[q["roe"].notna(), ["gvkey", "datadate", "available", "available_lagged", "roe", "beq"]]
    return out.reset_index(drop=True)


def crsp_shares_by_gvkey(panel: pd.DataFrame, candidates: pd.DataFrame) -> pd.DataFrame:
    """
    Company shares outstanding (millions) by GVKEY and month, from CRSP.

    Each GVKEY takes the company its strongest CUSIP path reaches — a static
    link, adequate for a share-count fallback where Compustat has none.
    """
    best = candidates.sort_values(["gvkey", "rank", "permco"]).drop_duplicates("gvkey")[["gvkey", "permco"]]
    shares = (panel.dropna(subset=["shrout"]).groupby(["permco", "month"])["shrout"].sum() / 1000.0)
    shares = shares.rename("shares").reset_index()
    return best.merge(shares, on="permco")[["gvkey", "month", "shares"]]


def roe_as_of(roe: pd.DataFrame, requests: pd.DataFrame) -> pd.Series:
    """
    The ROE each (GVKEY, formation month) would have used.

    ``requests`` carries ``gvkey`` and ``month`` (the formation month s, i.e.
    the end of t-1). A quarter qualifies if it became available on or before the
    last day of s — its announcement date for portfolios held from January 1972,
    four months after quarter end before then — and the *most recent*
    qualifying quarter is used, provided its fiscal quarter ended within six
    months of formation; a stale latest quarter yields NaN rather than falling
    back to an older one.

    Returned aligned to ``requests.index``.
    """
    left = requests[["gvkey", "month"]].copy()
    left["_row"] = np.arange(len(left))
    # merge_asof needs both keys at one resolution; pandas 3 makes Period ->
    # Timestamp microseconds while stored dates are nanoseconds.
    left["asof"] = left["month"].dt.to_timestamp(how="end").dt.normalize().astype("datetime64[ns]")
    announced_era = (left["month"] + 1) >= RDQ_REQUIRED_FROM

    out = pd.Series(np.nan, index=range(len(left)))
    for era, key in ((True, "available"), (False, "available_lagged")):
        part = left[announced_era == era].sort_values("asof")
        if part.empty:
            continue
        right = roe.dropna(subset=[key]).sort_values(key)[["gvkey", key, "datadate", "roe"]]
        right = right.rename(columns={key: "asof_key"})
        right["asof_key"] = right["asof_key"].astype("datetime64[ns]")
        right["datadate"] = right["datadate"].astype("datetime64[ns]")
        matched = pd.merge_asof(
            part, right, left_on="asof", right_on="asof_key", by="gvkey", direction="backward"
        )
        fresh = matched["datadate"] >= matched["asof"] - pd.DateOffset(months=MAX_STALENESS_MONTHS)
        out.iloc[matched["_row"].to_numpy()] = matched["roe"].where(fresh).to_numpy()
    out.index = requests.index
    return out.rename("roe")
