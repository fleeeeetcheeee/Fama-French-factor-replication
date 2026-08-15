"""
Shared fixtures.

Synthetic fixtures are written in French's *real* format — the prose preamble,
the `,`-leading headers, the stacked tables, the `-99.99` sentinels, the percent
units. A fixture that is merely "a CSV with the right columns" would pass while
the parser fails on the actual files, which is the failure mode these tests
exist to prevent.

Tests needing the real downloaded files skip cleanly when they are absent, so a
fresh clone still runs green without a network round trip.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ffrep.config import Config

# --- synthetic French returns file ------------------------------------------
#
# Two monthly tables with identical column names (value- and equal-weighted),
# one annual table, and a firm-count table. The duplicate column names are the
# whole point: this shape is what makes "take the first match" wrong.

SIX_PORTFOLIO_CSV = """This file was created by CMPT_ME_BEME_RETS using the 202606 CRSP database.

  Average Value Weighted Returns -- Monthly
,SMALL LoBM,ME1 BM2,SMALL HiBM,BIG LoBM,ME2 BM2,BIG HiBM
202601,    1.00,    2.00,    3.00,    4.00,    5.00,    6.00
202602,   -1.00,    0.50,    2.50,   -0.50,    1.50,    3.50
202603,    0.00,  -99.99,    1.00,    2.00,    3.00,    4.00

  Average Equal Weighted Returns -- Monthly
,SMALL LoBM,ME1 BM2,SMALL HiBM,BIG LoBM,ME2 BM2,BIG HiBM
202601,   10.00,   20.00,   30.00,   40.00,   50.00,   60.00
202602,  -10.00,    5.00,   25.00,   -5.00,   15.00,   35.00
202603,    0.00,    0.00,   10.00,   20.00,   30.00,   40.00

  Average Value Weighted Returns -- Annual
,SMALL LoBM,ME1 BM2,SMALL HiBM,BIG LoBM,ME2 BM2,BIG HiBM
2026,    7.00,    8.00,    9.00,   10.00,   11.00,   12.00

  Number of Firms in Portfolios
,SMALL LoBM,ME1 BM2,SMALL HiBM,BIG LoBM,ME2 BM2,BIG HiBM
202601,     100,     200,     300,      40,      50,      60
202602,     101,     201,     301,      41,      51,      61
202603,     102,     202,     302,      42,      52,      62

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""

FACTORS_CSV = """This file was created by CMPT_ME_BEME_RETS using the 202606 CRSP database.

,Mkt-RF,SMB,HML,RF
202601,    1.50,    0.50,    1.00,    0.40
202602,   -2.00,   -0.25,   -1.50,    0.40
202603,    0.75,    1.25,    0.50,    0.40

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""

# --- synthetic breakpoint files ---------------------------------------------
#
# ME has ONE count column; BE-ME has TWO. Both shapes must parse, because
# assuming the wrong one shifts every percentile by a column and yields a
# complete, well-formed, entirely wrong table.

ME_BREAKPOINTS_CSV = """This file was created using the 202606 CRSP database.  It contains every 5th NYSE ME percentile (divided by 1000000).

202601,   500,    1.0,    2.0,    3.0,    4.0,    5.0,    6.0,    7.0,    8.0,    9.0,   10.0,   11.0,   12.0,   13.0,   14.0,   15.0,   16.0,   17.0,   18.0,   19.0,   20.0
202602,   510,    2.0,    4.0,    6.0,    8.0,   10.0,   12.0,   14.0,   16.0,   18.0,   20.0,   22.0,   24.0,   26.0,   28.0,   30.0,   32.0,   34.0,   36.0,   38.0,   40.0

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""

BEME_BREAKPOINTS_CSV = """This file was created using the 202606 CRSP database.  It contains every 5th NYSE BEME percentile.

  ,<= 0,>0
2025,    67,  1074,   0.10,   0.20,   0.30,   0.40,   0.50,   0.60,   0.70,   0.80,   0.90,   1.00,   1.10,   1.20,   1.30,   1.40,   1.50,   1.60,   1.70,   1.80,   1.90,   2.00
2026,    70,  1015,   0.11,   0.21,   0.31,   0.41,   0.51,   0.61,   0.71,   0.81,   0.91,   1.01,   1.11,   1.21,   1.31,   1.41,   1.51,   1.61,   1.71,   1.81,   1.91,   2.01

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""


@pytest.fixture
def six_portfolio_file(tmp_path: Path) -> Path:
    path = tmp_path / "6_Portfolios_2x3.csv"
    path.write_text(SIX_PORTFOLIO_CSV)
    return path


@pytest.fixture
def factors_file(tmp_path: Path) -> Path:
    path = tmp_path / "F-F_Research_Data_Factors.csv"
    path.write_text(FACTORS_CSV)
    return path


@pytest.fixture
def me_breakpoints_file(tmp_path: Path) -> Path:
    path = tmp_path / "ME_Breakpoints.csv"
    path.write_text(ME_BREAKPOINTS_CSV)
    return path


@pytest.fixture
def beme_breakpoints_file(tmp_path: Path) -> Path:
    path = tmp_path / "BE-ME_Breakpoints.csv"
    path.write_text(BEME_BREAKPOINTS_CSV)
    return path


@pytest.fixture
def real_config() -> Config:
    """
    Config pointing at the real downloaded reference files.

    Tests using this must skip when the files are absent — see `requires_real`.
    """
    return Config()


def requires_real(config: Config, *keys: str) -> None:
    """Skip the calling test unless every named French file has been downloaded."""
    missing = [k for k in keys if not config.french_path(k).exists()]
    if missing:
        pytest.skip(
            f"reference data not downloaded: {missing}. "
            f"Run `python scripts/fetch_reference_data.py`."
        )
