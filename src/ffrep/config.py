"""
Single source of every path, URL, and protocol constant in this project.

Following Project 01's convention: derived paths are computed in
``__post_init__`` and nothing else in the codebase hardcodes a data path or a
breakpoint percentile. The Fama-French construction is a pile of specific,
arbitrary-looking choices — 30th/70th percentiles, June formation, December
accounting, a six-month reporting gap — and every one of them changes the
answer. Scattering them across modules is how a replication ends up unable to
explain why it missed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# --- Ken French's data library ---------------------------------------------
#
# The library republishes monthly, so files are fetched by name rather than
# cached by version. Every one of these is free and public.

FRENCH_BASE_URL = (
    "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp"
)

FRENCH_FILES: dict[str, str] = {
    # Published factor series — the targets we are trying to hit.
    "factors_3": "F-F_Research_Data_Factors_CSV.zip",
    "factors_5": "F-F_Research_Data_5_Factors_2x3_CSV.zip",
    "momentum": "F-F_Momentum_Factor_CSV.zip",
    # Source portfolios the factors are built from, with firm counts.
    "portfolios_6_beme": "6_Portfolios_2x3_CSV.zip",
    "portfolios_6_op": "6_Portfolios_ME_OP_2x3_CSV.zip",
    "portfolios_6_inv": "6_Portfolios_ME_INV_2x3_CSV.zip",
    # NYSE breakpoints. These are the reason this project is feasible at all
    # on free data: reproducing them from scratch would need a historical
    # exchange-listing map, which is not free. Using French's own removes the
    # single largest data blocker, at the cost of not having independently
    # derived them — recorded as a limitation, not hidden.
    "bp_me": "ME_Breakpoints_CSV.zip",
    "bp_beme": "BE-ME_Breakpoints_CSV.zip",
    "bp_op": "OP_Breakpoints_CSV.zip",
    "bp_inv": "INV_Breakpoints_CSV.zip",
    "bp_prior": "Prior_2-12_Breakpoints_CSV.zip",
}

# --- Hou-Xue-Zhang q-factors -----------------------------------------------
# Published free at global-q.org; used as the reference series for the
# q-factor extension and for the spanning tests in both directions.
GLOBAL_Q_URL = "https://global-q.org/data/factors/q5_factors_monthly_2024.csv"

# --- Fama-French construction protocol -------------------------------------
#
# From French's own documentation of the factor construction. Values that look
# arbitrary are: they are the published protocol, and deviating from any of
# them produces a series that correlates highly with HML and is still wrong.

#: Portfolios are formed at the end of June each year and held for 12 months.
FORMATION_MONTH = 6

#: Book equity comes from the fiscal year ending in calendar year t-1, and
#: market equity for the BE/ME ratio from the END OF DECEMBER of t-1 — not
#: from June. Using June ME for the ratio is a common and silent error: it
#: mixes a stale numerator with a fresh denominator and shifts the sort.
BEME_MARKET_EQUITY_MONTH = 12

#: Market equity used for the size sort and for value-weighting is measured at
#: the end of June of year t.
SIZE_MARKET_EQUITY_MONTH = 6

#: The minimum gap between fiscal year end and portfolio formation. Six months
#: is what guarantees the accounting data was public at formation — this is the
#: same lookahead concern Project 01 exists to solve, expressed as a calendar
#: rule rather than a filing-date gate. Where a real filed_date is available
#: (Project 01's store) it is used instead, and the two are compared.
MIN_MONTHS_BETWEEN_FYE_AND_FORMATION = 6

#: Size split: the NYSE median.
SIZE_BREAKPOINT_PERCENTILE = 50

#: Value split: NYSE 30th and 70th percentiles of BE/ME. Note the asymmetry
#: with the size sort — two size groups, three value groups, hence "2x3".
VALUE_BREAKPOINT_PERCENTILES = (30, 70)

#: Same 30/70 split is used for operating profitability (RMW) and investment
#: (CMA) in the 5-factor model.
PROFITABILITY_BREAKPOINT_PERCENTILES = (30, 70)
INVESTMENT_BREAKPOINT_PERCENTILES = (30, 70)

#: Momentum (UMD) is the only factor rebalanced monthly rather than annually,
#: on prior returns from t-12 to t-2. The one-month skip avoids the
#: short-term reversal effect contaminating the signal.
MOMENTUM_LOOKBACK_MONTHS = 12
MOMENTUM_SKIP_MONTHS = 1

#: Firms with non-positive book equity are excluded from the BE/ME sorts
#: entirely — the ratio is not meaningful and French drops them.
REQUIRE_POSITIVE_BOOK_EQUITY = True


@dataclass
class Config:
    """Paths and run-scoped settings. Derived paths computed in __post_init__."""

    data_root: Path = field(
        default_factory=lambda: Path(
            os.getenv("DATA_ROOT", Path(__file__).resolve().parents[2] / "data")
        )
    )

    #: Root of Project 01's processed store, if it is being used as the price
    #: and fundamentals source. Consumed as *data*, not imported as a package —
    #: the workspace rule is that projects do not import from each other.
    pit_store_root: Path | None = field(
        default_factory=lambda: (
            Path(os.environ["PIT_STORE_ROOT"])
            if os.getenv("PIT_STORE_ROOT")
            else None
        )
    )

    #: SEC requires a descriptive User-Agent on every request and bans the IP
    #: without one. Same requirement as Project 01.
    sec_user_agent: str = field(
        default_factory=lambda: os.getenv("SEC_USER_AGENT", "")
    )

    def __post_init__(self) -> None:
        self.data_root = Path(self.data_root)
        self.raw_root = self.data_root / "raw"
        self.processed_root = self.data_root / "processed"

        self.french_raw = self.raw_root / "french"
        self.global_q_raw = self.raw_root / "global_q"

        self.characteristics = self.processed_root / "characteristics"
        self.factors = self.processed_root / "factors"
        self.results = self.data_root / "results"

    def french_url(self, key: str) -> str:
        """Full download URL for a named French library file."""
        if key not in FRENCH_FILES:
            raise KeyError(
                f"unknown French file {key!r}; known: {sorted(FRENCH_FILES)}"
            )
        return f"{FRENCH_BASE_URL}/{FRENCH_FILES[key]}"

    def french_path(self, key: str) -> Path:
        """Local path a named French library file is cached at."""
        return self.french_raw / FRENCH_FILES[key]

    def require_real_user_agent(self) -> None:
        """
        Raise unless SEC_USER_AGENT looks like a real contact address.

        Project 01 learned this the expensive way: a warning in an hours-long
        job gets ignored, and the consequence is an SEC IP ban.
        """
        agent = self.sec_user_agent.strip()
        if not agent or "example.com" in agent or "@" not in agent:
            raise RuntimeError(
                "SEC_USER_AGENT must be set to a real 'Name email@domain' in .env. "
                f"Got {agent!r}. The SEC blocks programmatic access without one."
            )
