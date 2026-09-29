"""Global-q loader tests, on files in the published layout."""

from __future__ import annotations

import pandas as pd
import pytest

from ffrep.config import Config
from ffrep.reference.published import load_global_q


def test_global_q_files_become_decimal_monthly_frames(tmp_path):
    config = Config(data_root=tmp_path)
    config.global_q_raw.mkdir(parents=True)
    config.global_q_path("factors").write_text(
        "year,month,R_F,R_MKT,R_ME,R_IA,R_ROE,R_EG\n1972,1,0.30,2.50,1.00,-0.50,0.75,0.10\n"
    )
    config.global_q_path("portfolios").write_text(
        "year,month,rank_ME,rank_IA,rank_ROE,nstocks,ret_vw,retx_vw\n"
        "1972,1,1,3,2,40,1.50,1.40\n1972,1,2,1,1,10,-0.50,-0.60\n"
    )
    gq = load_global_q(config)
    jan = pd.Period("1972-01", "M")
    assert gq.factors.loc[jan, "ROE"] == pytest.approx(0.0075)
    assert gq.factors.loc[jan, "MKT"] == pytest.approx(0.025)
    assert gq.portfolios.loc[jan, "132"] == pytest.approx(0.015)
    assert gq.counts.loc[jan, "211"] == 10
