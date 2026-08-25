"""
Bottom-up factor construction: sorts, portfolios, factors.

    sorts.py        characteristics and 2x3 bucket assignment
    portfolios.py   value-weighted returns with weights that drift on retx
    factors.py      six portfolios into SMB and HML

Every function here is a pure transformation of frames, unit-tested against
cross-sections small enough to verify by hand. The construction is a pile of
specific, arbitrary-looking conventions — inclusive lower edges, December market
equity in the BE/ME denominator, drift on retx rather than ret — and each one
changes the answer without changing whether the code runs.
"""

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
    assign_2x3,
    assign_bucket,
    book_to_market,
    FormationInputs,
    nyse_size_breakpoint,
    nyse_value_breakpoints,
    size_bucket,
    value_bucket,
)

__all__ = [
    "assign_2x3",
    "assign_bucket",
    "book_to_market",
    "build_2x3_factors",
    "drifted_weights",
    "equal_weighted_return",
    "FormationInputs",
    "nyse_size_breakpoint",
    "nyse_value_breakpoints",
    "PORTFOLIO_LABELS",
    "portfolio_returns",
    "size_bucket",
    "size_factor",
    "value_bucket",
    "value_factor",
    "value_weighted_return",
]
