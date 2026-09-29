"""
Pull every WRDS table the bottom-up build needs into the local Parquet store.

    export WRDS_USERNAME=...          # credentials come from ~/.pgpass
    python scripts/extract_wrds.py                 # everything
    python scripts/extract_wrds.py --only comp_fundq crsp_delist

Writes ``data/processed/wrds/<name>.parquet`` plus ``manifest.json`` (rows,
date coverage, SHA-256, retrieval time, source function). Nothing here
transforms data — screening, linking and the delisting adjustment all happen
downstream in pure functions — so a re-pull is the only way the inputs change,
and the manifest records when that happened.

The monthly CRSP pull is chunked by decade. It is ~5M rows and fits in memory
comfortably, but a single query that long is the one most likely to hit the
server's intermittent connection drops, and a failed decade is cheap to retry.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone

import pandas as pd

from ffrep.config import Config
from ffrep.store import EXTRACTS, extract_path, read_manifest, write_atomic, write_manifest
from ffrep.universe.wrds_source import (
    ExtractWindow,
    connect,
    fetch_compustat_securities,
    fetch_delistings,
    fetch_fundamentals,
    fetch_monthly_stock,
    fetch_name_history,
    fetch_quarterly_fundamentals,
)

#: CRSP monthly (SIZ) begins 1925-12-31 and ends 2024-12-31 on this
#: subscription — the legacy format was discontinued after that release.
CRSP_START, CRSP_END = "1925-12-31", "2024-12-31"


def monthly_in_decades(db) -> pd.DataFrame:
    frames = []
    for start in range(1925, 2030, 10):
        if f"{start}-01-01" > CRSP_END:
            break
        window = ExtractWindow(max(f"{start}-01-01", CRSP_START), min(f"{start + 9}-12-31", CRSP_END))
        t0 = time.time()
        part = fetch_monthly_stock(db, window)
        print(f"    {window.start} .. {window.end}: {len(part):>9,} rows  ({time.time() - t0:.0f}s)", flush=True)
        frames.append(part)
    return pd.concat(frames, ignore_index=True)


PULLS = {
    "crsp_monthly": ("fetch_monthly_stock (by decade)", monthly_in_decades, "date"),
    "crsp_delist": ("fetch_delistings", lambda db: fetch_delistings(db, ExtractWindow("1925-01-01", "2025-12-31")), "date"),
    "crsp_names": ("fetch_name_history", fetch_name_history, "namedt"),
    "comp_funda": ("fetch_fundamentals", fetch_fundamentals, "datadate"),
    "comp_fundq": ("fetch_quarterly_fundamentals", fetch_quarterly_fundamentals, "datadate"),
    "comp_security": ("fetch_compustat_securities", fetch_compustat_securities, None),
}
assert set(PULLS) == set(EXTRACTS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--only", nargs="+", choices=EXTRACTS, help="pull only these extracts")
    args = parser.parse_args()

    username = os.getenv("WRDS_USERNAME")
    if not username:
        print("set WRDS_USERNAME (credentials come from ~/.pgpass)")
        return 1

    config = Config()
    manifest = read_manifest(config)
    names = args.only or list(EXTRACTS)

    db = connect(username)
    try:
        for name in names:
            source, pull, date_column = PULLS[name]
            print(f"pulling {name} ...", flush=True)
            t0 = time.time()
            frame = pull(db)
            path = extract_path(config, name)
            digest = write_atomic(frame, path)
            entry = {
                "source": f"ffrep.universe.wrds_source.{source}",
                "rows": len(frame),
                "columns": list(frame.columns),
                "sha256": digest,
                "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "wrds_username": username,
            }
            if date_column:
                dates = pd.to_datetime(frame[date_column])
                entry["coverage"] = [str(dates.min().date()), str(dates.max().date())]
            manifest[name] = entry
            write_manifest(config, manifest)
            print(f"  wrote {path.name}: {len(frame):,} rows, {path.stat().st_size / 1e6:,.0f} MB "
                  f"({time.time() - t0:.0f}s)", flush=True)
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
