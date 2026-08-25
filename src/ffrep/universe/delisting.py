"""
Delisting returns: the correction that keeps the value leg honest.

When a stock leaves CRSP, its final partial-month return lives in a separate
file (``msedelist``), not in ``msf``. Ignoring it is the single most common
survivorship-flavoured error in factor replication, and it is not
sign-symmetric: firms delist for distress far more often than for triumph, and
value portfolios are disproportionately distressed firms. Dropping the delisting
month therefore inflates the value leg specifically, which is exactly the number
this project is trying to measure.

Shumway (1997) documented that performance-related delistings whose return CRSP
never recorded averaged about -30%, and that convention is what the literature
standardised on. Applying it is a judgement call made explicitly rather than a
gap left implicit — the whole reason it lives in its own module with its own
constant in ``config.py``.

Measured relevance here: of 29,106 delisting events in our CRSP subscription,
193 are performance-related with a missing return. Small, and applied anyway,
because the cost of the check is nil and the cost of the omission is a biased
factor.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ffrep.config import PERFORMANCE_DELISTING_CODES, SHUMWAY_DELISTING_RETURN


def impute_delisting_return(
    dlret: pd.Series,
    dlstcd: pd.Series,
    *,
    shumway_return: float = SHUMWAY_DELISTING_RETURN,
) -> pd.Series:
    """
    Fill missing delisting returns.

    Performance-related codes get Shumway's -30%; everything else gets 0.0,
    which says "the delisting itself moved the price by nothing we know of" —
    appropriate for mergers and voluntary exchange moves, where the holder was
    generally made whole.

    Returns a new Series; inputs are not modified.
    """
    out = pd.to_numeric(dlret, errors="coerce").astype(float)
    codes = pd.to_numeric(dlstcd, errors="coerce")

    missing = out.isna()
    performance = codes.isin(PERFORMANCE_DELISTING_CODES)

    out = out.mask(missing & performance, shumway_return)
    out = out.mask(missing & ~performance, 0.0)
    return out


def compound_delisting(ret: pd.Series, dlret: pd.Series) -> pd.Series:
    """
    Combine a partial-month holding return with its delisting return.

    Compounded, never summed: the delisting return is measured *from* the last
    available price, so the two are sequential, not simultaneous. A missing
    ``ret`` with a present ``dlret`` yields the delisting return alone, which is
    the common case for a firm that stopped trading early in the month.
    """
    r = pd.to_numeric(ret, errors="coerce")
    d = pd.to_numeric(dlret, errors="coerce")

    both = (1.0 + r.fillna(0.0)) * (1.0 + d.fillna(0.0)) - 1.0
    # If neither leg exists there is no return, and 0.0 would be a fabrication.
    return both.mask(r.isna() & d.isna(), np.nan)


def apply_delisting_returns(
    monthly: pd.DataFrame,
    delist: pd.DataFrame,
    *,
    on: tuple[str, str] = ("permno", "date"),
) -> pd.DataFrame:
    """
    Merge delisting returns onto a monthly panel and compound them into ``ret``.

    ``delist`` must carry ``permno``, the delisting date column named to match
    ``on[1]``, ``dlret`` and ``dlstcd``. Rows of ``monthly`` with no delisting
    event pass through untouched. Adds ``dlret``/``dlstcd`` columns so the
    adjustment stays auditable after the fact rather than being folded away
    invisibly — the same reason SIZ was chosen over CIZ.
    """
    if "ret" not in monthly.columns:
        raise KeyError("apply_delisting_returns expects a 'ret' column")

    keys = list(on)
    d = delist.copy()
    d["dlret"] = impute_delisting_return(d["dlret"], d["dlstcd"])

    out = monthly.merge(d[keys + ["dlret", "dlstcd"]], on=keys, how="left")
    has_event = out["dlret"].notna()
    out.loc[has_event, "ret"] = compound_delisting(
        out.loc[has_event, "ret"], out.loc[has_event, "dlret"]
    )
    return out
