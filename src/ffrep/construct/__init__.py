"""
Bottom-up factor construction: sorts, portfolios, factors.

    book_equity.py  Compustat fundamentals into BE, profitability, investment
    sorts.py        characteristics and 2x3 bucket assignment
    formation.py    the June join: CRSP cross-sections + Compustat -> portfolios
    monthly.py      the monthly-rebalanced factors: momentum and the market
    portfolios.py   value-weighted returns with weights that drift on retx
    factors.py      six portfolios into SMB, HML, RMW, CMA, UMD

Every function here is a pure transformation of frames, unit-tested against
cross-sections small enough to verify by hand. The construction is a pile of
specific, arbitrary-looking conventions — inclusive lower edges, December market
equity in the BE/ME denominator, drift on retx rather than ret — and each one
changes the answer without changing whether the code runs.
"""

from ffrep.construct.book_equity import (
    accounting_year,
    book_equity,
    deferred_taxes,
    drop_empty_records,
    investment,
    latest_fiscal_year,
    operating_profitability,
    preferred_stock,
    stockholders_equity,
)
from ffrep.construct.factors import (
    build_2x3_factors,
    PORTFOLIO_LABELS,
    size_factor,
    value_factor,
)
from ffrep.construct.portfolios import (
    drifted_weights,
    equal_weighted_return,
    portfolio_returns,
    value_weighted_return,
)
from ffrep.construct.sorts import (
    assign_bucket,
    nyse_size_breakpoint,
    nyse_value_breakpoints,
    size_bucket,
    value_bucket,
)

__all__ = [
    "accounting_year",
    "assign_bucket",
    "book_equity",
    "build_2x3_factors",
    "deferred_taxes",
    "drifted_weights",
    "drop_empty_records",
    "equal_weighted_return",
    "investment",
    "latest_fiscal_year",
    "nyse_size_breakpoint",
    "nyse_value_breakpoints",
    "operating_profitability",
    "PORTFOLIO_LABELS",
    "portfolio_returns",
    "preferred_stock",
    "size_bucket",
    "size_factor",
    "stockholders_equity",
    "value_bucket",
    "value_factor",
    "value_weighted_return",
]
