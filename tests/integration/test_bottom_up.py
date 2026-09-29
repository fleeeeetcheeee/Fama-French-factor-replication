"""
The done criterion, as a test: bottom-up HML against French's published HML.

"Monthly returns of your HML factor correlate with French's published HML at
>0.99 over at least the 1990-2020 period."

Rebuilds the BE/ME sort from the local WRDS extracts (``scripts/extract_wrds.py``)
for formations June 1989 - June 2020, which hold every month of 1990-2020, and
scores it against French's December-2024 release — the last one built from the
same legacy CRSP files this build reads. Skips cleanly on a fresh clone: WRDS
data cannot be redistributed, so the extracts are never in the repository.

Also pins the two measured facts the result rests on, so a regression that
removes either fails here rather than quietly lowering the number: the
deferred-tax cutoff, and linking through Compustat's full security table.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from ffrep.config import Config
from ffrep.construct.formation import Conventions
from ffrep.evaluate.compare import fit
from ffrep.store import EXTRACTS, extract_path

SPEC = ("1990-01", "2020-12")
YEARS = range(1989, 2021)
FAST = dict(sorts=("beme",), momentum=False, market=False)


def _require_data(config: Config) -> None:
    missing = [n for n in EXTRACTS if not extract_path(config, n).exists()]
    if missing:
        pytest.skip(f"WRDS extracts not present: {missing}. Run scripts/extract_wrds.py.")
    if not config.french_path("factors_3", "fiz202412").exists():
        pytest.skip("French reference files not downloaded. Run scripts/fetch_reference_data.py.")


@pytest.fixture(scope="module")
def setup():
    from ffrep.pipeline import build, load_inputs
    from ffrep.reference.published import load_published

    config = Config()
    _require_data(config)
    inputs = load_inputs(config)
    published = load_published(config, "fiz202412").factors
    baseline = build(inputs, years=YEARS, **FAST)["factors"]
    return {"inputs": inputs, "published": published, "baseline": baseline, "build": build}


def _hml_fit(factors, published):
    start, end = SPEC
    return fit(factors["HML"].loc[start:end], published["HML"].loc[start:end])


def test_done_criterion_hml_correlation_above_099(setup):
    f = _hml_fit(setup["baseline"], setup["published"])
    assert f.n == 372
    assert f.corr > 0.99


def test_smb_is_replicated_too(setup):
    start, end = SPEC
    f = fit(setup["baseline"]["SMB"].loc[start:end], setup["published"]["SMB"].loc[start:end])
    assert f.corr > 0.99


def test_hml_scale_is_right_not_just_its_direction(setup):
    """Correlation is blind to scale; the slope and tracking error are not."""
    f = _hml_fit(setup["baseline"], setup["published"])
    assert 0.95 < f.slope < 1.05
    assert f.te_bps < 40


def test_deferred_tax_cutoff_is_load_bearing(setup):
    """Adding deferred taxes in every year, as the definition literally reads, fits worse."""
    always = setup["build"](setup["inputs"], replace(Conventions(), deferred_taxes_through=None),
                            years=YEARS, **FAST)["factors"]
    assert _hml_fit(always, setup["published"]).corr < _hml_fit(setup["baseline"], setup["published"]).corr - 0.01


def test_security_table_linking_is_load_bearing(setup):
    from ffrep.pipeline import load_inputs

    header_only = setup["build"](load_inputs(Config(), compustat_securities=False),
                                 years=YEARS, **FAST)["factors"]
    assert _hml_fit(header_only, setup["published"]).corr < _hml_fit(setup["baseline"], setup["published"]).corr
