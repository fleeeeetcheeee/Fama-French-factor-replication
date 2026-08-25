"""
Universe assembly: from raw CRSP rows to the Fama-French cross-section.

    wrds_source.py   queries only, no judgement
    screen.py        which securities are a firm  (share codes, SPACs, PERMCO)
    delisting.py     Shumway's -30% for performance delistings
    linker.py        PERMNO -> GVKEY, and the measured cost of not having CCM

The layering rule mirrors Project 01's: extraction may not transform, and
transformation may not reach the network. Everything except ``wrds_source`` is
a pure DataFrame function and unit-tested without a database.
"""

from ffrep.universe.delisting import (
    apply_delisting_returns,
    compound_delisting,
    impute_delisting_return,
)
from ffrep.universe.linker import CcmLinker, CusipLinker, Linker, normalise_cusip
from ffrep.universe.screen import (
    aggregate_to_company,
    apply_share_screen,
    full_universe,
    market_equity,
    nyse_breakpoint_universe,
)

__all__ = [
    "aggregate_to_company",
    "apply_delisting_returns",
    "apply_share_screen",
    "CcmLinker",
    "compound_delisting",
    "CusipLinker",
    "full_universe",
    "impute_delisting_return",
    "Linker",
    "market_equity",
    "normalise_cusip",
    "nyse_breakpoint_universe",
]
