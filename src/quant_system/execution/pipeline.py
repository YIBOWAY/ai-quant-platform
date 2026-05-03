from __future__ import annotations

from pathlib import Path

import pandas as pd
from pydantic import BaseModel, ConfigDict

from quant_system.backtest.models import TargetWeight
from quant_system.backtest.strategy import ScoreSignalStrategy
from quant_system.config.settings import Settings, load_settings
from quant_system.data.provider_factory import build_ohlcv_provider
from quant_system.execution.models import OrderRequest, OrderSide
from quant_system.execution.order_manager import OrderManager
from quant_system.execution.paper_broker import PaperBroker
from quant_system.execution.portfolio import PaperPortfolio
from quant_system.execution.reporting import generate_paper_trading_report
from quant_system.execution.storage import LocalPaperTradingStorage
from quant_system.factors.pipeline import (
    build_default_factors,
    build_factor_signal_frame,
    compute_factor_pipeline,
)
from quant_system.risk.engine import RiskEngine
from quant_system.risk.models import RiskContext, RiskLimits


class PaperTradingRunResult(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    source: str = "sample"
    signal_count: int = 0
    orders_path: Path
    order_events_path: Path
    trades_path: Path
    risk_breaches_path: Path
    report_path: Path
    order_count: int
    trade_count: int
    risk_breach_count: int
    final_equity: float


def run_paper_trading(
    *,
    symbols: list[str],
    start: str,
    end: str,
    output_dir: str | Path | None = None,
    initial_cash: float = 100_000.0,
    lookback: int = 20,
    top_n: int = 3,
    target_gross_exposure: float = 1.0,
    max_position_size: float = 0.50,
    max_order_value: float = 20_000.0,
    max_daily_loss: float = 0.02,
    max_drawdown: float = 0.10,
    allowed_symbols: list[str] | None = None,
    blocked_symbols: list[str] | None = None,
    kill_switch: bool | None = None,
    max_fill_ratio_per_tick: float = 1.0,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
    min_order_value: float = 0.0,
    provider: str | None = None,
    settings: Settings | None = None,
) -> PaperTradingRunResult:
    active_settings = settings or load_settings()
    ohlcv_provider, source = build_ohlcv_provider(active_settings, requested=provider)
    ohlcv = ohlcv_provider.fetch_ohlcv(symbols, start=start, end=end)
    factor_results = compute_factor_pipeline(
        ohlcv,
        factors=build_default_factors(lookback=lookback),
    )
    signal_frame = build_factor_signal_frame(factor_results)
    result = run_signal_paper_trading(
        ohlcv=ohlcv,
        signal_frame=signal_frame,
        output_dir=output_dir,
        top_n=top_n,
        target_gross_exposure=target_gross_exposure,
        initial_cash=initial_cash,
        max_position_size=max_position_size,
        max_order_value=max_order_value,
        max_daily_loss=max_daily_loss,
        max_drawdown=max_drawdown,
        allowed_symbols=allowed_symbols,
        blocked_symbols=blocked_symbols,
        kill_switch=kill_switch,
        max_fill_ratio_per_tick=max_fill_ratio_per_tick,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
        min_order_value=min_order_value,
    )
    return result.model_copy(
        update={
            "source": source,
            "signal_count": len(signal_frame),
        }
    )


def run_sample_paper_trading(
    *,
    symbols: list[str],
    start: str,
    end: str,
    output_dir: str | Path | None = None,
    initial_cash: float = 100_000.0,
    max_position_size: float = 0.50,
    max_order_value: float = 20_000.0,
    max_daily_loss: float = 0.02,
    max_drawdown: float = 0.10,
    allowed_symbols: list[str] | None = None,
    blocked_symbols: list[str] | None = None,
    kill_switch: bool | None = None,
    max_fill_ratio_per_tick: float = 1.0,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
) -> PaperTradingRunResult:
    settings = load_settings()
    effective_kill_switch = settings.safety.kill_switch if kill_switch is None else kill_switch
    provider, source = build_ohlcv_provider(settings, requested="sample")
    ohlcv = provider.fetch_ohlcv(symbols, start=start, end=end)
    portfolio = PaperPortfolio(initial_cash=initial_cash)
    broker = PaperBroker(
        portfolio=portfolio,
        max_fill_ratio_per_tick=max_fill_ratio_per_tick,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
    )
    limits = RiskLimits(
        kill_switch=effective_kill_switch,
        max_position_size=max_position_size,
        max_daily_loss=max_daily_loss,
        max_drawdown=max_drawdown,
        max_order_value=max_order_value,
        allowed_symbols=allowed_symbols or [],
        blocked_symbols=blocked_symbols or [],
    )
    manager = OrderManager(risk_engine=RiskEngine(limits), broker=broker)

    peak_equity = initial_cash
    previous_equity = initial_cash
    for timestamp, bars in ohlcv.groupby("timestamp", sort=True):
        prices = dict(zip(bars["symbol"], bars["open"], strict=True))
        close_prices = dict(zip(bars["symbol"], bars["close"], strict=True))
        equity = portfolio.equity(prices)
        peak_equity = max(peak_equity, equity)
        for symbol, price in prices.items():
            context = _build_risk_context(
                portfolio=portfolio,
                prices=prices,
                peak_equity=peak_equity,
                previous_equity=previous_equity,
            )
            order_value = min(max_order_value * 0.50, max(initial_cash * 0.05, 1.0))
            quantity = order_value / price
            request = OrderRequest(
                timestamp=timestamp,
                symbol=symbol,
                side=OrderSide.BUY,
                quantity=quantity,
                limit_price=float(price),
                reason="sample_paper_trading_loop",
            )
            manager.create_and_submit(request, context)
            manager.process_market_data(timestamp=timestamp, prices={symbol: price})
        close_equity = portfolio.equity(close_prices)
        peak_equity = max(peak_equity, close_equity)
        manager.check_post_trade_risk(
            _build_risk_context(
                portfolio=portfolio,
                prices=close_prices,
                peak_equity=peak_equity,
                previous_equity=previous_equity,
            )
        )
        previous_equity = close_equity

    return _persist_paper_run(
        manager=manager,
        portfolio=portfolio,
        ohlcv=ohlcv,
        output_dir=output_dir,
        kill_switch=effective_kill_switch,
        source=source,
    )


def run_signal_paper_trading(
    *,
    ohlcv: pd.DataFrame,
    signal_frame: pd.DataFrame,
    output_dir: str | Path | None = None,
    top_n: int = 3,
    target_gross_exposure: float = 1.0,
    initial_cash: float = 100_000.0,
    max_position_size: float = 0.50,
    max_order_value: float = 20_000.0,
    max_daily_loss: float = 0.02,
    max_drawdown: float = 0.10,
    allowed_symbols: list[str] | None = None,
    blocked_symbols: list[str] | None = None,
    kill_switch: bool | None = None,
    max_fill_ratio_per_tick: float = 1.0,
    commission_bps: float = 0.0,
    slippage_bps: float = 0.0,
    min_order_value: float = 0.0,
) -> PaperTradingRunResult:
    settings = load_settings()
    effective_kill_switch = settings.safety.kill_switch if kill_switch is None else kill_switch
    frame = _prepare_ohlcv(ohlcv)
    strategy = ScoreSignalStrategy(
        signal_frame,
        top_n=top_n,
        target_gross_exposure=target_gross_exposure,
    )
    portfolio = PaperPortfolio(initial_cash=initial_cash)
    broker = PaperBroker(
        portfolio=portfolio,
        max_fill_ratio_per_tick=max_fill_ratio_per_tick,
        commission_bps=commission_bps,
        slippage_bps=slippage_bps,
    )
    limits = RiskLimits(
        kill_switch=effective_kill_switch,
        max_position_size=max_position_size,
        max_daily_loss=max_daily_loss,
        max_drawdown=max_drawdown,
        max_order_value=max_order_value,
        allowed_symbols=allowed_symbols or [],
        blocked_symbols=blocked_symbols or [],
    )
    manager = OrderManager(risk_engine=RiskEngine(limits), broker=broker)

    peak_equity = initial_cash
    previous_equity = initial_cash
    for timestamp, bars in frame.groupby("timestamp", sort=True):
        open_prices = dict(zip(bars["symbol"], bars["open"], strict=True))
        close_prices = dict(zip(bars["symbol"], bars["close"], strict=True))
        open_equity = portfolio.equity(open_prices)
        peak_equity = max(peak_equity, open_equity)

        targets = strategy.target_weights(timestamp)
        if targets is not None:
            requests = _generate_rebalance_requests(
                timestamp=timestamp,
                targets=targets,
                portfolio=portfolio,
                prices=open_prices,
                min_order_value=min_order_value,
            )
            for request in requests:
                context = _build_risk_context(
                    portfolio=portfolio,
                    prices=open_prices,
                    peak_equity=peak_equity,
                    previous_equity=previous_equity,
                )
                manager.create_and_submit(request, context)
                manager.process_market_data(
                    timestamp=timestamp,
                    prices={request.normalized_symbol(): open_prices[request.normalized_symbol()]},
                )

        close_equity = portfolio.equity(close_prices)
        peak_equity = max(peak_equity, close_equity)
        manager.check_post_trade_risk(
            _build_risk_context(
                portfolio=portfolio,
                prices=close_prices,
                peak_equity=peak_equity,
                previous_equity=previous_equity,
            )
        )
        previous_equity = close_equity

    return _persist_paper_run(
        manager=manager,
        portfolio=portfolio,
        ohlcv=frame,
        output_dir=output_dir,
        kill_switch=effective_kill_switch,
        report_filename="signal_paper_trading_report.md",
    )


def _last_close_prices(ohlcv: pd.DataFrame) -> dict[str, float]:
    latest = ohlcv.sort_values(["symbol", "timestamp"]).groupby("symbol").tail(1)
    return dict(zip(latest["symbol"], latest["close"], strict=True))


def _prepare_ohlcv(ohlcv: pd.DataFrame) -> pd.DataFrame:
    required = {"symbol", "timestamp", "open", "close"}
    missing = required.difference(ohlcv.columns)
    if missing:
        raise ValueError(f"missing required OHLCV columns: {', '.join(sorted(missing))}")
    frame = ohlcv.copy()
    frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["open"] = pd.to_numeric(frame["open"], errors="coerce")
    frame["close"] = pd.to_numeric(frame["close"], errors="coerce")
    return frame.dropna(subset=["open", "close"]).sort_values(
        ["timestamp", "symbol"],
        ignore_index=True,
    )


def _generate_rebalance_requests(
    *,
    timestamp: pd.Timestamp,
    targets: list[TargetWeight],
    portfolio: PaperPortfolio,
    prices: dict[str, float],
    min_order_value: float,
) -> list[OrderRequest]:
    target_map = {target.symbol.upper(): float(target.target_weight) for target in targets}
    symbols = sorted(set(portfolio.positions).union(target_map))
    equity = portfolio.equity(prices)
    requests: list[OrderRequest] = []

    for symbol in symbols:
        price = prices.get(symbol)
        if price is None:
            continue
        current_value = portfolio.position(symbol) * price
        target_value = target_map.get(symbol, 0.0) * equity
        value_delta = target_value - current_value
        if abs(value_delta) <= min_order_value:
            continue
        side = OrderSide.BUY if value_delta > 0 else OrderSide.SELL
        quantity = abs(value_delta) / price
        if quantity <= 0:
            continue
        requests.append(
            OrderRequest(
                timestamp=timestamp,
                symbol=symbol,
                side=side,
                quantity=quantity,
                limit_price=price,
                reason="signal_rebalance_to_target_weight",
            )
        )

    return sorted(requests, key=lambda request: 0 if request.side == OrderSide.SELL else 1)


def _build_risk_context(
    *,
    portfolio: PaperPortfolio,
    prices: dict[str, float],
    peak_equity: float,
    previous_equity: float,
) -> RiskContext:
    equity = portfolio.equity(prices)
    return RiskContext(
        cash=portfolio.cash,
        equity=equity,
        peak_equity=peak_equity,
        daily_pnl=equity - previous_equity,
        positions=portfolio.positions.copy(),
        latest_prices={symbol.upper(): float(price) for symbol, price in prices.items()},
    )


def _persist_paper_run(
    *,
    manager: OrderManager,
    portfolio: PaperPortfolio,
    ohlcv: pd.DataFrame,
    output_dir: str | Path | None,
    kill_switch: bool,
    source: str = "sample",
    report_filename: str = "paper_trading_report.md",
) -> PaperTradingRunResult:
    final_prices = _last_close_prices(ohlcv)
    final_equity = portfolio.equity(final_prices)
    storage = _build_storage(output_dir)
    orders_frame = pd.DataFrame(
        [order.model_dump(mode="json") for order in manager.orders.values()],
        columns=[
            "order_id",
            "created_at",
            "symbol",
            "side",
            "quantity",
            "limit_price",
            "status",
            "filled_quantity",
            "reason",
            "rejected_reason",
        ],
    )
    events_frame = pd.DataFrame(
        [event.model_dump(mode="json") for event in manager.order_event_log],
        columns=["timestamp", "order_id", "symbol", "status", "message"],
    )
    trades_frame = pd.DataFrame(
        [fill.model_dump(mode="json") for fill in manager.trade_log],
        columns=[
            "fill_id",
            "order_id",
            "timestamp",
            "symbol",
            "side",
            "quantity",
            "fill_price",
            "gross_value",
            "commission",
        ],
    )
    breaches_frame = pd.DataFrame(
        [breach.model_dump(mode="json") for breach in manager.risk_breach_log],
        columns=["timestamp", "rule_name", "symbol", "message", "order_id"],
    )
    orders_path = storage.save_frame(
        orders_frame,
        filename="orders.parquet",
        table_name="paper_orders",
    )
    order_events_path = storage.save_frame(
        events_frame,
        filename="order_events.parquet",
        table_name="paper_order_events",
    )
    trades_path = storage.save_frame(
        trades_frame,
        filename="trades.parquet",
        table_name="paper_trades",
    )
    risk_breaches_path = storage.save_frame(
        breaches_frame,
        filename="risk_breaches.parquet",
        table_name="paper_risk_breaches",
    )
    report = generate_paper_trading_report(
        order_count=len(orders_frame),
        submitted_count=(
            int((orders_frame["status"] != "rejected").sum()) if not orders_frame.empty else 0
        ),
        filled_count=(
            int((orders_frame["status"] == "filled").sum()) if not orders_frame.empty else 0
        ),
        trade_count=len(trades_frame),
        risk_breach_count=len(breaches_frame),
        final_cash=portfolio.cash,
        final_equity=final_equity,
        kill_switch=kill_switch,
    )
    report_path = storage.save_report(report, filename=report_filename)
    return PaperTradingRunResult(
        source=source,
        orders_path=orders_path,
        order_events_path=order_events_path,
        trades_path=trades_path,
        risk_breaches_path=risk_breaches_path,
        report_path=report_path,
        order_count=len(orders_frame),
        trade_count=len(trades_frame),
        risk_breach_count=len(breaches_frame),
        final_equity=final_equity,
    )


def _build_storage(output_dir: str | Path | None) -> LocalPaperTradingStorage:
    if output_dir is not None:
        return LocalPaperTradingStorage(base_dir=output_dir)
    data_settings = load_settings().data
    return LocalPaperTradingStorage(
        base_dir=data_settings.data_dir,
        reports_dir=data_settings.reports_dir,
        duckdb_path=data_settings.duckdb_path,
    )
