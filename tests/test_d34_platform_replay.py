from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pandas as pd
import pytest

from quant_system.d34.platform_replay import PlatformReplayError, run_platform_replay


def test_platform_replays_target_weights_without_factor_formula(tmp_path: Path) -> None:
    bars = []
    for day, spy, qqq in ((1, 100.0, 200.0), (2, 102.0, 198.0), (3, 103.0, 201.0)):
        timestamp = pd.Timestamp(f"2026-01-0{day}", tz="UTC")
        for symbol, close in (("SPY", spy), ("QQQ", qqq)):
            bars.append(
                {
                    "symbol": symbol,
                    "timestamp": timestamp,
                    "open": close - 0.5,
                    "high": close + 1,
                    "low": close - 1,
                    "close": close,
                    "volume": 1_000_000,
                }
            )
    snapshot = tmp_path / "ohlcv.parquet"
    pd.DataFrame(bars).to_parquet(snapshot, index=False)
    weights = tmp_path / "target_weights.parquet"
    pd.DataFrame(
        [
            {
                "tradeable_ts": pd.Timestamp("2026-01-01", tz="UTC"),
                "symbol": "SPY",
                "target_weight": 0.5,
            },
            {
                "tradeable_ts": pd.Timestamp("2026-01-01", tz="UTC"),
                "symbol": "QQQ",
                "target_weight": 0.5,
            },
        ]
    ).to_parquet(weights, index=False)

    result = run_platform_replay(
        snapshot_id="snapshot-0123456789abcdef0123456789abcdef",
        snapshot_digest="a" * 64,
        snapshot_parquet=snapshot,
        target_weights_parquet=weights,
        output_root=tmp_path / "replays",
        initial_cash=100_000,
        commission_bps=1,
        slippage_bps=5,
    )

    assert result.contract == "hqa.d34_engine_receipt/v1"
    assert result.engine_receipt.engine == "platform"
    assert result.snapshot_digest == "a" * 64
    assert result.target_weights_digest == result.engine_receipt.target_weights_digest
    assert result.output_dir.is_dir()
    assert (result.output_dir / "equity_curve.parquet").is_file()
    assert (result.output_dir / "trade_blotter.parquet").is_file()
    assert (result.output_dir / "positions.parquet").is_file()
    assert (result.output_dir / "receipt.json").is_file()
    assert len(result.engine_receipt.daily_returns) == 3
    assert result.engine_receipt.terminal_nav > 0
    assert set(result.engine_receipt.terminal_weights) == {"SPY", "QQQ"}
    expected_universe = hashlib.sha256(
        json.dumps(
            ["SPY", "QQQ"],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
    assert result.engine_receipt.universe_digest == expected_universe
    assert len(result.receipt_digest) == 64

    receipt_path = result.output_dir / "receipt.json"
    tampered = json.loads(receipt_path.read_text(encoding="utf-8"))
    tampered["terminal_nav"] = 999
    receipt_path.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(PlatformReplayError, match="existing replay receipt is unreadable"):
        run_platform_replay(
            snapshot_id="snapshot-0123456789abcdef0123456789abcdef",
            snapshot_digest="a" * 64,
            snapshot_parquet=snapshot,
            target_weights_parquet=weights,
            output_root=tmp_path / "replays",
            initial_cash=100_000,
            commission_bps=1,
            slippage_bps=5,
        )


def test_platform_replay_rejects_invalid_execution_assumptions(tmp_path: Path) -> None:
    snapshot = tmp_path / "ohlcv.parquet"
    weights = tmp_path / "target_weights.parquet"
    snapshot.write_bytes(b"not-used")
    weights.write_bytes(b"not-used")

    with pytest.raises(PlatformReplayError) as invalid:
        run_platform_replay(
            snapshot_id="snapshot-0123456789abcdef0123456789abcdef",
            snapshot_digest="a" * 64,
            snapshot_parquet=snapshot,
            target_weights_parquet=weights,
            output_root=tmp_path / "replays",
            initial_cash=0,
            commission_bps=-1,
        )
    assert invalid.value.code == "platform_replay_validation"
