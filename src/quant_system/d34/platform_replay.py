"""Independent Platform execution replay over Qlib-produced target weights."""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from quant_system.backtest.engine import BacktestEngine
from quant_system.backtest.models import BacktestConfig, TargetWeight
from quant_system.d34.engine_comparison import EngineReceipt

ENGINE_RECEIPT_CONTRACT = "hqa.d34_engine_receipt/v1"


class PlatformReplayError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PlatformReplayReceipt:
    contract: str
    snapshot_id: str
    snapshot_digest: str
    target_weights_digest: str
    receipt_digest: str
    output_dir: Path
    engine_receipt: EngineReceipt


class _TargetWeightStrategy:
    def __init__(self, weights: pd.DataFrame) -> None:
        self._weights = weights

    def target_weights(self, timestamp: pd.Timestamp) -> list[TargetWeight] | None:
        ts = pd.Timestamp(timestamp)
        ts = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
        rows = self._weights[self._weights["tradeable_ts"] == ts]
        if rows.empty:
            return None
        return [
            TargetWeight(
                timestamp=ts,
                symbol=str(row.symbol),
                target_weight=float(row.target_weight),
                reason="qlib_target_weight",
            )
            for row in rows.itertuples(index=False)
        ]


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_weights(frame: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    required = {"tradeable_ts", "symbol", "target_weight"}
    if frame.empty or not required.issubset(frame.columns):
        raise PlatformReplayError(
            "platform_replay_weights_invalid", "target weights are empty or malformed"
        )
    weights = frame.loc[:, ["tradeable_ts", "symbol", "target_weight"]].copy()
    weights["tradeable_ts"] = pd.to_datetime(weights["tradeable_ts"], utc=True)
    weights["symbol"] = weights["symbol"].astype(str).str.upper().str.strip()
    weights["target_weight"] = pd.to_numeric(weights["target_weight"], errors="coerce")
    if (
        weights.isna().any().any()
        or weights.duplicated(subset=["tradeable_ts", "symbol"]).any()
        or (weights["target_weight"] < 0).any()
        or (weights["target_weight"] > 1).any()
        or not set(weights["symbol"]).issubset(set(bars["symbol"]))
        or not set(weights["tradeable_ts"]).issubset(set(bars["timestamp"]))
        or (weights.groupby("tradeable_ts")["target_weight"].sum() > 1.000000001).any()
    ):
        raise PlatformReplayError(
            "platform_replay_weights_invalid", "target weights violate replay constraints"
        )
    return weights.sort_values(["tradeable_ts", "symbol"], ignore_index=True)


def _engine_receipt(raw: dict[str, object]) -> EngineReceipt:
    return EngineReceipt(
        engine="platform",
        snapshot_digest=str(raw["snapshot_digest"]),
        universe_digest=str(raw["universe_digest"]),
        calendar_digest=str(raw["calendar_digest"]),
        target_weights_digest=str(raw["target_weights_digest"]),
        daily_returns=tuple(float(item) for item in raw["daily_returns"]),  # type: ignore[union-attr]
        terminal_nav=float(raw["terminal_nav"]),  # type: ignore[arg-type]
        terminal_weights={
            str(key): float(value)
            for key, value in dict(raw["terminal_weights"]).items()  # type: ignore[arg-type]
        },
        receipt_digest=str(raw["receipt_digest"]),
        return_dates=tuple(str(item) for item in raw["return_dates"]),  # type: ignore[union-attr]
    )


def _from_manifest(output_dir: Path, raw: dict[str, object]) -> PlatformReplayReceipt:
    return PlatformReplayReceipt(
        contract=str(raw["contract"]),
        snapshot_id=str(raw["snapshot_id"]),
        snapshot_digest=str(raw["snapshot_digest"]),
        target_weights_digest=str(raw["target_weights_digest"]),
        receipt_digest=str(raw["receipt_digest"]),
        output_dir=output_dir,
        engine_receipt=_engine_receipt(raw),
    )


def run_platform_replay(
    *,
    snapshot_id: str,
    snapshot_digest: str,
    snapshot_parquet: str | Path,
    target_weights_parquet: str | Path,
    output_root: str | Path,
    initial_cash: float = 100_000,
    commission_bps: float = 1,
    slippage_bps: float = 5,
    min_order_value: float = 0,
    whole_share_orders: bool = False,
) -> PlatformReplayReceipt:
    """Replay only weights/execution assumptions; factor code is never imported."""
    if not snapshot_id.startswith("snapshot-") or len(snapshot_digest) != 64:
        raise PlatformReplayError("platform_replay_validation", "snapshot identity is invalid")
    snapshot_path, weights_path = Path(snapshot_parquet), Path(target_weights_parquet)
    if not snapshot_path.is_file() or not weights_path.is_file():
        raise PlatformReplayError("platform_replay_unavailable", "replay input is unavailable")
    bars = pd.read_parquet(snapshot_path)
    required_bars = {"symbol", "timestamp", "open", "close"}
    if bars.empty or not required_bars.issubset(bars.columns):
        raise PlatformReplayError("platform_replay_snapshot_invalid", "snapshot bars are malformed")
    bars = bars.copy()
    bars["symbol"] = bars["symbol"].astype(str).str.upper().str.strip()
    bars["timestamp"] = pd.to_datetime(bars["timestamp"], utc=True)
    weights = _validate_weights(pd.read_parquet(weights_path), bars)
    target_digest = _file_digest(weights_path)
    universe = sorted(set(bars["symbol"]))
    dates = sorted(pd.Timestamp(value).isoformat() for value in set(bars["timestamp"]))
    universe_digest = _digest(universe)
    calendar_digest = _digest(dates)
    config_document = {
        "initial_cash": float(initial_cash),
        "commission_bps": float(commission_bps),
        "slippage_bps": float(slippage_bps),
        "min_order_value": float(min_order_value),
        "whole_share_orders": bool(whole_share_orders),
        "execution_price": "next_open",
    }
    replay_key = _digest(
        {
            "snapshot_digest": snapshot_digest,
            "target_weights_digest": target_digest,
            "config": config_document,
        }
    )
    root = Path(output_root)
    root.mkdir(parents=True, exist_ok=True)
    output_dir = root / f"replay-{replay_key[:32]}"
    if output_dir.exists():
        try:
            existing = json.loads((output_dir / "receipt.json").read_text(encoding="utf-8"))
            receipt = _from_manifest(output_dir, existing)
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise PlatformReplayError(
                "platform_replay_collision", "existing replay receipt is unreadable"
            ) from exc
        if (
            receipt.snapshot_digest != snapshot_digest
            or receipt.target_weights_digest != target_digest
        ):
            raise PlatformReplayError(
                "platform_replay_collision", "existing replay receipt mismatches its inputs"
            )
        return receipt

    temp = Path(tempfile.mkdtemp(prefix=".replay-", dir=root))
    try:
        config = BacktestConfig(
            initial_cash=initial_cash,
            commission_bps=commission_bps,
            slippage_bps=slippage_bps,
            min_order_value=min_order_value,
            whole_share_orders=whole_share_orders,
        )
        result = BacktestEngine(config).run(bars, _TargetWeightStrategy(weights))  # type: ignore[arg-type]
        outputs = {
            "equity_curve.parquet": result.equity_curve,
            "trade_blotter.parquet": result.trade_blotter,
            "orders.parquet": result.orders,
            "positions.parquet": result.positions,
            "attribution.parquet": result.attribution,
        }
        output_digests: dict[str, str] = {}
        for filename, frame in outputs.items():
            path = temp / filename
            frame.to_parquet(path, index=False)
            output_digests[filename] = _file_digest(path)
        equity = result.equity_curve
        if equity.empty:
            raise PlatformReplayError("platform_replay_empty", "Platform replay produced no NAV")
        daily_returns = equity["equity"].pct_change().fillna(0.0).astype(float).tolist()
        terminal_equity = float(equity.iloc[-1]["equity"])
        terminal_timestamp = equity.iloc[-1]["timestamp"]
        terminal_positions = result.positions[result.positions["timestamp"] == terminal_timestamp]
        terminal_weights = {
            str(row.symbol): float(row.market_value) / terminal_equity
            for row in terminal_positions.itertuples(index=False)
        }
        receipt_body = {
            "contract": ENGINE_RECEIPT_CONTRACT,
            "engine": "platform",
            "snapshot_id": snapshot_id,
            "snapshot_digest": snapshot_digest,
            "snapshot_parquet_digest": _file_digest(snapshot_path),
            "universe_digest": universe_digest,
            "calendar_digest": calendar_digest,
            "target_weights_digest": target_digest,
            "config": config_document,
            "daily_returns": daily_returns,
            "return_dates": [pd.Timestamp(value).isoformat() for value in equity["timestamp"]],
            "terminal_nav": terminal_equity / float(initial_cash),
            "terminal_weights": terminal_weights,
            "metrics": result.metrics.model_dump(mode="json"),
            "output_digests": output_digests,
        }
        receipt_digest = _digest(receipt_body)
        manifest = {**receipt_body, "receipt_digest": receipt_digest}
        (temp / "receipt.json").write_bytes(_canonical_json(manifest) + b"\n")
        temp.rename(output_dir)
        return _from_manifest(output_dir, manifest)
    finally:
        if temp.exists():
            shutil.rmtree(temp)


__all__ = [
    "ENGINE_RECEIPT_CONTRACT",
    "PlatformReplayError",
    "PlatformReplayReceipt",
    "run_platform_replay",
]
