from __future__ import annotations

import csv
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

from quant_system.options.universe import OptionsUniverse
from quant_system.options.vix_data import (
    fetch_vix_history,
    load_vix_history,
    save_vix_history,
)

REMOTE_CSV_MAX_ATTEMPTS = 3
REMOTE_CSV_RETRY_BACKOFF_SECONDS = (1.0, 2.0, 4.0)

SP500_RAW_CSV_URL = (
    "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/"
    "refs/heads/main/data/constituents.csv"
)
NASDAQ100_RAW_CSV_URL = (
    "https://raw.githubusercontent.com/Gary-Strauss/NASDAQ100_Constituents/"
    "master/data/nasdaq100_constituents.csv"
)
NASDAQ_EARNINGS_URL = "https://api.nasdaq.com/api/calendar/earnings?date={date}"
USER_AGENT = "ai-quant-platform/manual-universe-refresh"
NASDAQ_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


def refresh_options_universe(path: Path, *, source: str = "github") -> dict:
    active_source = _normalize_source(source, public_value="github")
    try:
        if active_source == "sample":
            rows = _sample_universe_rows()
        elif active_source == "github":
            rows = _build_universe_from_github_csv()
        else:
            raise ValueError("source must be public, github, or sample")
    except (URLError, HTTPError, TimeoutError, OSError) as exc:
        existing_count = _existing_universe_row_count(path)
        if existing_count > 0:
            return {
                **_result("universe", active_source, path, existing_count),
                "status": "kept_existing",
                "warning": (
                    "public universe refresh failed; existing universe CSV was kept "
                    f"({type(exc).__name__}: {exc})"
                ),
            }
        raise

    if not rows:
        existing_count = _existing_universe_row_count(path)
        if existing_count > 0:
            return {
                **_result("universe", active_source, path, existing_count),
                "status": "kept_existing",
                "warning": (
                    "public universe refresh returned no rows; "
                    "existing universe CSV was kept"
                ),
            }
        raise RuntimeError("public universe refresh returned no rows")

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["ticker", "name", "sector", "exchange", "source"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    return _result("universe", active_source, path, len(rows))


def refresh_earnings_calendar(
    *,
    universe_path: Path,
    output_path: Path,
    source: str = "yfinance",
    top: int = 100,
    today: date | None = None,
) -> dict:
    active_source = _normalize_source(source, public_value="nasdaq")
    if active_source == "sample" and not universe_path.exists():
        refresh_options_universe(universe_path, source="sample")

    entries = OptionsUniverse.load(universe_path, top_n=max(top, 1))
    if active_source == "sample":
        rows = _sample_earnings_rows(entries, today=today)
    elif active_source == "nasdaq":
        rows = _fetch_nasdaq_earnings_rows(entries, today=today)
    elif active_source == "yfinance":
        rows = _fetch_yfinance_earnings_rows(entries)
    else:
        raise ValueError("source must be public, nasdaq, yfinance, or sample")

    if active_source != "sample" and not rows:
        existing_count = _existing_earnings_row_count(output_path)
        if existing_count > 0:
            return {
                **_result("earnings", active_source, output_path, existing_count),
                "status": "kept_existing",
                "warning": "public earnings refresh returned no rows; existing calendar was kept",
            }
        raise RuntimeError(f"{active_source} earnings refresh returned no rows")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["ticker", "earnings_date"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    return _result("earnings", active_source, output_path, len(rows))


def refresh_vix_history(
    path: Path,
    *,
    source: str = "public",
    lookback_days: int = 400,
    end: date | None = None,
) -> dict:
    active_source = _normalize_source(source, public_value="public")
    end_date = end or datetime.now(UTC).date()
    lookback = max(int(lookback_days), 1)
    if active_source == "sample":
        vix, vix3m = _sample_vix_series(end_date=end_date, lookback_days=lookback)
    elif active_source == "public":
        vix, vix3m = fetch_vix_history(end=end_date, lookback_days=lookback)
    else:
        raise ValueError("source must be public or sample")

    if vix.empty and (vix3m is None or vix3m.empty):
        existing_vix, _existing_vix3m = load_vix_history(path)
        if not existing_vix.empty:
            return {
                **_result("vix", active_source, path, len(existing_vix)),
                "status": "kept_existing",
            }
        raise RuntimeError("empty VIX response and no existing cache")

    output_path = save_vix_history(path, vix, vix3m if vix3m is not None else None)
    return _result("vix", active_source, Path(output_path), len(vix))


def _normalize_source(source: str, *, public_value: str) -> str:
    active_source = source.lower().strip()
    return public_value if active_source == "public" else active_source


def _result(kind: str, source: str, path: Path, row_count: int) -> dict:
    return {
        "kind": kind,
        "source": source,
        "status": "refreshed",
        "row_count": row_count,
        "output_path": str(path),
        "fetched_at": datetime.now(UTC).isoformat(),
    }


def _sample_universe_rows() -> list[dict[str, str]]:
    return [
        {
            "ticker": "SPY",
            "name": "SPDR S&P 500 ETF",
            "sector": "ETF",
            "exchange": "US",
            "source": "both",
        },
        {
            "ticker": "QQQ",
            "name": "Invesco QQQ Trust",
            "sector": "ETF",
            "exchange": "US",
            "source": "nasdaq100",
        },
        {
            "ticker": "AAPL",
            "name": "Apple Inc.",
            "sector": "Information Technology",
            "exchange": "US",
            "source": "both",
        },
        {
            "ticker": "MSFT",
            "name": "Microsoft Corporation",
            "sector": "Information Technology",
            "exchange": "US",
            "source": "both",
        },
    ]


def _sample_earnings_rows(entries, *, today: date | None) -> list[dict[str, str]]:
    base_date = today or datetime.now(UTC).date()
    return [
        {
            "ticker": entry.ticker,
            "earnings_date": (base_date + timedelta(days=14 + index * 7)).isoformat(),
        }
        for index, entry in enumerate(entries)
    ]


def _sample_vix_series(*, end_date: date, lookback_days: int) -> tuple[pd.Series, pd.Series]:
    index = pd.date_range(end=end_date, periods=lookback_days, freq="D")
    vix = pd.Series([15.0 + (offset % 8) * 0.35 for offset in range(lookback_days)], index=index)
    vix3m = pd.Series(
        [17.0 + (offset % 8) * 0.25 for offset in range(lookback_days)],
        index=index,
    )
    return vix, vix3m


def _fetch_yfinance_earnings_rows(entries) -> list[dict[str, str]]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is required for public earnings refresh") from exc

    rows: list[dict[str, str]] = []
    for entry in entries:
        earnings_date = _next_earnings_date(yf, entry.ticker)
        if earnings_date:
            rows.append({"ticker": entry.ticker, "earnings_date": earnings_date})
    return rows


def _fetch_nasdaq_earnings_rows(
    entries,
    *,
    today: date | None,
    horizon_days: int = 45,
) -> list[dict[str, str]]:
    tickers = {entry.ticker.upper().strip() for entry in entries}
    if not tickers:
        return []
    start = today or datetime.now(UTC).date()
    dates = [start + timedelta(days=offset) for offset in range(horizon_days + 1)]
    found: dict[str, str] = {}
    successful_requests = 0

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(_fetch_nasdaq_earnings_for_date, active_date): active_date
            for active_date in dates
        }
        for future in as_completed(futures):
            active_date = futures[future]
            ok, rows = future.result()
            if not ok:
                continue
            successful_requests += 1
            for row in rows:
                ticker = str(row.get("symbol", "")).strip().replace(".", "-").upper()
                if ticker in tickers and ticker not in found:
                    found[ticker] = active_date.isoformat()

    if successful_requests == 0:
        raise RuntimeError("Nasdaq earnings calendar did not return any usable responses")
    return [
        {"ticker": ticker, "earnings_date": earnings_date}
        for ticker, earnings_date in sorted(found.items())
    ]


def _fetch_nasdaq_earnings_for_date(active_date: date) -> tuple[bool, list[dict]]:
    request = Request(
        NASDAQ_EARNINGS_URL.format(date=active_date.isoformat()),
        headers={
            "User-Agent": NASDAQ_USER_AGENT,
            "Accept": "application/json, text/plain, */*",
            "Origin": "https://www.nasdaq.com",
            "Referer": "https://www.nasdaq.com/market-activity/earnings",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except Exception:
        return False, []
    rows = (payload.get("data") or {}).get("rows") or []
    return True, rows if isinstance(rows, list) else []


def _next_earnings_date(yf_module, ticker: str) -> str | None:
    try:
        calendar = yf_module.Ticker(ticker).calendar
    except Exception:
        return None
    if calendar is None:
        return None
    raw = None
    if isinstance(calendar, dict):
        raw = calendar.get("Earnings Date") or calendar.get("EarningsDate")
    else:
        try:
            raw = calendar.loc["Earnings Date"][0]
        except Exception:
            raw = None
    if raw is None:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        text = str(raw).split()[0]
        return text if len(text) == 10 else None


def _existing_earnings_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return sum(1 for row in reader if row.get("ticker") and row.get("earnings_date"))


def _existing_universe_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return len(OptionsUniverse.load(path))
    except Exception:
        return 0


def _build_universe_from_github_csv() -> list[dict[str, str]]:
    sp500 = _read_remote_csv(
        SP500_RAW_CSV_URL,
        symbol_header="Symbol",
        name_header="Security",
        sector_header="GICS Sector",
        source="sp500",
    )
    nasdaq100 = _read_remote_csv(
        NASDAQ100_RAW_CSV_URL,
        symbol_header="Ticker",
        name_header="Company",
        sector_header="GICS_Sector",
        source="nasdaq100",
    )
    merged: dict[str, dict[str, str]] = {}
    for row in sp500 + nasdaq100:
        ticker = row["ticker"]
        if ticker in merged:
            merged[ticker]["source"] = "both"
            continue
        merged[ticker] = row

    def priority(item: dict[str, str]) -> tuple[int, str]:
        source_rank = {"both": 0, "nasdaq100": 1, "sp500": 2}[item["source"]]
        return source_rank, item["ticker"]

    return sorted(merged.values(), key=priority)


def _read_remote_csv(
    url: str,
    *,
    symbol_header: str,
    name_header: str,
    sector_header: str,
    source: str,
    max_attempts: int = REMOTE_CSV_MAX_ATTEMPTS,
) -> list[dict[str, str]]:
    request = Request(url, headers={"User-Agent": USER_AGENT})
    attempts = max(int(max_attempts), 1)
    last_error: Exception | None = None
    text = ""
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=30) as response:
                text = response.read().decode("utf-8-sig")
            break
        except (URLError, HTTPError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt + 1 >= attempts:
                raise
            delay = REMOTE_CSV_RETRY_BACKOFF_SECONDS[
                min(attempt, len(REMOTE_CSV_RETRY_BACKOFF_SECONDS) - 1)
            ]
            time.sleep(delay)
    else:
        if last_error is not None:
            raise last_error
        raise RuntimeError(f"failed to download universe CSV: {url}")

    rows: list[dict[str, str]] = []
    reader = csv.DictReader(text.splitlines())
    for raw in reader:
        ticker = str(raw.get(symbol_header, "")).strip().replace(".", "-").upper()
        if not ticker:
            continue
        rows.append(
            {
                "ticker": ticker,
                "name": str(raw.get(name_header, "")).strip(),
                "sector": str(raw.get(sector_header, "")).strip() or "Unknown",
                "exchange": "US",
                "source": source,
            }
        )
    return rows
