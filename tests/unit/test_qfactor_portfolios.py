"""
q-portfolio assembly on a synthetic world of 24 NYSE companies.

With every security returning the same 1% a month, every non-empty portfolio
must return exactly 1% — a check on the weighting and the month alignment that
needs no hand-sorted answer — and the counts must add up to the eligible firms.
Two firms are planted to be excluded: a bank (SIC 6021) and a firm with no ROE.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ffrep.construct.formation import annual_characteristics
from ffrep.construct.monthly import company_panel
from ffrep.qfactor.construct import LABELS, q_portfolios
from ffrep.universe.links import compustat_candidates, crsp_candidates, link_candidates
from ffrep.universe.panel import security_panel

N = 24
BANK, NO_ROE = 5, 7


@pytest.fixture(scope="module")
def world():
    months = pd.period_range("1999-12", "2001-06", freq="M")
    rows = []
    for i in range(1, N + 1):
        for m in months:
            rows.append({
                "permno": 100 + i, "permco": i, "date": m.to_timestamp(how="end").normalize(),
                "prc": 10.0 * i, "shrout": 1000.0, "ret": 0.01, "retx": 0.01,
                "shrcd": 11, "exchcd": 1, "siccd": 6021 if i == BANK else 2000,
                "cusip": f"C{i:07d}", "ncusip": None,
            })
    msf = pd.DataFrame(rows)
    funda = pd.DataFrame([
        {"gvkey": f"G{i}", "datadate": pd.Timestamp(f"{y}-12-31"), "cusip": f"C{i:07d}9",
         "seq": 50.0, "at": 100.0 * (1 + 0.01 * i) ** (y - 1998), "lt": 50.0}
        for i in range(1, N + 1) for y in (1998, 1999)
    ])
    roe = pd.DataFrame([
        {"gvkey": f"G{i}", "datadate": pd.Timestamp("2000-03-31"),
         "available": pd.Timestamp("2000-04-20"), "roe": 0.001 * i}
        for i in range(1, N + 1) if i != NO_ROE
    ] + [
        {"gvkey": f"G{i}", "datadate": pd.Timestamp("2000-09-30"),
         "available": pd.Timestamp("2000-10-20"), "roe": 0.001 * i}
        for i in range(1, N + 1) if i != NO_ROE
    ])
    events = pd.DataFrame({"permno": [], "date": pd.to_datetime([]), "dlret": [], "dlstcd": []})
    panel = security_panel(msf, events)
    candidates = link_candidates(crsp_candidates(msf), compustat_candidates(funda))
    returns, counts = q_portfolios(panel, company_panel(panel), candidates,
                                   annual_characteristics(funda), roe, range(2000, 2001))
    return returns, counts


def test_uniform_returns_give_uniform_portfolios(world):
    returns, _ = world
    assert np.allclose(returns.stack().dropna().to_numpy(), 0.01)


def test_counts_exclude_the_bank_and_the_firm_without_roe(world):
    _, counts = world
    july = counts.loc[pd.Period("2000-07", "M")]
    assert july.sum() == N - 2


def test_stale_earnings_empty_the_portfolios_rather_than_carrying_forward(world):
    """
    The last quarter in this world ended 2000-09-30. At the end-March 2001
    formation (held in April) it is exactly six months old and still usable; at
    the end-April formation it is stale, so May and June hold nothing — the
    sort does not fall back on older earnings.
    """
    _, counts = world
    totals = counts.sum(axis=1)
    assert totals.loc[pd.Period("2001-04", "M")] == N - 2
    assert pd.Period("2001-05", "M") not in totals.index or totals.loc[pd.Period("2001-05", "M")] == 0


def test_labels_are_global_q_ranks(world):
    returns, _ = world
    assert list(returns.columns) == list(LABELS)
