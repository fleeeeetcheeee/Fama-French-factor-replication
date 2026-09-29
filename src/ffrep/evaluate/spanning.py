"""
Spanning tests: does one factor model price the other's factors?

A factor is *spanned* by a model when regressing it on the model's factors
leaves an intercept indistinguishable from zero — the model already prices
everything the factor earns. Run in both directions, the test asks which model
nests the other:

    q-factors on FF5 (and FF5 + UMD)     is the q-model redundant given FF?
    FF factors on the q-model            is FF redundant given q?

Hou, Xue and Zhang (2015, 2019) report that the q-model spans HML and CMA but
FF5 does not span ROE; this module lets that be checked on both the published
series and the ones built here.

Each factor gets its own Newey-West alpha (``ols``); the set gets a GRS test,
because counting individual t-statistics above 2 ignores that the residuals are
correlated across factors.
"""

from __future__ import annotations

import pandas as pd

from ffrep.evaluate.regression import grs_test, ols


def spanning(
    targets: pd.DataFrame, model: pd.DataFrame, *, name: str = ""
) -> tuple[pd.DataFrame, dict]:
    """
    Regress each column of ``targets`` on all of ``model``.

    Returns a per-factor table (monthly alpha in percent, its Newey-West t,
    R²) and a GRS summary over the whole set, all on the months where every
    series is present — so the individual regressions and the joint test use
    the same sample.
    """
    common = targets.dropna().index.intersection(model.dropna().index, sort=False)
    targets, model = targets.loc[common], model.loc[common]
    rows = []
    for column in targets.columns:
        result = ols(targets[column], model)
        rows.append({
            "test": name, "factor": column, "alpha_pct": 100 * result.alpha,
            "t_alpha": result.alpha_t, "r2": result.r_squared, "n": result.n_obs,
        })
    grs = grs_test(targets, model)
    summary = {"test": name, "grs_f": grs.statistic, "grs_p": grs.p_value,
               "n": grs.n_obs, "assets": grs.n_assets, "factors": grs.n_factors,
               "first": str(common.min()), "last": str(common.max())}
    return pd.DataFrame(rows), summary
