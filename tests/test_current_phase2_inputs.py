"""Fixed-window input tests use explicitly synthetic temporary bars only."""

import importlib.util
import json
import sys
import types
from pathlib import Path

import exchange_calendars as xc
import numpy as np
import pandas as pd
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/prepare_current_phase2_inputs.py"
spec = importlib.util.spec_from_file_location("current_inputs", SCRIPT)
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


@pytest.fixture
def sources(tmp_path):
    root = tmp_path / "original"
    root.mkdir()
    dates = pd.to_datetime(
        xc.get_calendar("XNYS", start="2014-01-01", end="2027-12-31").sessions_in_range(
            builder.HISTORY_START, builder.REQUEST_END
        ),
        utc=True,
    )
    for symbol in builder.PRICE_SYMBOLS:
        close = 20 + np.arange(len(dates)) / 100
        frame = pd.DataFrame(
            {
                "symbol": symbol,
                "timestamp": dates,
                "open": close,
                "high": close + 1,
                "low": close - 1,
                "close": close,
                "volume": 100.0,
                "provider": "futu",
                "interval": "1d",
                "event_ts": dates,
                "knowledge_ts": pd.Timestamp("2026-09-20T08:00:00Z"),
                "price_adjustment": "qfq",
            }
        )
        path = root / (symbol + ".parquet")
        frame.to_parquet(path, index=False)
        path.with_suffix(".metadata.json").write_text(
            json.dumps(
                {
                    "symbol": symbol,
                    "source": "futu",
                    "adjustment": "futu_qfq",
                    "status": "available",
                    "rows": len(frame),
                    "sha256": builder.sha(path),
                }
            )
        )
    return root


def test_freeze_binds_all_sources_and_full_requested_calendar_without_editing_them(
    sources, tmp_path
):
    before = {p.name: builder.sha(p) for p in sources.iterdir()}
    output = tmp_path / "frozen"
    result = builder.freeze_current_inputs(sources, output)
    assert result["status"] == "ready"
    manifest = json.loads((output / "input-manifest.json").read_text())
    assert manifest["price_rows"] == 73625
    assert manifest["sessions_per_symbol"] == 2945
    assert manifest["effective_start"] == "2018-01-02"
    assert manifest["effective_end"] == "2026-09-18"
    assert manifest["requested_end"] == "2026-09-19"
    assert manifest["provider_requests"] == 0
    assert manifest["historical_pit_verified"] is False
    assert {p.name: builder.sha(p) for p in sources.iterdir()} == before


@pytest.mark.parametrize("defect", ["missing", "duplicate", "wrong_provider", "metadata_failed"])
def test_defects_are_recorded_without_creating_a_ready_partial_panel(sources, tmp_path, defect):
    path = sources / "AAPL.parquet"
    frame = pd.read_parquet(path)
    if defect == "missing":
        frame = frame.iloc[1:]
    elif defect == "duplicate":
        frame = pd.concat([frame, frame.iloc[-1:]], ignore_index=True)
    elif defect == "wrong_provider":
        frame["provider"] = "sample"
    frame.to_parquet(path, index=False)
    metadata_path = path.with_suffix(".metadata.json")
    meta = json.loads(metadata_path.read_text())
    meta.update(sha256=builder.sha(path), rows=len(frame))
    if defect == "metadata_failed":
        meta["status"] = "failed"
    metadata_path.write_text(json.dumps(meta))
    output = tmp_path / "failed"
    result = builder.freeze_current_inputs(sources, output)
    assert result["status"] == "failed"
    assert result["issues"][0]["symbol"] == "AAPL"
    assert not (output / "prices.parquet").exists()
    assert not (output / "input-manifest.json").exists()
    assert len(json.loads((output / "source-audit.json").read_text())["sources"]) == 25


def test_reader_rejects_changed_source_and_extra_payload_files(sources, tmp_path):
    output = tmp_path / "frozen"
    result = builder.freeze_current_inputs(sources, output)
    manifest = output / "input-manifest.json"
    frame, document = builder.read_frozen_inputs(manifest, result["manifest_sha256"])
    assert len(frame) == document["price_rows"] == 73625
    extra = output / "undeclared.json"
    extra.write_text("{}")
    with pytest.raises(ValueError, match="payload_closure"):
        builder.read_frozen_inputs(manifest, result["manifest_sha256"])
    extra.unlink()
    path = sources / "SPY.parquet"
    path.write_bytes(path.read_bytes() + b"changed")
    with pytest.raises(ValueError, match="source_changed"):
        builder.read_frozen_inputs(manifest, result["manifest_sha256"])


def _inject_provider_module(monkeypatch):
    module = types.ModuleType("quant_system.data.providers.offline_probe")
    monkeypatch.setitem(sys.modules, module.__name__, module)


def test_manifest_provider_requests_is_the_scanned_result_not_a_literal(sources, tmp_path):
    output = tmp_path / "frozen"
    builder.freeze_current_inputs(sources, output)
    manifest = json.loads((output / "input-manifest.json").read_text())
    audit = json.loads((output / "source-audit.json").read_text())
    assert manifest["provider_requests"] == 0
    assert manifest["provider_request_evidence"] == audit["provider_request_evidence"]
    evidence = manifest["provider_request_evidence"]
    assert evidence["provider_requests"] == 0
    assert evidence["provider_modules_loaded_since_import"] == []
    assert evidence["scanned_prefixes"] == list(builder.PROVIDER_MODULE_PREFIXES)
    # The builder's own import graph already loads the provider package; only modules
    # loaded beyond that floor are evidence of a new request path.
    assert "quant_system.data.providers" in evidence["import_time_provider_modules"]


def test_loaded_provider_module_blocks_the_offline_claim(sources, tmp_path, monkeypatch):
    output = tmp_path / "frozen"
    result = builder.freeze_current_inputs(sources, output)
    manifest = output / "input-manifest.json"

    _inject_provider_module(monkeypatch)

    with pytest.raises(ValueError, match="provider_module_loaded:frozen_input_read"):
        builder.read_frozen_inputs(manifest, result["manifest_sha256"])


def test_freeze_refuses_a_provider_module_loaded_during_the_source_audit(
    sources, tmp_path, monkeypatch
):
    _inject_provider_module(monkeypatch)
    with pytest.raises(ValueError, match="provider_module_loaded:source_audit"):
        builder.freeze_current_inputs(sources, tmp_path / "frozen")
    assert not (tmp_path / "frozen").exists()
