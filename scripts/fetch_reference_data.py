"""
Download every published reference series this project benchmarks against.

Small files from public academic servers; a few seconds in total. Re-running is
cheap because existing files are skipped, so this is safe to put at the front of
any pipeline.

    python scripts/fetch_reference_data.py
    python scripts/fetch_reference_data.py --force     # re-fetch even if cached
"""

from __future__ import annotations

import argparse
import logging
import sys

from ffrep.config import FRENCH_VINTAGES, GLOBAL_Q_FILES, Config
from ffrep.reference.library import download_all_french, download_global_q, download_historical_be


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="re-download files already present"
    )
    parser.add_argument(
        "--skip-global-q",
        action="store_true",
        help="skip global-q.org (only needed for the q-factor extension)",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = Config()

    for vintage in FRENCH_VINTAGES:
        paths = download_all_french(config, force=args.force, vintage=vintage)
        print(f"\n{len(paths)} French files ({vintage}) in "
              f"{config.french_path('factors_3', vintage).parent}")

    print(f"Moody's book equity: {download_historical_be(config, force=args.force)}")

    if not args.skip_global_q:
        try:
            for key in GLOBAL_Q_FILES:
                path = download_global_q(config, key, force=args.force)
                print(f"q-factors ({key}): {path}")
        except Exception as error:
            # Not fatal: global-q is only needed for the q-factor extension,
            # which is the last step. Failing the whole fetch over it would
            # block the steps that do not need it.
            print(f"\nWARNING: global-q.org fetch failed ({type(error).__name__}).")
            print("Only the q-factor extension needs it; everything else can proceed.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
