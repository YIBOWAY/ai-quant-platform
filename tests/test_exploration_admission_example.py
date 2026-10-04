"""Frozen-input adapter tests; never call a provider, Docker or formal state."""

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/exploration_admission_example.py"
spec = importlib.util.spec_from_file_location("exploration_admission_example", SCRIPT)
example = importlib.util.module_from_spec(spec)
spec.loader.exec_module(example)


def frozen_files(tmp_path):
    paths = []
    for symbol in example.SYMBOLS:
        path = tmp_path / f"{symbol}.parquet"
        pd.DataFrame(
            {
                "symbol": [symbol] * 3,
                "timestamp": pd.date_range("2020-01-02", periods=3, tz="UTC"),
                "open": [10.0, 11.0, 12.0],
                "high": [11.0, 12.0, 13.0],
                "low": [9.0, 10.0, 11.0],
                "close": [10.0, 11.0, 12.0],
                "volume": [100.0] * 3,
                "provider": ["futu"] * 3,
                "interval": ["1d"] * 3,
                "price_adjustment": ["qfq"] * 3,
            }
        ).to_parquet(path, index=False)
        meta = path.with_suffix(".metadata.json")
        meta.write_text(
            json.dumps(
                {
                    "symbol": symbol,
                    "source": "futu",
                    "adjustment": "futu_qfq",
                    "sha256": example.sha(path),
                }
            )
        )
        paths.append(
            {
                "symbol": symbol,
                "path": str(path),
                "sha256": example.sha(path),
                "metadata_sha256": example.sha(meta),
            }
        )
    return paths


def test_frozen_price_adapter_preserves_source_and_binds_each_file(tmp_path):
    files = frozen_files(tmp_path)
    before = {p["path"]: example.sha(Path(p["path"])) for p in files}
    frame = example.load_frozen_prices(files)
    assert len(frame) == 12
    assert set(frame.provider) == {"futu"}
    assert set(frame.price_adjustment) == {"qfq"}
    assert {p["path"]: example.sha(Path(p["path"])) for p in files} == before


@pytest.mark.parametrize("corruption", ["bytes", "provider", "adjustment", "duplicate", "missing"])
def test_corrupt_or_incompatible_frozen_prices_fail_closed(tmp_path, corruption):
    files = frozen_files(tmp_path)
    path = Path(files[0]["path"])
    if corruption == "bytes":
        path.write_bytes(path.read_bytes() + b"changed")
    else:
        frame = pd.read_parquet(path)
        if corruption == "provider":
            frame["provider"] = "sample"
        elif corruption == "adjustment":
            frame["price_adjustment"] = "raw"
        elif corruption == "duplicate":
            frame = pd.concat([frame, frame.iloc[[-1]]], ignore_index=True)
        else:
            frame = frame.iloc[:-1]
        frame.to_parquet(path, index=False)
        files[0]["sha256"] = example.sha(path)
        metadata = path.with_suffix(".metadata.json")
        raw = json.loads(metadata.read_text())
        raw["sha256"] = files[0]["sha256"]
        metadata.write_text(json.dumps(raw))
        files[0]["metadata_sha256"] = example.sha(metadata)
    with pytest.raises(ValueError, match="example_frozen_price_"):
        example.load_frozen_prices(files)


def test_isolated_settings_refuses_a_formal_data_target(tmp_path):
    with pytest.raises(ValueError, match="example_output_not_isolated"):
        example.isolated_settings(Path("/Users/sunyibo/programs/ai-quant-platform/data"))
    settings = example.isolated_settings(tmp_path / "example")
    assert settings.data.data_dir == tmp_path / "example" / "data"
    assert settings.database.enabled is False
    assert settings.database.url is None
    assert settings.paper_account.db_mode == "file"
    assert settings.safety.live_trading_enabled is False


def test_modified_candidate_is_rejected_before_intake_or_output_creation(tmp_path):
    path = tmp_path / "frozen-candidate.json"
    path.write_text(
        json.dumps({"candidate_digest": "0" * 64, "proposal": {"expression": "$close"}})
    )
    with pytest.raises(ValueError, match="example_candidate_digest_mismatch"):
        example.verify_candidate(path)
    assert list(tmp_path.iterdir()) == [path]


def test_intake_snapshot_is_real_bound_and_cannot_enable_capital(tmp_path):
    from quant_system.research import external_intake as intake
    from quant_system.research.intake_evaluation import validate_snapshot

    settings = example.isolated_settings(tmp_path / "isolated")
    proposal = {
        "schema_version": 1,
        "proposal_id": "sealed-adapter-test",
        "source_urls": ["https://example.org/sealed-test"],
        "source_title": "Sealed test",
        "published_at": None,
        "retrieved_at": "2026-09-20T10:00:00Z",
        "hypothesis": "Sealed adapter test, not an economic claim",
        "expression": "(($close/Ref($close,5))-1)",
        "adaptation_note": "Sealed test only",
        "baseline_factor_ids": [],
        "strategy_spec": {"symbols": example.SYMBOLS, "top_n": 2, "rebalance": "daily"},
    }
    frame = example.load_frozen_prices(frozen_files(tmp_path))
    job, evaluation = example.prepare_intake(settings, proposal, frame, {"source": "sealed_test"})
    assert intake.read_policy(settings).enabled is True
    assert intake.read_policy(settings).auto_enable is False
    assert intake.show(settings, job["job_id"])["status"] == "queued"
    assert len(pd.read_parquet(validate_snapshot(settings, evaluation))) == 12
    assert evaluation["start"] == example.START and evaluation["end"] == example.END
    assert evaluation["frozen_input_provenance"]["source"] == "sealed_test"
    assert not (settings.data.data_dir / "trials").exists()
