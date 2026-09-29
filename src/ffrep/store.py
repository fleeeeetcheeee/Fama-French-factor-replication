"""
The local Parquet store for WRDS extracts: atomic writes, checksums, one loader.

WRDS data cannot be redistributed, so ``data/`` is gitignored and the repository
ships the code that rebuilds it rather than the data. That makes provenance the
thing worth versioning: every extract is written next to a ``manifest.json``
recording what was pulled, when, how many rows, over what date range, and the
SHA-256 of the file — so a result can always be traced to the exact inputs that
produced it, and a silently changed input is detectable.

Writes are atomic (``.tmp`` then rename), the same discipline as the reference
downloads: an interrupted extract never leaves a truncated file that a later
step would read as complete.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from ffrep.config import Config

#: Every extract the build reads, by name. The names are the file stems.
EXTRACTS: tuple[str, ...] = (
    "crsp_monthly",
    "crsp_delist",
    "crsp_names",
    "comp_funda",
    "comp_fundq",
    "comp_security",
)

MANIFEST_NAME = "manifest.json"


def extract_path(config: Config, name: str) -> Path:
    if name not in EXTRACTS:
        raise KeyError(f"unknown extract {name!r}; known: {list(EXTRACTS)}")
    return config.wrds_extract / f"{name}.parquet"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def write_atomic(frame: pd.DataFrame, path: Path) -> str:
    """Write ``frame`` to ``path`` via a temporary file; return its SHA-256."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        frame.to_parquet(temporary, index=False)
        temporary.replace(path)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return sha256(path)


def to_numpy_dtypes(frame: pd.DataFrame) -> pd.DataFrame:
    """
    Replace pandas' nullable extension dtypes with plain numpy ones.

    The ``wrds`` package returns ``Float64``/``Int64``, which carry ``pd.NA``
    rather than ``NaN``. Two consequences, both measured: ``pd.NA`` propagates
    through comparisons (``NA > 0`` is ``NA``, not ``False``), which is a
    different missing-data semantics from the one every function here is
    written and tested against; and a wide months x securities frame of an
    extension dtype is stored one block per column, which made a single holding
    year's portfolio arithmetic take ~3 seconds instead of milliseconds.

    Integers stay integers when nothing is missing (identifiers); otherwise
    they become float with ``NaN``. Strings are left alone.
    """
    out = frame.copy()
    for column, dtype in out.dtypes.items():
        if isinstance(dtype, pd.Float64Dtype) or str(dtype) == "Float32":
            out[column] = out[column].to_numpy(dtype=float, na_value=np.nan)
        elif isinstance(dtype, pd.core.dtypes.dtypes.BaseMaskedDtype) and dtype.kind in "iu":
            has_na = bool(out[column].isna().any())
            out[column] = (out[column].to_numpy(dtype=float, na_value=np.nan) if has_na
                           else out[column].to_numpy(dtype="int64"))
    return out


def read_extract(
    config: Config, name: str, columns: list[str] | None = None
) -> pd.DataFrame:
    """Load one extract with numpy dtypes, or explain how to create it."""
    path = extract_path(config, name)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} does not exist. Run `python scripts/extract_wrds.py` "
            f"(needs WRDS_USERNAME and ~/.pgpass)."
        )
    return to_numpy_dtypes(pd.read_parquet(path, columns=columns))


def read_manifest(config: Config) -> dict:
    path = config.wrds_extract / MANIFEST_NAME
    return json.loads(path.read_text()) if path.exists() else {}


def write_manifest(config: Config, manifest: dict) -> None:
    path = config.wrds_extract / MANIFEST_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(manifest, indent=2, sort_keys=True, default=str))
    temporary.replace(path)
