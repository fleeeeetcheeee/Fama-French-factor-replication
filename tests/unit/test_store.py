"""Store tests: atomic writes, checksums, and the dtype boundary."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from ffrep.config import Config
from ffrep.store import extract_path, read_extract, sha256, to_numpy_dtypes, write_atomic


class TestDtypes:
    def test_nullable_floats_become_numpy_with_nan(self):
        frame = pd.DataFrame({"ret": pd.array([0.1, None], dtype="Float64")})
        out = to_numpy_dtypes(frame)
        assert out["ret"].dtype == np.float64
        assert np.isnan(out["ret"].iloc[1])

    def test_missing_compares_false_not_na(self):
        """The semantic reason for the conversion: NaN > 0 is False; pd.NA > 0 is NA."""
        frame = pd.DataFrame({"be": pd.array([1.0, None], dtype="Float64")})
        assert (to_numpy_dtypes(frame)["be"] > 0).tolist() == [True, False]

    def test_complete_integers_stay_integers(self):
        out = to_numpy_dtypes(pd.DataFrame({"permno": pd.array([10001, 10002], dtype="Int64")}))
        assert out["permno"].dtype == np.int64

    def test_integers_with_gaps_become_float(self):
        out = to_numpy_dtypes(pd.DataFrame({"siccd": pd.array([6799, None], dtype="Int64")}))
        assert out["siccd"].dtype == np.float64

    def test_strings_are_untouched(self):
        frame = pd.DataFrame({"cusip": pd.array(["12345678", None], dtype="string")})
        assert str(to_numpy_dtypes(frame)["cusip"].dtype) == "string"


class TestStore:
    def test_round_trip_and_checksum(self, tmp_path):
        config = Config(data_root=tmp_path)
        path = extract_path(config, "crsp_delist")
        digest = write_atomic(pd.DataFrame({"permno": [1], "dlret": [0.5]}), path)
        assert digest == sha256(path)
        assert not path.with_suffix(".parquet.tmp").exists()
        assert read_extract(config, "crsp_delist")["dlret"].tolist() == [0.5]

    def test_missing_extract_explains_how_to_make_it(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="extract_wrds.py"):
            read_extract(Config(data_root=tmp_path), "crsp_monthly")

    def test_unknown_extract_name_raises(self, tmp_path):
        with pytest.raises(KeyError):
            extract_path(Config(data_root=tmp_path), "crsp_daily")
