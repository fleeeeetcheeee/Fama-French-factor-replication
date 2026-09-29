"""
End-to-end assembly: local extracts in, bottom-up factors out.

Kept separate from ``construct/`` (open question 11 in the log): the steps here
reach across layers — the CRSP panel from ``universe/``, the link table, the
Compustat characteristics from ``construct/`` — and a module that owns only
that wiring keeps each layer free of the others' concepts. Nothing here makes a
modelling decision; every decision is a ``Conventions`` field or a function in
the layer that owns it, so the gap attribution can rebuild with one choice
changed and nothing else.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from ffrep.config import Config
from ffrep.construct.factors import second_sort_factor, size_factor, value_factor
from ffrep.construct.formation import Conventions, annual_characteristics, run_annual_sorts
from ffrep.construct.monthly import company_panel, market_return, momentum_portfolios
from ffrep.reference.historical_be import load_historical_be
from ffrep.store import read_extract
from ffrep.universe.links import compustat_candidates, crsp_candidates, link_candidates
from ffrep.universe.panel import security_panel

#: First formation with usable Compustat coverage. French's own series start in
#: July 1926 on hand-collected Moody's book equity; before the 1960s Compustat
#: covers a small minority of NYSE, so a bottom-up series there would measure
#: coverage, not construction.
FIRST_FORMATION_YEAR = 1963

#: CRSP's legacy monthly file ends here on this subscription.
LAST_MONTH = "2024-12"


@dataclass
class Inputs:
    """Everything the build reads, loaded once."""

    panel: pd.DataFrame
    candidates: pd.DataFrame
    funda: pd.DataFrame
    moody: pd.DataFrame | None = None


def load_inputs(
    config: Config | None = None,
    *,
    delisting: bool = True,
    terminal_rows: bool = True,
    compustat_securities: bool = True,
) -> Inputs:
    """
    Read the extracts and assemble the panel and the link candidates.

    ``delisting=False`` builds the panel with no delisting events at all — the
    ablation that measures what Shumway's adjustment and the terminal months are
    worth; ``terminal_rows=False`` keeps delisting returns but drops those that
    fall after a security's last ``msf`` month, as a month-matched left join
    would. ``compustat_securities=False`` links on the header CUSIP alone.
    """
    config = config or Config()
    msf = read_extract(config, "crsp_monthly")
    delist = read_extract(config, "crsp_delist")
    if not delisting:
        delist = delist.iloc[0:0]
    names = read_extract(config, "crsp_names")
    funda = read_extract(config, "comp_funda")
    securities = read_extract(config, "comp_security") if compustat_securities else None

    panel = security_panel(msf, delist, add_terminal_rows=terminal_rows)
    candidates = link_candidates(crsp_candidates(names), compustat_candidates(funda, securities))
    moody_path = config.historical_be_path()
    moody = load_historical_be(moody_path) if moody_path.exists() else None
    return Inputs(panel=panel, candidates=candidates, funda=funda, moody=moody)


def factors_from_portfolios(portfolios: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    The published factor algebra over our six-portfolio sets.

    CMA is Conservative *minus* Aggressive, and conservative is the *low*
    investment leg, so it is the negative of the generic high-minus-low. The
    five-factor SMB averages the small-minus-big spread of all three sorts; the
    three-factor SMB uses the BE/ME sort alone. The two are different series
    under the same name, and are kept apart as SMB and SMB5.
    """
    out = {}
    if "beme" in portfolios:
        out["SMB"] = size_factor(portfolios["beme"])
        out["HML"] = value_factor(portfolios["beme"])
    if "op" in portfolios:
        out["RMW"] = second_sort_factor(portfolios["op"], "RMW")
    if "inv" in portfolios:
        out["CMA"] = -second_sort_factor(portfolios["inv"], "CMA")
    if all(k in portfolios for k in ("beme", "op", "inv")):
        out["SMB5"] = (
            size_factor(portfolios["beme"]) + size_factor(portfolios["op"]) + size_factor(portfolios["inv"])
        ) / 3.0
    if "prior" in portfolios:
        out["UMD"] = value_factor(portfolios["prior"])
    return pd.DataFrame(out)


def build(
    inputs: Inputs,
    conventions: Conventions = Conventions(),
    *,
    years: range | None = None,
    sorts: tuple[str, ...] = ("beme", "op", "inv"),
    momentum: bool = True,
    market: bool = True,
    breakpoints: dict | None = None,
) -> dict:
    """
    Every bottom-up factor, plus the portfolios, counts and diagnostics behind it.

    Months after ``LAST_MONTH`` are cut: the last formation's holding year runs
    past the end of CRSP, and a month with no data is not a zero return.
    """
    years = years or range(FIRST_FORMATION_YEAR, int(LAST_MONTH[:4]) + 1)
    characteristics = annual_characteristics(inputs.funda, conventions)
    annual = run_annual_sorts(inputs.panel, inputs.candidates, characteristics, years, conventions, sorts,
                              breakpoints=breakpoints, moody=inputs.moody)

    portfolios = dict(annual["returns"])
    counts = dict(annual["counts"])
    first = f"{years.start}-07"
    if momentum:
        companies = company_panel(inputs.panel)
        portfolios["prior"], counts["prior"] = momentum_portfolios(inputs.panel, companies, start=first)

    cut = pd.Period(LAST_MONTH, "M")
    portfolios = {k: v.loc[(v.index >= pd.Period(first, "M")) & (v.index <= cut)] for k, v in portfolios.items()}
    counts = {k: v.loc[(v.index >= pd.Period(first, "M")) & (v.index <= cut)] for k, v in counts.items()}

    factors = factors_from_portfolios(portfolios)
    if market:
        mkt = market_return(inputs.panel, start=first)
        factors["Mkt"] = mkt.loc[(mkt.index >= pd.Period(first, "M")) & (mkt.index <= cut)]
    return {
        "factors": factors.sort_index(),
        "portfolios": portfolios,
        "counts": counts,
        "diagnostics": annual["diagnostics"],
        "characteristics": characteristics,
    }
