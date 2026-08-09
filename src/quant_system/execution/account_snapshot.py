from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

from quant_system.config.settings import Settings
from quant_system.execution.account import PaperAccount
from quant_system.execution.account_repository import (
    PaperAccountBootstrapRequired,
    PaperAccountRepository,
    PaperAccountStorageCorrupt,
)
from quant_system.execution.price_source import (
    PaperPriceSource,
    PricedQuote,
    PriceUnavailableError,
)


class PaperAccountSnapshotReadError(RuntimeError):
    """Stable, transport-agnostic failure for an observational account read."""

    def __init__(self, *, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class PaperAccountSnapshot:
    account_id: str
    account_exists: bool
    account: dict[str, Any] | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "account_exists": self.account_exists,
            "account": self.account,
        }


@dataclass(frozen=True)
class AccountObservedQuote:
    symbol: str
    price: float
    price_kind: str
    as_of: str
    source: str
    previous_close: float | None = None


class PaperAccountSnapshotReader:
    """Read the selected paper-account repository without mutating it."""

    def __init__(
        self,
        *,
        repository: PaperAccountRepository,
        settings: Settings,
        price_source: PaperPriceSource | None = None,
    ) -> None:
        self.repository = repository
        self.settings = settings
        self.price_source = price_source

    def read(self) -> PaperAccountSnapshot:
        try:
            account = self.repository.load()
        except PaperAccountStorageCorrupt as exc:
            raise PaperAccountSnapshotReadError(
                code=exc.code,
                message=str(exc),
            ) from exc
        except PaperAccountBootstrapRequired:
            raise
        except RuntimeError as exc:
            if self.settings.paper_account.db_mode == "canonical":
                raise PaperAccountSnapshotReadError(
                    code="paper_account_database_unavailable",
                    message=(
                        "Paper account database is unavailable; "
                        "snapshot reads are disabled in canonical mode."
                    ),
                ) from exc
            raise
        if account is None:
            warning = getattr(self.repository, "last_warning", None)
            if warning == "paper_account_storage_corrupt":
                raise PaperAccountSnapshotReadError(
                    code=warning,
                    message="Paper account storage is corrupt and has no valid backup.",
                )
            if self.settings.paper_account.db_mode == "canonical":
                raise PaperAccountBootstrapRequired(self.repository.account_id)
            return PaperAccountSnapshot(
                account_id=self.repository.account_id,
                account_exists=False,
                account=None,
            )
        return PaperAccountSnapshot(
            account_id=account.account_id,
            account_exists=True,
            account=materialize_account_view(
                account,
                settings=self.settings,
                repository=self.repository,
                quotes=resolve_account_quotes(
                    account,
                    settings=self.settings,
                    price_source=self.price_source,
                ),
            ),
        )


def resolve_account_quotes(
    account: PaperAccount,
    *,
    settings: Settings,
    price_source: PaperPriceSource | None = None,
) -> dict[str, PricedQuote | AccountObservedQuote]:
    """Resolve an observational quote or an explicit cost-basis fallback."""
    source = price_source or PaperPriceSource(settings)
    quotes: dict[str, PricedQuote | AccountObservedQuote] = {}
    for symbol, position in account.positions.items():
        quote: PricedQuote | AccountObservedQuote | None = None
        try:
            candidate = source.get_price(symbol)
            if isfinite(candidate.price) and candidate.price > 0:
                quote = candidate
        except (PriceUnavailableError, ValueError, TypeError):
            quote = None
        if quote is None:
            quote = PricedQuote(
                symbol=symbol,
                price=position.avg_cost,
                price_kind="avg_cost_fallback",
                as_of=account.updated_at,
                source="account",
            )
        quotes[symbol] = quote

    # Preserve the established PaperPriceSource seam first. Only real Futu
    # observations are replaced by one batch snapshot carrying both last and
    # previous-close values; injected/stub sources never trigger live OpenD.
    if price_source is None and any(
        quote.price_kind == "futu_snapshot" and quote.source == "futu"
        for quote in quotes.values()
    ):
        enriched = _resolve_futu_account_quotes(account, settings=settings)
        for symbol, quote in list(quotes.items()):
            if (
                quote.price_kind == "futu_snapshot"
                and quote.source == "futu"
                and symbol in enriched
            ):
                quotes[symbol] = enriched[symbol]
    return quotes


def _resolve_futu_account_quotes(
    account: PaperAccount,
    *,
    settings: Settings,
) -> dict[str, AccountObservedQuote]:
    """Batch current Futu observations so price and previous close share one snapshot."""
    if not account.positions or not getattr(settings.futu, "enabled", False):
        return {}
    try:
        from quant_system.data.providers.futu import (
            FutuMarketDataProvider,
            FutuProviderError,
        )

        provider = FutuMarketDataProvider(
            host=settings.futu.host,
            port=settings.futu.port,
            request_timeout_seconds=settings.futu.request_timeout_seconds,
        )
        futu_symbols = [
            FutuMarketDataProvider.normalize_symbol(symbol)[1]
            for symbol in account.positions
        ]
        frame = provider.fetch_market_snapshots(futu_symbols)
    except (FutuProviderError, ValueError, TypeError):
        return {}
    except Exception:  # noqa: BLE001 - observational Futu failures use the existing fallback
        return {}

    quotes: dict[str, AccountObservedQuote] = {}
    for row in frame.to_dict(orient="records"):
        raw_symbol = row.get("symbol")
        if not isinstance(raw_symbol, str):
            continue
        try:
            symbol, _futu_symbol = FutuMarketDataProvider.normalize_symbol(raw_symbol)
            price = float(row.get("last"))
        except (FutuProviderError, TypeError, ValueError):
            continue
        if not isfinite(price) or price <= 0:
            continue
        previous_close: float | None = None
        try:
            candidate_previous_close = float(row.get("prev_close"))
        except (TypeError, ValueError):
            candidate_previous_close = 0.0
        if isfinite(candidate_previous_close) and candidate_previous_close > 0:
            previous_close = candidate_previous_close
        raw_as_of = row.get("update_time")
        quotes[symbol] = AccountObservedQuote(
            symbol=symbol,
            price=price,
            price_kind="futu_snapshot",
            as_of=str(raw_as_of) if raw_as_of else account.updated_at,
            source="futu",
            previous_close=previous_close,
        )
    return quotes


def materialize_account_view(
    account: PaperAccount,
    *,
    settings: Settings,
    quotes: dict[str, PricedQuote | AccountObservedQuote] | None = None,
    repository: PaperAccountRepository | None = None,
) -> dict[str, Any]:
    """Build the canonical price-aware paper-account read model."""
    quotes = (
        quotes
        if quotes is not None
        else resolve_account_quotes(
            account,
            settings=settings,
        )
    )
    prices = {symbol: quote.price for symbol, quote in quotes.items()}
    price_kinds = {quote.price_kind for quote in quotes.values()}
    price_kind = (
        next(iter(price_kinds)) if len(price_kinds) == 1 else ("mixed" if price_kinds else "none")
    )
    as_of = next(iter(quotes.values())).as_of if len(quotes) == 1 else None

    equity = account.equity(prices)
    positions: list[dict[str, Any]] = []
    price_fallback_used = False
    for symbol, position in sorted(account.positions.items()):
        quote = quotes.get(symbol)
        last_price = quote.price if quote is not None else position.avg_cost
        position_price_kind = quote.price_kind if quote is not None else "avg_cost_fallback"
        previous_close = getattr(quote, "previous_close", None)
        if (
            previous_close is None
            or not isfinite(previous_close)
            or previous_close <= 0
            or not isfinite(last_price)
            or last_price <= 0
        ):
            previous_close = None
            day_change_ratio = None
            day_change_source = None
            day_change_as_of = None
        else:
            day_change_ratio = (last_price / previous_close) - 1.0
            day_change_source = position_price_kind
            day_change_as_of = quote.as_of if quote is not None else None
        if position_price_kind == "avg_cost_fallback":
            price_fallback_used = True
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
                "price_kind": position_price_kind,
                "price_as_of": quote.as_of if quote is not None else account.updated_at,
                "previous_close": previous_close,
                "day_change_ratio": day_change_ratio,
                "day_change_source": day_change_source,
                "day_change_as_of": day_change_as_of,
            }
        )

    pnl_abs = equity - account.initial_cash
    view: dict[str, Any] = {
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
        "pending_orders": [order.model_dump(mode="json") for order in account.pending_orders],
        "created_at": account.created_at,
        "updated_at": account.updated_at,
    }

    stale = False
    reconciliation = None
    if repository is not None:
        reconciliation_fn = getattr(repository, "reconciliation", None)
        if callable(reconciliation_fn):
            reconciliation = reconciliation_fn()
            stale = reconciliation.get("status") in {"different", "unavailable"}
        else:
            stale_fn = getattr(repository, "is_stale", None)
            if callable(stale_fn):
                stale = bool(stale_fn())

    warnings: list[str] = []
    if repository is not None:
        last_warning = getattr(repository, "last_warning", None)
        if isinstance(last_warning, str) and last_warning:
            warnings.append(last_warning)
    if reconciliation is not None:
        reconciliation_status = reconciliation.get("status")
        if reconciliation_status == "different":
            warnings.append("paper_account_repository_out_of_sync")
        elif reconciliation_status == "unavailable":
            warnings.append("paper_account_reconciliation_unavailable")
    if price_fallback_used:
        warnings.append("paper_account_price_unavailable")

    view["storage_mode"] = settings.paper_account.db_mode
    view["stale"] = stale
    view["warnings"] = list(dict.fromkeys(warnings))
    view["reconciliation"] = reconciliation
    return view
