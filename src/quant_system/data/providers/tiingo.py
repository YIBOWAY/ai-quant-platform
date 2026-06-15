from __future__ import annotations

import json
from collections.abc import Callable
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd
from pydantic import SecretStr

from quant_system.data.schema import normalize_ohlcv_dataframe

JsonGetter = Callable[[str, dict[str, str]], list[dict[str, object]]]


def _default_get_json(url: str, headers: dict[str, str]) -> list[dict[str, object]]:
    request = Request(url, headers=headers)
    with urlopen(request, timeout=30) as response:
        payload = response.read().decode("utf-8")
    parsed = json.loads(payload)
    if not isinstance(parsed, list):
        raise ValueError("Tiingo response must be a JSON list")
    return parsed


def _prefer_adjusted(
    item: dict[str, object],
    *,
    adjusted_key: str,
    raw_key: str,
) -> object:
    adjusted = item.get(adjusted_key)
    return item[raw_key] if adjusted is None else adjusted


def _price_adjustment_status(item: dict[str, object]) -> str:
    adjusted_keys = ("adjOpen", "adjHigh", "adjLow", "adjClose", "adjVolume")
    adjusted_count = sum(item.get(key) is not None for key in adjusted_keys)
    if adjusted_count == len(adjusted_keys):
        return "adjusted"
    if adjusted_count == 0:
        return "raw"
    return "mixed"


class TiingoEODProvider:
    provider_name = "tiingo"

    def __init__(
        self,
        api_token: str | SecretStr | None,
        *,
        get_json: JsonGetter = _default_get_json,
    ) -> None:
        self.api_token = (
            api_token.get_secret_value()
            if isinstance(api_token, SecretStr)
            else api_token
        )
        self.get_json = get_json

    def fetch_ohlcv(
        self,
        symbols: list[str],
        *,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        if interval.lower().strip() != "1d":
            raise ValueError(f"Tiingo provider only supports daily OHLCV: {interval}")
        if not self.api_token:
            raise ValueError("Tiingo API token is required")

        rows: list[dict[str, object]] = []
        for symbol in symbols:
            rows.extend(self._fetch_symbol(symbol.upper(), start=start, end=end))

        return normalize_ohlcv_dataframe(
            pd.DataFrame(rows),
            provider=self.provider_name,
            interval=interval,
        )

    def _fetch_symbol(self, symbol: str, *, start: str, end: str) -> list[dict[str, object]]:
        query = urlencode({"startDate": start, "endDate": end, "format": "json"})
        url = f"https://api.tiingo.com/tiingo/daily/{symbol}/prices?{query}"
        headers = {
            "Authorization": f"Token {self.api_token}",
            "Content-Type": "application/json",
        }
        payload = self.get_json(url, headers)
        # ``knowledge_ts`` reflects when the system actually learned about the row.
        # For end-of-day data we use the download time so PIT replays do not see
        # bars before they could have been observed in production.
        download_ts = pd.Timestamp.now(tz="UTC").isoformat()
        rows: list[dict[str, object]] = []
        for item in payload:
            price_adjustment = _price_adjustment_status(item)
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": item["date"],
                    "open": _prefer_adjusted(item, adjusted_key="adjOpen", raw_key="open"),
                    "high": _prefer_adjusted(item, adjusted_key="adjHigh", raw_key="high"),
                    "low": _prefer_adjusted(item, adjusted_key="adjLow", raw_key="low"),
                    "close": _prefer_adjusted(
                        item,
                        adjusted_key="adjClose",
                        raw_key="close",
                    ),
                    "volume": _prefer_adjusted(
                        item,
                        adjusted_key="adjVolume",
                        raw_key="volume",
                    ),
                    "price_adjustment": price_adjustment,
                    "event_ts": item["date"],
                    "knowledge_ts": download_ts,
                }
            )
        return rows
