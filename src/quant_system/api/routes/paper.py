from __future__ import annotations

import json
import threading
from contextlib import suppress

from fastapi import APIRouter, HTTPException

from quant_system.api.dependencies import ApiRunsDirDep, SettingsDep
from quant_system.api.errors import not_found_404, provider_unavailable_400
from quant_system.api.schemas.common import (
    make_run_id,
    read_parquet_records,
    resolve_run_dir,
)
from quant_system.api.schemas.paper import (
    AccountRebalanceRequest,
    AccountResetRequest,
    KillSwitchRequest,
    ManualOrderRequest,
    PaperAccountOrderResponse,
    PaperAccountOrdersProcessResponse,
    PaperAccountRebalanceResponse,
    PaperAccountResponse,
    PaperLedgerResponse,
    PaperRunDetailResponse,
    PaperRunRequest,
    PaperRunResponse,
    PaperRunsResponse,
    StrategyConfigCreateRequest,
    StrategyConfigMutationResponse,
    StrategyConfigsResponse,
    StrategySleeveCreateRequest,
    StrategySleeveDetailResponse,
    StrategySleeveMutationResponse,
    StrategySleevesResponse,
    StrategySleeveStopRequest,
)
from quant_system.data.provider_factory import DataProviderUnavailableError
from quant_system.execution.account import DEFAULT_INITIAL_CASH, PaperAccount
from quant_system.execution.account_service import (
    AccountFrozenError,
    OrderOutcome,
    PaperAccountService,
    PendingOrderNotFoundError,
    StrategyDataUnavailableError,
)
from quant_system.execution.account_storage import PaperAccountStorage
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    CashAllocationError,
    PaperStrategySleeveService,
    StrategyConfig,
    StrategySleeveMode,
)
from quant_system.execution.pipeline import run_paper_trading
from quant_system.execution.price_source import (
    PaperPriceSource,
    PricedQuote,
    PriceUnavailableError,
)
from quant_system.storage.runs_repository import list_run_metadatas, persist_run
from quant_system.strategies.registry import build_default_strategy_registry

router = APIRouter()


def _error_detail(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


@router.post("/paper/run", response_model=PaperRunResponse)
def run_paper(
    request: PaperRunRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    if request.enable_kill_switch:
        raise HTTPException(
            status_code=409,
            detail=_error_detail(
                "replay_kill_switch_enabled",
                (
                    "Replay kill switch is enabled; historical paper replay would "
                    "create orders with no fills. Disable the replay kill switch "
                    "only after turning off QS_KILL_SWITCH for this local simulation."
                ),
            ),
        )
    if settings.safety.kill_switch and not request.enable_kill_switch:
        raise HTTPException(
            status_code=409,
            detail=_error_detail(
                "global_kill_switch_enabled",
                "Global kill switch is enabled; API requests cannot disable the kill switch",
            ),
        )
    run_id = make_run_id("paper")
    run_dir = api_runs_dir / "paper" / run_id
    try:
        result = run_paper_trading(
            symbols=request.symbols,
            start=request.start,
            end=request.end,
            output_dir=run_dir,
            initial_cash=request.initial_cash,
            lookback=request.lookback,
            top_n=request.top_n,
            kill_switch=request.enable_kill_switch,
            max_fill_ratio_per_tick=request.max_fill_ratio_per_tick,
            provider=request.provider,
            settings=settings,
        )
    except DataProviderUnavailableError as exc:
        raise provider_unavailable_400(exc) from exc
    metadata = {
        "run_id": run_id,
        "source": result.source,
        "signal_count": result.signal_count,
        "order_count": result.order_count,
        "trade_count": result.trade_count,
        "risk_breach_count": result.risk_breach_count,
        "final_equity": result.final_equity,
        "execution_status": result.execution_status,
        "execution_note": result.execution_note,
        "request": {
            "symbols": request.symbols,
            "start": request.start,
            "end": request.end,
            "provider": request.provider,
            "initial_cash": request.initial_cash,
            "lookback": request.lookback,
            "top_n": request.top_n,
            "max_fill_ratio_per_tick": request.max_fill_ratio_per_tick,
            "enable_kill_switch": request.enable_kill_switch,
        },
        "paths": {
            "orders": str(result.orders_path),
            "order_events": str(result.order_events_path),
            "trades": str(result.trades_path),
            "risk_breaches": str(result.risk_breaches_path),
            "report": str(result.report_path),
        },
    }
    return persist_run(run_dir, "paper", metadata, settings=settings)

@router.get("/paper", response_model=PaperRunsResponse)
def list_paper(api_runs_dir: ApiRunsDirDep, settings: SettingsDep) -> dict:
    root = api_runs_dir / "paper"
    paper_runs = [
        {
            "id": metadata["run_id"],
            "source": metadata.get("source", "sample"),
            "summary": metadata,
        }
        for metadata in list_run_metadatas("paper", root, settings)
    ]
    return {"paper_runs": paper_runs}


# --- Persistent paper account (interactive auto + manual trading) ---------

# Serialise all mutations to a given account so concurrent requests (e.g. a
# scheduled rebalance landing while a manual order is in flight) cannot
# lost-update each other through the load -> mutate -> save cycle.
_ACCOUNT_LOCKS: dict[str, threading.Lock] = {}
_ACCOUNT_LOCKS_GUARD = threading.Lock()


def _account_lock(account_id: str) -> threading.Lock:
    with _ACCOUNT_LOCKS_GUARD:
        lock = _ACCOUNT_LOCKS.get(account_id)
        if lock is None:
            lock = threading.Lock()
            _ACCOUNT_LOCKS[account_id] = lock
        return lock


def _account_storage(api_runs_dir) -> PaperAccountStorage:
    return PaperAccountStorage(api_runs_dir)


def _strategy_sleeve_storage(api_runs_dir) -> PaperStrategySleeveStorage:
    return PaperStrategySleeveStorage(api_runs_dir)


def _account_quotes(account: PaperAccount, *, settings) -> dict[str, PricedQuote]:
    """Resolve a current read-only quote for every held symbol."""
    price_source = PaperPriceSource(settings)
    quotes: dict[str, PricedQuote] = {}
    for symbol, position in account.positions.items():
        try:
            quotes[symbol] = price_source.get_price(symbol)
        except PriceUnavailableError:
            quotes[symbol] = PricedQuote(
                symbol=symbol,
                price=position.avg_cost,
                price_kind="avg_cost_fallback",
                as_of=account.updated_at,
                source="account",
            )
    return quotes


def _save_account(
    storage: PaperAccountStorage,
    account: PaperAccount,
    quotes: dict[str, PricedQuote],
) -> None:
    storage.save(
        account,
        prices={symbol: quote.price for symbol, quote in quotes.items()},
        price_metadata={
            symbol: {"kind": quote.price_kind, "as_of": quote.as_of}
            for symbol, quote in quotes.items()
        },
    )


def _account_view(
    account: PaperAccount,
    *,
    settings,
    quotes: dict[str, PricedQuote] | None = None,
) -> dict:
    """Materialise a price-aware account view for the Position Map."""
    quotes = quotes if quotes is not None else _account_quotes(account, settings=settings)
    prices = {symbol: quote.price for symbol, quote in quotes.items()}
    price_kinds = {quote.price_kind for quote in quotes.values()}
    price_kind = (
        next(iter(price_kinds))
        if len(price_kinds) == 1
        else ("mixed" if price_kinds else "none")
    )
    as_of = next(iter(quotes.values())).as_of if len(quotes) == 1 else None

    equity = account.equity(prices)
    positions = []
    for symbol, position in sorted(account.positions.items()):
        quote = quotes.get(symbol)
        last_price = quote.price if quote is not None else position.avg_cost
        positions.append(
            {
                "symbol": symbol,
                "quantity": position.quantity,
                "avg_cost": position.avg_cost,
                "last_price": last_price,
                "market_value": position.market_value(last_price),
                "weight": (position.market_value(last_price) / equity) if equity else 0.0,
                "unrealized_pnl": position.unrealized_pnl(last_price),
                "source_breakdown": position.source_breakdown(),
                "price_kind": quote.price_kind if quote is not None else "avg_cost_fallback",
                "price_as_of": quote.as_of if quote is not None else account.updated_at,
            }
        )

    pnl_abs = equity - account.initial_cash
    return {
        "account_id": account.account_id,
        "base_currency": account.base_currency,
        "initial_cash": account.initial_cash,
        "cash": account.cash,
        "reserved_cash": account.reserved_cash(),
        "available_cash": account.available_cash(),
        "equity": equity,
        "realized_pnl": account.realized_pnl,
        "unrealized_pnl": account.unrealized_pnl(prices),
        "pnl_abs": pnl_abs,
        "pnl_pct": (pnl_abs / account.initial_cash) if account.initial_cash else 0.0,
        "invested_pct": (account.market_value(prices) / equity) if equity else 0.0,
        "kill_switch": account.kill_switch,
        "price_source": {"kind": price_kind, "as_of": as_of},
        "positions": positions,
        "pending_orders": [
            order.model_dump(mode="json") for order in account.pending_orders
        ],
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }


def _process_pending_account_orders(
    api_runs_dir,
    settings,
    *,
    open_if_missing: bool,
    quote_when_idle: bool,
) -> tuple[list[OrderOutcome], PaperAccount | None, dict[str, PricedQuote]]:
    storage = _account_storage(api_runs_dir)
    service = PaperAccountService(settings=settings)
    with _account_lock(storage.account_id), storage.mutation_lock():
        account = (
            storage.load_or_open(initial_cash=DEFAULT_INITIAL_CASH)
            if open_if_missing
            else storage.load()
        )
        if account is None:
            return [], None, {}
        if not account.pending_orders:
            quotes = (
                _account_quotes(account, settings=settings) if quote_when_idle else {}
            )
            return [], account, quotes
        outcomes = service.process_pending_orders(account)
        quotes = _account_quotes(account, settings=settings)
        _save_account(storage, account, quotes)
        return outcomes, account, quotes


def process_pending_account_orders_once(api_runs_dir, settings) -> list[OrderOutcome]:
    outcomes, _, _ = _process_pending_account_orders(
        api_runs_dir,
        settings,
        open_if_missing=False,
        quote_when_idle=False,
    )
    return outcomes


@router.get("/paper/account", response_model=PaperAccountResponse)
def get_account(api_runs_dir: ApiRunsDirDep, settings: SettingsDep) -> dict:
    storage = _account_storage(api_runs_dir)
    account = storage.load_or_open(initial_cash=DEFAULT_INITIAL_CASH)
    return _account_view(account, settings=settings)


@router.post("/paper/account/reset", response_model=PaperAccountResponse)
def reset_account(
    request: AccountResetRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    storage = _account_storage(api_runs_dir)
    with _account_lock(storage.account_id), storage.mutation_lock():
        account = storage.reset(initial_cash=request.initial_cash)
        return _account_view(account, settings=settings)


@router.post("/paper/account/kill-switch", response_model=PaperAccountResponse)
def set_account_kill_switch(
    request: KillSwitchRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    storage = _account_storage(api_runs_dir)
    with _account_lock(storage.account_id), storage.mutation_lock():
        account = storage.load_or_open(initial_cash=DEFAULT_INITIAL_CASH)
        account.kill_switch = request.enabled
        account.record_event(
            kind="freeze" if request.enabled else "unfreeze",
            note=f"account kill switch set to {request.enabled}",
        )
        quotes = _account_quotes(account, settings=settings)
        _save_account(storage, account, quotes)
        return _account_view(account, settings=settings, quotes=quotes)


@router.get("/paper/account/ledger", response_model=PaperLedgerResponse)
def get_account_ledger(
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    storage = _account_storage(api_runs_dir)
    account = storage.load_or_open(initial_cash=DEFAULT_INITIAL_CASH)
    entries = [entry.model_dump(mode="json") for entry in account.ledger]
    entries.reverse()  # newest first
    window = entries[offset : offset + max(limit, 0)]
    return {"total": len(entries), "limit": limit, "offset": offset, "entries": window}


@router.post("/paper/account/orders", response_model=PaperAccountOrderResponse)
def place_account_order(
    request: ManualOrderRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    storage = _account_storage(api_runs_dir)
    service = PaperAccountService(settings=settings)
    with _account_lock(storage.account_id), storage.mutation_lock():
        account = storage.load_or_open(initial_cash=DEFAULT_INITIAL_CASH)
        try:
            outcome = service.place_manual_order(
                account,
                symbol=request.symbol,
                side=request.side,
                quantity=request.quantity,
                notional=request.notional,
                limit_price=request.limit_price,
            )
        except AccountFrozenError as exc:
            raise HTTPException(
                status_code=409,
                detail=_error_detail("account_frozen", str(exc)),
            ) from exc
        except PriceUnavailableError as exc:
            raise HTTPException(
                status_code=422,
                detail=_error_detail("price_unavailable", str(exc)),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=_error_detail("invalid_account_order", str(exc)),
            ) from exc
        quotes = _account_quotes(account, settings=settings)
        _save_account(storage, account, quotes)
        return {
            "order": _order_outcome_view(outcome),
            "account": _account_view(account, settings=settings, quotes=quotes),
        }


@router.post(
    "/paper/account/orders/process",
    response_model=PaperAccountOrdersProcessResponse,
)
def process_pending_account_orders(
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    try:
        outcomes, account, quotes = _process_pending_account_orders(
            api_runs_dir,
            settings,
            open_if_missing=True,
            quote_when_idle=True,
        )
    except AccountFrozenError as exc:
        raise HTTPException(
            status_code=409,
            detail=_error_detail("account_frozen", str(exc)),
        ) from exc
    except PriceUnavailableError as exc:
        raise HTTPException(
            status_code=422,
            detail=_error_detail("price_unavailable", str(exc)),
        ) from exc
    if account is None:
        raise RuntimeError("paper account should be opened for manual processing")
    return {
        "orders": [_order_outcome_view(outcome) for outcome in outcomes],
        "account": _account_view(account, settings=settings, quotes=quotes),
    }


@router.post(
    "/paper/account/orders/{order_id}/cancel",
    response_model=PaperAccountOrderResponse,
)
def cancel_pending_account_order(
    order_id: str,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    storage = _account_storage(api_runs_dir)
    service = PaperAccountService(settings=settings)
    with _account_lock(storage.account_id), storage.mutation_lock():
        account = storage.load_or_open(initial_cash=DEFAULT_INITIAL_CASH)
        try:
            outcome = service.cancel_pending_order(account, order_id=order_id)
        except PendingOrderNotFoundError as exc:
            raise HTTPException(
                status_code=404,
                detail=_error_detail("pending_order_not_found", str(exc)),
            ) from exc
        quotes = _account_quotes(account, settings=settings)
        _save_account(storage, account, quotes)
        return {
            "order": _order_outcome_view(outcome),
            "account": _account_view(account, settings=settings, quotes=quotes),
        }


@router.post(
    "/paper/account/rebalance",
    response_model=PaperAccountRebalanceResponse,
)
def rebalance_account(
    request: AccountRebalanceRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    strategy_id = _account_rebalance_strategy_id(request.strategy_id)
    storage = _account_storage(api_runs_dir)
    service = PaperAccountService(settings=settings)
    with _account_lock(storage.account_id), storage.mutation_lock():
        account = storage.load_or_open(initial_cash=DEFAULT_INITIAL_CASH)
        try:
            outcome = service.rebalance_to_strategy(
                account,
                strategy_id=strategy_id,
                symbols=request.symbols,
                lookback=request.lookback,
                top_n=request.top_n,
                provider=request.provider,
            )
        except AccountFrozenError as exc:
            raise HTTPException(
                status_code=409,
                detail=_error_detail("account_frozen", str(exc)),
            ) from exc
        except (PriceUnavailableError, StrategyDataUnavailableError) as exc:
            code = (
                "price_unavailable"
                if isinstance(exc, PriceUnavailableError)
                else "strategy_data_unavailable"
            )
            raise HTTPException(
                status_code=422,
                detail=_error_detail(code, str(exc)),
            ) from exc
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=_error_detail("invalid_account_rebalance", str(exc)),
            ) from exc
        quotes = _account_quotes(account, settings=settings)
        _save_account(storage, account, quotes)
        return {
            "rebalance": {
                "strategy_id": outcome.strategy_id,
                "as_of": outcome.as_of,
                "aborted": outcome.aborted,
                "target_weights": outcome.target_weights,
                "note": outcome.note,
                "orders": [
                    _order_outcome_view(order)
                    for order in outcome.orders
                ],
            },
            "account": _account_view(account, settings=settings, quotes=quotes),
        }


@router.post(
    "/paper/strategy-configs",
    response_model=StrategyConfigMutationResponse,
)
def create_strategy_config(
    request: StrategyConfigCreateRequest,
    api_runs_dir: ApiRunsDirDep,
) -> dict:
    storage = _strategy_sleeve_storage(api_runs_dir)
    with storage.mutation_lock():
        config = StrategyConfig.create(**request.model_dump(mode="json"))
        try:
            storage.save_strategy_config(config)
        except FileExistsError as exc:
            raise HTTPException(
                status_code=409,
                detail=_error_detail("strategy_config_conflict", str(exc)),
            ) from exc
    return {"config": config.model_dump(mode="json")}


@router.get(
    "/paper/strategy-configs",
    response_model=StrategyConfigsResponse,
)
def list_strategy_configs(api_runs_dir: ApiRunsDirDep) -> dict:
    storage = _strategy_sleeve_storage(api_runs_dir)
    return {
        "configs": [
            config.model_dump(mode="json")
            for config in storage.list_strategy_configs()
        ]
    }


@router.post(
    "/paper/strategy-configs/{strategy_config_id}/versions",
    response_model=StrategyConfigMutationResponse,
)
def create_strategy_config_version(
    strategy_config_id: str,
    request: StrategyConfigCreateRequest,
    api_runs_dir: ApiRunsDirDep,
) -> dict:
    storage = _strategy_sleeve_storage(api_runs_dir)
    with storage.mutation_lock():
        try:
            latest = storage.load_strategy_config(strategy_config_id)
        except FileNotFoundError as exc:
            raise not_found_404("strategy_config", strategy_config_id) from exc
        config = latest.new_version(**request.model_dump(mode="json"))
        try:
            storage.save_strategy_config(config)
        except FileExistsError as exc:
            raise HTTPException(
                status_code=409,
                detail=_error_detail("strategy_config_conflict", str(exc)),
            ) from exc
    return {"config": config.model_dump(mode="json")}


@router.post(
    "/paper/strategy-sleeves",
    response_model=StrategySleeveMutationResponse,
)
def create_strategy_sleeve(
    request: StrategySleeveCreateRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    account_storage = _account_storage(api_runs_dir)
    sleeve_storage = _strategy_sleeve_storage(api_runs_dir)
    service = PaperStrategySleeveService(sleeve_storage)
    with _account_lock(account_storage.account_id), account_storage.mutation_lock():
        account = account_storage.load_or_open(initial_cash=DEFAULT_INITIAL_CASH)
        previous_account = account.model_copy(deep=True)
        try:
            config = sleeve_storage.load_strategy_config(
                request.strategy_config_id,
                version=request.strategy_config_version,
            )
            sleeve = service.create_sleeve(
                account,
                config=config,
                mode=StrategySleeveMode(request.mode),
                allocated_cash=request.allocated_cash,
                metadata=request.metadata,
            )
        except FileNotFoundError as exc:
            raise not_found_404(
                "strategy_config",
                request.strategy_config_id,
            ) from exc
        except CashAllocationError as exc:
            raise HTTPException(
                status_code=400,
                detail=_error_detail("cash_allocation_error", str(exc)),
            ) from exc
        quotes = _account_quotes(account, settings=settings)
        _save_account(account_storage, account, quotes)
        try:
            sleeve_storage.save_sleeve(sleeve)
        except (OSError, ValueError) as exc:
            with suppress(Exception):
                _save_account(account_storage, previous_account, quotes)
            raise HTTPException(
                status_code=500,
                detail=_error_detail(
                    "strategy_sleeve_storage_error",
                    "failed to persist strategy sleeve after account update",
                ),
            ) from exc
        return {
            "sleeve": sleeve.model_dump(mode="json"),
            "account": _account_view(account, settings=settings, quotes=quotes),
        }


@router.get(
    "/paper/strategy-sleeves",
    response_model=StrategySleevesResponse,
)
def list_strategy_sleeves(api_runs_dir: ApiRunsDirDep) -> dict:
    storage = _strategy_sleeve_storage(api_runs_dir)
    return {
        "sleeves": [
            sleeve.model_dump(mode="json")
            for sleeve in storage.list_sleeves()
        ]
    }


@router.get(
    "/paper/strategy-sleeves/{sleeve_id}",
    response_model=StrategySleeveDetailResponse,
)
def get_strategy_sleeve(sleeve_id: str, api_runs_dir: ApiRunsDirDep) -> dict:
    storage = _strategy_sleeve_storage(api_runs_dir)
    try:
        sleeve = storage.load_sleeve(sleeve_id)
    except FileNotFoundError as exc:
        raise not_found_404("strategy_sleeve", sleeve_id) from exc
    return {
        "sleeve": sleeve.model_dump(mode="json"),
        "lots": [lot.model_dump(mode="json") for lot in storage.load_sleeve_lots(sleeve_id)],
        "signals": [
            signal.model_dump(mode="json") for signal in storage.load_signals(sleeve_id)
        ],
    }


@router.post(
    "/paper/strategy-sleeves/{sleeve_id}/pause",
    response_model=StrategySleeveMutationResponse,
)
def pause_strategy_sleeve(
    sleeve_id: str,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    return _mutate_strategy_sleeve_status(
        sleeve_id,
        api_runs_dir=api_runs_dir,
        settings=settings,
        action="pause",
    )


@router.post(
    "/paper/strategy-sleeves/{sleeve_id}/resume",
    response_model=StrategySleeveMutationResponse,
)
def resume_strategy_sleeve(
    sleeve_id: str,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    return _mutate_strategy_sleeve_status(
        sleeve_id,
        api_runs_dir=api_runs_dir,
        settings=settings,
        action="resume",
    )


@router.post(
    "/paper/strategy-sleeves/{sleeve_id}/stop",
    response_model=StrategySleeveMutationResponse,
)
def stop_strategy_sleeve(
    sleeve_id: str,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
    request: StrategySleeveStopRequest | None = None,
) -> dict:
    return _mutate_strategy_sleeve_status(
        sleeve_id,
        api_runs_dir=api_runs_dir,
        settings=settings,
        action="stop",
        reason=request.reason if request else None,
    )


def _mutate_strategy_sleeve_status(
    sleeve_id: str,
    *,
    api_runs_dir,
    settings,
    action: str,
    reason: str | None = None,
) -> dict:
    account_storage = _account_storage(api_runs_dir)
    sleeve_storage = _strategy_sleeve_storage(api_runs_dir)
    service = PaperStrategySleeveService(sleeve_storage)
    with _account_lock(account_storage.account_id), account_storage.mutation_lock():
        account = account_storage.load_or_open(initial_cash=DEFAULT_INITIAL_CASH)
        try:
            sleeve = sleeve_storage.load_sleeve(sleeve_id)
        except FileNotFoundError as exc:
            raise not_found_404("strategy_sleeve", sleeve_id) from exc
        try:
            if action == "pause":
                sleeve = service.pause_sleeve(sleeve)
            elif action == "resume":
                sleeve = service.resume_sleeve(sleeve)
            elif action == "stop":
                sleeve = service.stop_sleeve(sleeve, reason=reason)
            else:
                raise ValueError(f"unknown sleeve action: {action}")
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=_error_detail("invalid_strategy_sleeve_state", str(exc)),
            ) from exc
        quotes = _account_quotes(account, settings=settings)
        return {
            "sleeve": sleeve.model_dump(mode="json"),
            "account": _account_view(account, settings=settings, quotes=quotes),
        }


def _account_rebalance_strategy_id(strategy_id: str) -> str:
    normalized = strategy_id.strip() or "cross_sectional_top_n"
    registry = build_default_strategy_registry()
    try:
        metadata = registry.get(normalized)
    except KeyError as exc:
        supported = [
            item.id
            for item in registry.list_metadata()
            if item.supports_account_rebalance
        ]
        raise HTTPException(
            status_code=400,
            detail=_error_detail(
                "unknown_account_rebalance_strategy",
                f"unknown account rebalance strategy {normalized!r}; "
                f"supported: {', '.join(supported)}",
            ),
        ) from exc
    if not metadata.supports_account_rebalance:
        raise HTTPException(
            status_code=400,
            detail=_error_detail(
                "unsupported_account_rebalance_strategy",
                f"strategy {normalized!r} does not support account rebalance",
            ),
        )
    return normalized


@router.get("/paper/{run_id}", response_model=PaperRunDetailResponse)
def paper_detail(run_id: str, api_runs_dir: ApiRunsDirDep) -> dict:
    run_dir = resolve_run_dir(api_runs_dir / "paper", run_id)
    metadata_path = run_dir / "metadata.json"
    if not metadata_path.exists():
        raise not_found_404("paper_run", run_id)
    return {
        "id": run_id,
        "metadata": json.loads(metadata_path.read_text(encoding="utf-8")),
        "orders": read_parquet_records(run_dir / "paper" / "orders.parquet"),
        "order_events": read_parquet_records(run_dir / "paper" / "order_events.parquet"),
        "trades": read_parquet_records(run_dir / "paper" / "trades.parquet"),
        "risk_breaches": read_parquet_records(run_dir / "paper" / "risk_breaches.parquet"),
    }


def _order_outcome_view(outcome) -> dict:
    return {
        "order_id": outcome.order_id,
        "status": outcome.status,
        "symbol": outcome.symbol,
        "side": outcome.side,
        "requested_quantity": outcome.requested_quantity,
        "filled_quantity": outcome.filled_quantity,
        "price": outcome.price,
        "price_kind": outcome.price_kind,
        "rejected_reason": outcome.rejected_reason,
    }
