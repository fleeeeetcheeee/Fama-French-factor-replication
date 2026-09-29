"""
Company-level link tests.

The resolution rules are arbitrary but must be deterministic and must *count*
what they resolve; each case here is a two- or three-row situation whose right
answer can be read off by eye.
"""

from __future__ import annotations

import pandas as pd

from ffrep.universe.links import (
    PATH_RANK,
    compustat_candidates,
    crsp_candidates,
    link_candidates,
    resolve,
)


def names(**cols) -> pd.DataFrame:
    return pd.DataFrame(cols)


class TestCandidates:
    def test_every_share_class_cusip_reaches_the_company(self):
        """Class A and class B of permco 7 both offer a path to Compustat."""
        n = names(permco=[7, 7], cusip=["AAAAAAAA", "BBBBBBBB"], ncusip=[None, None])
        c = crsp_candidates(n)
        assert set(c["c8"]) == {"AAAAAAAA", "BBBBBBBB"}
        assert set(c["permco"]) == {7}

    def test_historical_name_cusips_are_candidates_too(self):
        n = names(permco=[7], cusip=["AAAAAAAA"], ncusip=["OLDOLD01"])
        c = crsp_candidates(n)
        assert set(zip(c["c8"], c["source"])) == {
            ("AAAAAAAA", "crsp_header"), ("OLDOLD01", "crsp_name"),
        }

    def test_compustat_nine_digit_cusips_are_truncated(self):
        f = pd.DataFrame({"gvkey": ["001"], "cusip": ["AAAAAAAA9"]})
        assert compustat_candidates(f)["c8"].tolist() == ["AAAAAAAA"]

    def test_security_table_adds_non_primary_issues(self):
        f = pd.DataFrame({"gvkey": ["001"], "cusip": ["AAAAAAAA9"]})
        s = pd.DataFrame({"gvkey": ["001"], "cusip": ["BBBBBBBB1"]})
        c = compustat_candidates(f, s)
        assert set(zip(c["c8"], c["source"])) == {
            ("AAAAAAAA", "comp_header"), ("BBBBBBBB", "comp_security"),
        }

    def test_link_keeps_the_strongest_path_per_pair(self):
        crsp = crsp_candidates(names(permco=[7], cusip=["AAAAAAAA"], ncusip=["AAAAAAAA"]))
        comp = compustat_candidates(pd.DataFrame({"gvkey": ["001"], "cusip": ["AAAAAAAA9"]}))
        links = link_candidates(crsp, comp)
        assert len(links) == 1
        assert links.loc[0, "rank"] == PATH_RANK[("crsp_header", "comp_header")]


def candidates(rows) -> pd.DataFrame:
    return pd.DataFrame(rows, columns=["permco", "gvkey", "rank"])


class TestResolve:
    def test_one_to_one_links_pass_through(self):
        r = resolve(candidates([(1, "A", 0), (2, "B", 0)]),
                    pd.Series({1: 10.0, 2: 20.0}), pd.Index(["A", "B"]))
        assert r.links.to_dict() == {1: "A", 2: "B"}
        assert (r.ambiguous_permcos, r.ambiguous_gvkeys) == (0, 0)

    def test_a_candidate_without_data_that_year_is_not_ambiguity(self):
        r = resolve(candidates([(1, "A", 0), (1, "Z", 0)]),
                    pd.Series({1: 10.0}), pd.Index(["A"]))
        assert r.links.to_dict() == {1: "A"}
        assert r.ambiguous_permcos == 0

    def test_permco_with_two_gvkeys_takes_the_stronger_path_and_is_counted(self):
        r = resolve(candidates([(1, "A", 1), (1, "B", 0)]),
                    pd.Series({1: 10.0}), pd.Index(["A", "B"]))
        assert r.links.to_dict() == {1: "B"}
        assert r.ambiguous_permcos == 1

    def test_equal_paths_break_on_the_lower_gvkey(self):
        r = resolve(candidates([(1, "B", 0), (1, "A", 0)]),
                    pd.Series({1: 10.0}), pd.Index(["A", "B"]))
        assert r.links.to_dict() == {1: "A"}

    def test_one_balance_sheet_never_goes_to_two_companies(self):
        """Unresolved, GVKEY A's book equity would enter the sort twice."""
        r = resolve(candidates([(1, "A", 0), (2, "A", 0)]),
                    pd.Series({1: 10.0, 2: 90.0}), pd.Index(["A"]))
        assert r.links.to_dict() == {2: "A"}
        assert r.ambiguous_gvkeys == 1
        assert r.dropped_permcos == [1]

    def test_path_strength_outranks_size_for_a_shared_gvkey(self):
        r = resolve(candidates([(1, "A", 0), (2, "A", 3)]),
                    pd.Series({1: 10.0, 2: 90.0}), pd.Index(["A"]))
        assert r.links.to_dict() == {1: "A"}

    def test_companies_outside_the_cross_section_are_ignored(self):
        r = resolve(candidates([(1, "A", 0), (9, "A", 0)]),
                    pd.Series({1: 10.0}), pd.Index(["A"]))
        assert r.links.to_dict() == {1: "A"}
        assert r.ambiguous_gvkeys == 0

    def test_empty_pool(self):
        r = resolve(candidates([]), pd.Series({1: 10.0}), pd.Index(["A"]))
        assert r.links.empty

    def test_is_deterministic_under_row_order(self):
        rows = [(1, "A", 0), (1, "B", 0), (2, "A", 0), (3, "C", 2)]
        me = pd.Series({1: 10.0, 2: 10.0, 3: 5.0})
        a = resolve(candidates(rows), me, pd.Index(["A", "B", "C"]))
        b = resolve(candidates(rows[::-1]), me, pd.Index(["A", "B", "C"]))
        pd.testing.assert_series_equal(a.links, b.links)


class TestIssuerMatches:
    def test_issuer_code_links_when_no_full_cusip_does(self):
        """Class B's CUSIP 12345620 never appears in Compustat, whose record is 12345610."""
        crsp = crsp_candidates(names(permco=[7], cusip=["12345620"], ncusip=[None]))
        comp = compustat_candidates(pd.DataFrame({"gvkey": ["001"], "cusip": ["123456109"]}))
        links = link_candidates(crsp, comp)
        assert links.to_dict("records") == [{"permco": 7, "gvkey": "001", "rank": 4}]

    def test_full_cusip_outranks_the_issuer_match_of_the_same_pair(self):
        crsp = crsp_candidates(names(permco=[7], cusip=["12345610"], ncusip=[None]))
        comp = compustat_candidates(pd.DataFrame({"gvkey": ["001"], "cusip": ["123456109"]}))
        assert link_candidates(crsp, comp)["rank"].tolist() == [0]

    def test_issuer_matching_can_be_switched_off(self):
        crsp = crsp_candidates(names(permco=[7], cusip=["12345620"], ncusip=[None]))
        comp = compustat_candidates(pd.DataFrame({"gvkey": ["001"], "cusip": ["123456109"]}))
        assert link_candidates(crsp, comp, issuer_matches=False).empty

    def test_an_issuer_match_never_beats_a_full_cusip_to_another_company(self):
        """Permco 7 fully matches gvkey 002 and shares only an issuer code with 001."""
        crsp = crsp_candidates(names(permco=[7, 7], cusip=["12345620", "99999910"], ncusip=[None, None]))
        comp = compustat_candidates(pd.DataFrame({"gvkey": ["001", "002"], "cusip": ["123456109", "999999101"]}))
        resolved = resolve(link_candidates(crsp, comp), pd.Series({7: 10.0}), pd.Index(["001", "002"]))
        assert resolved.links.to_dict() == {7: "002"}
