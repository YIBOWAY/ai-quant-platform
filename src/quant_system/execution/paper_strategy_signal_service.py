from __future__ import annotations

from datetime import date, timedelta
from math import isfinite
from typing import Any

import pandas as pd

from quant_system.backtest.strategy import MeanReversionTopN, ScoreSignalStrategy
from quant_system.config.settings import Settings
from quant_system.data.provider_factory import build_ohlcv_provider
from quant_system.execution.account import PaperAccount
from quant_system.execution.paper_strategy_sleeves import (
    SignalStatus,
    StrategyConfig,
    StrategySignal,
    StrategySleeve,
    StrategySleeveMode,
    StrategySleeveStatus,
)
from quant_system.factors.pipeline import (
    build_factor_signal_frame,
    compute_factor_pipeline,
)
from quant_system.factors.registry import build_factor_registry


class StrategySignalGenerationError(ValueError):
    """Raised when a sleeve lifecycle state does not allow signal generation."""


class PaperStrategySignalService:
    """Generate and persist daily StrategySignal records without executing orders."""

    _strategy_builders: dict[str, type[ScoreSignalStrategy]] = {
        "cross_sectional_top_n": ScoreSignalStrategy,
        "mean_reversion_top_n": MeanReversionTopN,
    }

    def __init__(self, *, storage, settings: Settings) -> None:
        self.storage = storage
        self.settings = settings

    def generate_daily_signal(
        self,
        *,
        sleeve: StrategySleeve,
        config: StrategyConfig,
        account: PaperAccount,
        signal_date: str | date | None = None,
        history_days: int = 180,
    ) -> StrategySignal:
        if sleeve.status == StrategySleeveStatus.STOPPED:
            raise StrategySignalGenerationError("stopped sleeves cannot generate signals")
        resolved_signal_date = self._resolve_signal_date(signal_date)
        blocked_reason = self._execution_blocked_reason(sleeve, account)
        warnings = self._blocked_warnings(blocked_reason)

        signal = self._build_signal(
            sleeve=sleeve,
            config=config,
            account=account,
            signal_date=resolved_signal_date,
            history_days=history_days,
            execution_blocked_reason=blocked_reason,
            base_warnings=warnings,
        )
        self.storage.append_signal(signal)
        return signal

    def _build_signal(
        self,
        *,
        sleeve: StrategySleeve,
        config: StrategyConfig,
        account: PaperAccount,
        signal_date: date,
        history_days: int,
        execution_blocked_reason: str | None,
        base_warnings: list[str],
    ) -> StrategySignal:
        try:
            provider, source = build_ohlcv_provider(
                self.settings,
                requested=config.data_provider,
            )
        except Exception as exc:  # noqa: BLE001 - external provider boundary
            return self._data_unavailable_signal(
                sleeve=sleeve,
                config=config,
                signal_date=signal_date,
                data_provider=config.data_provider,
                warnings=[
                    *base_warnings,
                    f"strategy history provider is unavailable: {exc}",
                ],
                execution_blocked_reason=execution_blocked_reason,
            )

        if source.lower().startswith("sample"):
            return self._data_unavailable_signal(
                sleeve=sleeve,
                config=config,
                signal_date=signal_date,
                data_provider=source,
                warnings=[
                    *base_warnings,
                    "sample data is not allowed for strategy sleeve signal generation",
                ],
                execution_blocked_reason=execution_blocked_reason,
            )

        start = signal_date - timedelta(days=max(history_days, (config.lookback * 4) + 10, 60))
        try:
            ohlcv = provider.fetch_ohlcv(
                config.symbols,
                start=start.isoformat(),
                end=signal_date.isoformat(),
            )
        except Exception as exc:  # noqa: BLE001 - external provider boundary
            return self._data_unavailable_signal(
                sleeve=sleeve,
                config=config,
                signal_date=signal_date,
                data_provider=source,
                warnings=[*base_warnings, f"strategy history is unavailable: {exc}"],
                execution_blocked_reason=execution_blocked_reason,
            )
        if ohlcv is None or ohlcv.empty:
            return self._data_unavailable_signal(
                sleeve=sleeve,
                config=config,
                signal_date=signal_date,
                data_provider=source,
                warnings=[*base_warnings, "strategy history is empty"],
                execution_blocked_reason=execution_blocked_reason,
            )

        try:
            target_weights, data_as_of = self._compute_target_weights(config, ohlcv)
        except Exception as exc:  # noqa: BLE001 - invalid config/data boundary
            return StrategySignal.create(
                sleeve=sleeve,
                signal_date=signal_date.isoformat(),
                data_provider=source,
                warnings=[*base_warnings, f"strategy signal is invalid: {exc}"],
                status=SignalStatus.INVALID,
                execution_blocked_reason=execution_blocked_reason,
            )

        proposed_orders = []
        if execution_blocked_reason is None:
            proposed_orders = self._build_proposed_orders(
                sleeve=sleeve,
                config=config,
                account=account,
                target_weights=target_weights,
                ohlcv=ohlcv,
                warnings=base_warnings,
            )

        return StrategySignal.create(
            sleeve=sleeve,
            signal_date=signal_date.isoformat(),
            data_provider=source,
            data_as_of=data_as_of,
            target_weights=target_weights,
            proposed_orders=proposed_orders,
            warnings=base_warnings,
            status=SignalStatus.GENERATED,
            execution_blocked_reason=execution_blocked_reason,
            metadata={
                "strategy_id": config.strategy_id,
                "history_days": history_days,
                "execution_timing": config.execution_timing,
            },
        )

    def _compute_target_weights(
        self,
        config: StrategyConfig,
        ohlcv: pd.DataFrame,
    ) -> tuple[dict[str, float], str | None]:
        builder = self._strategy_builders.get(config.strategy_id)
        if builder is None:
            raise ValueError(f"unsupported strategy_id {config.strategy_id!r}")

        # D-20 resident-path purity: the registry factory can only construct the
        # default examples + promoted, code-reviewed set. Candidate execution is
        # confined to the exact-ID/digest one-shot research loader.
        registry = build_factor_registry()
        factor_ids = config.factor_ids or registry.factor_ids()
        factors = [
            registry.create(factor_id, lookback=config.lookback)
            for factor_id in factor_ids
        ]
        weights = {factor_id: config.weights.get(factor_id, 1.0) for factor_id in factor_ids}
        factor_results = compute_factor_pipeline(ohlcv, factors=factors)
        signal_frame = build_factor_signal_frame(factor_results, weights=weights)
        if signal_frame.empty:
            return {}, None

        latest_ts = signal_frame["tradeable_ts"].max()
        targets = builder(signal_frame, top_n=config.top_n).target_weights(latest_ts)
        if not targets:
            return {}, str(latest_ts)
        return (
            {
                target.symbol.upper(): min(
                    float(target.target_weight),
                    float(config.max_weight_per_symbol),
                )
                for target in targets
            },
            str(latest_ts),
        )

    def _build_proposed_orders(
        self,
        *,
        sleeve: StrategySleeve,
        config: StrategyConfig,
        account: PaperAccount,
        target_weights: dict[str, float],
        ohlcv: pd.DataFrame,
        warnings: list[str],
    ) -> list[dict[str, Any]]:
        if sleeve.mode != StrategySleeveMode.ALLOCATED or not target_weights:
            return []

        latest_prices = self._latest_prices(ohlcv)
        lots = self.storage.load_sleeve_lots(sleeve.sleeve_id)
        current_values = {
            lot.symbol.upper(): lot.quantity * latest_prices.get(lot.symbol.upper(), lot.avg_cost)
            for lot in lots
        }
        sleeve_equity = sleeve.cash + sum(current_values.values())
        proposed_orders: list[dict[str, Any]] = []
        for symbol in sorted(set(current_values) | set(target_weights)):
            price = latest_prices.get(symbol)
            if price is None or not isfinite(price) or price <= 0:
                warnings.append(f"missing latest price for {symbol}; proposed order skipped")
                continue
            current_value = current_values.get(symbol, 0.0)
            target_weight = float(target_weights.get(symbol, 0.0))
            target_value = sleeve_equity * target_weight
            delta = target_value - current_value
            if abs(delta) < config.min_order_value:
                continue
            proposed_orders.append(
                {
                    "symbol": symbol,
                    "side": "buy" if delta > 0 else "sell",
                    "target_weight": target_weight,
                    "current_value": current_value,
                    "target_value": target_value,
                    "notional_delta": delta,
                    "reference_price": price,
                    "estimated_quantity": abs(delta) / price,
                    "reason": "advisory_only_no_execution",
                    "account_id": account.account_id,
                }
            )
        return proposed_orders

    @staticmethod
    def _data_unavailable_signal(
        *,
        sleeve: StrategySleeve,
        config: StrategyConfig,
        signal_date: date,
        data_provider: str,
        warnings: list[str],
        execution_blocked_reason: str | None,
    ) -> StrategySignal:
        return StrategySignal.create(
            sleeve=sleeve,
            signal_date=signal_date.isoformat(),
            data_provider=data_provider,
            warnings=warnings,
            status=SignalStatus.DATA_UNAVAILABLE,
            execution_blocked_reason=execution_blocked_reason,
            metadata={"strategy_id": config.strategy_id},
        )

    @staticmethod
    def _resolve_signal_date(value: str | date | None) -> date:
        if value is None:
            return date.today()
        if isinstance(value, date):
            return value
        return date.fromisoformat(value)

    @staticmethod
    def _execution_blocked_reason(
        sleeve: StrategySleeve,
        account: PaperAccount,
    ) -> str | None:
        if sleeve.status == StrategySleeveStatus.PAUSED:
            return "sleeve_paused"
        if account.kill_switch:
            return "account_frozen"
        return None

    @staticmethod
    def _blocked_warnings(blocked_reason: str | None) -> list[str]:
        if blocked_reason == "sleeve_paused":
            return ["sleeve is paused; execution plan is blocked"]
        if blocked_reason == "account_frozen":
            return ["account is frozen; execution plan is blocked"]
        return []

    @staticmethod
    def _latest_prices(ohlcv: pd.DataFrame) -> dict[str, float]:
        frame = ohlcv.copy()
        frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
        frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
        frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
        latest = frame.sort_values(["symbol", "timestamp"])
        prices: dict[str, float] = {}
        for row in latest.groupby("symbol", sort=True).tail(1).itertuples(index=False):
            price = float(row.close)
            if isfinite(price) and price > 0:
                prices[row.symbol] = price
        return prices
