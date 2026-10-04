"""Read only the specified NYSE session's real Futu daily opening prices."""

from __future__ import annotations

from datetime import UTC, date, datetime
from math import isfinite

import pandas as pd

from quant_system.config.settings import Settings, load_settings
from quant_system.data.provider_factory import build_ohlcv_provider
from quant_system.execution.price_source import PricedQuote, PriceUnavailableError
from quant_system.research.strategy_runtime import session_open


class DefinitionOpenPriceSource:
    def __init__(self, settings: Settings | None = None, *, clock=None) -> None:
        self.settings = settings or load_settings()
        self.clock = clock or (lambda: datetime.now(UTC))

    def get_prices(self, symbols: list[str], *, target_date: str) -> dict[str, PricedQuote]:
        try:
            session = date.fromisoformat(target_date)
            opening = session_open(session).to_pydatetime()
            now = self.clock()
            if now.tzinfo is None or now < opening:
                raise ValueError("strategy_definition_open_not_available")
            provider, source = build_ohlcv_provider(self.settings, requested="futu")
            if source != "futu":
                raise ValueError("strategy_definition_real_provider_required")
            frame = provider.fetch_ohlcv(symbols, start=target_date, end=target_date, interval="1d")
            if frame is None or frame.empty:
                raise ValueError("strategy_definition_open_missing")
            frame = frame.copy()
            frame["symbol"] = frame["symbol"].astype(str).str.upper().str.strip()
            sessions = pd.to_datetime(frame["timestamp"], utc=True).dt.date
            frame = frame.loc[sessions == session]
            for field, expected in (
                ("provider", "futu"),
                ("interval", "1d"),
                ("price_adjustment", "qfq"),
            ):
                if field not in frame or not frame[field].eq(expected).all():
                    raise ValueError("strategy_definition_open_provenance_invalid")
            quotes = {}
            for symbol in symbols:
                rows = frame.loc[frame["symbol"] == symbol]
                if len(rows) != 1:
                    raise ValueError("strategy_definition_open_missing_or_duplicate")
                price = float(rows.iloc[0]["open"])
                if not isfinite(price) or price <= 0:
                    raise ValueError("strategy_definition_open_invalid")
                quotes[symbol] = PricedQuote(
                    symbol=symbol,
                    price=price,
                    price_kind="futu_daily_open",
                    as_of=opening.isoformat(),
                    source="futu",
                )
            return quotes
        except Exception as exc:  # noqa: BLE001 - no fallback across price semantics
            raise PriceUnavailableError(str(exc)) from exc
