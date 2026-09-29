"""
Company-level CRSP -> Compustat links, resolved per formation year.

``linker.py`` measured the CUSIP fallback security by security: one PERMNO, its
CUSIPs, one GVKEY. The formation join needs something slightly different,
because by the time a firm reaches the sort it is a *company* — a PERMCO whose
market equity sums every share class — and Compustat's book equity is a company
number too. Linking at the PERMCO level lets any share class's CUSIP find the
company, which matters exactly when the largest class (the one carrying the
aggregated market equity) is not the class Compustat happens to record.

What a CUSIP match can and cannot say
-------------------------------------
A link here is a *candidate*: some CUSIP some security of this company carried
at some point equals the CUSIP Compustat records for some company. Two kinds of
ambiguity follow, and both are resolved deterministically and **counted**, not
silently absorbed (review suggestion on linkage diagnostics):

* one PERMCO reaching several GVKEYs — typically a CUSIP reused across a
  reorganisation;
* one GVKEY reached from several PERMCOs in the same year — which, unresolved,
  would give one balance sheet to two companies and double its book equity in
  the sort.

A failed match is not evidence that a firm is absent from Compustat. It is only
evidence that no CUSIP path connects them; the true link table (CCM) is not in
this subscription. Coverage is therefore reported, never assumed.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ffrep.universe.linker import normalise_cusip

#: Strength of a match path, lower is stronger. A current-to-current CUSIP
#: match compares like with like — both CRSP's header CUSIP and Compustat's
#: ``funda.cusip`` are the *current* identifiers — so it outranks a historical
#: CRSP name CUSIP, which in turn outranks a Compustat non-primary issue.
PATH_RANK: dict[tuple[str, str], int] = {
    ("crsp_header", "comp_header"): 0,
    ("crsp_name", "comp_header"): 1,
    ("crsp_header", "comp_security"): 2,
    ("crsp_name", "comp_security"): 3,
}


def crsp_candidates(names: pd.DataFrame) -> pd.DataFrame:
    """(permco, c8, source) for every CUSIP any security of the company carried."""
    frames = [
        pd.DataFrame({"permco": names["permco"], "c8": normalise_cusip(names["cusip"]),
                      "source": "crsp_header"}),
        pd.DataFrame({"permco": names["permco"], "c8": normalise_cusip(names["ncusip"]),
                      "source": "crsp_name"}),
    ]
    out = pd.concat(frames, ignore_index=True).dropna(subset=["permco", "c8"])
    return out.drop_duplicates()


def compustat_candidates(
    funda: pd.DataFrame, securities: pd.DataFrame | None = None
) -> pd.DataFrame:
    """(gvkey, c8, source): the header CUSIP, and optionally every security issue."""
    frames = [
        pd.DataFrame({"gvkey": funda["gvkey"], "c8": normalise_cusip(funda["cusip"]),
                      "source": "comp_header"})
    ]
    if securities is not None:
        frames.append(
            pd.DataFrame({"gvkey": securities["gvkey"], "c8": normalise_cusip(securities["cusip"]),
                          "source": "comp_security"})
        )
    out = pd.concat(frames, ignore_index=True).dropna(subset=["gvkey", "c8"])
    return out.drop_duplicates()


def link_candidates(crsp: pd.DataFrame, compustat: pd.DataFrame) -> pd.DataFrame:
    """
    Every (permco, gvkey) pair connected by a shared 8-character CUSIP, with the
    rank of the strongest path connecting them.
    """
    pairs = crsp.merge(compustat, on="c8", suffixes=("_crsp", "_comp"))
    pairs["rank"] = [
        PATH_RANK[(a, b)] for a, b in zip(pairs["source_crsp"], pairs["source_comp"])
    ]
    return (
        pairs.groupby(["permco", "gvkey"], as_index=False)["rank"].min()
        .sort_values(["permco", "rank", "gvkey"])
        .reset_index(drop=True)
    )


@dataclass
class Resolution:
    """One year's resolved links, plus what it cost to resolve them."""

    links: pd.Series  # permco -> gvkey
    ambiguous_permcos: int = 0
    ambiguous_gvkeys: int = 0
    dropped_permcos: list = field(default_factory=list)


def resolve(
    candidates: pd.DataFrame,
    market_equity: pd.Series,
    available_gvkeys: pd.Index,
) -> Resolution:
    """
    One GVKEY per PERMCO and one PERMCO per GVKEY, for one formation year.

    ``market_equity`` is the year's company cross-section (PERMCO -> ME);
    ``available_gvkeys`` the companies with an accounting record for the year.
    Restricting to both *before* resolving means a PERMCO whose other candidate
    GVKEY has no data that year is not counted as ambiguous — it is not.

    Ties go to the stronger CUSIP path, then the lower GVKEY; a GVKEY reached by
    several companies stays with the strongest path, then the largest market
    equity (the continuing entity rather than a spun-off fragment), then the
    lower PERMCO. Every rule is deterministic, so rebuilding reproduces the
    same sort.
    """
    pool = candidates[
        candidates["permco"].isin(market_equity.index)
        & candidates["gvkey"].isin(available_gvkeys)
    ].copy()
    if pool.empty:
        return Resolution(links=pd.Series(dtype=object, name="gvkey"))

    per_permco = pool.groupby("permco")["gvkey"].nunique()
    ambiguous_permcos = int((per_permco > 1).sum())
    pool = pool.sort_values(["permco", "rank", "gvkey"]).drop_duplicates("permco", keep="first")

    pool["me"] = market_equity.reindex(pool["permco"]).to_numpy()
    per_gvkey = pool.groupby("gvkey")["permco"].nunique()
    ambiguous_gvkeys = int((per_gvkey > 1).sum())
    kept = pool.sort_values(["gvkey", "rank", "me", "permco"], ascending=[True, True, False, True])
    kept = kept.drop_duplicates("gvkey", keep="first")
    dropped = sorted(set(pool["permco"]) - set(kept["permco"]))

    return Resolution(
        links=kept.set_index("permco")["gvkey"].sort_index(),
        ambiguous_permcos=ambiguous_permcos,
        ambiguous_gvkeys=ambiguous_gvkeys,
        dropped_permcos=dropped,
    )
