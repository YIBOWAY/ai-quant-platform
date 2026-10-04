from __future__ import annotations

import csv
import json
import math
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
    top: int | None = None,
    today: date | None = None,
) -> dict:
    requested = source.lower().strip()
    active_source = _normalize_source(source, public_value="nasdaq")
    if active_source == "sample" and not universe_path.exists():
        refresh_options_universe(universe_path, source="sample")

    entries = OptionsUniverse.load(universe_path, top_n=top)
    warning: str | None = None
    if active_source == "sample":
        rows = _sample_earnings_rows(entries, today=today)
    elif active_source == "nasdaq":
        try:
            rows = _fetch_nasdaq_earnings_rows(entries, today=today)
        except RuntimeError as exc:
            rows = []
            warning = str(exc)
        if requested == "public" and _earnings_need_yfinance_fallback(rows, entries):
            try:
                yfinance_rows = _fetch_yfinance_earnings_rows(entries)
            except RuntimeError as exc:
                yfinance_rows = []
                warning = "; ".join(item for item in (warning, str(exc)) if item)
            if yfinance_rows:
                rows = yfinance_rows
                active_source = "yfinance"
                warning = warning or "nasdaq earnings calendar was sparse; used yfinance"
    elif active_source == "yfinance":
        rows = _fetch_yfinance_earnings_rows(entries)
    else:
        raise ValueError("source must be public, nasdaq, yfinance, or sample")

    existing_count = _existing_earnings_row_count(output_path)
    if active_source != "sample" and not rows:
        if existing_count > 0:
            kept = {
                **_result("earnings", active_source, output_path, existing_count),
                "status": "kept_existing",
                "warning": "public earnings refresh returned no rows; existing calendar was kept",
            }
            if warning:
                kept["warning"] = warning
            return kept
        raise RuntimeError(f"{active_source} earnings refresh returned no rows")
    if (
        active_source != "sample"
        and existing_count >= 50
        and len(rows) < existing_count // 2
    ):
        refreshed_count = len(rows)
        rows = _merge_earnings_rows(output_path, rows)
        warning = "; ".join(
            item
            for item in (
                warning,
                f"merged {refreshed_count} refreshed rows into {existing_count} existing rows",
            )
            if item
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["ticker", "earnings_date"],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    payload = _result("earnings", active_source, output_path, len(rows))
    if warning:
        payload["warning"] = warning
    return payload


def refresh_dividend_events(
    output_path: Path,
    *,
    universe_path: Path,
    source: str = "yfinance",
    top: int | None = None,
) -> dict:
    active_source = _normalize_source(source, public_value="yfinance")
    if active_source == "sample" and not universe_path.exists():
        refresh_options_universe(universe_path, source="sample")
    entries = OptionsUniverse.load(universe_path, top_n=top)
    skipped: list[str] = []
    if active_source == "sample":
        rows = _sample_dividend_rows(entries)
    elif active_source == "yfinance":
        rows, skipped = _fetch_yfinance_dividend_rows(entries)
    else:
        raise ValueError("source must be public, yfinance, or sample")

    if active_source != "sample" and not rows:
        existing_count = _existing_dividend_row_count(output_path)
        if existing_count > 0:
            return {
                **_result("dividends", active_source, output_path, existing_count),
                "status": "kept_existing",
                "warning": (
                    "public dividend refresh returned no rows; "
                    "existing dividend events were kept"
                ),
            }
        raise RuntimeError(f"{active_source} dividend refresh returned no rows")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "ticker",
                "ex_dividend_date",
                "dividend_per_share",
                "source",
                "fetched_at",
            ],
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)
    payload = _result("dividends", active_source, output_path, len(rows))
    if skipped:
        payload["warning"] = (
            f"dividend evidence unavailable for {len(skipped)} ticker(s): "
            + ", ".join(skipped)
        )
    return payload


def _fetch_yfinance_dividend_rows(entries) -> tuple[list[dict[str, str]], list[str]]:
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is required for public dividend refresh") from exc

    fetched_at = datetime.now(UTC).isoformat()
    rows: list[dict[str, str]] = []
    skipped: list[str] = []
    if not entries:
        return rows, skipped
    with ThreadPoolExecutor(max_workers=min(6, len(entries))) as executor:
        futures = {
            executor.submit(_next_dividend_event, yf, _yfinance_ticker(entry.ticker)): entry
            for entry in entries
        }
        results = [(futures[future], future.result()) for future in as_completed(futures)]
    for entry, event in results:
        if event is None:
            # Honest absence: a ticker whose fetch failed keeps no row at all.
            skipped.append(entry.ticker)
            continue
        ex_dividend_date, dividend_per_share = event
        rows.append(
            {
                "ticker": entry.ticker,
                "ex_dividend_date": ex_dividend_date or "",
                "dividend_per_share": repr(dividend_per_share),
                "source": "yfinance",
                "fetched_at": fetched_at,
            }
        )
    return sorted(rows, key=lambda row: row["ticker"]), sorted(skipped)


def fetch_screener_events(
    ticker: str, *, earnings: bool, dividends: bool,
) -> tuple[date | None, tuple[date | None, float] | None]:
    """Read missing event inputs for one requested symbol; never write the universe/cache."""
    try:
        import yfinance as yf
    except ImportError as exc:
        raise RuntimeError("yfinance is required for screener event data") from exc
    symbol = _yfinance_ticker(ticker)
    earnings_date = _next_earnings_date(yf, symbol) if earnings else None
    dividend_event = _next_dividend_event(yf, symbol) if dividends else None
    return (
        date.fromisoformat(earnings_date) if earnings_date else None,
        (
            date.fromisoformat(dividend_event[0]) if dividend_event[0] else None,
            dividend_event[1],
        ) if dividend_event is not None else None,
    )


def _next_dividend_event(yf_module, ticker: str) -> tuple[str | None, float] | None:
    """Return (next ex-dividend date ISO or None, last dividend per share).

    (None, 0.0) is the source's explicit no-dividend assertion: no dividends
    in the last 400 days and no ex-dividend date on the calendar. None means
    the evidence could not be fetched and the ticker stays honestly unknown.
    """
    try:
        instrument = yf_module.Ticker(ticker)
        calendar = instrument.calendar
        dividends = instrument.dividends
    except Exception:
        return None
    ex_dividend_date = _calendar_ex_dividend_date(calendar)
    last_amount = _last_dividend_amount(dividends)
    if ex_dividend_date is None and last_amount is None:
        return None, 0.0
    if last_amount is None:
        return None
    return ex_dividend_date, last_amount


def _calendar_ex_dividend_date(calendar: object) -> str | None:
    if calendar is None:
        return None
    raw = None
    if isinstance(calendar, dict):
        raw = calendar.get("Ex-Dividend Date") or calendar.get("ExDividendDate")
    else:
        try:
            raw = calendar.loc["Ex-Dividend Date"][0]
        except Exception:
            raw = None
    return _coerce_earnings_date(raw)


def _last_dividend_amount(dividends, *, lookback_days: int = 400) -> float | None:
    try:
        items = list(pd.Series(dividends).dropna().items())
    except Exception:
        return None
    if not items:
        return None
    today = datetime.now(UTC).date()
    best: tuple[date, float] | None = None
    for raw_date, raw_amount in items:
        parsed = _coerce_earnings_date(raw_date)
        if parsed is None:
            continue
        try:
            amount = float(raw_amount)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(amount) or amount <= 0:
            continue
        ex_date = date.fromisoformat(parsed)
        if (today - ex_date).days > lookback_days:
            continue
        if best is None or ex_date > best[0]:
            best = (ex_date, amount)
    return best[1] if best is not None else None


def _sample_dividend_rows(entries) -> list[dict[str, str]]:
    fetched_at = datetime.now(UTC).isoformat()
    return [
        {
            "ticker": entry.ticker,
            "ex_dividend_date": "",
            "dividend_per_share": "0.0",
            "source": "sample",
            "fetched_at": fetched_at,
        }
        for entry in entries
    ]


def _existing_dividend_row_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return sum(
            1 for row in reader if row.get("ticker") and row.get("dividend_per_share")
        )


def _earnings_need_yfinance_fallback(rows: list[dict[str, str]], entries) -> bool:
    if not rows:
        return True
    if len(entries) < 10:
        return False
    return len(rows) < min(100, max(len(entries) // 2, 1))


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
            from quant_system.options.market_regime import (
                VIX_CACHE_MAX_AGE_TRADING_DAYS,
            )
            from quant_system.options.vix_data import trading_day_age

            last_obs = existing_vix.index.max()
            age = trading_day_age(last_obs, end_date)
            kept = {
                **_result("vix", active_source, path, len(existing_vix)),
                "status": "kept_existing",
            }
            if age > VIX_CACHE_MAX_AGE_TRADING_DAYS:
                kept["warning"] = (
                    f"vix cache stale: last={pd.Timestamp(last_obs).date()} "
                    f"age_b={age}"
                )
            return kept
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

    if not entries:
        return []
    with ThreadPoolExecutor(max_workers=min(6, len(entries))) as executor:
        futures = {
            executor.submit(_next_earnings_date, yf, _yfinance_ticker(entry.ticker)): entry
            for entry in entries
        }
        rows = [
            {"ticker": futures[future].ticker, "earnings_date": earnings_date}
            for future in as_completed(futures)
            if (earnings_date := future.result())
        ]
    return sorted(rows, key=lambda row: row["ticker"])


def _yfinance_ticker(ticker: str) -> str:
    normalized = ticker.upper().strip()
    return "BRK-B" if normalized == "BRK.B" else normalized


def _nasdaq_ticker(ticker: str) -> str:
    normalized = ticker.upper().strip()
    return "BRK-B" if normalized == "BRK.B" else normalized


def _fetch_nasdaq_earnings_rows(
    entries,
    *,
    today: date | None,
    horizon_days: int = 45,
) -> list[dict[str, str]]:
    canonical_by_provider = {
        _nasdaq_ticker(entry.ticker): entry.ticker.upper().strip()
        for entry in entries
    }
    if not canonical_by_provider:
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
                provider_ticker = (
                    str(row.get("symbol", "")).strip().replace(".", "-").upper()
                )
                ticker = canonical_by_provider.get(provider_ticker)
                if ticker is not None and ticker not in found:
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
    return _coerce_earnings_date(raw)


def _coerce_earnings_date(raw: object) -> str | None:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)):
        for item in raw:
            parsed = _coerce_earnings_date(item)
            if parsed:
                return parsed
        return None
    if isinstance(raw, datetime):
        return raw.date().isoformat()
    if isinstance(raw, date):
        return raw.isoformat()
    if hasattr(raw, "date") and callable(raw.date):
        try:
            extracted = raw.date()
        except Exception:
            extracted = None
        if isinstance(extracted, date):
            return extracted.isoformat()
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


def _merge_earnings_rows(path: Path, rows: list[dict[str, str]]) -> list[dict[str, str]]:
    merged: dict[str, str] = {}
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            ticker = str(row.get("ticker", "")).strip()
            earnings_date = str(row.get("earnings_date", "")).strip()
            if ticker and earnings_date:
                merged[ticker] = earnings_date
    for row in rows:
        merged[str(row["ticker"])] = str(row["earnings_date"])
    return [
        {"ticker": ticker, "earnings_date": merged[ticker]}
        for ticker in sorted(merged)
    ]


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
