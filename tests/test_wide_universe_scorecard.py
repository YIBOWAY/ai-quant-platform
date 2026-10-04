import hashlib
import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest

from quant_system.research.wide_factor_set import frozen_factor_manifest

spec = importlib.util.spec_from_file_location(
    "wide_runner", Path(__file__).parents[1] / "scripts/wide_universe_scorecard.py"
)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


def test_diagnostic_outputs_all_27_objects_including_unavailable_without_promoting(tmp_path):
    days = pd.date_range("2015-12-01", "2016-02-29", freq="B", tz="UTC")
    prices = {}
    for number, symbol in enumerate(["A", "B", "C", "D", "E", "SPY"]):
        close = pd.Series(range(100, 100 + len(days)), dtype=float) * (1 + number / 7)
        price = pd.DataFrame(
            {
                "date": days,
                "adjOpen": close,
                "adjHigh": close + 1,
                "adjLow": close - 1,
                "adjClose": close,
                "adjVolume": 1000.0,
            }
        )
        file = tmp_path / f"{symbol}.parquet"
        price.to_parquet(file)
        prices[symbol] = {
            "path": file.name,
            "sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        }
    membership = pd.DataFrame(
        [
            {"month_end": month, "entity_id": symbol, "ticker_as_of": symbol}
            for month in ["2015-12-31", "2016-01-31"]
            for symbol in ["A", "B", "C", "D", "E"]
        ]
    )
    membership.to_csv(tmp_path / "members.csv", index=False)
    pd.DataFrame({"date": days}).to_csv(tmp_path / "calendar.csv", index=False)

    def file_spec(name):
        return {"path": name, "sha256": hashlib.sha256((tmp_path / name).read_bytes()).hexdigest()}

    manifest = {
        "schema_version": "qs.wide_inputs/v1",
        "provider": "tiingo",
        "adjustment": "tiingo_adjusted_ohlcv",
        "usage_restrictions": ["synthetic fixture"],
        "signal_window": ["2016-01-01", "2016-01-29"],
        "prices": prices,
        "membership": file_spec("members.csv"),
        "calendar": file_spec("calendar.csv"),
    }
    manifest_path = tmp_path / "input.json"
    manifest_path.write_text(json.dumps(manifest))
    freeze_path = tmp_path / "factors.json"
    freeze_path.write_text(json.dumps(frozen_factor_manifest()))
    result = runner.run_scorecard(manifest_path, freeze_path, tmp_path / "run", mode="diagnostic")
    assert len(result["factors"]) == 27
    assert result["data_acceptance"]["authority"] == "diagnostic_only"
    assert not result["data_acceptance"]["admission_authority"]
    assert (tmp_path / "run" / "ic_daily.parquet").is_file()
    assert (tmp_path / "run" / "factor-coverage.json").is_file()
    assert "provenance" in result
    with pytest.raises(FileExistsError):
        runner.run_scorecard(manifest_path, freeze_path, tmp_path / "run", mode="diagnostic")
    for descriptor in manifest["prices"].values():
        file = tmp_path / descriptor["path"]
        frame = pd.read_parquet(file)
        frame[frame.date != pd.Timestamp("2016-01-15", tz="UTC")].to_parquet(file)
        descriptor["sha256"] = hashlib.sha256(file.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="scorecard_global_session_gap"):
        runner.run_scorecard(manifest_path, freeze_path, tmp_path / "gap-run", mode="diagnostic")
