"""No real requests or panel writes: classify upstream failures conservatively."""

from __future__ import annotations

import importlib.util
import io
from pathlib import Path
from urllib.error import HTTPError

import pytest

SPEC = importlib.util.spec_from_file_location(
    "probe_tiingo_backfill",
    Path(__file__).resolve().parents[1] / "scripts/probe_tiingo_backfill.py",
)
probe = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(probe)


@pytest.mark.parametrize(
    "status,exception",
    [
        (400, "Stop"),
        (401, "Stop"),
        (403, "Stop"),
        (404, "SymbolError"),
        (408, "TransientError"),
        (429, "Stop"),
        (500, "TransientError"),
    ],
)
def test_http_errors_do_not_retire_symbols_without_not_found(monkeypatch, status, exception):
    def fail(*args, **kwargs):
        raise HTTPError("https://example.test", status, "failure", {}, io.BytesIO(b"failure"))

    monkeypatch.setattr(probe.urllib.request, "urlopen", fail)
    with pytest.raises(getattr(probe, exception)):
        probe.fetch("https://example.test", "sealed-test-only")


@pytest.mark.parametrize(
    "body,exception",
    [
        (b"Error: temporary database unavailable", "Stop"),
        (b"Error: invalid date parameter", "Stop"),
        (b"Error: You have run over your hourly request allocation", "Stop"),
        (b"Error: Ticker 'XYZ' not found", "SymbolError"),
    ],
)
def test_200_unknown_errors_never_mean_symbol_absent(monkeypatch, body, exception):
    monkeypatch.setattr(probe, "fetch", lambda *args: (200, body))
    with pytest.raises(getattr(probe, exception)):
        probe.Fetcher("sealed-test-only", 0, 1).get("https://example.test", "sealed")


def test_transient_timeout_does_not_create_a_tombstone(monkeypatch, tmp_path):
    monkeypatch.setenv("QS_TIINGO_API_TOKEN", "sealed-test-only")

    def timeout(*args, **kwargs):
        raise probe.TransientError("HTTP 408")

    monkeypatch.setattr(probe, "fetch", timeout)
    assert probe.main(["--symbols", "XYZ", "--no-meta", "--out", str(tmp_path)]) == 0
    assert not (tmp_path / "XYZ.absent").exists()
    assert not (tmp_path / "XYZ.parquet").exists()


def test_unknown_short_body_is_not_an_empty_price_result(monkeypatch):
    monkeypatch.setattr(probe, "fetch", lambda *args: (200, b"maintenance"))
    with pytest.raises(ValueError, match="unexpected_short_body"):
        probe.Fetcher("sealed-test-only", 0, 1).prices("XYZ")


def test_repeated_empty_results_do_not_permanently_retire_symbol(monkeypatch, tmp_path):
    monkeypatch.setenv("QS_TIINGO_API_TOKEN", "sealed-test-only")
    monkeypatch.setattr(probe, "fetch", lambda *args: (200, b"\r\n"))
    for i in range(2):
        assert (
            probe.main(
                ["--symbols", "XYZ", "--no-meta", "--out", str(tmp_path), "--tag", f"empty-{i}"]
            )
            == 0
        )
    assert not (tmp_path / "XYZ.absent").exists()
