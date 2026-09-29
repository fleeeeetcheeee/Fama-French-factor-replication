"""
Delisting returns: the correction that keeps the value leg honest.

When a stock leaves CRSP, its final partial-month return lives in a separate
file (``msedelist``), not in ``msf``. Ignoring it is the single most common
survivorship-flavoured error in factor replication, and it is not
sign-symmetric: firms delist for distress far more often than for triumph, and
value portfolios are disproportionately distressed firms. Dropping the delisting
month therefore inflates the value leg specifically, which is exactly the number
this project is trying to measure.

Shumway (1997) documented that performance-related delistings whose return CRSP
never recorded averaged about -30%, and that convention is what the literature
standardised on. Applying it is a judgement call made explicitly rather than a
gap left implicit — the whole reason it lives in its own module with its own
constant in ``config.py``.

Measured relevance here: of 29,106 delisting events in our CRSP subscription,
193 are performance-related with a missing return. Small, and applied anyway,
because the cost of the check is nil and the cost of the omission is a biased
factor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ffrep.config import PERFORMANCE_DELISTING_CODES, SHUMWAY_DELISTING_RETURN


def impute_delisting_return(
    dlret: pd.Series,
    dlstcd: pd.Series,
    *,
    shumway_return: float = SHUMWAY_DELISTING_RETURN,
) -> pd.Series:
    """
    Fill missing delisting returns.

    Performance-related codes get Shumway's -30%; everything else gets 0.0,
    which says "the delisting itself moved the price by nothing we know of" —
    appropriate for mergers and voluntary exchange moves, where the holder was
    generally made whole.

    Returns a new Series; inputs are not modified.
    """
    out = pd.to_numeric(dlret, errors="coerce").astype(float)
    codes = pd.to_numeric(dlstcd, errors="coerce")

    missing = out.isna()
    performance = codes.isin(PERFORMANCE_DELISTING_CODES)

    out = out.mask(missing & performance, shumway_return)
    out = out.mask(missing & ~performance, 0.0)
    return out


def compound_delisting(ret: pd.Series, dlret: pd.Series) -> pd.Series:
    """
    Combine a partial-month holding return with its delisting return.

    Compounded, never summed: the delisting return is measured *from* the last
    available price, so the two are sequential, not simultaneous. A missing
    ``ret`` with a present ``dlret`` yields the delisting return alone, which is
    the common case for a firm that stopped trading early in the month.
    """
    r = pd.to_numeric(ret, errors="coerce")
    d = pd.to_numeric(dlret, errors="coerce")

    both = (1.0 + r.fillna(0.0)) * (1.0 + d.fillna(0.0)) - 1.0
    # If neither leg exists there is no return, and 0.0 would be a fabrication.
    return both.mask(r.isna() & d.isna(), np.nan)


def apply_delisting_returns(
    monthly: pd.DataFrame,
    delist: pd.DataFrame,
    *,
    date_column: str = "date",
    add_terminal_rows: bool = True,
) -> pd.DataFrame:
    """
    Merge delisting returns onto a monthly panel and compound them into ``ret``.

    ``delist`` must carry ``permno``, a delisting date in ``date_column``,
    ``dlret`` and ``dlstcd``. Adds ``dlret``/``dlstcd`` columns so the
    adjustment stays auditable after the fact rather than being folded away
    invisibly — the same reason SIZ was chosen over CIZ.

    Matched on **calendar month**, not on date. ``msf`` stamps a row with the
    month's last trading day while ``dlstdt`` is whatever day the security left,
    so an exact-date join matches almost nothing: January 15 never equals
    January 31, and the delisting loss silently disappears (review finding R12).

    A delisting in a month *after* the security's last panel row has no row to
    compound into — the firm stopped trading before month end and ``msf`` never
    recorded that month. With ``add_terminal_rows`` such an event becomes a row
    of its own carrying ``ret = dlret`` and a missing ``retx``, so the final
    loss is applied to the beginning-of-month holding before the position is
    retired. Dropping it — what a left join does — is the same survivorship
    error this module exists to prevent. Events for securities absent from the
    panel entirely are not added: the panel's scope is the caller's decision.
    """
    if "ret" not in monthly.columns:
        raise KeyError("apply_delisting_returns expects a 'ret' column")

    events = delist.copy()
    events["dlret"] = impute_delisting_return(events["dlret"], events["dlstcd"])
    events["_month"] = pd.to_datetime(events[date_column]).dt.to_period("M")
    events = (
        events.sort_values(["permno", date_column])
        .drop_duplicates(subset=["permno", "_month"], keep="last")
    )

    out = monthly.copy()
    out["_month"] = pd.to_datetime(out[date_column]).dt.to_period("M")
    out = out.merge(
        events[["permno", "_month", "dlret", "dlstcd"]],
        on=["permno", "_month"],
        how="left",
    )
    has_event = out["dlret"].notna()
    out.loc[has_event, "ret"] = compound_delisting(
        out.loc[has_event, "ret"], out.loc[has_event, "dlret"]
    )

    if add_terminal_rows and len(events):
        last = out.groupby("permno")["_month"].max().rename("_last")
        pending = events.merge(last, left_on="permno", right_index=True, how="inner")
        pending = pending[pending["_month"] > pending["_last"]]
        if len(pending):
            terminal = pd.DataFrame({
                "permno": pending["permno"].to_numpy(),
                date_column: pending["_month"].dt.to_timestamp(how="end").dt.normalize().to_numpy(),
                "ret": pending["dlret"].to_numpy(),
                "dlret": pending["dlret"].to_numpy(),
                "dlstcd": pending["dlstcd"].to_numpy(),
                "_month": pending["_month"].to_numpy(),
            })
            if "retx" in out.columns:
                terminal["retx"] = np.nan
            out = pd.concat([out, terminal], ignore_index=True)
            out = out.sort_values(["permno", "_month"], kind="stable").reset_index(drop=True)

    return out.drop(columns="_month")
