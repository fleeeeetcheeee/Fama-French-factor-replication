"""
The PERMNO -> GVKEY bridge, and the seam where its cost is measured.

CRSP identifies securities by PERMNO; Compustat identifies companies by GVKEY.
Joining them is normally CRSP/Compustat Merged's job — a curated, date-aware
link table that is the correct answer to this problem.

We do not have it. ``crsp_a_ccm`` is outside this subscription and cannot be
added, so the join falls back to matching CUSIPs. That is a real, permanent
limitation of this replication and it is given a first-class interface rather
than being buried in a merge call, for three reasons: the assumption stays in
one place, its cost is measurable by ablation in step 5, and if CCM ever becomes
available it is a substitution rather than a rewrite.

Measured cost of the fallback (June 2020, 3,549 securities, $30.7T):

    current CUSIP            92.2% of firms   96.1% of market equity
    NCUSIP alone             81.9%            94.2%
    union of all historical  92.9%            96.1%

The union buys +0.7pp of firms and nothing by market equity, so the residual is
structural — those firms are genuinely absent from Compustat — rather than a
CUSIP-vintage artifact. Unmatched names have a median market equity of $122m
against $724m for matched ones: the gap is a small-cap gap, which is precisely
where a value factor carries risk. Reported, not hidden.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

#: Compustat stores a 9-character CUSIP (8 + check digit); CRSP stores 8.
#: Comparing the two without truncating matches nothing at all, silently.
CUSIP_MATCH_LENGTH = 8


def normalise_cusip(s: pd.Series) -> pd.Series:
    """Upper-case, strip, and truncate to the 8-character issue-level CUSIP."""
    return (
        s.astype("string")
        .str.strip()
        .str.upper()
        .str.slice(0, CUSIP_MATCH_LENGTH)
        .replace({"": pd.NA})
    )


class Linker(ABC):
    """A mapping from CRSP securities to Compustat companies."""

    #: Name recorded alongside results so an output can always be traced back
    #: to the linkage assumption that produced it.
    name: str

    @abstractmethod
    def link(self, crsp: pd.DataFrame, compustat: pd.DataFrame) -> pd.DataFrame:
        """Return ``crsp`` with a ``gvkey`` column added (NA where unmatched)."""

    def coverage(self, linked: pd.DataFrame) -> dict[str, float]:
        """
        Match rate by count and by market equity.

        Both numbers are reported because they answer different questions: the
        count says how much of the cross-section is missing, the weight says how
        much of the *factor* is. For a value-weighted factor they can differ by
        several points, and quoting only the flattering one would be dishonest.
        """
        matched = linked["gvkey"].notna()
        out = {"n": float(len(linked)), "by_count": float(matched.mean())}
        if "me" in linked.columns:
            total = linked["me"].sum()
            out["by_market_equity"] = float(linked.loc[matched, "me"].sum() / total) if total else 0.0
        return out


class CusipLinker(Linker):
    """
    Link on the 8-character CUSIP, optionally against a PERMNO's full history.

    ``historical`` supplies every CUSIP a PERMNO ever carried (both ``cusip``
    and ``ncusip`` from ``msenames``). Passing it widens the match slightly and
    costs one extra table; omitting it uses only the CUSIP on the row.
    """

    name = "cusip"

    def __init__(self, historical: pd.DataFrame | None = None) -> None:
        self._historical = historical

    def _candidates(self, crsp: pd.DataFrame) -> pd.DataFrame:
        """One row per (permno, candidate CUSIP)."""
        frames = [
            pd.DataFrame({"permno": crsp["permno"], "c8": normalise_cusip(crsp["cusip"])})
        ]
        if self._historical is not None:
            h = self._historical
            for col in ("cusip", "ncusip"):
                if col in h.columns:
                    frames.append(
                        pd.DataFrame({"permno": h["permno"], "c8": normalise_cusip(h[col])})
                    )
        return pd.concat(frames, ignore_index=True).dropna().drop_duplicates()

    def link(self, crsp: pd.DataFrame, compustat: pd.DataFrame) -> pd.DataFrame:
        if "cusip" not in crsp.columns:
            raise KeyError("CusipLinker needs a 'cusip' column on the CRSP frame")

        comp = compustat.copy()
        comp["c8"] = normalise_cusip(comp["cusip"])
        comp = comp.dropna(subset=["c8"]).drop_duplicates(subset=["c8"], keep="first")

        pairs = self._candidates(crsp).merge(comp[["c8", "gvkey"]], on="c8", how="inner")
        # A PERMNO reaching two GVKEYs through different historical CUSIPs is
        # ambiguous; keep the lowest so the build stays reproducible, and let
        # the count of such cases be visible rather than silently resolved.
        best = pairs.sort_values(["permno", "gvkey"]).drop_duplicates("permno", keep="first")

        return crsp.merge(best[["permno", "gvkey"]], on="permno", how="left")


class CcmLinker(Linker):
    """
    The correct implementation, kept unbuilt on purpose.

    Raises rather than silently degrading to CUSIP, so that the day CCM access
    appears the failure is a loud one at the seam instead of a quiet difference
    in results. Everything it needs is documented in LOG.md, 2026-08-24.
    """

    name = "ccm"

    def link(self, crsp: pd.DataFrame, compustat: pd.DataFrame) -> pd.DataFrame:
        raise NotImplementedError(
            "CRSP/Compustat Merged (crsp_a_ccm) is not in this WRDS subscription "
            "and cannot be added; see LOG.md open question 4. Use CusipLinker, "
            "whose measured coverage is 92.9% of firms / 96.1% of market equity."
        )
