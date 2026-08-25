"""
WRDS extraction: the only module in this project that talks to a network.

Kept deliberately thin. Everything here is a query and a rename; every decision
that could be wrong in an interesting way lives in ``screen.py``, ``delisting.py``
or ``linker.py``, where it can be tested against a hand-built cross-section
without a database. This module can only ever be integration-tested, so the less
judgement it carries the better.

Subscription reality, verified 2026-08-24/25 and not assumed:

* ``crsp.msf`` / ``msenames`` / ``msedelist`` (SIZ) — readable, history to 2024-12-31.
* ``crsp.msf_v2`` / ``stksecurityinfohist`` (CIZ) — readable; verified to give an
  identical NYSE median to SIZ, so SIZ is used and CIZ kept as a cross-check.
* ``comp.funda`` — readable, all 949 columns.
* ``crsp_a_ccm`` — **denied**, permanently. See ``linker.py``.

CRSP's coverage ending 2024-12-31 while French's published files are built from
the 202606 vintage is a real and unfixable asymmetry: any comparison window ends
2024-12, and French's numbers carry 18 further months of restatement we cannot
see.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

#: Compustat fields needed for Fama-French book equity, profitability and
#: investment. Pulling 26 of 949 columns rather than `select *` is the
#: difference between a few hundred MB and an extract that will not fit.
FUNDA_FIELDS: tuple[str, ...] = (
    "gvkey", "datadate", "fyear", "indfmt", "datafmt", "popsrc", "consol", "curcd",
    "cusip", "tic", "sich",
    "seq", "ceq", "pstk", "at", "lt", "mib",      # stockholders' equity hierarchy
    "pstkrv", "pstkl",                             # preferred stock hierarchy
    "txditc", "txdb", "itcb",                      # deferred taxes
    "revt", "cogs", "xsga", "xint",                # operating profitability
)

#: Compustat's standard filter for a single, comparable annual record per
#: firm-year. Omitting it returns restated and non-US duplicates, which
#: silently double-counts firms in the sort.
FUNDA_FILTER = (
    "indfmt='INDL' and datafmt='STD' and popsrc='D' and consol='C' and curcd='USD'"
)


@dataclass(frozen=True)
class ExtractWindow:
    """Inclusive date bounds for an extract."""

    start: str
    end: str

    def __post_init__(self) -> None:
        if pd.Timestamp(self.start) > pd.Timestamp(self.end):
            raise ValueError(f"start {self.start!r} is after end {self.end!r}")


#: The WRDS server intermittently refuses the first connection of a session.
#: Observed twice; both times the immediate retry succeeded.
CONNECT_ATTEMPTS = 3

#: Seconds between connection attempts.
CONNECT_BACKOFF_SECONDS = 2.0


def connect(username: str, *, attempts: int = CONNECT_ATTEMPTS) -> Any:
    """
    Open a WRDS connection, retrying a flaky first handshake.

    Credentials come from ``~/.pgpass`` (mode 0600). Nothing in this repo reads,
    stores, or logs a password, and no extract is ever committed — WRDS data
    cannot be redistributed, so ``data/`` stays gitignored and only derived
    factor series are versioned.

    The retry is not defensive padding. The WRDS server intermittently refuses
    the first connection, and the ``wrds`` package responds by falling back to
    an interactive ``input()`` prompt for credentials. Under any non-interactive
    caller — a script, a test, a scheduled job — that prompt raises ``EOFError``
    from inside the library, which is why ``EOFError`` is caught here alongside
    the connection errors: it is this library's way of reporting a failed
    handshake, not a real end-of-input.
    """
    import time

    import wrds  # imported lazily so the package imports without a network stack

    last: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return wrds.Connection(wrds_username=username)
        except (EOFError, OSError) as exc:
            last = exc
            if attempt < attempts:
                time.sleep(CONNECT_BACKOFF_SECONDS)

    raise ConnectionError(
        f"could not connect to WRDS as {username!r} after {attempts} attempts. "
        f"Check ~/.pgpass (mode 0600, host wrds-pgdata.wharton.upenn.edu:9737). "
        f"Last error: {last!r}"
    )


def fetch_monthly_stock(db: Any, window: ExtractWindow) -> pd.DataFrame:
    """
    CRSP monthly securities joined to their name record, over ``window``.

    The ``namedt``/``nameendt`` bounds are what make the join point-in-time: a
    security's share code, exchange and SIC all change over its life, and using
    the *current* name record would apply today's classification to 1990 —
    exactly the lookahead Project 01 exists to prevent, in a different guise.
    """
    return db.raw_sql(
        f"""
        select a.permno, a.permco, a.date, a.prc, a.shrout, a.ret, a.retx, a.vol,
               b.shrcd, b.exchcd, b.siccd, b.comnam, b.cusip, b.ncusip, b.ticker
        from crsp.msf a
        join crsp.msenames b
          on a.permno = b.permno
         and b.namedt <= a.date
         and a.date <= b.nameendt
        where a.date between '{window.start}' and '{window.end}'
        """,
        date_cols=["date"],
    )


def fetch_delistings(db: Any, window: ExtractWindow) -> pd.DataFrame:
    """CRSP delisting events, for the Shumway adjustment in ``delisting.py``."""
    return db.raw_sql(
        f"""
        select permno, dlstdt as date, dlret, dlstcd
        from crsp.msedelist
        where dlstdt between '{window.start}' and '{window.end}'
        """,
        date_cols=["date"],
    )


def fetch_cusip_history(db: Any) -> pd.DataFrame:
    """
    Every CUSIP each PERMNO has ever carried.

    Feeds ``CusipLinker(historical=...)``. Small enough to pull whole — there is
    no date filter because a firm's *current* Compustat CUSIP may correspond to
    a CRSP NCUSIP it stopped using years earlier.
    """
    return db.raw_sql("select distinct permno, cusip, ncusip from crsp.msenames")


def fetch_fundamentals(db: Any, window: ExtractWindow) -> pd.DataFrame:
    """Compustat annual fundamentals, restricted to the standard consolidated view."""
    cols = ", ".join(FUNDA_FIELDS)
    return db.raw_sql(
        f"""
        select {cols}
        from comp.funda
        where datadate between '{window.start}' and '{window.end}'
          and {FUNDA_FILTER}
        """,
        date_cols=["datadate"],
    )
