"""Parser tests for French's Moody's book-equity file, in its real layout."""

from __future__ import annotations

import pytest

from ffrep.reference.historical_be import FIRST_YEAR, LAST_YEAR, load_historical_be

N_YEARS = LAST_YEAR - FIRST_YEAR + 1


def record(permno: int, values: dict[int, float]) -> str:
    cells = [f"{values.get(y, -99.99):11.3f}" for y in range(FIRST_YEAR, LAST_YEAR + 1)]
    years = sorted(values) or [FIRST_YEAR]
    return f"{permno:7d} {years[0]} {years[-1]} " + " ".join(cells)


def test_reads_values_by_formation_year(tmp_path):
    path = tmp_path / "DFF_BE_With_Nonindust.txt"
    path.write_text(record(10006, {1926: 67.743, 1953: 64.269}) + "\n" + record(10014, {1960: 6.527}) + "\n")
    frame = load_historical_be(path)
    got = {(r.permno, r.year): r.be for r in frame.itertuples()}
    assert got == {(10006, 1926): pytest.approx(67.743), (10006, 1953): pytest.approx(64.269),
                   (10014, 1960): pytest.approx(6.527)}


def test_missing_code_is_dropped_not_kept_as_a_value(tmp_path):
    path = tmp_path / "be.txt"
    path.write_text(record(10006, {}) + "\n")
    assert load_historical_be(path).empty


def test_rejects_a_short_record(tmp_path):
    path = tmp_path / "be.txt"
    path.write_text("10006 1926 1926 1.0 2.0\n")
    with pytest.raises(ValueError, match="fields"):
        load_historical_be(path)
