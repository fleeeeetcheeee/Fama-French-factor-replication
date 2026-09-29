"""
Parser for Ken French's NYSE breakpoint files.

Why these matter more than they look
------------------------------------
Fama-French sorts use breakpoints computed from **NYSE stocks only**, then apply
them to the whole NYSE+AMEX+NASDAQ cross-section. That asymmetry is the entire
point: NASDAQ is thick with small firms, so all-listed breakpoints would put the
median far below NYSE's and load the "small" bucket with thousands of microcaps.
Getting this wrong does not crash anything — it produces a size factor that is
plausible and wrong.

Reproducing the breakpoints from scratch needs a historical exchange-listing map
per firm per date, which is not free and which Project 01 does not store. French
publishes his own, which removes the blocker entirely. The cost is honesty about
what was borrowed: see the caveat at the bottom of this docstring.

The format, verified against the real files
-------------------------------------------
These do **not** match the stacked-table layout in `parser.py` — there is no
`,`-leading header row, so that parser will not find them. Two distinct shapes:

`ME_Breakpoints` — monthly, values in $ millions::

    This file was created using the 202606 CRSP database. ...
    <blank>
    192512,   488,   1.40,   2.38, ...  (21 percentile columns, p5..p100)
    ...
    Copyright 2026 Eugene F. Fama and Kenneth R. French

  fields: YYYYMM, count, then every 5th percentile from 5 to 100.

`BE-ME_Breakpoints` (and `OP_`, `INV_`) — annual, with **two** count columns::

    ,<= 0,>0
    1926,     3,   429,   0.296,   0.404, ...

  fields: YYYY, n(BE<=0), n(BE>0), then every 5th percentile.

The two-count shape exists because a firm can have non-positive book equity,
which is excluded from the BE/ME sort but still worth counting. Assuming the
single-count shape shifts every percentile by one column — an error that yields
a complete, well-formed, entirely wrong breakpoint table.

Honesty caveat
--------------
Every file states the CRSP database it "was created using" — a recent vintage,
carrying restatements that were not known at the time. Using them in a build
would therefore introduce a mild lookahead and borrow rather than derive the
breakpoints. The build does neither: it derives its breakpoints from CRSP's
point-in-time exchange codes (``construct/sorts.py``), and these files serve as
the validation reference and, in the attribution only, as the "borrowed"
alternative whose effect is measured.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ffrep.reference.parser import read_text

#: French reports every 5th percentile, from the 5th to the 100th.
PERCENTILES: tuple[int, ...] = tuple(range(5, 101, 5))

#: A data row starts with a bare 4- or 6-digit year or year-month.
_DATA_ROW = re.compile(r"^\s*(\d{4}|\d{6})\s*,")

#: French's missing-data sentinels, shared with the returns files.
MISSING_CODES = (-99.99, -999.0)


@dataclass(frozen=True)
class BreakpointTable:
    """
    Percentile breakpoints indexed by period end.

    `counts` holds the firm-count columns that preceded the percentiles: one
    column for ME, two for the ratio files (non-positive and positive). They are
    kept rather than discarded because they are the cheapest available check on
    whether a parse landed on the right columns.
    """

    values: pd.DataFrame  # index: period end, columns: percentile ints
    counts: pd.DataFrame  # index: period end, columns: count labels
    periodicity: str      # "monthly" | "annual"
    preamble: str


def _parse_rows(lines: list[str]) -> tuple[list[str], list[list[float]]]:
    """Split the file into date keys and numeric fields, ignoring prose."""
    keys: list[str] = []
    rows: list[list[float]] = []

    for line in lines:
        if not _DATA_ROW.match(line):
            continue
        fields = [f.strip() for f in line.split(",")]
        keys.append(fields[0])
        rows.append([float(f) if f else np.nan for f in fields[1:] if f != ""])

    return keys, rows


def _index_from_keys(keys: list[str], periodicity: str) -> pd.DatetimeIndex:
    """
    Index by period *end*, matching the convention in `parser.py`.

    A breakpoint stamped 192512 was computed from data through the end of
    December 1925, so December 31 is the date it describes.
    """
    if periodicity == "monthly":
        index = pd.to_datetime(keys, format="%Y%m") + pd.offsets.MonthEnd(0)
    else:
        index = pd.to_datetime(keys, format="%Y") + pd.offsets.YearEnd(0)
    index.name = "date"
    return index


def load_breakpoints(source: Path | str) -> BreakpointTable:
    """
    Parse a French breakpoint file.

    The count columns are identified by subtraction rather than by reading the
    header: the percentile block is always exactly 20 wide, so anything to its
    left is a count. That is more robust than parsing the `,<= 0,>0` header,
    which is present in the ratio files and absent from `ME_Breakpoints`.
    """
    text = read_text(source)
    lines = text.splitlines()

    keys, rows = _parse_rows(lines)
    if not rows:
        raise ValueError(f"no data rows found in {source}")

    widths = {len(r) for r in rows}
    if len(widths) != 1:
        raise ValueError(
            f"ragged breakpoint rows in {source}: field counts {sorted(widths)}"
        )
    width = widths.pop()

    n_counts = width - len(PERCENTILES)
    if n_counts < 0:
        raise ValueError(
            f"{source} has {width} numeric fields, fewer than the "
            f"{len(PERCENTILES)} percentiles French publishes"
        )

    periodicity = "monthly" if len(keys[0]) == 6 else "annual"
    index = _index_from_keys(keys, periodicity)
    matrix = np.asarray(rows, dtype=float)

    count_labels = (
        ["n_firms"] if n_counts == 1 else [f"n_{i}" for i in range(n_counts)]
    )
    if n_counts == 2:
        # The ratio files split the count into non-positive and positive.
        count_labels = ["n_nonpositive", "n_positive"]

    counts = pd.DataFrame(matrix[:, :n_counts], index=index, columns=count_labels)
    values = pd.DataFrame(
        matrix[:, n_counts:], index=index, columns=list(PERCENTILES)
    )
    for code in MISSING_CODES:
        values = values.mask(np.isclose(values, code, atol=1e-9))

    preamble = next((line for line in lines if line.strip()), "")

    return BreakpointTable(
        values=values, counts=counts, periodicity=periodicity, preamble=preamble
    )


def percentile(table: BreakpointTable, pct: int) -> pd.Series:
    """
    One percentile as a time series.

    Only multiples of 5 exist in the source. Asking for the 33rd would have to
    be interpolated, and silently interpolating a breakpoint is exactly the kind
    of quiet deviation from the published protocol this project exists to avoid,
    so it raises instead.
    """
    if pct not in PERCENTILES:
        raise ValueError(
            f"French publishes every 5th percentile only; {pct} is not among "
            f"{PERCENTILES}. Interpolating would silently depart from the "
            f"published breakpoints."
        )
    return table.values[pct].rename(f"p{pct}")
