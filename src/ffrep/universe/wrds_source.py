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
from typing import Any, Callable

import pandas as pd

from ffrep.config import NYSE_EXCHANGE_CODES

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


#: WRDS's PostgreSQL endpoint. Public connection details, not credentials.
WRDS_HOST = "wrds-pgdata.wharton.upenn.edu"
WRDS_PORT = 9737
WRDS_DATABASE = "wrds"

#: The WRDS server intermittently refuses the first connection of a session.
#: Observed twice; both times the immediate retry succeeded.
CONNECT_ATTEMPTS = 3

#: Seconds between connection attempts.
CONNECT_BACKOFF_SECONDS = 2.0

#: How long one login may take. WRDS logins can wait on a Duo push to the
#: account holder's phone, so this is generous; without any timeout a login
#: nobody approves hangs forever.
CONNECT_TIMEOUT_SECONDS = 120

#: TCP keepalives, so a connection the server drops mid-query raises within a
#: couple of minutes instead of blocking on a dead socket.
KEEPALIVE_ARGS = {"keepalives": 1, "keepalives_idle": 60, "keepalives_interval": 15, "keepalives_count": 4}


class WrdsConnection:
    """
    The two operations this project needs from WRDS, over plain SQLAlchemy.

    This replaces the ``wrds`` package, which this project used for exactly
    ``Connection(...)``, ``raw_sql(...)`` and ``close()``. Two costs of keeping
    it were measured, not assumed: every release pins ``pandas<2.3`` (3.5.0, the
    newest, included), so it could only be installed with ``--no-deps`` against
    the pandas 3 this project is verified on and ``pip check`` failed; and when a
    login fails it falls back to an interactive ``input()`` prompt, which hung a
    background extract indefinitely. A bare SQLAlchemy engine has neither
    problem, and the password still comes only from ``~/.pgpass``.

    ``raw_sql`` returns numpy dtypes (``coerce_float`` turns Postgres NUMERIC into
    float) — not the nullable ``Float64``/``Int64`` the ``wrds`` package produced.
    """

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def raw_sql(self, sql: str, date_cols: list[str] | None = None) -> pd.DataFrame:
        with self._engine.connect() as conn:
            return pd.read_sql_query(sql, conn, parse_dates=date_cols, coerce_float=True)

    def close(self) -> None:
        self._engine.dispose()


def _retryable() -> tuple[type[BaseException], ...]:
    try:
        from sqlalchemy.exc import OperationalError
    except ImportError:  # the offline test suite runs without the WRDS extras
        return (OSError,)
    return (OSError, OperationalError)


def _create_engine(username: str) -> Any:
    from sqlalchemy import create_engine
    from sqlalchemy.engine import URL

    url = URL.create(
        "postgresql+psycopg2",
        username=username,          # no password: libpq reads ~/.pgpass
        host=WRDS_HOST,
        port=WRDS_PORT,
        database=WRDS_DATABASE,
        query={"sslmode": "require"},
    )
    return create_engine(
        url, connect_args={"connect_timeout": CONNECT_TIMEOUT_SECONDS, **KEEPALIVE_ARGS}
    )


def connect(
    username: str,
    *,
    attempts: int = CONNECT_ATTEMPTS,
    engine_factory: Callable[[str], Any] = _create_engine,
) -> WrdsConnection:
    """
    Open a WRDS connection, retrying a flaky first handshake.

    Credentials come from ``~/.pgpass`` (mode 0600). Nothing in this repo reads,
    stores, or logs a password, and no extract is ever committed — WRDS data
    cannot be redistributed, so ``data/processed/`` stays gitignored and only
    derived factor series are versioned.

    A login is verified with ``select 1`` before it is returned, so a refused
    handshake is retried here rather than surfacing inside the first query.
    """
    import time

    last: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            engine = engine_factory(username)
            with engine.connect() as conn:
                conn.exec_driver_sql("select 1")
            return WrdsConnection(engine)
        except _retryable() as exc:
            last = exc
            if attempt < attempts:
                time.sleep(CONNECT_BACKOFF_SECONDS)

    raise ConnectionError(
        f"could not connect to WRDS as {username!r} after {attempts} attempts. "
        f"Check ~/.pgpass (mode 0600, host {WRDS_HOST}:{WRDS_PORT}) and approve the "
        f"Duo push if one was sent. Last error: {last!r}"
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


#: Months whose cross-sections the annual sorts need: June (size sort and value
#: weights) and December (the BE/ME denominator). Pulling only these is what
#: makes a whole-history NYSE extract cheap enough to run interactively —
#: 318,114 security-months against roughly 1.9m for every month.
ANNUAL_SORT_MONTHS: tuple[int, ...] = (6, 12)


def fetch_nyse_month_ends(
    db: Any, months: tuple[int, ...] = ANNUAL_SORT_MONTHS
) -> pd.DataFrame:
    """
    NYSE cross-sections for the given calendar months, over all of CRSP.

    The breakpoint universe, and nothing else: exchange is filtered in SQL
    because NYSE is under a tenth of the rows and pulling the rest to discard
    them in pandas is the difference between a minute and twenty.

    Deliberately not date-bounded. The comparison against French's published
    breakpoints is strongest on the decades old enough that CRSP cannot have
    been restated since, so the whole history is the point.
    """
    month_list = ", ".join(str(int(m)) for m in months)
    exchanges = ", ".join(str(c) for c in NYSE_EXCHANGE_CODES)
    return db.raw_sql(
        f"""
        select a.permno, a.permco, a.date, a.prc, a.shrout, a.ret, a.retx,
               b.shrcd, b.exchcd, b.siccd, b.comnam, b.cusip, b.ncusip
        from crsp.msf a
        join crsp.msenames b
          on a.permno = b.permno
         and b.namedt <= a.date
         and a.date <= b.nameendt
        where b.exchcd in ({exchanges})
          and extract(month from a.date) in ({month_list})
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


def fetch_fundamentals(
    db: Any, window: ExtractWindow | None = None
) -> pd.DataFrame:
    """
    Compustat annual fundamentals, restricted to the standard consolidated view.

    ``window`` is optional because the book-equity validation wants all of it:
    528,573 firm-years back to 1950, which is a few hundred MB and the only
    honest way to compare against breakpoints French publishes from 1926.
    """
    cols = ", ".join(FUNDA_FIELDS)
    bounds = (
        f"datadate between '{window.start}' and '{window.end}' and "
        if window is not None
        else ""
    )
    return db.raw_sql(
        f"""
        select {cols}
        from comp.funda
        where {bounds}{FUNDA_FILTER}
        """,
        date_cols=["datadate"],
    )


#: Compustat quarterly fields for the Hou-Xue-Zhang ROE factor: earnings, the
#: quarterly book-equity hierarchy (same shape as the annual one), and ``rdq`` —
#: the earnings announcement date, which is what makes ROE point-in-time.
#: Every name verified against ``information_schema`` before this was written.
FUNDQ_FIELDS: tuple[str, ...] = (
    "gvkey", "datadate", "fyearq", "fqtr", "fyr", "rdq", "cusip",
    "indfmt", "datafmt", "popsrc", "consol", "curcdq",
    "ibq",                                        # income before extraordinary items
    "dvpsxq", "cshoq", "ajexq",                   # dividends/share, shares, split factor:
                                                  # the clean-surplus book-equity imputation
    "seqq", "ceqq", "pstkq", "atq", "ltq",        # stockholders' equity hierarchy
    "pstkrq",                                     # preferred stock, redemption value
    "txditcq",                                    # deferred taxes and ITC
)

#: The quarterly counterpart of ``FUNDA_FILTER``. The currency field is named
#: ``curcdq`` in ``fundq``, not ``curcd``.
FUNDQ_FILTER = (
    "indfmt='INDL' and datafmt='STD' and popsrc='D' and consol='C' and curcdq='USD'"
)


def fetch_quarterly_fundamentals(
    db: Any, window: ExtractWindow | None = None
) -> pd.DataFrame:
    """Compustat quarterly fundamentals, for the q-factor ROE sort."""
    cols = ", ".join(FUNDQ_FIELDS)
    bounds = (
        f"datadate between '{window.start}' and '{window.end}' and "
        if window is not None
        else ""
    )
    return db.raw_sql(
        f"""
        select {cols}
        from comp.fundq
        where {bounds}{FUNDQ_FILTER}
        """,
        date_cols=["datadate", "rdq"],
    )


def fetch_name_history(db: Any) -> pd.DataFrame:
    """
    Every CRSP name record, with its effective dates.

    The dated version of ``fetch_cusip_history``: the link diagnostics need to
    know *when* a PERMNO carried a CUSIP, not just that it once did.
    """
    return db.raw_sql(
        """
        select permno, permco, namedt, nameendt, cusip, ncusip,
               shrcd, exchcd, siccd, comnam
        from crsp.msenames
        """,
        date_cols=["namedt", "nameendt"],
    )


def fetch_compustat_securities(db: Any) -> pd.DataFrame:
    """
    Every security issue Compustat records for a company.

    ``funda.cusip`` carries one CUSIP per company — its current primary issue.
    ``comp.security`` carries every issue, including other share classes and
    retired ones, so it can reach CRSP securities the header CUSIP cannot.
    """
    return db.raw_sql(
        """
        select gvkey, iid, cusip, tic, excntry, dldtei, tpci, exchg
        from comp.security
        """,
        date_cols=["dldtei"],
    )


def missing_columns(db: Any, schema: str, table: str, columns: tuple[str, ...]) -> list[str]:
    """
    Which of ``columns`` the live table does not have.

    Checked against ``information_schema`` before an extract runs, because
    writing queries against assumed column names has cost this project time
    twice. ``schema`` and ``table`` are module constants, never user input.
    """
    present = set(
        db.raw_sql(
            "select column_name from information_schema.columns "
            f"where table_schema = '{schema}' and table_name = '{table}'"
        )["column_name"]
    )
    return [c for c in columns if c not in present]
