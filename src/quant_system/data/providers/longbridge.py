"""Bounded, read-only Longbridge CLI transport and attributed daily bars.

Authentication belongs to the installed CLI. This adapter never opens credential
files, accepts arbitrary commands, or calls any account/trading operation.
"""

from __future__ import annotations

import json
import math
import os
import re
import selectors
import shutil
import signal
import subprocess
import threading
import time
from contextlib import suppress
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import exchange_calendars
import pandas as pd

from quant_system.data.schema import normalize_ohlcv_dataframe

_OPERATIONS: dict[str, tuple[tuple[str, ...], frozenset[str]]] = {
    "quote": (("quote",), frozenset()),
    "static": (("static",), frozenset()),
    "calc_index": (("calc-index",), frozenset({"fields"})),
    "kline": (("kline",), frozenset({"count", "period", "adjust"})),
    "history": (("kline", "history"), frozenset({"start", "end", "period", "adjust"})),
    "financial_statement": (("financial-statement",), frozenset({"kind", "report"})),
    "company": (("company",), frozenset()),
    "segments": (("business-segments",), frozenset({"report"})),
    "dividend": (("dividend",), frozenset()),
    "corporate_actions": (("corp-action",), frozenset()),
    "news": (("news",), frozenset({"count"})),
    "filing": (("filing",), frozenset({"count"})),
    "consensus": (("consensus",), frozenset()),
    "institution_rating": (("institution-rating",), frozenset()),
    "insider_trades": (("insider-trades",), frozenset({"count"})),
    "option_chain": (("option", "chain"), frozenset({"expiry"})),
    "option_quote": (("option", "quote"), frozenset()),
}
_INDEX_FIELDS = frozenset(
    [
        "last_done",
        "change_value",
        "change_rate",
        "vol",
        "turnover",
        "ytd_change_rate",
        "turnover_rate",
        "mktcap",
        "capital_flow",
        "amplitude",
        "volume_ratio",
        "pe",
        "pb",
        "dps_rate",
        "five_day_change_rate",
        "ten_day_change_rate",
        "half_year_change_rate",
        "five_minutes_change_rate",
        "iv",
        "delta",
        "gamma",
        "theta",
        "vega",
        "rho",
        "oi",
        "exp",
        "strike",
        "upper_strike_price",
        "lower_strike_price",
        "outstanding_qty",
        "outstanding_ratio",
        "premium",
        "itm_otm",
        "warrant_delta",
        "call_price",
        "to_call_price",
        "effective_leverage",
        "leverage_ratio",
        "conversion_ratio",
        "balance_point",
    ]
)
_MESSAGES = {
    "not_installed": "Longbridge CLI is not installed or executable",
    "invalid_params": "Longbridge request parameters are not supported",
    "invalid_symbol": "Longbridge symbol is invalid or unsupported",
    "unsupported_interval": "Longbridge daily bars only support interval 1d",
    "permission_denied": "Longbridge permission does not allow this data request",
    "quota_exceeded": "Longbridge historical data quota is exhausted",
    "rate_limited": "Longbridge data request was rate limited",
    "timeout": "Longbridge data request timed out",
    "invalid_json": "Longbridge did not return valid JSON",
    "empty": "Longbridge returned no data for this request",
    "output_too_large": "Longbridge response exceeded the output limit",
    "provider_failed": "Longbridge data request failed",
    "invalid_data": "Longbridge daily bars failed data validation",
    "incomplete_data": "Longbridge daily bars do not cover all completed requested sessions",
}
_REQUEST_SEMAPHORE = threading.BoundedSemaphore(1)
_LAST_REQUEST_STARTED: dict[str, float] = {}
_MIN_REQUEST_INTERVAL = 1.05
_MAX_STDOUT = 8 * 1024 * 1024
_MAX_STDERR = 256 * 1024
_CALENDARS = {"US": "XNYS", "HK": "XHKG", "SH": "XSHG", "SZ": "XSHG", "SG": "XSES"}
_TIMEZONES = {
    "US": "America/New_York",
    "HK": "Asia/Hong_Kong",
    "SH": "Asia/Shanghai",
    "SZ": "Asia/Shanghai",
    "SG": "Asia/Singapore",
}


class LongbridgeProviderError(RuntimeError):
    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code if code in _MESSAGES else "provider_failed"
        # Only fixed messages cross the boundary; raw CLI errors may contain secrets.
        self.message = _MESSAGES[self.code]
        super().__init__(self.message)


def normalize_longbridge_symbol(symbol: str) -> str:
    """Accept platform US prefixes/bare tickers and canonical market suffixes."""
    if not isinstance(symbol, str):
        raise LongbridgeProviderError("invalid_symbol")
    value = symbol.strip().upper()
    if not value or len(value) > 40 or not re.fullmatch(r"[A-Z0-9.\-]+", value):
        raise LongbridgeProviderError("invalid_symbol")
    if "." in value and value.split(".", 1)[0] in _CALENDARS:
        market, code = value.split(".", 1)
    elif "." in value and value.rsplit(".", 1)[-1] in _CALENDARS:
        code, market = value.rsplit(".", 1)
    else:
        # A suffix-looking unsupported market must not become a US share class.
        if value.rsplit(".", 1)[-1] in {"HAS", "JP", "UK", "DE", "AU", "CN"}:
            raise LongbridgeProviderError("invalid_symbol")
        market, code = "US", value
    if market == "HK":
        if not re.fullmatch(r"[0-9]{1,5}", code) or int(code) == 0:
            raise LongbridgeProviderError("invalid_symbol")
        code = str(int(code))
    elif market in {"SH", "SZ"}:
        if not re.fullmatch(r"[0-9]{6}", code):
            raise LongbridgeProviderError("invalid_symbol")
    elif not re.fullmatch(r"\.?[A-Z][A-Z0-9]*(?:[.\-][A-Z0-9]+)*", code):
        raise LongbridgeProviderError("invalid_symbol")
    return f"{code}.{market}"


def _iso_date(value: Any) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise LongbridgeProviderError("invalid_params")
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise LongbridgeProviderError("invalid_params") from exc


class LongbridgeClient:
    def __init__(self, executable: str | None = None, timeout_seconds: float = 20) -> None:
        if isinstance(timeout_seconds, bool) or not 0 < timeout_seconds <= 120:
            raise LongbridgeProviderError("invalid_params")
        self.timeout_seconds = float(timeout_seconds)
        self.executable = executable

    def resolve_executable(self) -> str:
        """Resolve the installed executable without reading credentials or data."""
        return self._resolve_executable()

    def _resolve_executable(self) -> str:
        if self.executable is not None:
            candidate = shutil.which(self.executable)
            if candidate:
                return str(Path(candidate).resolve())
            raise LongbridgeProviderError("not_installed")
        candidates = [
            shutil.which("longbridge"),
            "/opt/homebrew/bin/longbridge",
            "/usr/local/bin/longbridge",
            str(Path.home() / ".local/bin/longbridge"),
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file() and os.access(candidate, os.X_OK):
                self.executable = str(Path(candidate).resolve())
                return self.executable
        raise LongbridgeProviderError("not_installed")

    def request(self, operation: str, symbol: str, **params: Any) -> Any:
        if not isinstance(operation, str) or operation not in _OPERATIONS:
            raise LongbridgeProviderError("invalid_params")
        command, allowed = _OPERATIONS[operation]
        if set(params) - allowed:
            raise LongbridgeProviderError("invalid_params")
        normalized = normalize_longbridge_symbol(symbol)
        if operation in {
            "insider_trades",
            "option_chain",
            "option_quote",
        } and not normalized.endswith(".US"):
            raise LongbridgeProviderError("invalid_symbol")
        if operation == "option_quote":
            contract = re.fullmatch(r"[A-Z][A-Z0-9.]*([0-9]{6})[CP][0-9]{1,9}\.US", normalized)
            if contract is None:
                raise LongbridgeProviderError("invalid_symbol")
            try:
                datetime.strptime(contract.group(1), "%y%m%d")
            except ValueError as exc:
                raise LongbridgeProviderError("invalid_symbol") from exc
        argv = [*command, normalized]
        if operation == "history":
            if not {"start", "end"}.issubset(params):
                raise LongbridgeProviderError("invalid_params")
            if _iso_date(params["start"]) > _iso_date(params["end"]):
                raise LongbridgeProviderError("invalid_params")
        if operation == "segments" and "report" in params:
            argv.append("--history")
        for key, value in params.items():
            if key == "count":
                if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1000:
                    raise LongbridgeProviderError("invalid_params")
            elif key in {"start", "end", "expiry"}:
                value = _iso_date(value)
            elif key == "fields":
                fields = value.split(",") if isinstance(value, str) else value
                if (
                    not isinstance(fields, (list, tuple))
                    or not fields
                    or any(
                        not isinstance(item, str) or item not in _INDEX_FIELDS for item in fields
                    )
                    or len(set(fields)) != len(fields)
                ):
                    raise LongbridgeProviderError("invalid_params")
                value = ",".join(fields)
            else:
                choices = {
                    "report": {"qf", "af"},
                    "kind": {"IS", "BS", "CF"},
                    "period": {"day"},
                    "adjust": {"forward", "none"},
                }
                if not isinstance(value, str) or value not in choices[key]:
                    raise LongbridgeProviderError("invalid_params")
            argv.extend(("--date" if key == "expiry" else f"--{key}", str(value)))
        argv = [self._resolve_executable(), *argv, "--format", "json"]
        # Inherit only non-credential process essentials. In particular, the CLI
        # must not inherit staging, host overrides, token env vars or debug flags.
        environment = {
            key: os.environ[key]
            for key in ("HOME", "PATH", "LANG", "LC_ALL", "TMPDIR", "SYSTEMROOT")
            if key in os.environ
        }
        if not _REQUEST_SEMAPHORE.acquire(timeout=self.timeout_seconds):
            raise LongbridgeProviderError("timeout")
        try:
            delay = _MIN_REQUEST_INTERVAL - (
                time.monotonic() - _LAST_REQUEST_STARTED.get(operation, 0)
            )
            if delay > 0:
                time.sleep(delay)
            _LAST_REQUEST_STARTED[operation] = time.monotonic()
            stdout, stderr, returncode = self._run(argv, environment)
        finally:
            _REQUEST_SEMAPHORE.release()
        error = _upstream_error(stderr if returncode else b"")
        if error:
            raise LongbridgeProviderError(error)
        if returncode:
            raise LongbridgeProviderError(_upstream_error(stdout) or "provider_failed")
        try:
            payload = json.loads(stdout)
        except (ValueError, UnicodeDecodeError) as exc:
            raise LongbridgeProviderError("invalid_json") from exc
        if isinstance(payload, dict) and (
            payload.get("code") not in (None, 0, "0", 200, "200") or payload.get("error")
        ):
            encoded = json.dumps(payload).encode()
            raise LongbridgeProviderError(_upstream_error(encoded) or "provider_failed")
        content = payload.get("data", payload) if isinstance(payload, dict) else payload
        if content is None or content == [] or content == {}:
            raise LongbridgeProviderError("empty")
        return payload

    def _run(self, argv: list[str], environment: dict[str, str]) -> tuple[bytes, bytes, int]:
        try:
            process = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=environment,
                start_new_session=True,
            )
        except OSError as exc:
            raise LongbridgeProviderError("not_installed") from exc
        outputs = {"stdout": bytearray(), "stderr": bytearray()}
        deadline = time.monotonic() + self.timeout_seconds
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ, "stdout")
                selector.register(process.stderr, selectors.EVENT_READ, "stderr")
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise LongbridgeProviderError("timeout")
                    for key, _ in selector.select(timeout=min(remaining, 0.1)):
                        chunk = os.read(key.fileobj.fileno(), 65536)
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        outputs[key.data].extend(chunk)
                        limit = _MAX_STDOUT if key.data == "stdout" else _MAX_STDERR
                        if len(outputs[key.data]) > limit:
                            raise LongbridgeProviderError("output_too_large")
                try:
                    returncode = process.wait(timeout=max(0.001, deadline - time.monotonic()))
                except subprocess.TimeoutExpired as exc:
                    raise LongbridgeProviderError("timeout") from exc
            return bytes(outputs["stdout"]), bytes(outputs["stderr"]), returncode
        finally:
            # Kill the session group even if the CLI exited but a child still has
            # a pipe open. Never leave a timed-out HTTP worker running in background.
            with suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()


def _upstream_error(raw: bytes) -> str | None:
    text = raw.decode("utf-8", errors="replace").lower()
    if "301607" in text:
        return "quota_exceeded"
    if "301604" in text or "permission denied" in text or "no permission" in text:
        return "permission_denied"
    if "429002" in text or "rate limit" in text:
        return "rate_limited"
    if "timed out" in text or "timeout" in text:
        return "timeout"
    return None


class LongbridgeMarketDataProvider:
    provider_name = "longbridge"
    price_adjustment = "forward"
    MAX_BARS_PER_WINDOW = 900

    def __init__(self, client: LongbridgeClient | None = None) -> None:
        self.client = client if client is not None else LongbridgeClient()

    def fetch_ohlcv(
        self,
        symbols: list[str],
        *,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        if interval != "1d":
            raise LongbridgeProviderError("unsupported_interval")
        start_date, end_date = (
            date.fromisoformat(_iso_date(start)),
            date.fromisoformat(_iso_date(end)),
        )
        if (
            start_date > end_date
            or (end_date - start_date).days > 40 * 366
            or not symbols
            or len(symbols) > 100
        ):
            raise LongbridgeProviderError("invalid_params")
        normalized = [normalize_longbridge_symbol(symbol) for symbol in symbols]
        if len(set(normalized)) != len(normalized):
            raise LongbridgeProviderError("invalid_params")
        fetched_at = _now_utc()
        rows: list[dict[str, Any]] = []
        for symbol, canonical in zip(symbols, normalized, strict=True):
            market = canonical.rsplit(".", 1)[1]
            expected = completed_longbridge_sessions(
                canonical, start=start_date, end=end_date, as_of=fetched_at,
            )
            if not expected:
                raise LongbridgeProviderError("empty")
            seen: set[date] = set()
            for offset in range(0, len(expected), self.MAX_BARS_PER_WINDOW):
                window = expected[offset : offset + self.MAX_BARS_PER_WINDOW]
                payload = self.client.request(
                    "history",
                    canonical,
                    start=window[0].isoformat(),
                    end=window[-1].isoformat(),
                    period="day",
                    adjust="forward",
                )
                if isinstance(payload, dict):
                    payload = payload.get("data")
                if not isinstance(payload, list) or not payload:
                    raise LongbridgeProviderError("empty")
                window_seen: set[date] = set()
                for raw in payload:
                    row, day = _daily_row(raw, canonical, symbol, market, fetched_at)
                    if day in seen or day not in window:
                        raise LongbridgeProviderError("invalid_data")
                    seen.add(day)
                    window_seen.add(day)
                    rows.append(row)
                if window_seen != set(window):
                    raise LongbridgeProviderError("incomplete_data")
        frame = pd.DataFrame(rows)
        frame["knowledge_ts"] = _now_utc()
        return normalize_ohlcv_dataframe(frame, provider=self.provider_name, interval=interval)


def _daily_row(
    raw: Any,
    canonical: str,
    symbol: str,
    market: str,
    fetched_at: pd.Timestamp,
) -> tuple[dict[str, Any], date]:
    try:
        if not isinstance(raw, dict):
            raise ValueError
        if "symbol" in raw and normalize_longbridge_symbol(raw["symbol"]) != canonical:
            raise ValueError
        if raw.get("provider", "longbridge") != "longbridge":
            raise ValueError
        if raw.get("price_adjustment", "forward") != "forward":
            raise ValueError
        stamp = pd.Timestamp(raw.get("time", raw.get("timestamp")))
        if pd.isna(stamp):
            raise ValueError
        # Longbridge daily time is midnight in the exchange timezone, e.g.
        # 04:00Z for a US summer session and 16:00Z on the preceding day for HK.
        local = (
            stamp.tz_localize(_TIMEZONES[market])
            if stamp.tzinfo is None
            else stamp.tz_convert(_TIMEZONES[market])
        )
        day = local.date()
        values = {key: float(raw[key]) for key in ("open", "high", "low", "close", "volume")}
        if any(not math.isfinite(value) for value in values.values()):
            raise ValueError
        if (
            any(values[key] <= 0 for key in ("open", "high", "low", "close"))
            or values["volume"] < 0
        ):
            raise ValueError
        if values["low"] > min(values["open"], values["close"]) or values["high"] < max(
            values["open"], values["close"]
        ):
            raise ValueError
    except (TypeError, ValueError, KeyError, OverflowError, LongbridgeProviderError) as exc:
        raise LongbridgeProviderError("invalid_data") from exc
    timestamp = pd.Timestamp(day, tz="UTC")
    return {
        "symbol": symbol.upper().strip(),
        "timestamp": timestamp,
        **values,
        "event_ts": timestamp,
        "knowledge_ts": fetched_at,
        "price_adjustment": "forward",
    }, day


def _now_utc() -> pd.Timestamp:
    return pd.Timestamp.now(tz="UTC")


def completed_longbridge_sessions(
    symbol: str, *, start: date, end: date, as_of: pd.Timestamp | None = None,
) -> list[date]:
    """The session coverage required of both live and cached daily bars now."""
    canonical = normalize_longbridge_symbol(symbol)
    market = canonical.rsplit(".", 1)[1]
    clock = pd.Timestamp(as_of) if as_of is not None else _now_utc()
    if pd.isna(clock) or clock.tzinfo is None:
        raise LongbridgeProviderError("invalid_params")
    try:
        calendar = exchange_calendars.get_calendar(
            _CALENDARS[market], start=start - timedelta(days=7), end=end + timedelta(days=7),
        )
        sessions = calendar.sessions_in_range(start, end)
        return [
            session.date() for session in sessions
            if calendar.session_close(session) <= clock
        ]
    except (ValueError, KeyError) as exc:
        raise LongbridgeProviderError("invalid_params") from exc
