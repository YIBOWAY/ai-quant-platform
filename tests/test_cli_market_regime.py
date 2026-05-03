from __future__ import annotations

from pathlib import Path

import pandas as pd

from quant_system.cli import _load_market_regime
from quant_system.config.settings import OptionsRadarSettings, Settings
from quant_system.options.vix_data import save_vix_history


def test_load_market_regime_returns_none_when_csv_missing(tmp_path: Path) -> None:
    settings = Settings(
        options_radar=OptionsRadarSettings(vix_history_path=tmp_path / "absent.csv"),
    )
    assert _load_market_regime(settings, run_date=None) is None


def test_load_market_regime_uses_csv(tmp_path: Path) -> None:
    target = tmp_path / "vix.csv"
    idx = pd.date_range("2024-06-01", periods=260, freq="B")
    save_vix_history(
        target,
        pd.Series([14.0] * len(idx), index=idx),
        pd.Series([16.0] * len(idx), index=idx),
    )
    settings = Settings(
        options_radar=OptionsRadarSettings(vix_history_path=target),
    )
    snapshot = _load_market_regime(settings, run_date=None)
    assert snapshot is not None
    assert snapshot.volatility_regime in {"Normal", "Elevated", "Panic"}


def test_load_market_regime_handles_invalid_run_date(tmp_path: Path) -> None:
    target = tmp_path / "vix.csv"
    idx = pd.date_range("2024-06-01", periods=260, freq="B")
    save_vix_history(target, pd.Series([15.0] * len(idx), index=idx), None)
    settings = Settings(
        options_radar=OptionsRadarSettings(vix_history_path=target),
    )
    snapshot = _load_market_regime(settings, run_date="not-a-date")
    assert snapshot is not None
