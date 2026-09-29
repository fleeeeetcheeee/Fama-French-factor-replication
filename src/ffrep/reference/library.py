"""
Download the published reference series — Ken French's library and the
Hou-Xue-Zhang q-factors.

Same ingestion discipline as Projects 01 and 02: this module **downloads and
writes bytes verbatim**. No parsing, no cleaning, no interpretation. Anything
that reads the contents belongs in `parser.py` or `breakpoints.py`.

Writes are atomic (`.tmp` then rename) so an interrupted download never leaves a
truncated zip that a later run would happily treat as cached.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import requests

from ffrep.config import (
    FRENCH_BASE_URL,
    FRENCH_FILES,
    FRENCH_HISTORICAL_BE,
    GLOBAL_Q_BASE_URL,
    GLOBAL_Q_FILES,
    Config,
)

log = logging.getLogger(__name__)

#: French's library is a normal academic web server, not an API with a published
#: rate limit. A courtesy delay between files costs nothing on eleven small
#: downloads and keeps this well clear of anything that looks like abuse.
COURTESY_DELAY_SECONDS = 0.5

#: A descriptive User-Agent is good manners everywhere and mandatory at the SEC.
USER_AGENT = "ffrep/0.1 (academic factor replication; contact via repository)"

REQUEST_TIMEOUT_SECONDS = 120


def _download(url: str, destination: Path, *, force: bool = False) -> Path:
    """
    Fetch `url` to `destination`, verbatim and atomically.

    Returns the destination path. Skips the request entirely if the file is
    already present and `force` is False — the reference files are large-ish,
    republished monthly, and re-fetching them on every run is both slow and
    impolite.
    """
    if destination.exists() and not force:
        log.info("cached, skipping: %s", destination.name)
        return destination

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")

    log.info("downloading %s", url)
    response = requests.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT_SECONDS
    )
    response.raise_for_status()

    if not response.content:
        raise RuntimeError(f"empty response body from {url}")

    try:
        temporary.write_bytes(response.content)
        temporary.replace(destination)
    except BaseException:
        # A partial .tmp left behind would be invisible to the caller but would
        # not be picked up as cached either, so it is pure litter. Remove it.
        temporary.unlink(missing_ok=True)
        raise

    log.info("wrote %s (%d bytes)", destination.name, len(response.content))
    return destination


def download_french(
    config: Config, key: str, *, force: bool = False, vintage: str = "current"
) -> Path:
    """Download one named file from French's library."""
    return _download(
        config.french_url(key, vintage), config.french_path(key, vintage), force=force
    )


def download_all_french(
    config: Config, *, force: bool = False, vintage: str = "current"
) -> dict[str, Path]:
    """
    Download every file listed in `FRENCH_FILES`, from one vintage.

    Returns {key: path}. Fails loudly on the first error rather than collecting
    them: these are small files from one host, so a failure means the host or
    the naming scheme has changed, and continuing would only produce a partial
    reference set that a later step would misread as complete.
    """
    paths: dict[str, Path] = {}
    for index, key in enumerate(FRENCH_FILES):
        paths[key] = download_french(config, key, force=force, vintage=vintage)
        if index < len(FRENCH_FILES) - 1:
            time.sleep(COURTESY_DELAY_SECONDS)
    return paths


def download_global_q(config: Config, key: str = "factors", *, force: bool = False) -> Path:
    """Download one Hou-Xue-Zhang file from global-q.org."""
    return _download(
        f"{GLOBAL_Q_BASE_URL}/{GLOBAL_Q_FILES[key]}", config.global_q_path(key), force=force
    )


def download_historical_be(config: Config, *, force: bool = False) -> Path:
    """Download French's Moody's book-equity file (vintage-independent)."""
    return _download(
        f"{FRENCH_BASE_URL}/{FRENCH_HISTORICAL_BE}", config.historical_be_path(), force=force
    )
