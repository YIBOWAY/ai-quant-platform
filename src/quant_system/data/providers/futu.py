from __future__ import annotations

import signal
import socket
import threading
import time
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import pandas as pd

from quant_system.data.schema import normalize_ohlcv_dataframe
from quant_system.storage.options_cache import OptionQuotesCache, OptionQuotesCacheKey


class FutuProviderError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


SdkBindings = SimpleNamespace
ContextFactory = Callable[[str, int], Any]
SdkLoader = Callable[[], SdkBindings]


def _batched(items: list[str], batch_size: int) -> list[list[str]]:
    return [items[index : index + batch_size] for index in range(0, len(items), batch_size)]


def _default_sdk_loader() -> SdkBindings:
    try:
        from futu import (
            RET_OK,
            AuType,
            KLType,
            OpenQuoteContext,
            OptionType,
            Session,
        )
    except Exception as exc:  # pragma: no cover - depends on local SDK install
        raise FutuProviderError(
            "sdk_unavailable",
            "futu-api is not installed in the active Python environment",
        ) from exc
    return SimpleNamespace(
        AuType=AuType,
        KLType=KLType,
        OpenQuoteContext=OpenQuoteContext,
        OptionType=OptionType,
        RET_OK=RET_OK,
        Session=Session,
    )


class FutuMarketDataProvider:
    provider_name = "futu"
    snapshot_batch_size = 400
    option_chain_max_span_days = 30
    option_quotes_cache_ttl_seconds = 900.0
    _option_quotes_range_cache: ClassVar[
        dict[tuple[object, ...], tuple[float, pd.DataFrame]]
    ] = {}

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 11111,
        request_timeout_seconds: float = 15,
        context_factory: ContextFactory | None = None,
        sdk_loader: SdkLoader = _default_sdk_loader,
        rate_limit_retry_seconds: float = 30.5,
        rate_limit_max_retries: int = 1,
        sleep_func: Callable[[float], None] = time.sleep,
        option_quotes_cache_path: str | Path | None = None,
    ) -> None:
        self.host = host
        self.port = port
        if request_timeout_seconds <= 0:
            raise ValueError("request_timeout_seconds must be positive")
        self.request_timeout_seconds = request_timeout_seconds
        self._context_factory = context_factory
        self._sdk_loader = sdk_loader
        self.rate_limit_retry_seconds = rate_limit_retry_seconds
        self.rate_limit_max_retries = rate_limit_max_retries
        self._sleep_func = sleep_func
        # OptionQuotesCache creates its DuckDB/schema in __init__. Keep plain
        # OHLCV and snapshot reads observational by constructing that cache
        # only when an option-quote cache operation is actually requested.
        self._option_quotes_cache_path = (
            Path(option_quotes_cache_path) if option_quotes_cache_path is not None else None
        )
        self._option_quotes_database_cache: OptionQuotesCache | None = None
        self.last_option_quotes_cache_status = "disabled"
        self.last_option_quotes_cache_error: str | None = None

    def fetch_ohlcv(
        self,
        symbols: list[str],
        *,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        if not symbols:
            raise FutuProviderError("invalid_symbol", "at least one symbol is required")

        sdk = self._sdk_loader()
        kl_type = self._resolve_interval(sdk, interval)
        session = self._resolve_session(sdk, interval)
        fetched_at = pd.Timestamp.now(tz="UTC")
        context = self._create_context(sdk)
        try:
            rows: list[dict[str, object]] = []
            for symbol in symbols:
                plain_symbol, futu_symbol = self.normalize_symbol(symbol)
                rows.extend(
                    self._fetch_symbol_rows(
                        context=context,
                        sdk=sdk,
                        plain_symbol=plain_symbol,
                        futu_symbol=futu_symbol,
                        start=start,
                        end=end,
                        interval=interval,
                        kl_type=kl_type,
                        session=session,
                        fetched_at=fetched_at,
                    )
                )
        finally:
            self._safe_close(context)

        return normalize_ohlcv_dataframe(
            pd.DataFrame(rows),
            provider=self.provider_name,
            interval=interval,
        )

    def fetch_option_expirations(self, underlying: str) -> pd.DataFrame:
        _plain_symbol, futu_symbol = self.normalize_symbol(underlying)
        sdk = self._sdk_loader()
        context = self._create_context(sdk)
        try:
            _ret, data = self._call_with_rate_limit_retry(
                sdk=sdk,
                symbol=futu_symbol,
                action=lambda: context.get_option_expiration_date(futu_symbol),
            )
            if data is None or data.empty:
                raise FutuProviderError(
                    "no_data",
                    f"no option expirations returned for {futu_symbol}",
                )
            frame = data.copy()
            frame["underlying"] = futu_symbol
            return frame
        finally:
            self._safe_close(context)

    def fetch_option_chain(
        self,
        underlying: str,
        *,
        expiration: str,
        option_type: str = "ALL",
    ) -> pd.DataFrame:
        return self.fetch_option_chain_range(
            underlying,
            start_expiration=expiration,
            end_expiration=expiration,
            option_type=option_type,
        )

    def fetch_option_chain_range(
        self,
        underlying: str,
        *,
        start_expiration: str,
        end_expiration: str,
        option_type: str = "ALL",
    ) -> pd.DataFrame:
        windows = self._expiration_windows(
            start_expiration,
            end_expiration,
            max_span_days=self.option_chain_max_span_days,
        )
        if len(windows) > 1:
            frames = []
            for window_start, window_end in windows:
                try:
                    frames.append(
                        self._fetch_option_chain_range_once(
                            underlying,
                            start_expiration=window_start,
                            end_expiration=window_end,
                            option_type=option_type,
                        )
                    )
                except FutuProviderError as exc:
                    if exc.code != "no_data":
                        raise
            if not frames:
                _plain_symbol, futu_symbol = self.normalize_symbol(underlying)
                raise FutuProviderError(
                    "no_data",
                    f"no option chain returned for {futu_symbol} "
                    f"{start_expiration} to {end_expiration}",
                )
            return (
                pd.concat(frames, ignore_index=True)
                .drop_duplicates(subset=["symbol"])
                .reset_index(drop=True)
            )
        return self._fetch_option_chain_range_once(
            underlying,
            start_expiration=start_expiration,
            end_expiration=end_expiration,
            option_type=option_type,
        )

    def _fetch_option_chain_range_once(
        self,
        underlying: str,
        *,
        start_expiration: str,
        end_expiration: str,
        option_type: str = "ALL",
    ) -> pd.DataFrame:
        _plain_symbol, futu_symbol = self.normalize_symbol(underlying)
        sdk = self._sdk_loader()
        context = self._create_context(sdk)
        try:
            _ret, data = self._call_with_rate_limit_retry(
                sdk=sdk,
                symbol=futu_symbol,
                action=lambda: context.get_option_chain(
                    futu_symbol,
                    start=start_expiration,
                    end=end_expiration,
                    option_type=self._resolve_option_type(sdk, option_type),
                ),
            )
            if data is None or data.empty:
                raise FutuProviderError(
                    "no_data",
                    f"no option chain returned for {futu_symbol} "
                    f"{start_expiration} to {end_expiration}",
                )
            return self._normalize_option_chain(data, underlying=futu_symbol)
        finally:
            self._safe_close(context)

    def fetch_option_quotes(
        self,
        underlying: str,
        *,
        expiration: str,
        option_type: str = "ALL",
    ) -> pd.DataFrame:
        return self.fetch_option_quotes_range(
            underlying,
            start_expiration=expiration,
            end_expiration=expiration,
            option_type=option_type,
        )

    def fetch_option_quotes_range(
        self,
        underlying: str,
        *,
        start_expiration: str,
        end_expiration: str,
        option_type: str = "ALL",
    ) -> pd.DataFrame:
        cache_key = self._option_quotes_cache_key(
            underlying,
            start_expiration=start_expiration,
            end_expiration=end_expiration,
            option_type=option_type,
        )
        cached = self._read_option_quotes_cache(cache_key)
        if cached is not None:
            self.last_option_quotes_cache_status = "memory_cache"
            return cached
        database_cache_key = self._option_quotes_database_cache_key(
            underlying,
            start_expiration=start_expiration,
            end_expiration=end_expiration,
            option_type=option_type,
        )
        cached = self._read_option_quotes_database_cache(database_cache_key)
        if cached is not None:
            self._write_option_quotes_cache(cache_key, cached)
            self.last_option_quotes_cache_status = "database_cache"
            return cached
        chain = self.fetch_option_chain_range(
            underlying,
            start_expiration=start_expiration,
            end_expiration=end_expiration,
            option_type=option_type,
        )
        codes = chain["symbol"].dropna().astype(str).tolist()
        if not codes:
            self._write_option_quotes_cache(cache_key, chain)
            self._write_option_quotes_database_cache(database_cache_key, chain)
            self.last_option_quotes_cache_status = "live"
            return chain
        snapshots = self.fetch_market_snapshots(codes)
        if snapshots.empty:
            self._write_option_quotes_cache(cache_key, chain)
            self._write_option_quotes_database_cache(database_cache_key, chain)
            self.last_option_quotes_cache_status = "live"
            return chain
        merged = chain.merge(snapshots, how="left", on="symbol", suffixes=("", "_snapshot"))
        self._write_option_quotes_cache(cache_key, merged)
        self._write_option_quotes_database_cache(database_cache_key, merged)
        self.last_option_quotes_cache_status = "live"
        return merged

    def fetch_market_snapshots(self, symbols: list[str]) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame()
        sdk = self._sdk_loader()
        context = self._create_context(sdk)
        try:
            frames = []
            for batch in _batched(symbols, self.snapshot_batch_size):
                _ret, data = self._call_with_rate_limit_retry(
                    sdk=sdk,
                    symbol=",".join(batch[:3]),
                    action=lambda batch=batch: context.get_market_snapshot(batch),
                )
                if data is None or data.empty:
                    continue
                frames.append(self._normalize_snapshots(data))
            if not frames:
                raise FutuProviderError("no_data", "no snapshot data returned")
            return pd.concat(frames, ignore_index=True)
        finally:
            self._safe_close(context)

    def fetch_underlying_snapshot(self, symbol: str) -> dict[str, object]:
        _plain_symbol, futu_symbol = self.normalize_symbol(symbol)
        frame = self.fetch_market_snapshots([futu_symbol])
        if frame.empty:
            raise FutuProviderError("no_data", f"no snapshot data returned for {futu_symbol}")
        return frame.iloc[0].to_dict()

    @classmethod
    def clear_option_quotes_cache(cls) -> None:
        cls._option_quotes_range_cache.clear()

    @staticmethod
    def normalize_symbol(symbol: str) -> tuple[str, str]:
        normalized = symbol.upper().strip()
        if not normalized:
            raise FutuProviderError("invalid_symbol", "symbol must not be empty")
        if normalized.startswith("US."):
            plain_symbol = normalized.split(".", 1)[1]
            if not plain_symbol:
                raise FutuProviderError("invalid_symbol", f"invalid Futu US symbol: {symbol}")
            return plain_symbol, normalized
        if "." in normalized:
            raise FutuProviderError(
                "invalid_symbol",
                f"Futu US market data expects plain US tickers or US-prefixed codes: {symbol}",
            )
        return normalized, f"US.{normalized}"

    def _call_with_rate_limit_retry(
        self,
        *,
        sdk: SdkBindings,
        symbol: str,
        action: Callable[[], tuple[Any, ...]],
    ) -> tuple[Any, ...]:
        last_error: FutuProviderError | None = None
        for attempt in range(self.rate_limit_max_retries + 1):
            try:
                result = self._run_with_request_timeout(action)
            except Exception as exc:
                raise FutuProviderError(
                    "provider_timeout",
                    f"OpenD request failed for {symbol}",
                ) from exc
            if result and result[0] == sdk.RET_OK:
                return result
            payload = result[1] if len(result) > 1 else result
            error = self._map_provider_failure(symbol, payload)
            if error.code == "rate_limited" and attempt < self.rate_limit_max_retries:
                last_error = error
                self._sleep_func(self.rate_limit_retry_seconds)
                continue
            raise error
        if last_error is not None:
            raise last_error
        raise FutuProviderError(
            "provider_query_failed",
            f"Futu request failed for {symbol}",
        )

    def _create_context(self, sdk: SdkBindings) -> Any:
        # Pre-flight TCP probe so that a closed OpenD fails in <1s rather than
        # blocking the SDK's internal reconnect loop for minutes.
        if self._context_factory is None:
            try:
                with socket.create_connection(
                    (self.host, self.port),
                    timeout=min(2.0, float(self.request_timeout_seconds)),
                ):
                    pass
            except OSError as exc:
                raise FutuProviderError(
                    "opend_unavailable",
                    f"unable to connect to OpenD at {self.host}:{self.port}",
                ) from exc
        try:
            if self._context_factory is not None:
                context = self._run_with_request_timeout(
                    lambda: self._context_factory(self.host, self.port)
                )
            else:
                context = self._run_with_request_timeout(
                    lambda: sdk.OpenQuoteContext(
                        host=self.host,
                        port=self.port,
                        is_async_connect=True,
                    )
                )
            self._configure_context_timeout(context)
            return context
        except TimeoutError as exc:
            raise FutuProviderError(
                "provider_timeout",
                f"OpenD context creation timed out for {self.host}:{self.port}",
            ) from exc
        except FutuProviderError:
            raise
        except Exception as exc:
            raise FutuProviderError(
                "opend_unavailable",
                f"unable to connect to OpenD at {self.host}:{self.port}",
            ) from exc

    def _configure_context_timeout(self, context: Any) -> None:
        """Apply the configured deadline to the Futu SDK's synchronous waits."""
        connect_timeout = getattr(context, "set_sync_query_connect_timeout", None)
        if callable(connect_timeout):
            connect_timeout(self.request_timeout_seconds)
        if hasattr(context, "_query_timeout"):
            context._query_timeout = self.request_timeout_seconds

    def _run_with_request_timeout(
        self,
        action: Callable[[], Any],
    ) -> Any:
        """Bound a synchronous SDK action without spawning an orphan worker."""
        if (
            threading.current_thread() is not threading.main_thread()
            or not hasattr(signal, "setitimer")
        ):
            return action()
        previous_timer = signal.getitimer(signal.ITIMER_REAL)
        if previous_timer[0] > 0:
            # Do not steal a process-wide alarm owned by the caller. Real Futu
            # contexts are still bounded by `_query_timeout` above.
            return action()
        previous_handler = signal.getsignal(signal.SIGALRM)

        def raise_timeout(_signum: int, _frame: Any) -> None:
            raise TimeoutError("Futu request deadline exceeded")

        signal.signal(signal.SIGALRM, raise_timeout)
        signal.setitimer(signal.ITIMER_REAL, self.request_timeout_seconds)
        try:
            return action()
        finally:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, previous_handler)

    def _option_quotes_cache_key(
        self,
        underlying: str,
        *,
        start_expiration: str,
        end_expiration: str,
        option_type: str,
    ) -> tuple[object, ...]:
        plain_symbol, _futu_symbol = self.normalize_symbol(underlying)
        namespace = "live" if self._context_factory is None else id(self._context_factory)
        return (
            namespace,
            self.host,
            self.port,
            plain_symbol,
            start_expiration,
            end_expiration,
            option_type.upper().strip(),
        )

    def _read_option_quotes_cache(self, key: tuple[object, ...]) -> pd.DataFrame | None:
        cached = self._option_quotes_range_cache.get(key)
        if cached is None:
            return None
        created_at, frame = cached
        if time.monotonic() - created_at > self.option_quotes_cache_ttl_seconds:
            self._option_quotes_range_cache.pop(key, None)
            return None
        return frame.copy()

    def _write_option_quotes_cache(
        self,
        key: tuple[object, ...],
        frame: pd.DataFrame,
    ) -> None:
        self._option_quotes_range_cache[key] = (time.monotonic(), frame.copy())

    def _option_quotes_database_cache_key(
        self,
        underlying: str,
        *,
        start_expiration: str,
        end_expiration: str,
        option_type: str,
    ) -> OptionQuotesCacheKey:
        plain_symbol, _futu_symbol = self.normalize_symbol(underlying)
        return OptionQuotesCacheKey(
            provider=self.provider_name,
            host=self.host,
            port=self.port,
            underlying=plain_symbol,
            start_expiration=start_expiration,
            end_expiration=end_expiration,
            option_type=option_type,
        )

    def _read_option_quotes_database_cache(
        self,
        key: OptionQuotesCacheKey,
    ) -> pd.DataFrame | None:
        cache = self._get_option_quotes_database_cache()
        if cache is None:
            return None
        try:
            return cache.read_option_quotes(key)
        except Exception as exc:  # pragma: no cover - cache should fail open
            self.last_option_quotes_cache_error = f"{type(exc).__name__}: {exc}"
            return None

    def _write_option_quotes_database_cache(
        self,
        key: OptionQuotesCacheKey,
        frame: pd.DataFrame,
    ) -> None:
        cache = self._get_option_quotes_database_cache()
        if cache is None:
            return
        try:
            cache.write_option_quotes(
                key,
                frame,
                ttl_seconds=self.option_quotes_cache_ttl_seconds,
            )
        except Exception as exc:  # pragma: no cover - cache should fail open
            self.last_option_quotes_cache_error = f"{type(exc).__name__}: {exc}"

    def _get_option_quotes_database_cache(self) -> OptionQuotesCache | None:
        if self._option_quotes_cache_path is None:
            return None
        if self._option_quotes_database_cache is None:
            self._option_quotes_database_cache = OptionQuotesCache(
                self._option_quotes_cache_path
            )
        return self._option_quotes_database_cache

    def _fetch_symbol_rows(
        self,
        *,
        context: Any,
        sdk: SdkBindings,
        plain_symbol: str,
        futu_symbol: str,
        start: str,
        end: str,
        interval: str,
        kl_type: Any,
        session: Any,
        fetched_at: pd.Timestamp,
    ) -> list[dict[str, object]]:
        page_req_key = None
        rows: list[dict[str, object]] = []
        while True:
            _ret, data, page_req_key = self._call_with_rate_limit_retry(
                sdk=sdk,
                symbol=futu_symbol,
                action=lambda page_req_key=page_req_key: context.request_history_kline(
                    futu_symbol,
                    start=start,
                    end=end,
                    ktype=kl_type,
                    autype=sdk.AuType.QFQ,
                    max_count=1000,
                    page_req_key=page_req_key,
                    session=session,
                ),
            )
            if data is None or data.empty:
                if not rows:
                    raise FutuProviderError("no_data", f"no OHLCV data returned for {futu_symbol}")
                break
            for item in data.to_dict(orient="records"):
                rows.append(
                    {
                        "symbol": plain_symbol,
                        "timestamp": item["time_key"],
                        "open": item["open"],
                        "high": item["high"],
                        "low": item["low"],
                        "close": item["close"],
                        "volume": item["volume"],
                        "event_ts": item["time_key"],
                        "knowledge_ts": fetched_at,
                        "price_adjustment": "qfq",
                    }
                )
            if page_req_key is None:
                break
        return rows

    @staticmethod
    def _resolve_interval(sdk: SdkBindings, interval: str) -> Any:
        normalized = interval.lower().strip()
        mapping = {
            "1d": sdk.KLType.K_DAY,
            "1h": sdk.KLType.K_60M,
            "60m": sdk.KLType.K_60M,
            "30m": sdk.KLType.K_30M,
            "15m": sdk.KLType.K_15M,
            "5m": sdk.KLType.K_5M,
            "1m": sdk.KLType.K_1M,
        }
        if normalized not in mapping:
            raise FutuProviderError(
                "unsupported_interval",
                f"unsupported Futu interval: {interval}",
            )
        return mapping[normalized]

    @staticmethod
    def _resolve_session(sdk: SdkBindings, interval: str) -> Any:
        normalized = interval.lower().strip()
        intraday = {"1h", "60m", "30m", "15m", "5m", "1m"}
        return sdk.Session.ALL if normalized in intraday else sdk.Session.NONE

    @staticmethod
    def _resolve_option_type(sdk: SdkBindings, option_type: str) -> Any:
        normalized = option_type.upper().strip()
        if normalized == "CALL":
            return sdk.OptionType.CALL
        if normalized == "PUT":
            return sdk.OptionType.PUT
        return sdk.OptionType.ALL

    @staticmethod
    def _normalize_option_chain(frame: pd.DataFrame, *, underlying: str) -> pd.DataFrame:
        normalized = pd.DataFrame(
            {
                "symbol": frame.get("code"),
                "name": frame.get("name"),
                "underlying": frame.get("stock_owner", underlying),
                "option_type": frame.get("option_type"),
                "strike": pd.to_numeric(frame.get("strike_price"), errors="coerce"),
                "expiry": frame.get("strike_time"),
            }
        )
        return normalized.dropna(subset=["symbol"]).reset_index(drop=True)

    @staticmethod
    def _normalize_snapshots(frame: pd.DataFrame) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "symbol": frame.get("code"),
                "update_time": frame.get("update_time"),
                "last": pd.to_numeric(frame.get("last_price"), errors="coerce"),
                "bid": pd.to_numeric(frame.get("bid_price"), errors="coerce"),
                "ask": pd.to_numeric(frame.get("ask_price"), errors="coerce"),
                "bid_size": pd.to_numeric(frame.get("bid_vol"), errors="coerce"),
                "ask_size": pd.to_numeric(frame.get("ask_vol"), errors="coerce"),
                "volume": pd.to_numeric(frame.get("volume"), errors="coerce"),
                "turnover": pd.to_numeric(frame.get("turnover"), errors="coerce"),
                "market_val": pd.to_numeric(
                    frame.get("total_market_val"),
                    errors="coerce",
                ),
                "open_interest": pd.to_numeric(
                    frame.get("option_open_interest"),
                    errors="coerce",
                ),
                "implied_volatility": pd.to_numeric(
                    frame.get("option_implied_volatility"),
                    errors="coerce",
                ),
                "delta": pd.to_numeric(frame.get("option_delta"), errors="coerce"),
                "gamma": pd.to_numeric(frame.get("option_gamma"), errors="coerce"),
                "theta": pd.to_numeric(frame.get("option_theta"), errors="coerce"),
                "vega": pd.to_numeric(frame.get("option_vega"), errors="coerce"),
                "rho": pd.to_numeric(frame.get("option_rho"), errors="coerce"),
                "contract_size": pd.to_numeric(
                    frame.get("option_contract_size"),
                    errors="coerce",
                ),
            }
        ).dropna(subset=["symbol"]).reset_index(drop=True)

    @staticmethod
    def _expiration_windows(
        start_expiration: str,
        end_expiration: str,
        *,
        max_span_days: int,
    ) -> list[tuple[str, str]]:
        start = pd.Timestamp(start_expiration)
        end = pd.Timestamp(end_expiration)
        if end < start:
            raise FutuProviderError(
                "invalid_expiration_range",
                f"end expiration {end_expiration} is before start {start_expiration}",
            )
        windows = []
        current = start
        while current <= end:
            window_end = min(
                current + pd.Timedelta(days=max_span_days - 1),
                end,
            )
            windows.append((current.date().isoformat(), window_end.date().isoformat()))
            current = window_end + pd.Timedelta(days=1)
        return windows

    @staticmethod
    def _map_provider_failure(symbol: str, payload: object) -> FutuProviderError:
        message = str(payload)
        lowered = message.lower()
        if (
            "rate limit" in lowered
            or "too many" in lowered
            or "frequency" in lowered
            or "频率" in message
            or "每30秒最多10次" in message
        ):
            return FutuProviderError(
                "rate_limited",
                f"Futu rate limit for {symbol}: {message}",
            )
        if "permission" in lowered:
            return FutuProviderError(
                "permission_denied",
                f"Futu permission denied for {symbol}: {message}",
            )
        if "timeout" in lowered:
            return FutuProviderError(
                "provider_timeout",
                f"Futu request timed out for {symbol}: {message}",
            )
        if "security not found" in lowered or "stock code" in lowered:
            return FutuProviderError(
                "invalid_symbol",
                f"invalid Futu symbol {symbol}: {message}",
            )
        return FutuProviderError(
            "provider_query_failed",
            f"Futu request failed for {symbol}: {message}",
        )

    @staticmethod
    def _safe_close(context: Any) -> None:
        if context is None:
            return
        close = getattr(context, "close", None)
        if callable(close):
            close()
