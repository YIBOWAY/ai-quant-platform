import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from quant_system.research.public_pilot_evidence import (
    inspect_public_pilot,
    recompute_monthly_statistics,
    trusted_source_identity,
)


def test_local_statistics_form_groups_without_consulting_future_labels():
    records, labels = [], []
    for method in ("Mom12m", "STreversal", "generic_monthly_realized_volatility"):
        for number in range(10):
            records.append(
                {
                    "month": "2020-01",
                    "signal_date": "2020-01-31",
                    "entity_id": str(number),
                    "symbol": str(number),
                    "factor": method,
                    "value": float(number),
                    "quintile": number // 2 + 1,
                }
            )
    for number in range(10):
        labels.append(
            {
                "month": "2020-01",
                "signal_date": "2020-01-31",
                "entity_id": str(number),
                "symbol": str(number),
                "entry_date": "2020-02-03",
                "exit_date": "2020-03-02",
                "forward_return": number / 100,
            }
        )
    signals, future = pd.DataFrame(records), pd.DataFrame(labels)
    monthly, summary = recompute_monthly_statistics(signals, future)
    assert np.allclose(monthly.rank_ic, 1.0)
    assert np.allclose(monthly.q5_q1, 0.08)
    future.loc[future.symbol == "9", "forward_return"] = np.nan
    broken, _ = recompute_monthly_statistics(signals, future)
    assert broken.q5_q1.isna().all()
    assert set(broken.Q5_formation_count) == {2}
    assert set(broken.Q5_label_count) == {1}
    assert len(summary) == 3
    with pytest.raises(ValueError, match="signal_label_separation"):
        recompute_monthly_statistics(signals.assign(forward_return=1.0), future)


def _bundle(tmp_path):
    identity, config = trusted_source_identity()
    contents = {
        name: b"fixture"
        for name in (
            "signals.parquet",
            "signals.csv",
            "future-labels.parquet",
            "future-labels.csv",
            "monthly-statistics.csv",
            "monthly-coverage.csv",
            "input-audit.json",
            "summary.json",
            "research-index.jsonl",
        )
    }
    contents["input-manifest-snapshot.json"] = b'{"schema_version":"qs.wide_inputs/v1"}'
    contents["script-snapshot.py"] = (
        Path(__file__).resolve().parents[1] / identity["script_path"]
    ).read_bytes()
    contents["frozen-config.json"] = json.dumps(
        {
            **config,
            **{
                k: identity[k]
                for k in ("script_sha256", "loader_sha256", "statistics_sha256", "pandas_version")
            },
            "input_manifest_sha256": hashlib.sha256(
                contents["input-manifest-snapshot.json"]
            ).hexdigest(),
        }
    ).encode()
    for name, value in contents.items():
        (tmp_path / name).write_bytes(value)
    manifest = {name: hashlib.sha256(value).hexdigest() for name, value in contents.items()}
    (tmp_path / "artifact-manifest.json").write_text(json.dumps(manifest))
    return hashlib.sha256((tmp_path / "artifact-manifest.json").read_bytes()).hexdigest()


def test_package_script_is_only_compared_to_trusted_local_source_never_executed(tmp_path):
    digest = _bundle(tmp_path)
    result = inspect_public_pilot(tmp_path, expected_manifest_sha256=digest)
    assert result["source_code_executed"] is False
    assert result["input_manifest_sha256"]
    (tmp_path / "rogue.py").write_text("raise RuntimeError('must not execute')")
    with pytest.raises(ValueError, match="pilot_file_closure"):
        inspect_public_pilot(tmp_path, expected_manifest_sha256=digest)


def test_self_signed_script_replacement_does_not_become_trusted(tmp_path):
    _bundle(tmp_path)
    (tmp_path / "script-snapshot.py").write_text("raise RuntimeError('untrusted')")
    manifest = json.loads((tmp_path / "artifact-manifest.json").read_text())
    manifest["script-snapshot.py"] = hashlib.sha256(
        (tmp_path / "script-snapshot.py").read_bytes()
    ).hexdigest()
    config = json.loads((tmp_path / "frozen-config.json").read_text())
    config["script_sha256"] = manifest["script-snapshot.py"]
    (tmp_path / "frozen-config.json").write_text(json.dumps(config))
    manifest["frozen-config.json"] = hashlib.sha256(
        (tmp_path / "frozen-config.json").read_bytes()
    ).hexdigest()
    (tmp_path / "artifact-manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="trusted_source_version_mismatch"):
        inspect_public_pilot(
            tmp_path,
            expected_manifest_sha256=hashlib.sha256(
                (tmp_path / "artifact-manifest.json").read_bytes()
            ).hexdigest(),
        )
