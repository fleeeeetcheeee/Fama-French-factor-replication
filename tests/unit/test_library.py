"""
Tests for the reference-data downloader.

Project 01 shipped with `ingestion/` at 0% coverage and every one of the five
bugs its first live run found lived there — a dead URL, a relocated table, a
parser that had never met a real response. The lesson taken from that: the
download layer gets tested even though "it obviously works", because the way it
fails is silently and months later.

`requests.get` is stubbed rather than mocked at the socket level; the surface
this module uses is small enough that a fake response object covers it exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
import requests

from ffrep.config import FRENCH_FILES, Config
from ffrep.reference import library


@dataclass
class FakeResponse:
    content: bytes
    status_code: int = 200

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}")


@pytest.fixture
def config(tmp_path) -> Config:
    return Config(data_root=tmp_path)


@pytest.fixture
def calls(monkeypatch):
    """Record every request and serve a fixed body."""
    recorded: list[tuple[str, dict]] = []

    def fake_get(url, headers=None, timeout=None):
        recorded.append((url, {"headers": headers, "timeout": timeout}))
        return FakeResponse(b"zip-bytes")

    monkeypatch.setattr(library.requests, "get", fake_get)
    return recorded


class TestDownload:
    def test_writes_the_body_verbatim(self, config, calls):
        path = library.download_french(config, "bp_me")
        assert path.read_bytes() == b"zip-bytes"

    def test_writes_to_the_configured_path(self, config, calls):
        path = library.download_french(config, "bp_me")
        assert path == config.french_path("bp_me")
        assert path.parent == config.french_raw

    def test_creates_missing_parent_directories(self, config, calls):
        assert not config.french_raw.exists()
        library.download_french(config, "bp_me")
        assert config.french_raw.is_dir()

    def test_sends_a_descriptive_user_agent(self, config, calls):
        library.download_french(config, "bp_me")
        _, kwargs = calls[0]
        assert "ffrep" in kwargs["headers"]["User-Agent"]

    def test_sets_a_timeout(self, config, calls):
        """An untimed request in a batch job hangs forever rather than failing."""
        library.download_french(config, "bp_me")
        assert calls[0][1]["timeout"] == library.REQUEST_TIMEOUT_SECONDS

    def test_leaves_no_temporary_file_behind(self, config, calls):
        library.download_french(config, "bp_me")
        assert list(config.french_raw.glob("*.tmp")) == []

    def test_skips_the_request_when_already_cached(self, config, calls):
        library.download_french(config, "bp_me")
        library.download_french(config, "bp_me")
        assert len(calls) == 1

    def test_force_re_downloads(self, config, calls):
        library.download_french(config, "bp_me")
        library.download_french(config, "bp_me", force=True)
        assert len(calls) == 2

    def test_rejects_an_empty_body(self, config, monkeypatch):
        """
        A zero-byte response would otherwise be cached as a valid file and every
        later run would skip re-fetching it — a silent, permanent failure.
        """
        monkeypatch.setattr(
            library.requests, "get", lambda *a, **k: FakeResponse(b"")
        )
        with pytest.raises(RuntimeError, match="empty response"):
            library.download_french(config, "bp_me")
        assert not config.french_path("bp_me").exists()

    def test_propagates_http_errors(self, config, monkeypatch):
        monkeypatch.setattr(
            library.requests,
            "get",
            lambda *a, **k: FakeResponse(b"not found", status_code=404),
        )
        with pytest.raises(requests.HTTPError):
            library.download_french(config, "bp_me")

    def test_cleans_up_after_a_failed_write(self, config, monkeypatch):
        """A leftover .tmp is not treated as cached, so it is pure litter."""
        monkeypatch.setattr(
            library.requests, "get", lambda *a, **k: FakeResponse(b"data")
        )

        def exploding_replace(self, target):
            raise OSError("disk full")

        monkeypatch.setattr(library.Path, "replace", exploding_replace)
        with pytest.raises(OSError):
            library.download_french(config, "bp_me")
        assert list(config.french_raw.glob("*.tmp")) == []

    def test_partial_writes_are_never_visible(self, config, monkeypatch):
        """
        The atomic-write guarantee, stated as a property: at no point does the
        destination path hold anything other than the complete body. Same
        discipline as Project 01's storage writer.
        """
        seen: list[bool] = []
        real_write = library.Path.write_bytes

        def watching_write(self, data):
            seen.append(config.french_path("bp_me").exists())
            return real_write(self, data)

        monkeypatch.setattr(library.requests, "get", lambda *a, **k: FakeResponse(b"x" * 100))
        monkeypatch.setattr(library.Path, "write_bytes", watching_write)
        library.download_french(config, "bp_me")
        assert seen == [False]


class TestDownloadAll:
    def test_fetches_every_configured_file(self, config, calls, monkeypatch):
        monkeypatch.setattr(library, "COURTESY_DELAY_SECONDS", 0.0)
        paths = library.download_all_french(config)
        assert set(paths) == set(FRENCH_FILES)
        assert len(calls) == len(FRENCH_FILES)

    def test_fails_loudly_on_the_first_error(self, config, monkeypatch):
        """
        Collecting errors and continuing would leave a partial reference set
        that a later step reads as complete. One host, eleven small files: a
        failure means something structural changed.
        """
        monkeypatch.setattr(library, "COURTESY_DELAY_SECONDS", 0.0)
        monkeypatch.setattr(
            library.requests,
            "get",
            lambda *a, **k: FakeResponse(b"", status_code=500),
        )
        with pytest.raises(requests.HTTPError):
            library.download_all_french(config)


class TestUrls:
    def test_every_configured_file_has_a_well_formed_url(self, config):
        for key in FRENCH_FILES:
            url = config.french_url(key)
            assert url.startswith("https://")
            assert url.endswith(".zip")

    def test_unknown_key_raises_with_the_valid_options(self, config):
        with pytest.raises(KeyError, match="unknown French file"):
            config.french_url("not_a_file")

    def test_urls_are_unique(self, config):
        """A duplicated filename would silently overwrite one series with another."""
        urls = [config.french_url(k) for k in FRENCH_FILES]
        assert len(set(urls)) == len(urls)


class TestVintages:
    def test_current_vintage_keeps_the_original_layout(self, config):
        assert config.french_path("factors_3") == config.french_raw / FRENCH_FILES["factors_3"]
        assert "/ftp/" in config.french_url("factors_3")

    def test_fiz_archive_lives_in_its_own_directory(self, config):
        """Two vintages of one filename must never overwrite each other."""
        current = config.french_path("factors_3")
        archive = config.french_path("factors_3", "fiz202412")
        assert current != archive
        assert archive.name == current.name
        assert "/ftp_202412/" in config.french_url("factors_3", "fiz202412")

    def test_unknown_vintage_raises(self, config):
        with pytest.raises(KeyError, match="vintage"):
            config.french_path("factors_3", "ftp_1999")
