"""Public, dated valuation inputs; no demonstration data or provider substitution."""

from __future__ import annotations

import calendar
import csv
import html
import json
import math
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from io import StringIO
from statistics import median
from typing import Any

import httpx

ISHARES_PRODUCTS = {
    "EWY": "239681",
    "EWT": "239686",
    "EWJ": "239665",
    "INDA": "239659",
    "EIDO": "239661",
    "EWH": "239657",
    "EWS": "239678",
    "THD": "239688",
    "EWM": "239669",
    "EWA": "239607",
    "EPHE": "239675",
}
MULTPL_SERIES = {
    "cape": "shiller-pe",
    "pe": "s-p-500-pe-ratio",
    "pb": "s-p-500-price-to-book",
}


def _download(url: str) -> str:
    response = httpx.get(
        url,
        timeout=20.0,
        follow_redirects=True,
        headers={
            "User-Agent": "Mozilla/5.0 (local market research)",
            "Accept": "text/html,text/csv",
        },
    )
    response.raise_for_status()
    if len(response.content) > 4_000_000:
        raise ValueError("source_response_too_large")
    return response.text


def _positive(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def parse_multpl_history(text: str, *, as_of: date) -> list[tuple[date, float, bool]]:
    table = re.search(r'<table[^>]+id=["\']datatable["\'][^>]*>(.*?)</table>', text, re.S)
    if table is None:
        raise ValueError("valuation_table_missing")
    observations = {}
    for row in re.findall(r"<tr\b[^>]*>(.*?)</tr>", table.group(1), re.S):
        cells = re.findall(r"<td\b[^>]*>(.*?)</td>", row, re.S)
        if len(cells) != 2:
            continue
        cleaned = [html.unescape(re.sub(r"<[^>]+>", "", cell)).strip() for cell in cells]
        try:
            observed = datetime.strptime(cleaned[0], "%b %d, %Y").date()
        except ValueError:
            continue
        estimated = "†" in cleaned[1]
        value = _positive(cleaned[1].replace(",", "").replace("†", "").strip())
        if value is not None and as_of - timedelta(days=3660) <= observed <= as_of:
            if observed in observations and observations[observed] != (value, estimated):
                raise ValueError("valuation_date_conflict")
            observations[observed] = (value, estimated)
    return [(day, *values) for day, values in sorted(observations.items())]


def _history_reference(observations: list[tuple[date, float]], frequency: str) -> dict | None:
    """Describe exactly the prior observations used for comparison, without today's value."""
    if not observations:
        return None
    values = [value for _, value in observations]
    return {
        "samples": len(values),
        "frequency": frequency,
        "start_date": observations[0][0].isoformat(),
        "end_date": observations[-1][0].isoformat(),
        "minimum": round(min(values), 4),
        "median": round(median(values), 4),
        "maximum": round(max(values), 4),
    }


def fetch_us_valuations(*, as_of: date, download=_download) -> dict[str, dict]:
    def fetch(item):
        key, slug = item
        url = f"https://www.multpl.com/{slug}/table/by-month"
        try:
            history = parse_multpl_history(download(url), as_of=as_of)
            if not history or (as_of - history[-1][0]).days > 45:
                raise ValueError("valuation_history_stale_or_missing")
            latest_date, value, estimated = history[-1]
            # One sample per prior month; today's observation is not its own baseline.
            period_format = "%Y" if key == "pb" else "%Y-%m"
            periods = {
                day.strftime(period_format): (day, number)
                for day, number, _ in history[:-1]
                if day.strftime(period_format) != latest_date.strftime(period_format)
            }
            prior_observations = list(periods.values())[-(10 if key == "pb" else 120) :]
            baseline = [number for _, number in prior_observations]
            if len(baseline) < (8 if key == "pb" else 60):
                raise ValueError("valuation_history_too_short")
            percentile = 100 * sum(number <= value for number in baseline) / len(baseline)
            return key, {
                "value": value,
                "score": round(percentile, 2),
                "source_date": latest_date.isoformat(),
                "source_url": url,
                "samples": len(baseline),
                "frequency": "year" if key == "pb" else "month",
                "history_reference": _history_reference(
                    prior_observations, "year" if key == "pb" else "month"
                ),
                "estimated": estimated,
                "error": None,
            }
        except (httpx.HTTPError, ValueError) as exc:
            return key, {
                "source_url": url,
                "error": type(exc).__name__
                + ":"
                + (str(exc) if isinstance(exc, ValueError) else "source_unavailable"),
            }

    with ThreadPoolExecutor(max_workers=3) as pool:
        return dict(pool.map(fetch, MULTPL_SERIES.items()))


def _download_fred(url: str) -> str:
    # Native curl succeeds on this host where Python's FRED requests stall.
    # This is the sole FRED transport, with one bounded request and no retry.
    return subprocess.run(
        ["curl", "-fsSL", "--max-time", "20", url],
        capture_output=True,
        text=True,
        check=True,
        timeout=25,
    ).stdout


def fetch_treasury_spread(*, as_of: date, download=_download_fred) -> dict:
    url = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=T10Y2Y"
    try:
        text = download(url + f"&cosd={(as_of - timedelta(days=370)).isoformat()}")
        rows = csv.DictReader(StringIO(text))
        if rows.fieldnames != ["observation_date", "T10Y2Y"]:
            raise ValueError("treasury_csv_contract_invalid")
        history = {}
        for row in rows:
            observed = date.fromisoformat(row["observation_date"])
            if row["T10Y2Y"] in {"", "."}:
                continue
            value = float(row["T10Y2Y"])
            if math.isfinite(value) and as_of - timedelta(days=370) <= observed <= as_of:
                history[observed] = value
        ordered = sorted(history.items())
        if not ordered or (as_of - ordered[-1][0]).days > 7:
            raise ValueError("treasury_history_stale_or_missing")
        observed, value = ordered[-1]
        prior_observations = [
            (day, number) for day, number in ordered[:-1] if day >= observed - timedelta(days=180)
        ]
        recently_inverted = any(
            number < 0 for _, number in prior_observations
        )
        score = 80.0 if value < 0 else 65.0 if recently_inverted else 25.0
        return {
            "value": value,
            "score": score,
            "source_date": observed.isoformat(),
            "source_url": url,
            "recently_inverted": recently_inverted,
            "history_reference": _history_reference(prior_observations, "day"),
            "error": None,
        }
    except (httpx.HTTPError, ValueError, subprocess.SubprocessError, OSError) as exc:
        return {
            "source_url": url,
            "error": type(exc).__name__
            + ":"
            + (str(exc) if isinstance(exc, ValueError) else "source_unavailable"),
        }


def _quarterly_values(text: str, series_id: str, *, as_of: date) -> dict[date, float]:
    reader = csv.DictReader(StringIO(text))
    if reader.fieldnames != ["observation_date", series_id]:
        raise ValueError("buffett_csv_contract_invalid")
    values = {}
    for row in reader:
        day = date.fromisoformat(row["observation_date"])
        if day.day != 1 or day.month not in {1, 4, 7, 10}:
            raise ValueError("buffett_quarter_invalid")
        quarter_end = date(day.year, day.month + 2, calendar.monthrange(day.year, day.month + 2)[1])
        value = _positive(row[series_id])
        if value is None or quarter_end > as_of or day.year < 1997:
            continue
        if day in values and values[day] != value:
            raise ValueError("buffett_quarter_conflict")
        values[day] = value
    return values


def fetch_buffett_indicator(*, as_of: date, download=_download_fred) -> dict:
    """Quarter-end domestic public equity value / matching annualized nominal GDP.

    Latest-vintage observations, not a point-in-time backtest dataset. The Fed
    series includes closely held shares before 1996Q4, so that earlier range
    is not used. A source publication date is required, never inferred.
    """
    cap_id = "BOGZ1LM883164115Q"
    source_urls = {
        "market_cap": f"https://fred.stlouisfed.org/series/{cap_id}",
        "gdp": "https://fred.stlouisfed.org/series/GDP",
        "release": "https://www.federalreserve.gov/releases/z1/",
    }
    base = {"source_url": source_urls["market_cap"], "source_urls": source_urls}
    start = f"{max(1997, as_of.year - 21)}-01-01"
    urls = [
        f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={name}&cosd={start}"
        for name in (cap_id, "GDP")
    ] + [source_urls["release"]]
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:
            cap_text, gdp_text, release_html = pool.map(download, urls)
        release_text = html.unescape(re.sub(r"<[^>]+>", " ", release_html))
        release = re.search(
            r"Release Date:\s*([A-Za-z]+\s+\d{1,2},\s+\d{4})\s+(\d{4}):Q([1-4])\s+Release",
            release_text,
        )
        if release is None:
            raise ValueError("buffett_release_date_missing")
        release_date = datetime.strptime(release[1], "%B %d, %Y").date()
        if release_date > as_of:
            raise ValueError("buffett_release_after_asof")
        cap = _quarterly_values(cap_text, cap_id, as_of=as_of)
        gdp = _quarterly_values(gdp_text, "GDP", as_of=as_of)
        common = sorted(cap.keys() & gdp.keys())
        if len(common) < 21:
            raise ValueError("buffett_history_too_short")
        latest = common[-1]
        period = f"{latest.year}Q{(latest.month - 1) // 3 + 1}"
        if period != f"{release[2]}Q{release[3]}":
            raise ValueError("buffett_release_period_mismatch")
        # Fed market capitalization: USD millions. BEA nominal GDP: USD billions, SAAR.
        value = cap[latest] / (gdp[latest] * 1000) * 100
        prior_observations = [
            (
                date(day.year, day.month + 2, calendar.monthrange(day.year, day.month + 2)[1]),
                cap[day] / (gdp[day] * 1000) * 100,
            )
            for day in common[:-1][-80:]
        ]
        baseline = [number for _, number in prior_observations]
        quarter_end = date(
            latest.year, latest.month + 2, calendar.monthrange(latest.year, latest.month + 2)[1]
        )
        return {
            **base,
            "value": round(value, 4),
            "score": round(100 * sum(item <= value for item in baseline) / len(baseline), 2),
            "source_date": quarter_end.isoformat(),
            "period": period,
            "release_date": release_date.isoformat(),
            "samples": len(baseline),
            "history_reference": _history_reference(prior_observations, "quarter"),
            "market_cap": cap[latest],
            "market_cap_unit": "USD millions, quarter end",
            "gdp": gdp[latest],
            "gdp_unit": "USD billions, nominal SAAR",
            "error": None,
        }
    except (ValueError, OSError, subprocess.SubprocessError, httpx.HTTPError) as exc:
        return {
            **base,
            "value": None,
            "score": None,
            "source_date": None,
            "period": None,
            "release_date": None,
            "error": type(exc).__name__
            + ":"
            + (str(exc) if isinstance(exc, ValueError) else "source_unavailable"),
        }


class _IssuerData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ticker = None
        self.metrics: dict[str, dict] = {}

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        raw = attributes.get("componentprops")
        if not raw:
            return
        try:
            payload = json.loads(raw)
        except ValueError:
            return
        if attributes.get("componentkey") == "ProductIdSetterForPPContainerV3":
            self.ticker = payload.get("ticker")
        self._walk(payload)

    def _walk(self, payload):
        if isinstance(payload, list):
            for item in payload:
                self._walk(item)
        elif isinstance(payload, dict):
            name = payload.get("name")
            value = _positive(payload.get("value"))
            if name in {"priceEarnings", "priceBook"} and value is not None:
                try:
                    observed = datetime.strptime(str(payload["asOfDate"]), "%Y%m%d").date()
                except (KeyError, ValueError):
                    pass
                else:
                    self.metrics["pe" if name == "priceEarnings" else "pb"] = {
                        "value": value,
                        "source_date": observed.isoformat(),
                    }
            for item in payload.values():
                self._walk(item)


def parse_ishares_valuation(text: str, *, ticker: str, as_of: date) -> dict:
    parser = _IssuerData()
    parser.feed(text)
    if parser.ticker != ticker:
        raise ValueError("issuer_ticker_mismatch")
    valid = {}
    for key, metric in parser.metrics.items():
        observed = date.fromisoformat(metric["source_date"])
        if 0 <= (as_of - observed).days <= 14:
            valid[key] = metric
    if not valid:
        raise ValueError("issuer_valuation_stale_or_missing")
    return valid


def fetch_asia_valuations(symbols: tuple[str, ...], *, as_of: date, download=_download) -> dict:
    def fetch(ticker):
        if ticker == "ASHR":
            # The US fund (US2330518794), not the similarly named UCITS listing.
            # This records a source investigation, not a valuation or a fresh fetch.
            return ticker, {
                "source_url": "https://etf.dws.com/en-us/ASHR-harvest-csi-300-china-a-shares-etf/",
                "searched_date": "2026-09-05",
                "error": (
                    "issuer_valuation_unavailable:2026-09-05核查DWS美国ASHR公开数据接口"
                    "未找到可核验的PE/PB，文档目录为空；不使用同名UCITS基金或旧报告估计"
                ),
            }
        product = ISHARES_PRODUCTS.get(ticker)
        if product is None:
            return ticker, {"source_url": None, "error": "issuer_source_not_connected"}
        url = f"https://www.ishares.com/us/products/{product}/{ticker}"
        try:
            return ticker, {
                **parse_ishares_valuation(download(url), ticker=ticker, as_of=as_of),
                "source_url": url,
                "error": None,
            }
        except (httpx.HTTPError, ValueError) as exc:
            return ticker, {
                "source_url": url,
                "error": type(exc).__name__
                + ":"
                + (str(exc) if isinstance(exc, ValueError) else "source_unavailable"),
            }

    with ThreadPoolExecutor(max_workers=3) as pool:
        return dict(pool.map(fetch, symbols))
