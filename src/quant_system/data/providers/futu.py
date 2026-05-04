from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pandas as pd

from quant_system.data.schema import normalize_ohlcv_dataframe


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

    def __init__(
        self,
        *,
        host: str = "127.0.0.1",
        port: int = 11111,
        request_timeout_seconds: int = 15,
        context_factory: ContextFactory | None = None,
        sdk_loader: SdkLoader = _default_sdk_loader,
    ) -> None:
        self.host = host
        self.port = port
        self.request_timeout_seconds = request_timeout_seconds
        self._context_factory = context_factory
        self._sdk_loader = sdk_loader

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
            ret, data = context.get_option_expiration_date(futu_symbol)
            if ret != sdk.RET_OK:
                raise self._map_provider_failure(futu_symbol, data)
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
        _plain_symbol, futu_symbol = self.normalize_symbol(underlying)
        sdk = self._sdk_loader()
        context = self._create_context(sdk)
        try:
            ret, data = context.get_option_chain(
                futu_symbol,
                start=start_expiration,
                end=end_expiration,
                option_type=self._resolve_option_type(sdk, option_type),
            )
            if ret != sdk.RET_OK:
                raise self._map_provider_failure(futu_symbol, data)
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
        chain = self.fetch_option_chain(
            underlying,
            expiration=expiration,
            option_type=option_type,
        )
        codes = chain["symbol"].dropna().astype(str).tolist()
        if not codes:
            return chain
        snapshots = self.fetch_market_snapshots(codes)
        if snapshots.empty:
            return chain
        return chain.merge(snapshots, how="left", on="symbol", suffixes=("", "_snapshot"))

    def fetch_option_quotes_range(
        self,
        underlying: str,
        *,
        start_expiration: str,
        end_expiration: str,
        option_type: str = "ALL",
    ) -> pd.DataFrame:
        chain = self.fetch_option_chain_range(
            underlying,
            start_expiration=start_expiration,
            end_expiration=end_expiration,
            option_type=option_type,
        )
        codes = chain["symbol"].dropna().astype(str).tolist()
        if not codes:
            return chain
        snapshots = self.fetch_market_snapshots(codes)
        if snapshots.empty:
            return chain
        return chain.merge(snapshots, how="left", on="symbol", suffixes=("", "_snapshot"))

    def fetch_market_snapshots(self, symbols: list[str]) -> pd.DataFrame:
        if not symbols:
            return pd.DataFrame()
        sdk = self._sdk_loader()
        context = self._create_context(sdk)
        try:
            frames = []
            for batch in _batched(symbols, self.snapshot_batch_size):
                ret, data = context.get_market_snapshot(batch)
                if ret != sdk.RET_OK:
                    raise self._map_provider_failure(",".join(batch[:3]), data)
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

    def _create_context(self, sdk: SdkBindings) -> Any:
        try:
            if self._context_factory is not None:
                return self._context_factory(self.host, self.port)
            return sdk.OpenQuoteContext(host=self.host, port=self.port)
        except Exception as exc:
            raise FutuProviderError(
                "opend_unavailable",
                f"unable to connect to OpenD at {self.host}:{self.port}",
            ) from exc

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
            try:
                ret, data, page_req_key = context.request_history_kline(
                    futu_symbol,
                    start=start,
                    end=end,
                    ktype=kl_type,
                    autype=sdk.AuType.QFQ,
                    max_count=1000,
                    page_req_key=page_req_key,
                    session=session,
                )
            except Exception as exc:
                raise FutuProviderError(
                    "provider_timeout",
                    f"OpenD history request failed for {futu_symbol}",
                ) from exc

            if ret != sdk.RET_OK:
                raise self._map_provider_failure(futu_symbol, data)
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
    def _map_provider_failure(symbol: str, payload: object) -> FutuProviderError:
        message = str(payload)
        lowered = message.lower()
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
