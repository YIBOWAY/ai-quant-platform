"""V7g-A-M2: read-only Futu façade for Vertical A live bind.

Hard surface guarantee: this module only exposes quote/chain snapshot helpers.
It must never import or call order, account, position, or trade APIs.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Protocol

from quant_system.config.settings import Settings


class VerticalRoProviderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _QuoteProvider(Protocol):
    def fetch_option_quotes(
        self,
        underlying: str,
        *,
        expiration: str,
        option_type: str = "ALL",
    ) -> Any: ...

    def fetch_underlying_snapshot(self, symbol: str) -> dict[str, object]: ...


_ALLOWED_PUBLIC_METHODS = frozenset(
    {
        "fetch_option_quote_row",
        "provider_name",
    }
)


@dataclass(frozen=True)
class VerticalRoQuote:
    ticker: str
    expiry: str
    strike: float | int
    bid: float | int
    ask: float | int
    delta: float | int
    iv: float | int
    apr: float | int | None
    as_of: str
    provider_name: str
    request_id: str
    evidence: tuple[str, ...]
    raw_symbol: str | None = None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _dt_public(dt: datetime | None = None) -> str:
    value = dt or _utc_now()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _finite_number(value: object, field: str) -> float | int:
    if type(value) is bool or value is None:
        raise VerticalRoProviderError("provider_schema", f"{field} missing")
    if type(value) is int:
        return value
    if type(value) is float:
        if value != value or value in (float("inf"), float("-inf")):
            raise VerticalRoProviderError("provider_schema", f"{field} not finite")
        return value
    # pandas / numpy scalars
    try:
        as_float = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise VerticalRoProviderError(
            "provider_schema", f"{field} not numeric"
        ) from exc
    if as_float != as_float or as_float in (float("inf"), float("-inf")):
        raise VerticalRoProviderError("provider_schema", f"{field} not finite")
    if as_float.is_integer():
        return int(as_float)
    return as_float


def _days_to_expiry(expiry: str, *, as_of: datetime) -> int | None:
    try:
        exp = datetime.fromisoformat(expiry[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    day = as_of.astimezone(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return max(int((exp - day).days), 0)


def _apr_sell_put(
    *,
    bid: float | int,
    ask: float | int,
    strike: float | int,
    expiry: str,
    as_of: datetime,
) -> float | None:
    mid = (float(bid) + float(ask)) / 2.0
    base = float(strike)
    if base <= 0 or mid <= 0:
        return None
    dte = _days_to_expiry(expiry, as_of=as_of)
    if dte is None or dte <= 0:
        return None
    return round((mid / base) * (365.0 / dte), 6)


def _pick_put_row(frame: Any, *, strike: float | int) -> dict[str, object] | None:
    if frame is None:
        return None
    try:
        empty = bool(getattr(frame, "empty", True))
    except Exception:
        return None
    if empty:
        return None
    try:
        work = frame.copy()
    except Exception:
        return None
    if "option_type" in work.columns:
        ot = work["option_type"].astype(str).str.upper()
        puts = work[ot.str.contains("PUT", na=False)]
        if not puts.empty:
            work = puts
    if "strike" not in work.columns:
        return None
    try:
        strikes = work["strike"].astype(float)
        target = float(strike)
        idx = (strikes - target).abs().idxmin()
        row = work.loc[idx]
    except Exception:
        try:
            row = work.iloc[0]
        except Exception:
            return None
    return {str(k): row[k] for k in row.index}


class FutuReadOnlyOptionsFacade:
    """RO-only options quote façade.

    Public surface is intentionally tiny. Trade/account methods are not
    delegated even if the underlying provider object has them.
    """

    provider_name = "futu_ro"

    def __init__(
        self,
        inner: _QuoteProvider,
        *,
        provider_label: str = "futu",
    ) -> None:
        self._inner = inner
        self._provider_label = provider_label

    def fetch_option_quote_row(
        self,
        *,
        ticker: str,
        expiry: str,
        strike: float | int,
        option_type: str = "PUT",
    ) -> VerticalRoQuote:
        tkr = ticker.strip().upper()
        exp = expiry.strip()
        as_of_dt = _utc_now()
        as_of = _dt_public(as_of_dt)
        request_seed = f"{tkr}|{exp}|{strike}|{option_type}|{as_of}"
        request_id = hashlib.sha256(request_seed.encode("utf-8")).hexdigest()[:24]

        try:
            frame = self._inner.fetch_option_quotes(
                tkr,
                expiration=exp,
                option_type=option_type,
            )
        except VerticalRoProviderError:
            raise
        except Exception as exc:
            raise VerticalRoProviderError(
                "provider_error",
                f"futu RO quote failed: {exc}",
            ) from exc

        row = _pick_put_row(frame, strike=strike)
        if row is None:
            raise VerticalRoProviderError("provider_empty", "no option quote row")

        try:
            bid = _finite_number(row.get("bid"), "bid")
            ask = _finite_number(row.get("ask"), "ask")
            delta = _finite_number(row.get("delta"), "delta")
            iv_raw = row.get("implied_volatility")
            if iv_raw is None:
                iv_raw = row.get("iv")
            iv = _finite_number(iv_raw, "iv")
            strike_n = _finite_number(row.get("strike", strike), "strike")
            expiry_v = row.get("expiry") or exp
            if type(expiry_v) is not str or not str(expiry_v).strip():
                expiry_v = exp
            else:
                expiry_v = str(expiry_v).strip()[:32]
        except VerticalRoProviderError:
            raise
        except Exception as exc:
            raise VerticalRoProviderError(
                "provider_schema", f"quote row unusable: {exc}"
            ) from exc

        apr = _apr_sell_put(
            bid=bid, ask=ask, strike=strike_n, expiry=expiry_v, as_of=as_of_dt
        )
        raw_symbol = row.get("symbol")
        evidence = (
            f"provider:{self._provider_label}",
            f"request_id:{request_id}",
            f"as_of:{as_of}",
            f"ticker:{tkr}",
            f"expiry:{expiry_v}",
            f"strike:{strike_n}",
        )
        return VerticalRoQuote(
            ticker=tkr,
            expiry=expiry_v,
            strike=strike_n,
            bid=bid,
            ask=ask,
            delta=delta,
            iv=iv,
            apr=apr,
            as_of=as_of,
            provider_name=self._provider_label,
            request_id=request_id,
            evidence=evidence,
            raw_symbol=str(raw_symbol) if raw_symbol is not None else None,
        )

    def __getattr__(self, name: str) -> Any:
        # Fail closed: do not proxy trade/account methods from the inner provider.
        raise AttributeError(
            f"FutuReadOnlyOptionsFacade has no attribute {name!r} "
            f"(RO surface only: {sorted(_ALLOWED_PUBLIC_METHODS)})"
        )


def build_futu_ro_facade(
    settings: Settings,
    *,
    inner_factory: Callable[[Settings], _QuoteProvider] | None = None,
) -> FutuReadOnlyOptionsFacade:
    """Construct the RO façade from settings (or an injectable factory)."""
    if inner_factory is not None:
        inner = inner_factory(settings)
        return FutuReadOnlyOptionsFacade(inner, provider_label="futu")
    if not settings.futu.enabled:
        raise VerticalRoProviderError("provider_disabled", "futu provider disabled")
    if not settings.futu.options_enabled:
        raise VerticalRoProviderError(
            "provider_disabled", "futu options provider disabled"
        )
    from quant_system.data.providers.futu import FutuMarketDataProvider

    inner = FutuMarketDataProvider(
        host=settings.futu.host,
        port=settings.futu.port,
        request_timeout_seconds=settings.futu.request_timeout_seconds,
        option_quotes_cache_path=(
            settings.futu.cache_dir / "options_cache.duckdb"
            if settings.futu.use_cache
            else None
        ),
    )
    return FutuReadOnlyOptionsFacade(inner, provider_label="futu")


def adapter_public_surface() -> tuple[str, ...]:
    """Audit helper: public callables on the RO façade class."""
    names: list[str] = []
    for name in dir(FutuReadOnlyOptionsFacade):
        if name.startswith("_"):
            continue
        attr = getattr(FutuReadOnlyOptionsFacade, name)
        if callable(attr) or name == "provider_name":
            names.append(name)
    return tuple(sorted(names))


__all__ = [
    "FutuReadOnlyOptionsFacade",
    "VerticalRoProviderError",
    "VerticalRoQuote",
    "adapter_public_surface",
    "build_futu_ro_facade",
]
