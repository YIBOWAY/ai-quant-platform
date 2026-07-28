from __future__ import annotations

import json
import threading
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta
from functools import wraps
from typing import Annotated, Literal

from fastapi import APIRouter, HTTPException, Query

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
    PaperAccountActivityResponse,
    PaperAccountEquityCurveResponse,
    PaperAccountOrderResponse,
    PaperAccountOrdersProcessResponse,
    PaperAccountPerformanceResponse,
    PaperAccountRebalanceResponse,
    PaperAccountResponse,
    PaperAccountSnapshotResponse,
    PaperLedgerResponse,
    PaperRunDetailResponse,
    PaperRunRequest,
    PaperRunResponse,
    PaperRunsResponse,
    StrategyConfigCreateRequest,
    StrategyConfigMutationResponse,
    StrategyConfigsResponse,
    StrategyExecutionCreateRequest,
    StrategyExecutionMutationResponse,
    StrategyExecutionProcessRequest,
    StrategyExecutionProcessResponse,
    StrategyOpsStatusResponse,
    StrategySignalGenerateRequest,
    StrategySignalMutationResponse,
    StrategySleeveCreateRequest,
    StrategySleeveDetailResponse,
    StrategySleeveMutationResponse,
    StrategySleevesResponse,
    StrategySleeveStopRequest,
)
from quant_system.data.provider_factory import DataProviderUnavailableError
from quant_system.execution.account import (
    DEFAULT_INITIAL_CASH,
    AccountPosition,
    PaperAccount,
)
from quant_system.execution.account_performance import build_account_performance
from quant_system.execution.account_repository import (
    PaperAccountBootstrapRequired,
    PaperAccountRepository,
    PaperAccountStorageCorrupt,
)
from quant_system.execution.account_repository_factory import (
    build_paper_account_repository,
)
from quant_system.execution.account_service import (
    AccountFrozenError,
    OrderOutcome,
    PaperAccountService,
    PendingOrderNotFoundError,
    StrategyDataUnavailableError,
)
from quant_system.execution.account_snapshot import (
    PaperAccountSnapshotReader,
    PaperAccountSnapshotReadError,
    materialize_account_view,
    resolve_account_quotes,
)
from quant_system.execution.paper_strategy_execution_service import (
    PaperStrategyExecutionService,
)
from quant_system.execution.paper_strategy_operations import (
    PaperStrategyOperationsRunner,
    PaperStrategyOpsObserver,
)
from quant_system.execution.paper_strategy_signal_service import (
    PaperStrategySignalService,
    StrategySignalGenerationError,
)
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    CashAllocationError,
    PaperStrategySleeveService,
    StrategyConfig,
    StrategyExecutionPlanError,
    StrategySleeveMode,
)
from quant_system.execution.pipeline import run_paper_trading
from quant_system.execution.price_source import (
    PricedQuote,
    PriceUnavailableError,
)
from quant_system.storage.runs_repository import list_run_metadatas, persist_run
from quant_system.strategies.registry import build_default_strategy_registry
from quant_system.trading_kernel import roll_position_on_fill

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


def _account_repository(api_runs_dir, settings) -> PaperAccountRepository:
    return build_paper_account_repository(
        api_runs_dir,
        settings=settings,
    )


class PaperAccountDatabaseUnavailable(RuntimeError):
    def __init__(
        self,
        message: str = (
            "Paper account database is unavailable; mutations are disabled in canonical mode."
        ),
    ) -> None:
        super().__init__(message)
        self.code = "paper_account_database_unavailable"


def _map_repository_runtime_error(
    exc: Exception,
) -> PaperAccountDatabaseUnavailable | None:
    """Map repository DB outage RuntimeErrors to the stable fail-closed exception."""
    if isinstance(exc, PaperAccountDatabaseUnavailable):
        return exc
    if not isinstance(exc, RuntimeError):
        return None
    text = str(exc).lower()
    if "paper account" not in text:
        return None
    if "unavailable" in text or "mirror write skipped" in text or "not configured" in text:
        return PaperAccountDatabaseUnavailable(
            "Paper account database is unavailable; mutations are disabled in canonical mode."
        )
    return None


def _ensure_account_mutable(
    repository: PaperAccountRepository,
    settings,
) -> None:
    if settings.paper_account.db_mode != "canonical":
        return
    if getattr(repository, "available_for_mutation", lambda: True)():
        return
    raise PaperAccountDatabaseUnavailable(
        "Paper account database is unavailable; mutations are disabled in canonical mode."
    )


def _http_account_db_unavailable(
    exc: PaperAccountDatabaseUnavailable,
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=_error_detail(exc.code, str(exc)),
    )


def _http_account_bootstrap_required(
    exc: PaperAccountBootstrapRequired,
) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail=_error_detail(exc.code, str(exc)),
    )


def _http_account_storage_corrupt(
    exc: PaperAccountStorageCorrupt,
) -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=_error_detail(exc.code, str(exc)),
    )


@contextmanager
def _canonical_mutation_guard(settings):
    """Map repository DB RuntimeErrors to HTTP 503 in canonical mode."""
    try:
        yield
    except HTTPException:
        raise
    except PaperAccountStorageCorrupt as exc:
        raise _http_account_storage_corrupt(exc) from exc
    except PaperAccountBootstrapRequired as exc:
        raise _http_account_bootstrap_required(exc) from exc
    except PaperAccountDatabaseUnavailable as exc:
        raise _http_account_db_unavailable(exc) from exc
    except Exception as exc:  # noqa: BLE001
        if settings.paper_account.db_mode == "canonical":
            _reraise_account_db_http(exc)
        raise


def _with_canonical_db_errors(settings, fn, *args, **kwargs):
    with _canonical_mutation_guard(settings):
        return fn(*args, **kwargs)


def _fail_closed_canonical(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        settings = kwargs.get("settings")
        if settings is None:
            for value in list(args) + list(kwargs.values()):
                if hasattr(value, "paper_account"):
                    settings = value
                    break
        try:
            return handler(*args, **kwargs)
        except HTTPException:
            raise
        except PaperAccountStorageCorrupt as exc:
            raise _http_account_storage_corrupt(exc) from exc
        except PaperAccountBootstrapRequired as exc:
            raise _http_account_bootstrap_required(exc) from exc
        except PaperAccountDatabaseUnavailable as exc:
            raise _http_account_db_unavailable(exc) from exc
        except Exception as exc:  # noqa: BLE001
            if (
                settings is not None
                and getattr(settings, "paper_account", None) is not None
                and settings.paper_account.db_mode == "canonical"
            ):
                _reraise_account_db_http(exc)
            raise

    return wrapped


def _reraise_account_db_http(exc: Exception) -> None:
    """Re-raise mapped paper-account DB failures as HTTP 503."""
    if isinstance(exc, PaperAccountStorageCorrupt):
        raise _http_account_storage_corrupt(exc) from exc
    if isinstance(exc, PaperAccountBootstrapRequired):
        raise _http_account_bootstrap_required(exc) from exc
    if isinstance(exc, PaperAccountDatabaseUnavailable):
        raise _http_account_db_unavailable(exc) from exc
    mapped = _map_repository_runtime_error(exc)
    if mapped is not None:
        raise _http_account_db_unavailable(mapped) from exc


def _load_or_open_account(
    storage: PaperAccountRepository,
    *,
    settings,
) -> PaperAccount:
    try:
        with _account_lock(storage.account_id), storage.mutation_lock():
            return storage.load_or_open(initial_cash=DEFAULT_INITIAL_CASH)
    except Exception as exc:  # noqa: BLE001 - map canonical DB failures only
        if settings.paper_account.db_mode == "canonical":
            _reraise_account_db_http(exc)
        raise


def _strategy_sleeve_storage(api_runs_dir) -> PaperStrategySleeveStorage:
    return PaperStrategySleeveStorage(api_runs_dir)


def _load_account_mapped(
    storage: PaperAccountRepository,
    *,
    settings,
) -> PaperAccount | None:
    try:
        return storage.load()
    except Exception as exc:  # noqa: BLE001
        if settings.paper_account.db_mode == "canonical":
            _reraise_account_db_http(exc)
        raise


def _account_snapshot_or_default(account_storage: PaperAccountRepository) -> PaperAccount:
    account = account_storage.load()
    if account is not None:
        return account
    return PaperAccount.open_new(
        account_id=account_storage.account_id,
        initial_cash=DEFAULT_INITIAL_CASH,
    )


def _reconcile_pending_strategy_sleeves(
    *,
    account_storage: PaperAccountRepository,
    sleeve_storage: PaperStrategySleeveStorage,
    settings=None,
    require_account_write: bool = False,
) -> None:
    try:
        account = account_storage.load()
    except RuntimeError as exc:
        mapped = _map_repository_runtime_error(exc)
        if mapped is None:
            raise
        if require_account_write or (
            settings is not None and settings.paper_account.db_mode == "canonical"
        ):
            if require_account_write:
                raise mapped from exc
            # Read/status paths: skip recovery writes when DB is down.
            return
        raise

    sleeve_storage.reconcile_pending_sleeves(account)
    if account is None:
        return
    service = PaperStrategyExecutionService(
        storage=sleeve_storage,
        price_source=None,
    )
    recovered = service.reconcile_execution_journals(account, commit=False)
    if not recovered:
        return

    can_write = True
    if settings is not None and settings.paper_account.db_mode == "canonical":
        can_write = bool(getattr(account_storage, "available_for_mutation", lambda: True)())
    if not can_write:
        if require_account_write:
            raise PaperAccountDatabaseUnavailable(
                "Paper account database is unavailable; mutations are disabled in canonical mode."
            )
        return

    try:
        account_storage.save(account)
    except RuntimeError as exc:
        mapped = _map_repository_runtime_error(exc)
        if mapped is None:
            raise
        if require_account_write:
            raise mapped from exc
        return
    for execution in recovered:
        service.commit_execution_journal(execution)


def _account_quotes(account: PaperAccount, *, settings) -> dict[str, PricedQuote]:
    return resolve_account_quotes(account, settings=settings)


def _parse_timestamp(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


_EQUITY_CURVE_FILL_KINDS = {"fill", "rebalance_fill", "sleeve_execution_fill"}


def _price_source_from_quotes(quotes: dict[str, PricedQuote]) -> dict[str, str | None]:
    price_kinds = {quote.price_kind for quote in quotes.values()}
    price_kind = (
        next(iter(price_kinds)) if len(price_kinds) == 1 else ("mixed" if price_kinds else "none")
    )
    as_of = next(iter(quotes.values())).as_of if len(quotes) == 1 else None
    return {"kind": price_kind, "as_of": as_of}


def _replay_account_equity_curve(
    account: PaperAccount,
    *,
    settings,
) -> list[dict]:
    cash = 0.0
    realized_pnl = 0.0
    positions: dict[str, AccountPosition] = {}
    mark_prices: dict[str, float] = {}
    points: list[dict] = []

    for entry in account.ledger:
        if entry.kind == "reset":
            positions = {}
            mark_prices = {}
            realized_pnl = 0.0

        if (
            entry.kind in _EQUITY_CURVE_FILL_KINDS
            and entry.symbol
            and entry.side
            and entry.quantity is not None
            and entry.price is not None
        ):
            symbol = entry.symbol.upper()
            position = positions.get(symbol, AccountPosition(symbol=symbol))
            quantity = float(entry.quantity)
            price = float(entry.price)
            gross_value = (
                float(entry.gross_value) if entry.gross_value is not None else quantity * price
            )
            new_quantity, new_avg_cost, realized_delta, _ = roll_position_on_fill(
                side=entry.side,
                position_quantity=position.quantity,
                position_avg_cost=position.avg_cost,
                fill_quantity=quantity,
                fill_price=price,
                gross_value=gross_value,
                commission=float(entry.commission or 0.0),
            )
            realized_pnl += realized_delta
            position.quantity = new_quantity
            position.avg_cost = new_avg_cost
            mark_prices[symbol] = price
            if abs(position.quantity) < 1e-9:
                positions.pop(symbol, None)
                mark_prices.pop(symbol, None)
            else:
                positions[symbol] = position
        else:
            realized_pnl += float(entry.realized_pnl_delta or 0.0)

        cash = float(entry.cash_after)
        market_value = sum(
            position.market_value(mark_prices.get(symbol, position.avg_cost))
            for symbol, position in positions.items()
        )
        points.append(
            {
                "timestamp": entry.timestamp,
                "equity": cash + market_value,
                "cash": cash,
                "market_value": market_value,
                "realized_pnl": realized_pnl,
                "source": "ledger",
                "event_id": entry.entry_id,
                "event_kind": entry.kind,
                "symbol": entry.symbol,
                "side": entry.side,
                "quantity": entry.quantity,
                "price": entry.price,
                "price_source": {
                    "kind": entry.price_kind or "ledger",
                    "as_of": entry.timestamp,
                },
            }
        )

    quotes = _account_quotes(account, settings=settings)
    prices = {symbol: quote.price for symbol, quote in quotes.items()}
    current_price_source = _price_source_from_quotes(quotes)
    current_market_value = account.market_value(prices)
    points.append(
        {
            "timestamp": current_price_source["as_of"] or datetime.now(UTC).isoformat(),
            "equity": account.cash + current_market_value,
            "cash": account.cash,
            "market_value": current_market_value,
            "realized_pnl": account.realized_pnl,
            "source": "current_quote",
            "event_id": None,
            "event_kind": "current",
            "symbol": None,
            "side": None,
            "quantity": None,
            "price": None,
            "price_source": current_price_source,
        }
    )
    return points


def _filter_recent_equity_points(points: list[dict], *, days: int) -> list[dict]:
    if days <= 0:
        return points
    cutoff = datetime.now(UTC) - timedelta(days=days)
    filtered: list[dict] = []
    for point in points:
        if point.get("source") == "current_quote":
            filtered.append(point)
            continue
        timestamp = point.get("timestamp")
        if not isinstance(timestamp, str):
            continue
        parsed = _parse_timestamp(timestamp)
        if parsed is None or parsed >= cutoff:
            filtered.append(point)
    return filtered


def _account_equity_curve_view(
    account: PaperAccount | None,
    *,
    settings,
    days: int,
    limit: int,
    offset: int,
) -> dict:
    if account is None:
        return {
            "account_id": "default",
            "account_exists": False,
            "total": 0,
            "limit": limit,
            "offset": max(offset, 0),
            "points": [],
        }

    points = _filter_recent_equity_points(
        _replay_account_equity_curve(account, settings=settings),
        days=days,
    )
    return {
        "account_id": account.account_id,
        "account_exists": True,
        "total": len(points),
        "limit": limit,
        "offset": max(offset, 0),
        "points": _window_rows(points, limit=limit, offset=offset),
    }


def _normalized_strategy_config_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def _strategy_config_name_conflict(
    storage: PaperStrategySleeveStorage,
    name: str,
    *,
    exclude_strategy_config_id: str | None = None,
) -> StrategyConfig | None:
    normalized_name = _normalized_strategy_config_name(name)
    if not normalized_name:
        return None
    for config in storage.list_strategy_configs():
        if config.archived:
            continue
        if exclude_strategy_config_id and config.strategy_config_id == exclude_strategy_config_id:
            continue
        if _normalized_strategy_config_name(config.name) == normalized_name:
            return config
    return None


def _save_account(
    storage: PaperAccountRepository,
    account: PaperAccount,
    quotes: dict[str, PricedQuote],
    *,
    settings=None,
) -> None:
    try:
        storage.save(
            account,
            prices={symbol: quote.price for symbol, quote in quotes.items()},
            price_metadata={
                symbol: {"kind": quote.price_kind, "as_of": quote.as_of}
                for symbol, quote in quotes.items()
            },
        )
    except Exception as exc:  # noqa: BLE001 - map canonical DB failures only
        if settings is not None and settings.paper_account.db_mode == "canonical":
            mapped = _map_repository_runtime_error(exc)
            if mapped is not None:
                raise mapped from exc
        raise


def _has_strategy_sleeve_positions(
    account: PaperAccount,
    *,
    sleeve_ids: set[str],
) -> bool:
    sleeve_sources = {f"strategy:{sleeve_id}" for sleeve_id in sleeve_ids}
    for position in account.positions.values():
        for source, quantity in position.source_quantity.items():
            if source in sleeve_sources and quantity > 1e-9:
                return True
    return False


def _account_view(
    account: PaperAccount,
    *,
    settings,
    quotes: dict[str, PricedQuote] | None = None,
    repository: PaperAccountRepository | None = None,
) -> dict:
    return materialize_account_view(
        account,
        settings=settings,
        quotes=quotes,
        repository=repository,
    )


_ORDER_HISTORY_KINDS = {"fill", "rebalance_fill", "sleeve_execution_fill", "order_cancelled"}


def _window_rows(rows: list[dict], *, limit: int, offset: int) -> list[dict]:
    safe_offset = max(offset, 0)
    safe_limit = max(limit, 0)
    return rows[safe_offset : safe_offset + safe_limit]


def _entry_order_id(entry: dict) -> str | None:
    note = entry.get("note")
    if not isinstance(note, str) or not note:
        return None
    return note.split(":", 1)[0].strip() or None


def _entry_order_status(entry: dict) -> str:
    kind = entry.get("kind")
    if kind == "order_cancelled":
        return "cancelled"
    if kind in {"fill", "rebalance_fill", "sleeve_execution_fill"}:
        return "filled"
    return str(kind or "event")


def _account_activity_view(
    account: PaperAccount,
    *,
    settings,
    limit: int,
    offset: int,
    repository: PaperAccountRepository | None = None,
) -> dict:
    quotes = _account_quotes(account, settings=settings)
    account_view = _account_view(
        account,
        settings=settings,
        quotes=quotes,
        repository=repository,
    )
    chronological = [entry.model_dump(mode="json") for entry in account.ledger]
    newest_first = list(reversed(chronological))

    order_history = [
        {
            "event_id": entry["entry_id"],
            "order_id": _entry_order_id(entry),
            "timestamp": entry["timestamp"],
            "status": _entry_order_status(entry),
            "kind": entry["kind"],
            "source": entry["source"],
            "symbol": entry.get("symbol"),
            "side": entry.get("side"),
            "quantity": entry.get("quantity"),
            "price": entry.get("price"),
            "gross_value": entry.get("gross_value"),
            "commission": entry.get("commission", 0.0),
            "price_kind": entry.get("price_kind"),
            "realized_pnl_delta": entry.get("realized_pnl_delta", 0.0),
            "cash_after": entry.get("cash_after"),
            "note": entry.get("note"),
        }
        for entry in newest_first
        if entry.get("kind") in _ORDER_HISTORY_KINDS
    ]

    balance_history_chronological = []
    previous_cash: float | None = None
    for entry in chronological:
        cash_after = entry.get("cash_after")
        if cash_after is None:
            continue
        cash_after = float(cash_after)
        cash_delta = 0.0 if previous_cash is None else cash_after - previous_cash
        balance_history_chronological.append(
            {
                "event_id": entry["entry_id"],
                "timestamp": entry["timestamp"],
                "kind": entry["kind"],
                "source": entry["source"],
                "cash_after": cash_after,
                "cash_delta": cash_delta,
                "note": entry.get("note"),
            }
        )
        previous_cash = cash_after
    balance_history = list(reversed(balance_history_chronological))

    return {
        "account": account_view,
        "pending_orders": account_view["pending_orders"],
        "order_history": _window_rows(order_history, limit=limit, offset=offset),
        "balance_history": _window_rows(balance_history, limit=limit, offset=offset),
        "trade_log": _window_rows(newest_first, limit=limit, offset=offset),
        "pending_order_total": len(account_view["pending_orders"]),
        "order_history_total": len(order_history),
        "balance_history_total": len(balance_history),
        "trade_log_total": len(newest_first),
        "limit": limit,
        "offset": max(offset, 0),
    }


def _process_pending_account_orders(
    api_runs_dir,
    settings,
    *,
    open_if_missing: bool,
    quote_when_idle: bool,
) -> tuple[list[OrderOutcome], PaperAccount | None, dict[str, PricedQuote]]:
    storage = _account_repository(api_runs_dir, settings)
    _ensure_account_mutable(storage, settings)
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
            quotes = _account_quotes(account, settings=settings) if quote_when_idle else {}
            return [], account, quotes
        outcomes = service.process_pending_orders(account)
        quotes = _account_quotes(account, settings=settings)
        _save_account(storage, account, quotes, settings=settings)
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
    storage = _account_repository(api_runs_dir, settings)
    account = _load_or_open_account(storage, settings=settings)
    return _account_view(account, settings=settings, repository=storage)


@router.get(
    "/paper/account/snapshot",
    response_model=PaperAccountSnapshotResponse,
    responses={
        409: {"description": "Canonical paper account requires explicit bootstrap."},
        503: {"description": ("Paper account storage or canonical database is unavailable.")},
    },
)
def get_account_snapshot(api_runs_dir: ApiRunsDirDep, settings: SettingsDep) -> dict:
    storage = _account_repository(api_runs_dir, settings)
    try:
        return (
            PaperAccountSnapshotReader(
                repository=storage,
                settings=settings,
            )
            .read()
            .to_dict()
        )
    except PaperAccountBootstrapRequired as exc:
        raise _http_account_bootstrap_required(exc) from exc
    except PaperAccountSnapshotReadError as exc:
        raise HTTPException(
            status_code=503,
            detail=_error_detail(exc.code, str(exc)),
        ) from exc


@router.get("/paper/account/equity-curve", response_model=PaperAccountEquityCurveResponse)
def get_account_equity_curve(
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
    days: int = 7,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    storage = _account_repository(api_runs_dir, settings)
    account = _load_account_mapped(storage, settings=settings)
    return _account_equity_curve_view(
        account,
        settings=settings,
        days=days,
        limit=max(limit, 0),
        offset=max(offset, 0),
    )


@router.get(
    "/paper/account/performance",
    response_model=PaperAccountPerformanceResponse,
)
def get_account_performance(
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
    range_key: Annotated[
        Literal["7d", "1m", "3m"],
        Query(alias="range"),
    ] = "7d",
    granularity: Literal["1d"] = "1d",
    benchmarks: str = "SPY,QQQ",
) -> dict:
    del granularity
    requested_benchmarks = [
        symbol.upper().strip()
        for symbol in benchmarks.split(",")
        if symbol.strip()
    ]
    try:
        return build_account_performance(
            account=_load_account_mapped(
                _account_repository(api_runs_dir, settings),
                settings=settings,
            ),
            settings=settings,
            cache_path=api_runs_dir / "_cache" / "futu_equity_bars.duckdb",
            range_key=range_key,
            benchmarks=requested_benchmarks,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=_error_detail("invalid_performance_request", str(exc)),
        ) from exc


@router.post("/paper/account/reset", response_model=PaperAccountResponse)
@_fail_closed_canonical
def reset_account(
    request: AccountResetRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    storage = _account_repository(api_runs_dir, settings)
    try:
        _ensure_account_mutable(storage, settings)
    except PaperAccountDatabaseUnavailable as exc:
        raise _http_account_db_unavailable(exc) from exc
    with _account_lock(storage.account_id), storage.mutation_lock():
        account = storage.reset(initial_cash=request.initial_cash)
        return _account_view(account, settings=settings, repository=storage)


@router.post("/paper/account/kill-switch", response_model=PaperAccountResponse)
@_fail_closed_canonical
def set_account_kill_switch(
    request: KillSwitchRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    storage = _account_repository(api_runs_dir, settings)
    try:
        _ensure_account_mutable(storage, settings)
    except PaperAccountDatabaseUnavailable as exc:
        raise _http_account_db_unavailable(exc) from exc
    with _account_lock(storage.account_id), storage.mutation_lock():
        account = storage.load_or_open(initial_cash=DEFAULT_INITIAL_CASH)
        account.kill_switch = request.enabled
        account.record_event(
            kind="freeze" if request.enabled else "unfreeze",
            note=f"account kill switch set to {request.enabled}",
        )
        quotes = _account_quotes(account, settings=settings)
        _save_account(storage, account, quotes, settings=settings)
        return _account_view(account, settings=settings, quotes=quotes, repository=storage)


@router.get("/paper/account/ledger", response_model=PaperLedgerResponse)
def get_account_ledger(
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    storage = _account_repository(api_runs_dir, settings)
    account = _load_or_open_account(storage, settings=settings)
    entries = [entry.model_dump(mode="json") for entry in account.ledger]
    entries.reverse()  # newest first
    window = entries[offset : offset + max(limit, 0)]
    return {"total": len(entries), "limit": limit, "offset": offset, "entries": window}


@router.get("/paper/account/activity", response_model=PaperAccountActivityResponse)
def get_account_activity(
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
    limit: int = 200,
    offset: int = 0,
) -> dict:
    storage = _account_repository(api_runs_dir, settings)
    account = _load_or_open_account(storage, settings=settings)
    return _account_activity_view(
        account,
        settings=settings,
        limit=limit,
        offset=offset,
        repository=storage,
    )


@router.post("/paper/account/orders", response_model=PaperAccountOrderResponse)
@_fail_closed_canonical
def place_account_order(
    request: ManualOrderRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    storage = _account_repository(api_runs_dir, settings)
    try:
        _ensure_account_mutable(storage, settings)
    except PaperAccountDatabaseUnavailable as exc:
        raise _http_account_db_unavailable(exc) from exc
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
        _save_account(storage, account, quotes, settings=settings)
        return {
            "order": _order_outcome_view(outcome),
            "account": _account_view(account, settings=settings, quotes=quotes, repository=storage),
        }


@router.post(
    "/paper/account/orders/process",
    response_model=PaperAccountOrdersProcessResponse,
)
@_fail_closed_canonical
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
    except PaperAccountDatabaseUnavailable as exc:
        raise _http_account_db_unavailable(exc) from exc
    except RuntimeError as exc:
        _reraise_account_db_http(exc)
        raise
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
    storage = _account_repository(api_runs_dir, settings)
    return {
        "orders": [_order_outcome_view(outcome) for outcome in outcomes],
        "account": _account_view(account, settings=settings, quotes=quotes, repository=storage),
    }


@router.post(
    "/paper/account/orders/{order_id}/cancel",
    response_model=PaperAccountOrderResponse,
)
@_fail_closed_canonical
def cancel_pending_account_order(
    order_id: str,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    storage = _account_repository(api_runs_dir, settings)
    try:
        _ensure_account_mutable(storage, settings)
    except PaperAccountDatabaseUnavailable as exc:
        raise _http_account_db_unavailable(exc) from exc
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
        _save_account(storage, account, quotes, settings=settings)
        return {
            "order": _order_outcome_view(outcome),
            "account": _account_view(account, settings=settings, quotes=quotes, repository=storage),
        }


@router.post(
    "/paper/account/rebalance",
    response_model=PaperAccountRebalanceResponse,
)
@_fail_closed_canonical
def rebalance_account(
    request: AccountRebalanceRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    strategy_id = _account_rebalance_strategy_id(request.strategy_id)
    storage = _account_repository(api_runs_dir, settings)
    try:
        _ensure_account_mutable(storage, settings)
    except PaperAccountDatabaseUnavailable as exc:
        raise _http_account_db_unavailable(exc) from exc
    sleeve_storage = _strategy_sleeve_storage(api_runs_dir)
    service = PaperAccountService(settings=settings)
    with (
        _account_lock(storage.account_id),
        storage.mutation_lock(),
        sleeve_storage.mutation_lock(),
    ):
        account = storage.load_or_open(initial_cash=DEFAULT_INITIAL_CASH)
        sleeve_storage.reconcile_pending_sleeves(account)
        sleeve_ids = {sleeve.sleeve_id for sleeve in sleeve_storage.list_sleeves()}
        if _has_strategy_sleeve_positions(account, sleeve_ids=sleeve_ids):
            raise HTTPException(
                status_code=409,
                detail=_error_detail(
                    "strategy_sleeve_positions_present",
                    (
                        "full-account rebalance is disabled while strategy sleeve "
                        "positions exist; use the strategy sleeve execution panel"
                    ),
                ),
            )
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
        _save_account(storage, account, quotes, settings=settings)
        return {
            "rebalance": {
                "strategy_id": outcome.strategy_id,
                "as_of": outcome.as_of,
                "aborted": outcome.aborted,
                "target_weights": outcome.target_weights,
                "note": outcome.note,
                "orders": [_order_outcome_view(order) for order in outcome.orders],
            },
            "account": _account_view(account, settings=settings, quotes=quotes, repository=storage),
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
        existing = _strategy_config_name_conflict(storage, request.name)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=_error_detail(
                    "strategy_config_name_conflict",
                    f"strategy config name already exists: {existing.name}",
                ),
            )
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
        "configs": [config.model_dump(mode="json") for config in storage.list_strategy_configs()]
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
        existing = _strategy_config_name_conflict(
            storage,
            config.name,
            exclude_strategy_config_id=strategy_config_id,
        )
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=_error_detail(
                    "strategy_config_name_conflict",
                    f"strategy config name already exists: {existing.name}",
                ),
            )
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
@_fail_closed_canonical
def create_strategy_sleeve(
    request: StrategySleeveCreateRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    account_storage = _account_repository(api_runs_dir, settings)
    try:
        _ensure_account_mutable(account_storage, settings)
    except PaperAccountDatabaseUnavailable as exc:
        raise _http_account_db_unavailable(exc) from exc
    sleeve_storage = _strategy_sleeve_storage(api_runs_dir)
    service = PaperStrategySleeveService(sleeve_storage)
    with (
        _account_lock(account_storage.account_id),
        account_storage.mutation_lock(),
        sleeve_storage.mutation_lock(),
    ):
        _reconcile_pending_strategy_sleeves(
            account_storage=account_storage,
            sleeve_storage=sleeve_storage,
            settings=settings,
        )
        account = account_storage.load_or_open(initial_cash=DEFAULT_INITIAL_CASH)
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
        if sleeve.mode == StrategySleeveMode.ALLOCATED:
            try:
                sleeve_storage.save_pending_sleeve(sleeve)
                _save_account(account_storage, account, quotes, settings=settings)
            except (OSError, ValueError) as exc:
                sleeve_storage.discard_pending_sleeve(sleeve.sleeve_id)
                raise HTTPException(
                    status_code=500,
                    detail=_error_detail(
                        "strategy_sleeve_storage_error",
                        "failed to persist strategy sleeve allocation",
                    ),
                ) from exc
            try:
                sleeve_storage.finalize_pending_sleeve(sleeve.sleeve_id)
            except (OSError, ValueError) as exc:
                raise HTTPException(
                    status_code=500,
                    detail=_error_detail(
                        "strategy_sleeve_storage_pending",
                        (
                            "strategy sleeve allocation was saved to the account; "
                            "run 'paper strategies recover-pending' or wait for "
                            "the next explicit strategy mutation"
                        ),
                    ),
                ) from exc
        else:
            try:
                sleeve_storage.save_sleeve(sleeve)
                _save_account(account_storage, account, quotes, settings=settings)
            except (OSError, ValueError) as exc:
                raise HTTPException(
                    status_code=500,
                    detail=_error_detail(
                        "strategy_sleeve_storage_error",
                        "failed to persist strategy sleeve",
                    ),
                ) from exc
        return {
            "sleeve": sleeve.model_dump(mode="json"),
            "account": _account_view(
                account,
                settings=settings,
                quotes=quotes,
                repository=account_storage,
            ),
        }


@router.get(
    "/paper/strategy-sleeves",
    response_model=StrategySleevesResponse,
)
def list_strategy_sleeves(api_runs_dir: ApiRunsDirDep) -> dict:
    storage = _strategy_sleeve_storage(api_runs_dir)
    sleeves = storage.list_sleeves()
    return {"sleeves": [sleeve.model_dump(mode="json") for sleeve in sleeves]}


@router.get(
    "/paper/strategy-sleeves/ops/status",
    response_model=StrategyOpsStatusResponse,
)
def get_strategy_sleeve_ops_status(
    api_runs_dir: ApiRunsDirDep,
    target_date: date | None = None,
    execution_window: Literal["next_open"] = "next_open",
) -> dict:
    sleeve_storage = _strategy_sleeve_storage(api_runs_dir)
    status = PaperStrategyOpsObserver(
        sleeve_storage=sleeve_storage,
    ).observe(
        target_date=target_date,
        execution_window=execution_window,
    )
    return {"status": status.to_dict()}


@router.get(
    "/paper/strategy-sleeves/{sleeve_id}",
    response_model=StrategySleeveDetailResponse,
)
def get_strategy_sleeve(
    sleeve_id: str,
    api_runs_dir: ApiRunsDirDep,
) -> dict:
    storage = _strategy_sleeve_storage(api_runs_dir)
    try:
        sleeve = storage.load_sleeve(sleeve_id)
    except FileNotFoundError as exc:
        raise not_found_404("strategy_sleeve", sleeve_id) from exc
    lots = storage.load_sleeve_lots(sleeve_id)
    signals = storage.load_signals(sleeve_id)
    executions = storage.load_executions(sleeve_id)
    return {
        "sleeve": sleeve.model_dump(mode="json"),
        "lots": [lot.model_dump(mode="json") for lot in lots],
        "signals": [signal.model_dump(mode="json") for signal in signals],
        "executions": [execution.model_dump(mode="json") for execution in executions],
    }


@router.post(
    "/paper/strategy-sleeves/{sleeve_id}/executions",
    response_model=StrategyExecutionMutationResponse,
)
def create_strategy_sleeve_execution(
    sleeve_id: str,
    request: StrategyExecutionCreateRequest,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
) -> dict:
    account_storage = _account_repository(api_runs_dir, settings)
    sleeve_storage = _strategy_sleeve_storage(api_runs_dir)
    service = PaperStrategySleeveService(sleeve_storage)
    with (
        _account_lock(account_storage.account_id),
        account_storage.mutation_lock(),
        sleeve_storage.mutation_lock(),
    ):
        _reconcile_pending_strategy_sleeves(
            account_storage=account_storage,
            sleeve_storage=sleeve_storage,
            settings=settings,
        )
        account = _account_snapshot_or_default(account_storage)
        try:
            sleeve = sleeve_storage.load_sleeve(sleeve_id)
        except FileNotFoundError as exc:
            raise not_found_404("strategy_sleeve", sleeve_id) from exc
        signal = next(
            (
                item
                for item in sleeve_storage.load_signals(sleeve_id)
                if item.signal_id == request.signal_id
            ),
            None,
        )
        if signal is None:
            raise not_found_404("strategy_signal", request.signal_id)
        try:
            execution = service.create_execution_plan(
                account,
                sleeve=sleeve,
                signal=signal,
                execution_window=request.execution_window,
                target_date=request.target_date,
                metadata=request.metadata,
            )
        except StrategyExecutionPlanError as exc:
            raise HTTPException(
                status_code=409,
                detail=_error_detail(exc.code, str(exc)),
            ) from exc
    return {"execution": execution.model_dump(mode="json")}


@router.post(
    "/paper/strategy-sleeves/executions/process",
    response_model=StrategyExecutionProcessResponse,
)
@_fail_closed_canonical
def process_strategy_sleeve_executions(
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
    request: StrategyExecutionProcessRequest | None = None,
) -> dict:
    payload = request or StrategyExecutionProcessRequest()
    account_storage = _account_repository(api_runs_dir, settings)
    try:
        _ensure_account_mutable(account_storage, settings)
    except PaperAccountDatabaseUnavailable as exc:
        raise _http_account_db_unavailable(exc) from exc
    sleeve_storage = _strategy_sleeve_storage(api_runs_dir)
    runner = PaperStrategyOperationsRunner(
        account_storage=account_storage,
        sleeve_storage=sleeve_storage,
        settings=settings,
    )
    with _account_lock(account_storage.account_id):
        try:
            result = runner.process_pending_executions_once(
                sleeve_id=payload.sleeve_id,
                execution_window=payload.execution_window,
                target_date=payload.target_date,
                limit=payload.limit,
            )
        except FileNotFoundError as exc:
            raise not_found_404("strategy_sleeve", payload.sleeve_id or "") from exc
        account = result.account or _account_snapshot_or_default(account_storage)
        quotes = _account_quotes(account, settings=settings)
        account_view = _account_view(
            account,
            settings=settings,
            quotes=quotes,
            repository=account_storage,
        )
    return {
        "processed_count": result.processed_count,
        "filled_count": result.filled_count,
        "blocked_count": result.blocked_count,
        "executions": [execution.model_dump(mode="json") for execution in result.executions],
        "account": account_view,
    }


@router.post(
    "/paper/strategy-sleeves/{sleeve_id}/signals",
    response_model=StrategySignalMutationResponse,
)
def generate_strategy_sleeve_signal(
    sleeve_id: str,
    api_runs_dir: ApiRunsDirDep,
    settings: SettingsDep,
    request: StrategySignalGenerateRequest | None = None,
) -> dict:
    payload = request or StrategySignalGenerateRequest()
    account_storage = _account_repository(api_runs_dir, settings)
    sleeve_storage = _strategy_sleeve_storage(api_runs_dir)
    service = PaperStrategySignalService(storage=sleeve_storage, settings=settings)
    with (
        _account_lock(account_storage.account_id),
        account_storage.mutation_lock(),
        sleeve_storage.mutation_lock(),
    ):
        _reconcile_pending_strategy_sleeves(
            account_storage=account_storage,
            sleeve_storage=sleeve_storage,
            settings=settings,
        )
        account = _account_snapshot_or_default(account_storage)
        try:
            sleeve = sleeve_storage.load_sleeve(sleeve_id)
            config = sleeve_storage.load_strategy_config(
                sleeve.strategy_config_id,
                version=sleeve.strategy_config_version,
            )
            signal = service.generate_daily_signal(
                sleeve=sleeve,
                config=config,
                account=account,
                signal_date=payload.signal_date,
                history_days=payload.history_days,
            )
        except FileNotFoundError as exc:
            raise not_found_404("strategy_sleeve", sleeve_id) from exc
        except StrategySignalGenerationError as exc:
            raise HTTPException(
                status_code=409,
                detail=_error_detail("strategy_sleeve_stopped", str(exc)),
            ) from exc
    return {"signal": signal.model_dump(mode="json")}


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
    account_storage = _account_repository(api_runs_dir, settings)
    sleeve_storage = _strategy_sleeve_storage(api_runs_dir)
    service = PaperStrategySleeveService(sleeve_storage)
    with (
        _account_lock(account_storage.account_id),
        account_storage.mutation_lock(),
        sleeve_storage.mutation_lock(),
    ):
        _reconcile_pending_strategy_sleeves(
            account_storage=account_storage,
            sleeve_storage=sleeve_storage,
            settings=settings,
        )
        account = _account_snapshot_or_default(account_storage)
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
            "account": _account_view(
                account,
                settings=settings,
                quotes=quotes,
                repository=account_storage,
            ),
        }


def _account_rebalance_strategy_id(strategy_id: str) -> str:
    normalized = strategy_id.strip() or "cross_sectional_top_n"
    registry = build_default_strategy_registry()
    try:
        metadata = registry.get(normalized)
    except KeyError as exc:
        supported = [
            item.id for item in registry.list_metadata() if item.supports_account_rebalance
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
