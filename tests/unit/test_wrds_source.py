"""
Tests for the parts of the extraction layer that do not need a network.

`wrds_source` is deliberately thin, but two things in it are real logic and
worth pinning: the window guard, and the connection retry — which exists
because the `wrds` package reports a failed handshake by falling back to an
interactive prompt, and that prompt raises EOFError under any non-interactive
caller.
"""

from __future__ import annotations

import sys
import types

import pytest

from ffrep.config import NYSE_EXCHANGE_CODES
from ffrep.universe import wrds_source
from ffrep.universe.wrds_source import (
    ANNUAL_SORT_MONTHS,
    CONNECT_ATTEMPTS,
    ExtractWindow,
    fetch_delistings,
    fetch_fundamentals,
    fetch_nyse_month_ends,
    FUNDA_FIELDS,
    FUNDA_FILTER,
)


class TestExtractWindow:
    def test_accepts_an_ordered_window(self):
        w = ExtractWindow("1990-01-01", "2024-12-31")
        assert w.start == "1990-01-01"

    def test_rejects_a_reversed_window(self):
        with pytest.raises(ValueError, match="after end"):
            ExtractWindow("2024-01-01", "1990-01-01")

    def test_allows_a_single_day(self):
        assert ExtractWindow("2020-06-30", "2020-06-30").start == "2020-06-30"

    def test_is_frozen(self):
        w = ExtractWindow("1990-01-01", "1990-12-31")
        with pytest.raises(Exception):
            w.start = "2000-01-01"


class TestFundaFields:
    def test_carries_the_book_equity_hierarchy(self):
        """SE = SEQ -> CEQ+PSTK -> AT-LT, so all five must be pulled."""
        for field in ("seq", "ceq", "pstk", "at", "lt"):
            assert field in FUNDA_FIELDS

    def test_carries_the_preferred_stock_hierarchy(self):
        for field in ("pstkrv", "pstkl", "pstk"):
            assert field in FUNDA_FIELDS

    def test_carries_deferred_taxes(self):
        assert "txditc" in FUNDA_FIELDS

    def test_carries_the_operating_profitability_inputs(self):
        for field in ("revt", "cogs", "xsga", "xint"):
            assert field in FUNDA_FIELDS

    def test_carries_the_join_keys(self):
        for field in ("gvkey", "datadate", "cusip"):
            assert field in FUNDA_FIELDS

    def test_has_no_duplicates(self):
        assert len(FUNDA_FIELDS) == len(set(FUNDA_FIELDS))

    def test_filter_pins_the_standard_consolidated_view(self):
        """Omitting these returns restated and non-US duplicates per firm-year."""
        for clause in ("indfmt='INDL'", "datafmt='STD'", "popsrc='D'", "consol='C'"):
            assert clause in FUNDA_FILTER


class FakeWrdsModule(types.ModuleType):
    """Stand-in for the `wrds` package, counting Connection attempts."""

    def __init__(self, failures: int, exc: type[Exception] = EOFError):
        super().__init__("wrds")
        self.calls = 0
        self._failures = failures
        self._exc = exc

        def Connection(**kwargs):  # noqa: N802 - mirrors the real API
            self.calls += 1
            if self.calls <= self._failures:
                raise self._exc("simulated handshake failure")
            return f"connection<{kwargs.get('wrds_username')}>"

        self.Connection = Connection


@pytest.fixture
def fake_wrds(monkeypatch):
    def install(failures: int, exc: type[Exception] = EOFError) -> FakeWrdsModule:
        module = FakeWrdsModule(failures, exc)
        monkeypatch.setitem(sys.modules, "wrds", module)
        monkeypatch.setattr(wrds_source, "CONNECT_BACKOFF_SECONDS", 0.0)
        return module

    return install


class TestConnectRetry:
    def test_succeeds_first_time_without_retrying(self, fake_wrds):
        module = fake_wrds(failures=0)
        assert wrds_source.connect("someone") == "connection<someone>"
        assert module.calls == 1

    def test_retries_past_a_transient_failure(self, fake_wrds):
        """The observed failure mode: first attempt refused, second succeeds."""
        module = fake_wrds(failures=1)
        assert wrds_source.connect("someone") == "connection<someone>"
        assert module.calls == 2

    def test_eof_is_treated_as_a_failed_handshake_not_real_input(self, fake_wrds):
        """
        The wrds package prompts via input() when a connection fails, so under a
        script or test that surfaces as EOFError rather than a connection error.
        """
        module = fake_wrds(failures=CONNECT_ATTEMPTS, exc=EOFError)
        with pytest.raises(ConnectionError):
            wrds_source.connect("someone")
        assert module.calls == CONNECT_ATTEMPTS

    def test_os_errors_are_retried_too(self, fake_wrds):
        module = fake_wrds(failures=1, exc=OSError)
        assert wrds_source.connect("someone") == "connection<someone>"
        assert module.calls == 2

    def test_gives_up_with_an_actionable_message(self, fake_wrds):
        fake_wrds(failures=CONNECT_ATTEMPTS)
        with pytest.raises(ConnectionError, match="pgpass"):
            wrds_source.connect("someone")

    def test_attempt_count_is_caller_overridable(self, fake_wrds):
        module = fake_wrds(failures=99)
        with pytest.raises(ConnectionError):
            wrds_source.connect("someone", attempts=2)
        assert module.calls == 2


class RecordingDb:
    """Captures the SQL a fetch function builds, without a database."""

    def __init__(self):
        self.sql = None
        self.kwargs = None

    def raw_sql(self, sql, **kwargs):
        self.sql = sql
        self.kwargs = kwargs
        return "frame"


class TestFetchNyseMonthEnds:
    """
    The one fetch function that interpolates a list into SQL rather than a pair
    of dates, so the one worth pinning without a network.
    """

    def test_restricts_to_the_nyse_exchange_codes(self):
        db = RecordingDb()
        fetch_nyse_month_ends(db)
        assert f"b.exchcd in ({', '.join(str(c) for c in NYSE_EXCHANGE_CODES)})" in db.sql

    def test_defaults_to_the_annual_sort_months(self):
        db = RecordingDb()
        fetch_nyse_month_ends(db)
        assert "extract(month from a.date) in (6, 12)" in db.sql

    def test_months_are_caller_overridable(self):
        db = RecordingDb()
        fetch_nyse_month_ends(db, months=(3,))
        assert "extract(month from a.date) in (3)" in db.sql

    def test_months_are_coerced_to_integers(self):
        """The month list goes into SQL unquoted, so it must not carry strings."""
        db = RecordingDb()
        fetch_nyse_month_ends(db, months=("6", "12"))
        assert "in (6, 12)" in db.sql

    def test_joins_on_the_point_in_time_name_window(self):
        db = RecordingDb()
        fetch_nyse_month_ends(db)
        assert "b.namedt <= a.date" in db.sql and "a.date <= b.nameendt" in db.sql

    def test_parses_the_date_column(self):
        db = RecordingDb()
        fetch_nyse_month_ends(db)
        assert db.kwargs["date_cols"] == ["date"]

    def test_annual_sort_months_are_june_and_december(self):
        """June drives the size sort; December is the BE/ME denominator."""
        assert ANNUAL_SORT_MONTHS == (6, 12)


class TestFetchFundamentals:
    def test_bounds_the_pull_when_given_a_window(self):
        db = RecordingDb()
        fetch_fundamentals(db, ExtractWindow("1990-01-01", "2024-12-31"))
        assert "datadate between '1990-01-01' and '2024-12-31'" in db.sql

    def test_pulls_all_history_without_a_window(self):
        """
        The breakpoint validation compares against files French publishes from
        1926, so an unbounded pull is the honest default rather than an
        oversight.
        """
        db = RecordingDb()
        fetch_fundamentals(db)
        assert "datadate between" not in db.sql
        assert FUNDA_FILTER in db.sql

    def test_selects_only_the_named_fields(self):
        db = RecordingDb()
        fetch_fundamentals(db)
        assert "select *" not in db.sql
        for field in FUNDA_FIELDS:
            assert field in db.sql


class TestFetchDelistings:
    def test_bounds_and_renames_the_delisting_date(self):
        db = RecordingDb()
        fetch_delistings(db, ExtractWindow("1990-01-01", "1990-12-31"))
        assert "dlstdt as date" in db.sql
        assert "dlstdt between '1990-01-01' and '1990-12-31'" in db.sql
