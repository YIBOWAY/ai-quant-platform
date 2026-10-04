"""Explicit, bounded checks; install status is not a market-data permission claim."""

from __future__ import annotations

import json
import subprocess
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache

import exchange_calendars as xcals
import pandas as pd

from quant_system.api.schemas.company_research import DataSourceCheckRecord
from quant_system.data.providers.longbridge import (
    LongbridgeClient,
    LongbridgeMarketDataProvider,
    LongbridgeProviderError,
    _daily_row,
    completed_longbridge_sessions,
)
from quant_system.research import company_research as company


@lru_cache(maxsize=4)
def _version(executable: str) -> str | None:
    try:
        result = subprocess.run(
            [executable, "--version"], capture_output=True, text=True, timeout=3, check=True
        )
        return result.stdout.strip()[:80] if result.stdout.startswith("longbridge ") else None
    except (OSError, subprocess.SubprocessError):
        return None


def _installed():
    try:
        path = LongbridgeClient().resolve_executable()
        return True, _version(str(path))
    except LongbridgeProviderError:
        return False, None


def read_checks(settings):
    installed, version = _installed()
    result = {
        "status": "not_checked",
        "checked_at": None,
        "symbol": None,
        "default_provider": "futu",
        "backup_provider": "longbridge",
        "checks": [],
    }
    directory = company._root(settings) / "capabilities"
    path = directory / "current.json"
    if path.exists():
        try:
            stored = DataSourceCheckRecord.model_validate(json.loads(path.read_text())).model_dump()
            if stored["status"] in {"available", "partial"}:
                if not stored["checks"] or not stored["checked_at"] or not stored["symbol"]:
                    raise ValueError("check_evidence_missing")
                keys = [row["key"] for row in stored["checks"]]
                if len(keys) != len(set(keys)):
                    raise ValueError("check_evidence_duplicate")
                available = sum(row["status"] == "available" for row in stored["checks"])
                if available == 0 or (stored["status"] == "available" and available != len(keys)):
                    raise ValueError("check_status_mismatch")
            if stored.get("checked_at"):
                stamp = datetime.fromisoformat(stored["checked_at"])
                if stamp.tzinfo is None or stamp > datetime.now(UTC):
                    raise ValueError("future_check")
            result.update(stored)
            if result["status"] == "updating" and not company._active(directory):
                result.update(status="failed", reason="上次能力检查已中断，请重新检查。")
        except (OSError, ValueError, TypeError):
            result.update(status="failed", reason="能力检查记录无法读取。")
    result["sources"] = [
        {
            "provider": "futu",
            "installed": settings.futu.enabled,
            "version": None,
            "status": "configured" if settings.futu.enabled else "disabled",
            "reason": None,
        },
        {
            "provider": "longbridge",
            "installed": installed,
            "version": version,
            "status": "installed" if installed else "not_installed",
            "reason": "安装状态不代表所有行情权限已开通。",
        },
    ]
    return result


def _valid_quote(data, symbol, *, primary=False):
    rows = [data] if primary else data
    if not isinstance(rows, list):
        raise LongbridgeProviderError("invalid_data")
    found = [row for row in rows if isinstance(row, dict) and row.get("symbol") == symbol]
    if len(found) != 1:
        raise LongbridgeProviderError("invalid_data")
    price = company._number(found[0].get("last", found[0].get("last_done")))
    if price is None or price <= 0:
        raise LongbridgeProviderError("invalid_data")


def _valid_recent(data, symbol, *, now=None):
    if not isinstance(data, list):
        raise LongbridgeProviderError("invalid_data")
    clock = pd.Timestamp(now) if now is not None else pd.Timestamp.now(tz="UTC")
    market = symbol.rsplit(".", 1)[1]
    days = []
    for raw in data:
        _, day = _daily_row(raw, symbol, symbol, market, clock)
        if day > clock.date():
            raise LongbridgeProviderError("invalid_data")
        days.append(day)
    if not days or len(set(days)) != len(days):
        raise LongbridgeProviderError("invalid_data")
    completed = completed_longbridge_sessions(symbol, start=min(days), end=max(days), as_of=clock)
    latest_sessions = completed_longbridge_sessions(
        symbol,
        start=clock.date() - timedelta(days=14),
        end=clock.date(),
        as_of=clock,
    )
    if (
        not completed
        or not set(completed).issubset(days)
        or not latest_sessions
        or max(completed) != latest_sessions[-1]
    ):
        raise LongbridgeProviderError("incomplete_data")


def _valid_financials(data, _symbol):
    if not isinstance(data, dict) or data.get("report") != "qf":
        raise LongbridgeProviderError("invalid_data")
    analysis = company.analyze_statements({"IS": data})
    if analysis["status"] == "invalid" or not any(
        row.get("revenue") is not None for row in analysis.get("periods", [])
    ):
        raise LongbridgeProviderError("invalid_data")


def _valid_expiries(data, _symbol):
    if not isinstance(data, list):
        raise LongbridgeProviderError("invalid_data")
    try:
        for row in data:
            date.fromisoformat(row["expiry_date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise LongbridgeProviderError("invalid_data") from exc


def _valid_strikes(data, symbol):
    if not isinstance(data, list):
        raise LongbridgeProviderError("invalid_data")
    for row in data:
        if not isinstance(row, dict) or (company._number(row.get("strike")) or 0) <= 0:
            raise LongbridgeProviderError("invalid_data")
        contract = row.get("put_symbol") or row.get("call_symbol")
        if not isinstance(contract, str) or not contract.startswith(symbol[:-3]):
            raise LongbridgeProviderError("invalid_data")


def _valid_option_quote(data, symbol):
    rows = (
        [row for row in data if isinstance(row, dict) and row.get("symbol") == symbol]
        if isinstance(data, list)
        else []
    )
    if len(rows) != 1:
        raise LongbridgeProviderError("invalid_data")
    # A quoted, untraded option can legitimately have last=0. This checks data
    # permission, not liquidity or whether its last is an executable price.
    price = company._number(rows[0].get("last", rows[0].get("last_done")))
    if price is None or price < 0:
        raise LongbridgeProviderError("invalid_data")


def begin_checks(settings, symbol):
    symbol = company.normalize_longbridge_symbol(symbol)
    directory = company._root(settings) / "capabilities"
    stream = company._try_lock(directory / "refresh.lock")
    if stream is None:
        raise company.ResearchBusy("数据源能力正在检查。")
    lease = company.RefreshLease([stream])
    try:
        company._write(
            directory / "current.json",
            {
                "status": "updating",
                "checked_at": None,
                "symbol": symbol,
                "default_provider": "futu",
                "backup_provider": "longbridge",
                "checks": [],
            },
        )
        return lease
    except Exception:
        lease.close()
        raise


def collect_checks(settings, symbol, *, client=None, quote_reader=company._primary_quote):
    symbol = company.normalize_longbridge_symbol(symbol)
    client = client or LongbridgeClient()
    checks = []

    def check(key, label, callback, validator=None):
        try:
            data = callback()
            empty = data is None or data == [] or data == {}
            if isinstance(data, dict) and "list" in data:
                empty = not data["list"]
            if not empty and validator:
                validator(data, symbol)
            checks.append(
                {
                    "key": key,
                    "label": label,
                    "status": "empty" if empty else "available",
                    "reason": "empty_response" if empty else None,
                    "detail": f"本次检查标的：{symbol}；不代表所有标的或长期稳定性。",
                }
            )
            return data
        except Exception as exc:
            checks.append(
                {
                    "key": key,
                    "label": label,
                    "status": "unavailable",
                    "reason": company._reason(exc),
                    "detail": None,
                }
            )
            return None

    check(
        "futu_quote",
        "Futu 报价",
        lambda: quote_reader(settings, symbol),
        lambda data, sym: _valid_quote(data, sym, primary=True),
    )
    check(
        "longbridge_quote", "Longbridge 报价", lambda: client.request("quote", symbol), _valid_quote
    )
    check(
        "longbridge_recent",
        "Longbridge 最近已收盘日线",
        lambda: client.request("kline", symbol, count=5, adjust="forward", period="day"),
        _valid_recent,
    )
    # Permission check only; every item carries its own status. Never use recent
    # candles as a replacement for this exact date-range request.
    market = symbol.rsplit(".", 1)[1]
    calendar = xcals.get_calendar(
        {"US": "XNYS", "HK": "XHKG", "SH": "XSHG", "SZ": "XSHG", "SG": "XSES"}[market]
    )
    now = pd.Timestamp.now(tz="UTC")
    last = calendar.date_to_session(now.tz_convert(calendar.tz).date(), direction="previous")
    if calendar.session_close(last) > now:
        last = calendar.previous_session(last)
    start = (last.date() - timedelta(days=7)).isoformat()
    check(
        "longbridge_history",
        "Longbridge 指定日期历史日线",
        lambda: {
            "row_count": len(
                LongbridgeMarketDataProvider(client).fetch_ohlcv(
                    [symbol], start=start, end=last.date().isoformat()
                )
            )
        },
    )
    check(
        "longbridge_financials",
        "Longbridge 季度财报",
        lambda: client.request("financial_statement", symbol, kind="IS", report="qf"),
        _valid_financials,
    )
    if market == "US":
        dates = check(
            "longbridge_option_chain",
            "Longbridge 期权到期日",
            lambda: client.request("option_chain", symbol),
            _valid_expiries,
        )
        future = sorted(
            str(row.get("expiry_date", ""))
            for row in (dates or [])
            if isinstance(row, dict) and str(row.get("expiry_date", "")) >= now.date().isoformat()
        )
        if future:
            strikes = check(
                "longbridge_option_strikes",
                "Longbridge 期权行权价列表",
                lambda: client.request("option_chain", symbol, expiry=future[0]),
                _valid_strikes,
            )
            contract = next(
                (
                    row.get("put_symbol")
                    for row in (strikes or [])
                    if isinstance(row, dict) and row.get("put_symbol")
                ),
                None,
            )
            if contract:
                check(
                    "longbridge_option_quote",
                    "Longbridge 期权报价权限",
                    lambda: client.request("option_quote", contract),
                    lambda data, _sym: _valid_option_quote(data, contract),
                )
        if not any(row["key"] == "longbridge_option_quote" for row in checks):
            checks.append(
                {
                    "key": "longbridge_option_quote",
                    "label": "Longbridge 期权报价权限",
                    "status": "unavailable",
                    "reason": "no_current_contract_for_probe",
                    "detail": "未取得可检查的当前合约，不能据股票行情确认期权权限。",
                }
            )
    success = sum(row["status"] == "available" for row in checks)
    return {
        "status": "available" if success == len(checks) else "partial" if success else "failed",
        "checked_at": company._now(),
        "symbol": symbol,
        "checks": checks,
        "default_provider": "futu",
        "backup_provider": "longbridge",
    }


def finish_checks(settings, symbol, lease, *, client=None):
    try:
        result = collect_checks(settings, symbol, client=client)
        company._write(company._root(settings) / "capabilities" / "current.json", result)
    except Exception:
        company._write(
            company._root(settings) / "capabilities" / "current.json",
            {
                "status": "failed",
                "checked_at": company._now(),
                "symbol": symbol,
                "checks": [],
                "reason": "检查未完整完成，不能认定数据源已就绪。",
            },
        )
    finally:
        lease.close()
