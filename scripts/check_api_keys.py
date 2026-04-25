"""Local-only smoke test for the API keys configured in ``.env``.

Run with:

    conda activate ai-quant
    python scripts/check_api_keys.py

The script makes one cheap, read-only request per provider and prints a
concise OK / FAIL summary. It never prints the secret value back.

This file is intentionally not part of the pytest suite because it hits the
public internet and depends on credentials.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

# Make sure ``src/`` is on sys.path when running this as a script.
ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_system.config.settings import reload_settings  # noqa: E402  # isort:skip


TIMEOUT_SECONDS = 15


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str


_DEFAULT_USER_AGENT = "ai-quant-platform/0.1 (+https://github.com/YIBOWAY/ai-quant-platform)"


def _http_json(url: str, headers: dict[str, str] | None = None) -> tuple[int, object]:
    merged = {"User-Agent": _DEFAULT_USER_AGENT, "Accept": "application/json"}
    if headers:
        merged.update(headers)
    request = Request(url, headers=merged)
    try:
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.getcode()
            payload = response.read().decode("utf-8", errors="replace")
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        return exc.code, body
    except URLError as exc:
        raise RuntimeError(f"network error: {exc.reason}") from exc

    try:
        return status, json.loads(payload)
    except json.JSONDecodeError:
        return status, payload


def check_tiingo(token: str) -> CheckResult:
    # /tiingo/daily/AAPL/prices?startDate=...&endDate=... is the same endpoint the
    # production provider uses, so a 200 here proves the token works for OHLCV.
    query = urlencode({"startDate": "2024-01-02", "endDate": "2024-01-02", "format": "json"})
    url = f"https://api.tiingo.com/tiingo/daily/AAPL/prices?{query}"
    try:
        status, body = _http_json(url, {"Authorization": f"Token {token}"})
    except RuntimeError as exc:
        return CheckResult("tiingo", False, str(exc))
    if status == 200 and isinstance(body, list):
        return CheckResult("tiingo", True, f"status=200 rows={len(body)}")
    snippet = str(body)[:80].replace("\n", " ")
    return CheckResult("tiingo", False, f"status={status} body={snippet}")


def check_alpha_vantage(key: str) -> CheckResult:
    # Use GLOBAL_QUOTE — it is the cheapest endpoint and respects the free tier.
    query = urlencode({"function": "GLOBAL_QUOTE", "symbol": "AAPL", "apikey": key})
    url = f"https://www.alphavantage.co/query?{query}"
    try:
        status, body = _http_json(url)
    except RuntimeError as exc:
        return CheckResult("alpha_vantage", False, str(exc))
    if not isinstance(body, dict):
        return CheckResult("alpha_vantage", False, f"status={status} non-json body")
    if "Error Message" in body:
        return CheckResult("alpha_vantage", False, f"status={status} {body['Error Message']}")
    if "Note" in body or "Information" in body:
        # Rate-limited responses still mean the key is recognised.
        msg = body.get("Note") or body.get("Information")
        return CheckResult("alpha_vantage", True, f"status={status} rate-limited: {str(msg)[:60]}")
    ok = "Global Quote" in body and bool(body["Global Quote"])
    return CheckResult("alpha_vantage", ok, f"status={status}")


def check_finnhub(key: str) -> CheckResult:
    url = f"https://finnhub.io/api/v1/quote?symbol=AAPL&token={key}"
    try:
        status, body = _http_json(url)
    except RuntimeError as exc:
        return CheckResult("finnhub", False, str(exc))
    ok = status == 200 and isinstance(body, dict) and "c" in body and body["c"] is not None
    return CheckResult("finnhub", ok, f"status={status}")


def check_twelvedata(key: str) -> CheckResult:
    url = f"https://api.twelvedata.com/quote?symbol=AAPL&apikey={key}"
    try:
        status, body = _http_json(url)
    except RuntimeError as exc:
        return CheckResult("twelvedata", False, str(exc))
    if isinstance(body, dict):
        if str(body.get("status", "")).lower() == "error":
            return CheckResult(
                "twelvedata",
                False,
                f"status={status} {str(body.get('message', ''))[:80]}",
            )
        if "symbol" in body:
            return CheckResult("twelvedata", True, f"status={status}")
    snippet = str(body)[:80].replace("\n", " ")
    return CheckResult("twelvedata", False, f"status={status} body={snippet}")


def check_polygon(key: str) -> CheckResult:
    # /v3/reference/tickers/AAPL is available on every Polygon tier.
    url = f"https://api.polygon.io/v3/reference/tickers/AAPL?apiKey={key}"
    try:
        status, body = _http_json(url)
    except RuntimeError as exc:
        return CheckResult("polygon", False, str(exc))
    ok = status == 200 and isinstance(body, dict) and body.get("status") == "OK"
    return CheckResult("polygon", ok, f"status={status}")


def check_newsapi(key: str) -> CheckResult:
    # Tiny query to keep the daily quota intact.
    url = f"https://newsapi.org/v2/top-headlines?country=us&pageSize=1&apiKey={key}"
    try:
        status, body = _http_json(url)
    except RuntimeError as exc:
        return CheckResult("newsapi", False, str(exc))
    ok = status == 200 and isinstance(body, dict) and body.get("status") == "ok"
    return CheckResult("newsapi", ok, f"status={status}")


def check_twitter_bearer(token: str) -> CheckResult:
    url = "https://api.twitter.com/2/users/by/username/Twitter"
    try:
        status, body = _http_json(url, {"Authorization": f"Bearer {token}"})
    except RuntimeError as exc:
        return CheckResult("twitter_bearer", False, str(exc))
    if status == 401:
        return CheckResult("twitter_bearer", False, "status=401 unauthorized (bad bearer token)")
    if status == 403:
        # 403 here usually means the token is valid but the app does not have
        # the required v2 access level (e.g. free tier without elevated access).
        snippet = str(body)[:80].replace("\n", " ")
        return CheckResult(
            "twitter_bearer",
            False,
            f"status=403 token recognised but plan lacks v2 access. body={snippet}",
        )
    if status == 429:
        return CheckResult("twitter_bearer", True, "status=429 rate-limited (token recognised)")
    ok = status == 200 and isinstance(body, dict) and "data" in body
    return CheckResult("twitter_bearer", ok, f"status={status}")


CHECKS: dict[str, Callable[[str], CheckResult]] = {
    "tiingo_api_token": check_tiingo,
    "alpha_vantage_api_key": check_alpha_vantage,
    "finnhub_api_key": check_finnhub,
    "twelvedata_api_key": check_twelvedata,
    "polygon_api_key": check_polygon,
    "newsapi_key": check_newsapi,
    "twitter_bearer_token": check_twitter_bearer,
}


def main() -> int:
    settings = reload_settings()
    api = settings.api_keys
    results: list[CheckResult] = []

    for field_name, checker in CHECKS.items():
        secret = getattr(api, field_name)
        if secret is None or not secret.get_secret_value():
            results.append(CheckResult(field_name, False, "not configured"))
            continue
        try:
            results.append(checker(secret.get_secret_value()))
        except Exception as exc:  # noqa: BLE001 — surface anything unexpected
            results.append(CheckResult(field_name, False, f"unexpected error: {exc}"))

    print(f"{'provider':<24} {'status':<6} detail")
    print("-" * 70)
    failures = 0
    for result in results:
        status = "OK" if result.ok else "FAIL"
        if not result.ok and result.detail != "not configured":
            failures += 1
        print(f"{result.name:<24} {status:<6} {result.detail}")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
