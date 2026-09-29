"""Spanning-test tests: a factor built from the model is spanned; one with alpha is not."""

from __future__ import annotations

import numpy as np
import pandas as pd

from ffrep.evaluate.spanning import spanning


def model_and_targets(alpha: float, T: int = 400, seed: int = 3):
    rng = np.random.default_rng(seed)
    idx = pd.period_range("1980-01", periods=T, freq="M")
    model = pd.DataFrame({"mkt": rng.normal(0.006, 0.045, T), "smb": rng.normal(0.002, 0.03, T)}, index=idx)
    targets = pd.DataFrame({
        "a": alpha + 0.5 * model["mkt"] + rng.normal(0, 0.01, T),
        "b": alpha - 0.3 * model["smb"] + rng.normal(0, 0.01, T),
    }, index=idx)
    return targets, model


def test_a_spanned_set_is_not_rejected():
    targets, model = model_and_targets(alpha=0.0)
    table, joint = spanning(targets, model, name="null")
    assert joint["grs_p"] > 0.05
    assert (table["t_alpha"].abs() < 2.5).all()


def test_a_set_with_alpha_is_rejected():
    targets, model = model_and_targets(alpha=0.004)
    table, joint = spanning(targets, model, name="alt")
    assert joint["grs_p"] < 0.001
    assert (table["alpha_pct"] > 0.2).all()


def test_individual_and_joint_tests_use_the_same_months():
    targets, model = model_and_targets(alpha=0.0)
    targets.iloc[:10, 0] = np.nan            # only one target has a gap
    table, joint = spanning(targets, model)
    assert set(table["n"]) == {joint["n"]} == {390}
