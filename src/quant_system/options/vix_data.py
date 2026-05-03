"""Read-only VIX/VIX3M history loader and Yahoo Chart fetcher.

The fetcher mirrors the reference implementation at
``E:\\programs\\APEXUSTech_Inter\\quantplatform\\backend\\app\\services\\
data_fetcher.py::_fetch_yahoo_single``. It performs HTTP GETs against
``query1.finance.yahoo.com`` only — no Futu connection, no broker context —
and is used purely to compute the daily seller-options regime weight.

Tickers are CBOE indices ``^VIX`` and ``^VIX3M``. They are not exposed via
Futu's ``US.VIX`` symbol (Futu returns ``unknown stock`` for those), so a
direct Yahoo HTTP call is the closest reproducible source compatible with
our read-only research mandate.
"""

from __future__ import annotations

import csv
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/123.0 Safari/537.36"
)
VIX_TICKER = "^VIX"
VIX3M_TICKER = "^VIX3M"


HttpGet = Callable[..., Any]


def _default_http_get() -> HttpGet:
    import requests

    return requests.get


def fetch_yahoo_chart(
    ticker: str,
    start: date,
    end: date,
    *,
    http_get: HttpGet | None = None,
    timeout: float = 10.0,
) -> pd.Series:
    """Fetch a daily close-price series from Yahoo Chart API.

    Returns a pandas Series indexed by tz-naive ``DatetimeIndex`` with
    float close values. Empty series is returned on any non-200 response or
    malformed payload (errors are logged, never raised) so callers can
    gracefully fall back to a cached CSV.
    """
    if http_get is None:
        http_get = _default_http_get()
    period1 = int(datetime(start.year, start.month, start.day, tzinfo=UTC).timestamp())
    period2 = int(datetime(end.year, end.month, end.day, tzinfo=UTC).timestamp())
    url = YAHOO_CHART_URL.format(ticker=ticker)
    params = {"period1": period1, "period2": period2, "interval": "1d"}
    headers = {"User-Agent": DEFAULT_USER_AGENT, "Accept": "application/json"}
    try:
        response = http_get(url, params=params, headers=headers, timeout=timeout)
    except Exception as exc:  # pragma: no cover - network errors are runtime
        logger.warning("vix_fetch_failed ticker=%s reason=%s", ticker, exc)
        return pd.Series(dtype="float64")
    status = getattr(response, "status_code", None)
    if status != 200:
        logger.warning("vix_fetch_status ticker=%s status=%s", ticker, status)
        return pd.Series(dtype="float64")
    try:
        payload = response.json()
    except Exception as exc:  # pragma: no cover
        logger.warning("vix_fetch_json_error ticker=%s reason=%s", ticker, exc)
        return pd.Series(dtype="float64")
    return _parse_chart_payload(payload)


def _parse_chart_payload(payload: dict) -> pd.Series:
    chart = (payload or {}).get("chart") or {}
    error = chart.get("error")
    if error:
        logger.warning("vix_fetch_yahoo_error error=%s", error)
        return pd.Series(dtype="float64")
    results = chart.get("result") or []
    if not results:
        return pd.Series(dtype="float64")
    result = results[0]
    timestamps = result.get("timestamp") or []
    indicators = (result.get("indicators") or {}).get("quote") or [{}]
    closes = (indicators[0] or {}).get("close") or []
    if not timestamps or not closes:
        return pd.Series(dtype="float64")
    pairs = [
        (datetime.fromtimestamp(ts, tz=UTC).date(), float(close))
        for ts, close in zip(timestamps, closes, strict=False)
        if close is not None
    ]
    if not pairs:
        return pd.Series(dtype="float64")
    index = pd.DatetimeIndex([pd.Timestamp(d) for d, _ in pairs])
    series = pd.Series([value for _, value in pairs], index=index, dtype="float64")
    series = series[~series.index.duplicated(keep="last")].sort_index()
    return series


def save_vix_history(
    path: str | Path,
    vix: pd.Series,
    vix3m: pd.Series | None = None,
) -> Path:
    """Persist VIX / VIX3M close series to a CSV with header ``date,vix,vix3m``."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame({"vix": vix})
    if vix3m is not None and not vix3m.empty:
        frame = frame.join(vix3m.rename("vix3m"), how="outer")
    else:
        frame["vix3m"] = pd.NA
    frame = frame.sort_index()
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["date", "vix", "vix3m"])
        for ts, row in frame.iterrows():
            vix_value = row.get("vix")
            vix3m_value = row.get("vix3m")
            writer.writerow(
                [
                    pd.Timestamp(ts).date().isoformat(),
                    "" if pd.isna(vix_value) else f"{float(vix_value):.4f}",
                    "" if pd.isna(vix3m_value) else f"{float(vix3m_value):.4f}",
                ]
            )
    return target


def load_vix_history(path: str | Path) -> tuple[pd.Series, pd.Series | None]:
    """Load a previously persisted VIX history CSV.

    Returns ``(vix_series, vix3m_series_or_None)``. When the file does not
    exist, returns ``(empty_series, None)`` so callers can degrade to an
    Unknown regime rather than failing the daily scan.
    """
    target = Path(path)
    if not target.exists():
        return pd.Series(dtype="float64"), None
    frame = pd.read_csv(target)
    if "date" not in frame.columns:
        return pd.Series(dtype="float64"), None
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.dropna(subset=["date"]).set_index("date").sort_index()
    vix = (
        pd.to_numeric(frame.get("vix"), errors="coerce").dropna()
        if "vix" in frame.columns
        else pd.Series(dtype="float64")
    )
    vix3m_col = pd.to_numeric(frame.get("vix3m"), errors="coerce")
    vix3m: pd.Series | None
    if vix3m_col is not None:
        vix3m = vix3m_col.dropna()
        if vix3m.empty:
            vix3m = None
    else:
        vix3m = None
    return vix, vix3m


def fetch_vix_history(
    *,
    end: date,
    lookback_days: int = 400,
    http_get: HttpGet | None = None,
) -> tuple[pd.Series, pd.Series]:
    """Fetch ``^VIX`` and ``^VIX3M`` daily closes ending at ``end``."""
    start = end - timedelta(days=lookback_days)
    vix = fetch_yahoo_chart(VIX_TICKER, start, end, http_get=http_get)
    vix3m = fetch_yahoo_chart(VIX3M_TICKER, start, end, http_get=http_get)
    return vix, vix3m
