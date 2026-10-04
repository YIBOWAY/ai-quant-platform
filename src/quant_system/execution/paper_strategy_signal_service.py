from __future__ import annotations

from datetime import date, timedelta
from math import isfinite
from typing import Any

import pandas as pd

from quant_system.backtest.strategy import MeanReversionTopN, ScoreSignalStrategy
from quant_system.config.settings import Settings
from quant_system.d34.artifact_factor import load_d34_paper_factor_registry
from quant_system.data.provider_factory import build_ohlcv_provider
from quant_system.data.providers.futu import FutuProviderError
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
        allow_frozen_account: bool = False,
        persist: bool = True,
    ) -> StrategySignal:
        if sleeve.status == StrategySleeveStatus.STOPPED:
            raise StrategySignalGenerationError("stopped sleeves cannot generate signals")
        resolved_signal_date = self._resolve_signal_date(signal_date)
        blocked_reason = self._execution_blocked_reason(
            sleeve,
            account,
            allow_frozen_account=allow_frozen_account,
        )
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
        if persist:
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
        if config.strategy_definition is not None:
            return self._build_definition_signal(
                sleeve=sleeve, config=config, account=account, signal_date=signal_date,
                history_days=history_days, execution_blocked_reason=execution_blocked_reason,
                base_warnings=base_warnings,
            )
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
                provider_error=self._provider_error_payload(exc),
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
                provider_error=self._provider_error_payload(exc),
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

    def _build_definition_signal(
        self, *, sleeve: StrategySleeve, config: StrategyConfig, account: PaperAccount,
        signal_date: date, history_days: int, execution_blocked_reason: str | None,
        base_warnings: list[str],
    ) -> StrategySignal:
        from quant_system.research.definition_paper import (
            definition_orders,
            paper_definition,
            require_paper_costs,
        )
        from quant_system.research.strategy_runtime import decision_for_session, latest_session

        source = config.data_provider
        metadata: dict[str, Any] = {"strategy_id": config.strategy_id}
        try:
            # Revalidate nested JSON even if the caller mutated a model in memory.
            config = StrategyConfig.model_validate(config.model_dump(mode="json"))
            definition = paper_definition(config.strategy_definition)
            require_paper_costs(definition, self.settings)
            decision_session = latest_session(signal_date - timedelta(days=1)).date()
            history_start = date.fromisoformat(definition.history_start)
            history_days = (decision_session - history_start).days
            if history_days < 0:
                raise ValueError("strategy_history_start_after_cutoff")
            metadata.update({
                "definition_digest": definition.content_digest,
                "decision_session": decision_session.isoformat(),
                "history_days": history_days,
                "history_start": definition.history_start,
                "execution_timing": definition.execution_price,
                "reference_initial_cash": definition.initial_cash,
                "simulation_allocation_usd": sleeve.initial_allocated_cash,
            })
        except (ValueError, TypeError) as exc:
            return StrategySignal.create(
                sleeve=sleeve, signal_date=signal_date.isoformat(), data_provider=source,
                warnings=[*base_warnings, f"strategy definition is invalid: {exc}"],
                status=SignalStatus.INVALID, execution_blocked_reason=execution_blocked_reason,
                metadata=metadata,
            )

        try:
            provider, source = build_ohlcv_provider(self.settings, requested=definition.provider)
            if source != "futu":
                raise ValueError("strategy_definition_real_provider_required")
            lots = self.storage.load_sleeve_lots(sleeve.sleeve_id)
            if any(lot.symbol.upper() not in definition.symbols for lot in lots):
                raise ValueError("strategy_definition_position_outside_universe")
            ohlcv = provider.fetch_ohlcv(
                list(dict.fromkeys([*definition.symbols, definition.benchmark_symbol])),
                start=definition.history_start,
                end=decision_session.isoformat(),
            )
            if ohlcv is None or ohlcv.empty:
                raise ValueError("strategy history is empty")
            ohlcv = ohlcv.copy()
            timestamps = pd.to_datetime(ohlcv["timestamp"], utc=True)
            # A provider that returns extra rows must never expose future bars.
            ohlcv = ohlcv.loc[timestamps.dt.date <= decision_session].copy()
            latest = ohlcv.loc[
                pd.to_datetime(ohlcv["timestamp"], utc=True).dt.date == decision_session
            ]
            prices = self._latest_prices(latest)
            holdings: dict[str, float] = {}
            for lot in lots:
                symbol = lot.symbol.upper()
                holdings[symbol] = holdings.get(symbol, 0.0) + lot.quantity
            # The shared kernel owns pool eligibility. Only prices required to
            # value this sleeve and align its benchmark are mandatory up front.
            required_prices = set(holdings) | {definition.benchmark_symbol}
            if required_prices - set(prices):
                raise ValueError("strategy_definition_decision_prices_missing")
            equity = sleeve.cash + sum(holdings[symbol] * prices[symbol] for symbol in holdings)
            if not isfinite(equity) or equity <= 0:
                raise ValueError("strategy_definition_equity_unavailable")
            current_weights = {symbol: quantity * prices[symbol] / equity
                               for symbol, quantity in holdings.items()}
            decision = decision_for_session(
                ohlcv, definition, decision_session=decision_session.isoformat(),
                current_weights=current_weights,
            )
            metadata.update(decision)
            if not decision["ready"]:
                raise ValueError(str(
                    decision.get("reason") or "strategy_definition_data_unavailable"
                ))
            targets = decision["targets"]
            if set(targets or {}) - set(prices):
                raise ValueError("strategy_definition_selected_prices_missing")
            metadata["rebalance_required"] = decision["rebalance_due"] and targets is not None
            orders = []
            if execution_blocked_reason is None and sleeve.mode == StrategySleeveMode.ALLOCATED:
                orders = definition_orders(
                    definition=definition, holdings=holdings, cash=sleeve.cash, targets=targets,
                    prices=prices, account_id=account.account_id,
                )
            return StrategySignal.create(
                sleeve=sleeve, signal_date=signal_date.isoformat(), data_provider=source,
                data_as_of=decision_session.isoformat(), target_weights=targets or {},
                proposed_orders=orders, warnings=base_warnings, status=SignalStatus.GENERATED,
                execution_blocked_reason=execution_blocked_reason, metadata=metadata,
            )
        except Exception as exc:  # noqa: BLE001 - data/provider boundary fails closed
            provider_error = self._provider_error_payload(exc)
            if provider_error is not None:
                metadata = {**metadata, "provider_error": provider_error}
            return StrategySignal.create(
                sleeve=sleeve, signal_date=signal_date.isoformat(), data_provider=source,
                warnings=[*base_warnings, f"strategy definition data is unavailable: {exc}"],
                status=SignalStatus.DATA_UNAVAILABLE,
                execution_blocked_reason=execution_blocked_reason, metadata=metadata,
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
        if config.metadata.get("automation_source") == "d34":
            registry = load_d34_paper_factor_registry(
                code_path=str(config.metadata.get("artifact_code_path", "")),
                expected_code_digest=str(
                    config.metadata.get("candidate_code_digest", "")
                ),
                expected_factor_id=str(config.metadata.get("factor_id", "")),
            )
        else:
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
    def _provider_error_payload(exc: Exception) -> dict[str, Any] | None:
        """Structured provider failure detail for signal records, or None.

        Only FutuProviderError carries a classified code; other exceptions
        remain warning strings so unrelated validation failures are not
        mislabeled as provider outages.
        """
        if not isinstance(exc, FutuProviderError):
            return None
        payload: dict[str, Any] = {"code": exc.code, "message": exc.message}
        if exc.ret_code is not None:
            payload["ret_code"] = exc.ret_code
        if exc.ret_msg is not None:
            payload["ret_msg"] = str(exc.ret_msg)[:500]
        return payload

    @staticmethod
    def _data_unavailable_signal(
        *,
        sleeve: StrategySleeve,
        config: StrategyConfig,
        signal_date: date,
        data_provider: str,
        warnings: list[str],
        execution_blocked_reason: str | None,
        provider_error: dict[str, Any] | None = None,
    ) -> StrategySignal:
        metadata: dict[str, Any] = {"strategy_id": config.strategy_id}
        if provider_error is not None:
            metadata["provider_error"] = provider_error
        return StrategySignal.create(
            sleeve=sleeve,
            signal_date=signal_date.isoformat(),
            data_provider=data_provider,
            warnings=warnings,
            status=SignalStatus.DATA_UNAVAILABLE,
            execution_blocked_reason=execution_blocked_reason,
            metadata=metadata,
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
        *,
        allow_frozen_account: bool = False,
    ) -> str | None:
        if sleeve.status == StrategySleeveStatus.PAUSED:
            return "sleeve_paused"
        if account.kill_switch and not allow_frozen_account:
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
