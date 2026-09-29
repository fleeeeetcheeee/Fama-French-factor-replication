"""
The monthly security panel every construction step reads from.

One row per (PERMNO, calendar month), carrying market equity and the
delisting-adjusted return. Built once from the raw ``msf`` extract and the
delisting file, then sliced: the June and December company cross-sections for
the annual sorts, the prior-return windows for momentum, and the twelve holding
months after each formation.

Months, not dates, are the key. ``msf`` stamps each row with the month's last
*trading* day (1990-06-29, not 1990-06-30), delistings carry whatever day the
security left, and French's files are indexed by ``YYYYMM``. Joining any two of
those on a date is how a delisting return goes missing (review finding R12);
joining on the calendar month is how it does not.
"""

from __future__ import annotations

import pandas as pd

from ffrep.config import LISTED_EXCHANGE_CODES
from ffrep.universe.delisting import apply_delisting_returns
from ffrep.universe.screen import aggregate_to_company, apply_share_screen, market_equity


def security_panel(
    msf: pd.DataFrame, delist: pd.DataFrame, *, add_terminal_rows: bool = True
) -> pd.DataFrame:
    """
    Monthly CRSP rows with delisting returns folded in and a ``month`` column.

    ``ret`` becomes the delisting-adjusted return; a delisting in a month after
    the security's last ``msf`` row becomes a terminal row of its own (see
    ``apply_delisting_returns``). ``me`` is market equity in $ millions, NaN
    where price or shares are missing — terminal rows have neither.

    Duplicate (PERMNO, date) rows would double a firm's weight silently, so they
    raise rather than being dropped: the name-window join that produces ``msf``
    was verified to produce none, and a future extract that does is a bug to
    find, not to paper over.
    """
    duplicated = msf.duplicated(subset=["permno", "date"])
    if duplicated.any():
        raise ValueError(
            f"{int(duplicated.sum())} duplicate (permno, date) rows in the monthly "
            f"extract; check the msenames name-window join"
        )

    frame = apply_delisting_returns(msf, delist, add_terminal_rows=add_terminal_rows)
    frame["month"] = pd.to_datetime(frame["date"]).dt.to_period("M")
    frame["me"] = market_equity(frame)
    return frame.sort_values(["permno", "month"], kind="stable").reset_index(drop=True)


def company_cross_section(
    panel: pd.DataFrame,
    month: pd.Period,
    *,
    exchanges: tuple[int, ...] = LISTED_EXCHANGE_CODES,
) -> pd.DataFrame:
    """
    The screened, company-level cross-section for one month.

    Share screen first, then aggregation to PERMCO — the order that keeps a
    blank-check company's market equity out of a real company's total. One row
    per PERMCO, carried on its largest security, with ``me`` the company total.
    """
    rows = panel.loc[panel["month"] == month]
    return aggregate_to_company(apply_share_screen(rows, exchanges=exchanges))


def wide(
    panel: pd.DataFrame,
    column: str,
    months: pd.PeriodIndex,
    permnos: pd.Index,
) -> pd.DataFrame:
    """
    ``column`` as a months x PERMNO frame, restricted to the given months and
    securities. Absent (PERMNO, month) pairs are NaN — which is what the
    portfolio drift logic reads as "no observation".
    """
    rows = panel.loc[panel["month"].isin(months) & panel["permno"].isin(permnos),
                     ["month", "permno", column]]
    out = rows.pivot(index="month", columns="permno", values=column)
    return out.reindex(index=months, columns=permnos)
