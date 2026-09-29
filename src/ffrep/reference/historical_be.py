"""
Parser for French's historical (Moody's) book-equity file.

"This file contains hand-collected book equity values from the Moody's
Industrial, Public Utility, Transportation, and Bank and Finance Manuals. It
includes the data used in Davis, Fama and French (2000) and similar data for
non-industrial firms." Each record is::

    CRSP_Permno  First_Moody_Year  Last_Moody_Year  BE(1926) ... BE(2001)

in $ millions, missing as -99.990. "The book equity observation for year t
would be publicly available as of June 30 of year t" — so BE(t) is exactly the
number a June-t formation may use, with no further lag to apply.

It is keyed by PERMNO, so unlike Compustat it needs no CUSIP link. French builds
book equity "from Compustat data or collected from the Moody's ... manuals",
which is why this file is the right source for firms Compustat does not reach —
the thin early decades, where our linked Compustat coverage is 64-76% of the
June cross-section by count.
"""

from __future__ import annotations

import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

FIRST_YEAR, LAST_YEAR = 1926, 2001
MISSING = -99.99


def load_historical_be(source: Path | str) -> pd.DataFrame:
    """Long frame: ``permno``, ``year`` (the June formation it serves), ``be``."""
    path = Path(source)
    if path.suffix.lower() == ".zip":
        with zipfile.ZipFile(path) as archive:
            (name,) = archive.namelist()
            text = archive.read(name).decode("ascii")
    else:
        text = path.read_text()

    years = list(range(FIRST_YEAR, LAST_YEAR + 1))
    rows = [line.split() for line in text.splitlines() if line.strip()]
    width = 3 + len(years)
    bad = [i for i, r in enumerate(rows) if len(r) != width]
    if bad:
        raise ValueError(f"expected {width} fields per record; rows {bad[:5]} differ")

    values = np.array([[float(v) for v in r[3:]] for r in rows])
    frame = pd.DataFrame(values, columns=years)
    frame.insert(0, "permno", [int(r[0]) for r in rows])
    long = frame.melt(id_vars="permno", var_name="year", value_name="be")
    long = long[~np.isclose(long["be"], MISSING)]
    long["year"] = long["year"].astype(int)
    return long.sort_values(["permno", "year"]).reset_index(drop=True)
