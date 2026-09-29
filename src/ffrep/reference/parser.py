"""
Parser for the stacked-table CSV layout used by French's returns files.

Vendored and extended from Project 02's `evbt/data/french.py`. Vendored rather
than imported: the workspace rule is that projects here do not depend on each
other's packages, and this needs changes Project 02 has no use for (the 5-factor
and momentum files, and a table lookup that does not assume the six
book-to-market portfolios).

The format, and why it is worth describing
------------------------------------------
  - A prose preamble, then several stacked tables in one file.
    `6_Portfolios_2x3.csv` holds **ten**.
  - Each table has a free-text title line, then a header row beginning with a
    bare comma (the date column has no name).
  - Monthly and annual blocks share identical column names and are told apart
    only by the width of the date field: `202606` vs `2026`.
  - Missing data is `-99.99` or `-999`, never blank.
  - Returns are in **percent**.

Line offsets are useless — French republishes monthly and every table shifts —
so tables are located structurally.

The trap, inherited from Project 02 and worth restating
--------------------------------------------------------
The value-weighted and equal-weighted monthly tables are adjacent and have
identical column names. **The factors are built from the value-weighted set.**
Project 02 measured the consequence of reading the wrong one: a series that
still correlates 0.93 with real HML and is wrong by 92 bps a month — plausible
enough to publish. `weighting` is therefore a required argument with no default.

Note that the **breakpoint** files do not use this layout at all; they have no
`,`-leading header and are handled by `breakpoints.py`.
"""

from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

#: French's sentinels for missing data.
MISSING_CODES = (-99.99, -999.0)

_DATA_ROW = re.compile(r"^\s*(\d{4}|\d{6})\s*(?:,|$)")

#: The six size x book-to-market portfolios. The renaming is not cosmetic:
#: "SMALL LoBM" is small-cap *growth* (low book-to-market), and reading it as
#: value inverts the sign of HML.
SIX_BEME_PORTFOLIOS = {
    "SMALL LoBM": "SmallGrowth",
    "ME1 BM2": "SmallNeutral",
    "SMALL HiBM": "SmallValue",
    "BIG LoBM": "BigGrowth",
    "ME2 BM2": "BigNeutral",
    "BIG HiBM": "BigValue",
}

#: The six size x operating-profitability portfolios, source of RMW.
#: "LoOP" is weak profitability, "HiOP" robust — hence Robust Minus Weak.
SIX_OP_PORTFOLIOS = {
    "SMALL LoOP": "SmallWeak",
    "ME1 OP2": "SmallNeutralOP",
    "SMALL HiOP": "SmallRobust",
    "BIG LoOP": "BigWeak",
    "ME2 OP2": "BigNeutralOP",
    "BIG HiOP": "BigRobust",
}

#: The six size x investment portfolios, source of CMA. Note the direction:
#: CMA is Conservative Minus Aggressive, so **low** investment is the long leg.
SIX_INV_PORTFOLIOS = {
    "SMALL LoINV": "SmallConservative",
    "ME1 INV2": "SmallNeutralINV",
    "SMALL HiINV": "SmallAggressive",
    "BIG LoINV": "BigConservative",
    "ME2 INV2": "BigNeutralINV",
    "BIG HiINV": "BigAggressive",
}


#: The six size x prior (2-12) return portfolios, source of UMD. "LoPRIOR" is
#: the losers, "HiPRIOR" the winners.
SIX_PRIOR_PORTFOLIOS = {
    "SMALL LoPRIOR": "SmallLoser",
    "ME1 PRIOR2": "SmallNeutralPRIOR",
    "SMALL HiPRIOR": "SmallWinner",
    "BIG LoPRIOR": "BigLoser",
    "ME2 PRIOR2": "BigNeutralPRIOR",
    "BIG HiPRIOR": "BigWinner",
}


@dataclass
class FrenchTable:
    """One table extracted from a French CSV, with the title that introduced it."""

    title: str
    periodicity: str  # "monthly" | "annual"
    data: pd.DataFrame


def read_text(source: Path | str) -> str:
    """Read a French CSV, transparently unwrapping a single-member zip."""
    path = Path(source)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
            if len(names) != 1:
                raise ValueError(
                    f"expected exactly one CSV in {path.name}, found {names}"
                )
            return archive.read(names[0]).decode("utf-8-sig", errors="replace")
    return path.read_text(encoding="utf-8-sig", errors="replace")


def parse_tables(source: Path | str) -> list[FrenchTable]:
    """
    Split a French CSV into its constituent tables.

    Structural, not positional: a table is a `,`-leading header row followed by
    consecutive rows whose first field is a 4- or 6-digit integer. The title is
    the nearest preceding non-empty line.
    """
    lines = read_text(source).splitlines()
    tables: list[FrenchTable] = []

    i = 0
    while i < len(lines):
        if not lines[i].startswith(","):
            i += 1
            continue

        columns = [c.strip() for c in lines[i].split(",")][1:]

        title = ""
        for back in range(i - 1, -1, -1):
            if lines[back].strip():
                title = lines[back].strip()
                break

        rows: list[list[str]] = []
        j = i + 1
        while j < len(lines) and _DATA_ROW.match(lines[j]):
            rows.append([c.strip() for c in lines[j].split(",")])
            j += 1

        if rows:
            periodicity = "monthly" if len(rows[0][0]) == 6 else "annual"
            frame = pd.DataFrame(
                [r[1 : len(columns) + 1] for r in rows],
                columns=columns,
                index=[r[0] for r in rows],
            )
            tables.append(
                FrenchTable(
                    title=title,
                    periodicity=periodicity,
                    data=frame.apply(pd.to_numeric, errors="coerce"),
                )
            )

        i = max(j, i + 1)

    return tables


def to_period_index(frame: pd.DataFrame, periodicity: str) -> pd.DataFrame:
    """
    Index by period end. `202606` becomes 2026-06-30.

    Month *end* rather than start because a monthly return is realised over the
    month and known at its close.
    """
    out = frame.copy()
    if periodicity == "monthly":
        out.index = pd.to_datetime(out.index, format="%Y%m") + pd.offsets.MonthEnd(0)
    else:
        out.index = pd.to_datetime(out.index, format="%Y") + pd.offsets.YearEnd(0)
    out.index.name = "date"
    return out


def clean_returns(frame: pd.DataFrame) -> pd.DataFrame:
    """Replace French's missing sentinels with NaN and convert percent to decimal."""
    out = frame.copy()
    for code in MISSING_CODES:
        out = out.mask(np.isclose(out, code, atol=1e-9))
    return out / 100.0


def find_table(
    source: Path | str,
    *,
    title_contains: tuple[str, ...],
    periodicity: str = "monthly",
) -> FrenchTable:
    """
    Locate exactly one table by substrings of its title.

    Raises when the match is not unique. That strictness is the point: these
    files hold several tables with identical column names, so a lenient
    "take the first match" would silently pick the wrong one and produce a
    well-formed, incorrect answer.
    """
    tables = parse_tables(source)
    matches = [
        t
        for t in tables
        if t.periodicity == periodicity
        and all(s.lower() in t.title.lower() for s in title_contains)
    ]
    if len(matches) != 1:
        raise ValueError(
            f"expected exactly one {periodicity} table whose title contains "
            f"{title_contains}, found {len(matches)}. "
            f"Titles present: {[t.title for t in tables]}"
        )
    return matches[0]


def load_six_portfolios(
    source: Path | str,
    *,
    weighting: str,
    names: dict[str, str] = SIX_BEME_PORTFOLIOS,
    periodicity: str = "monthly",
) -> pd.DataFrame:
    """
    A 2x3 set of six portfolios, as decimal returns.

    `weighting` must be given explicitly — "value" or "equal". The factors are
    built from the value-weighted portfolios; the equal-weighted table has
    identical column names and silently produces a wrong factor.
    """
    if weighting not in ("value", "equal"):
        raise ValueError(f"weighting must be 'value' or 'equal', got {weighting!r}")

    wanted = "Value Weighted" if weighting == "value" else "Equal Weighted"
    table = find_table(
        source, title_contains=(wanted, "Returns"), periodicity=periodicity
    )

    frame = to_period_index(table.data, periodicity)
    missing = set(names) - set(frame.columns)
    if missing:
        raise ValueError(
            f"missing expected portfolio columns {sorted(missing)}; "
            f"present: {sorted(frame.columns)}"
        )
    return clean_returns(frame[list(names)].rename(columns=names))


def load_firm_counts(
    source: Path | str,
    *,
    names: dict[str, str] = SIX_BEME_PORTFOLIOS,
    periodicity: str = "monthly",
) -> pd.DataFrame:
    """
    Number of firms in each portfolio, as published.

    This is the cheapest honest measure of universe coverage: comparing a
    constructed portfolio's firm count against French's says how much of the
    cross-section is missing without needing a single return.
    """
    table = find_table(
        source, title_contains=("Number of Firms",), periodicity=periodicity
    )
    frame = to_period_index(table.data, periodicity)
    missing = set(names) - set(frame.columns)
    if missing:
        raise ValueError(f"missing expected portfolio columns {sorted(missing)}")
    return frame[list(names)].rename(columns=names)


def load_factors(source: Path | str, periodicity: str = "monthly") -> pd.DataFrame:
    """
    The published factor series, as decimal returns.

    Works for the 3-factor file (Mkt-RF, SMB, HML, RF), the 5-factor file
    (adding RMW and CMA) and the momentum file (Mom), by locating the single
    table of the requested periodicity rather than matching on column names.
    """
    tables = [t for t in parse_tables(source) if t.periodicity == periodicity]
    if len(tables) != 1:
        raise ValueError(
            f"expected exactly one {periodicity} table, found {len(tables)}: "
            f"{[t.title for t in tables]}"
        )
    return clean_returns(to_period_index(tables[0].data, periodicity))


def construct_hml_from_portfolios(portfolios: pd.DataFrame) -> pd.Series:
    """
    Rebuild HML from the six portfolios, exactly as French defines it:

        HML = 1/2 (SmallValue + BigValue) - 1/2 (SmallGrowth + BigGrowth)

    The two neutral portfolios are unused: HML is the high-minus-low spread and
    the middle third of the book-to-market sort contributes nothing to it.
    """
    required = ["SmallValue", "BigValue", "SmallGrowth", "BigGrowth"]
    missing = [c for c in required if c not in portfolios.columns]
    if missing:
        raise ValueError(f"portfolios frame is missing {missing}")

    value = 0.5 * (portfolios["SmallValue"] + portfolios["BigValue"])
    growth = 0.5 * (portfolios["SmallGrowth"] + portfolios["BigGrowth"])
    return (value - growth).rename("HML")


def construct_smb_from_portfolios(portfolios: pd.DataFrame) -> pd.Series:
    """
    Rebuild SMB from the six book-to-market portfolios:

        SMB = 1/3 (SmallValue + SmallNeutral + SmallGrowth)
            - 1/3 (BigValue + BigNeutral + BigGrowth)

    Note this is the *3-factor* SMB. The 5-factor SMB averages the small-minus-
    big spread across all three 2x3 sorts (BE/ME, OP, INV), so the two differ —
    conflating them is a real and easy mistake.
    """
    required = [
        "SmallValue", "SmallNeutral", "SmallGrowth",
        "BigValue", "BigNeutral", "BigGrowth",
    ]
    missing = [c for c in required if c not in portfolios.columns]
    if missing:
        raise ValueError(f"portfolios frame is missing {missing}")

    # skipna=False: a missing leg means no SMB that month, not an SMB silently
    # averaged over the legs that happen to be present.
    small = portfolios[["SmallValue", "SmallNeutral", "SmallGrowth"]].mean(axis=1, skipna=False)
    big = portfolios[["BigValue", "BigNeutral", "BigGrowth"]].mean(axis=1, skipna=False)
    return (small - big).rename("SMB")
