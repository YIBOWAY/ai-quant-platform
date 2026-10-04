"""Company evidence collection. Saved observations are not backtest-ready factors."""

from __future__ import annotations

import fcntl
import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from quant_system.api.schemas.company_research import CompanyResearchResponse
from quant_system.data.providers.futu import FutuMarketDataProvider
from quant_system.data.providers.longbridge import (
    LongbridgeClient,
    LongbridgeProviderError,
    normalize_longbridge_symbol,
)
from quant_system.research.company_financials import analyze_statements

# Deliberately independent sections: one unavailable endpoint must not invent or
# erase a successful report. None of these operations is a broker account read.
SECTIONS = (
    ("company", "公司概况", "company", {}),
    ("income", "季度利润表", "financial_statement", {"kind": "IS", "report": "qf"}),
    ("balance", "季度资产负债表", "financial_statement", {"kind": "BS", "report": "qf"}),
    ("cashflow", "季度现金流表", "financial_statement", {"kind": "CF", "report": "qf"}),
    ("valuation", "当前估值", "calc_index", {"fields": "pe,pb,dps_rate,mktcap"}),
    ("segments", "业务与地区构成", "segments", {}),
    ("dividends", "分红记录", "dividend", {}),
    ("corporate_actions", "公司行动", "corporate_actions", {}),
    ("news", "公司新闻", "news", {"count": 10}),
    ("filings", "原始公告", "filing", {"count": 10}),
    ("consensus", "盈利预期与历史实际值", "consensus", {}),
    ("ratings", "分析师观点", "institution_rating", {}),
    ("insiders", "内部人交易记录", "insider_trades", {"count": 10}),
)
FRESH_SECONDS = 24 * 3600


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _root(settings) -> Path:
    directory = settings.data.data_dir
    if not directory.is_absolute():
        directory = Path(__file__).resolve().parents[3] / directory
    return directory / "company_research"


def _directory(settings, symbol: str) -> Path:
    return _root(settings) / normalize_longbridge_symbol(symbol)


def _digest(value) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()
    return hashlib.sha256(raw).hexdigest()


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("company_snapshot_path_invalid")
    body = json.dumps(document, ensure_ascii=False, allow_nan=False).encode()
    fd, name = tempfile.mkstemp(prefix=".company-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _empty(symbol: str) -> dict:
    return CompanyResearchResponse(
        symbol=symbol,
        status="not_loaded",
        headline="尚未取得这家公司的研究资料",
        summary=["更新后展示真实财报、公司行动和数据检查；页面读取不会启动研究或交易。"],
    ).model_dump()


class ResearchBusy(RuntimeError):
    pass


@dataclass
class RefreshLease:
    streams: list[Any]

    def close(self):
        for stream in self.streams:
            stream.close()
        self.streams.clear()


def _try_lock(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise ValueError("company_lock_path_invalid")
    stream = path.open("a+")
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        stream.close()
        return None
    return stream


def _active(directory: Path) -> bool:
    path = directory / "refresh.lock"
    if not path.is_file():
        return False
    with path.open("r") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return True
    return False


def read_company(settings, symbol: str) -> dict:
    symbol = normalize_longbridge_symbol(symbol)
    directory = _directory(settings, symbol)
    path = directory / "current.json"
    if not path.exists():
        return _empty(symbol)
    try:
        pointer = json.loads(path.read_text())
        if pointer["symbol"] != symbol:
            raise ValueError("company_snapshot_identity_changed")
        result = _empty(symbol)
        snapshot_id = pointer.get("snapshot_id")
        if snapshot_id:
            if not isinstance(snapshot_id, str) or len(snapshot_id) != 64:
                raise ValueError("company_snapshot_id_invalid")
            if any(char not in "0123456789abcdef" for char in snapshot_id):
                raise ValueError("company_snapshot_id_invalid")
            stored = json.loads((directory / "snapshots" / (snapshot_id + ".json")).read_text())
            if _digest(stored) != snapshot_id or stored["symbol"] != symbol:
                raise ValueError("company_snapshot_changed")
            result = CompanyResearchResponse.model_validate(stored).model_dump()
            result["snapshot_id"] = snapshot_id
        result["status"] = pointer["status"]
        result["error"] = pointer.get("error")
        if result["status"] == "updating" and not _active(directory):
            result.update(status="failed", error="上次更新已中断；已保存结果保留，请重新更新。")
        if result.get("updated_at"):
            updated = datetime.fromisoformat(result["updated_at"])
            if updated.tzinfo is None or updated > datetime.now(UTC):
                raise ValueError("company_snapshot_time_invalid")
            result["stale"] = (datetime.now(UTC) - updated).total_seconds() > FRESH_SECONDS
        return CompanyResearchResponse.model_validate(result).model_dump()
    except (OSError, ValueError, KeyError, TypeError):
        return {**_empty(symbol), "status": "failed", "error": "保存的资料无法通过完整性检查。"}


def begin_refresh(settings, symbol: str) -> RefreshLease:
    symbol = normalize_longbridge_symbol(symbol)
    directory = _directory(settings, symbol)
    stream = _try_lock(directory / "refresh.lock")
    if stream is None:
        raise ResearchBusy("这家公司的资料正在更新。")
    lease = RefreshLease([stream])
    try:
        for index in range(2):
            slot = _try_lock(_root(settings) / f"slot-{index}.lock")
            if slot is not None:
                lease.streams.append(slot)
                break
        else:
            raise ResearchBusy("已有两项数据更新，请稍后再试。")
        previous = read_company(settings, symbol)
        _write(
            directory / "current.json",
            {
                "symbol": symbol,
                "status": "updating",
                "snapshot_id": previous["snapshot_id"],
                "error": None,
                "started_at": _now(),
            },
        )
        return lease
    except Exception:
        lease.close()
        raise


def save_snapshot(settings, document: dict) -> dict:
    stored = CompanyResearchResponse.model_validate(document).model_dump()
    stored["snapshot_id"] = None
    identity = _digest(stored)
    directory = _directory(settings, stored["symbol"])
    path = directory / "snapshots" / (identity + ".json")
    if path.exists():
        if _digest(json.loads(path.read_text())) != identity:
            raise ValueError("company_snapshot_changed")
    else:
        _write(path, stored)
    _write(
        directory / "current.json",
        {
            "symbol": stored["symbol"],
            "status": stored["status"],
            "snapshot_id": identity,
            "error": stored["error"],
        },
    )
    return {**stored, "snapshot_id": identity}


def _reason(exc: Exception) -> str:
    if isinstance(exc, LongbridgeProviderError):
        return exc.code
    from quant_system.data.providers.futu import FutuProviderError

    return exc.code if isinstance(exc, FutuProviderError) else "provider_unavailable"


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (ValueError, TypeError):
        return None
    return number if math.isfinite(number) else None


def _source_url(symbol: str) -> str:
    return "https://longbridge.com/quote/" + symbol


def _section(key, label, operation, symbol, data, *, provider="longbridge", reason=None):
    empty = data is None or data == [] or data == {}
    if operation == "financial_statement" and isinstance(data, dict):
        empty = not data.get("list")
    return {
        "key": key,
        "label": label,
        "status": "unavailable" if reason else "empty" if empty else "available",
        "provider": provider,
        "operation": operation,
        "fetched_at": _now(),
        "source_url": _source_url(symbol)
        if provider == "longbridge"
        else "https://openapi.futunn.com/futu-api-doc/quote/get-market-snapshot.html",
        "raw_sha256": _digest(data) if data is not None else None,
        "reason": reason or ("empty_response" if empty else None),
        "data": data,
    }


def _primary_quote(settings, symbol):
    if not settings.futu.enabled or not symbol.endswith(".US"):
        raise ValueError("primary_quote_unavailable")
    provider = FutuMarketDataProvider(
        host=settings.futu.host,
        port=settings.futu.port,
        request_timeout_seconds=settings.futu.request_timeout_seconds,
    )
    row = provider.fetch_underlying_snapshot(symbol[:-3])
    last = _number(row.get("last"))
    if last is None or last <= 0:
        raise ValueError("primary_quote_invalid")
    return {
        "symbol": symbol,
        "last": last,
        "currency": "USD",
        "as_of": row.get("update_time"),
        "timestamp_kind": "market_local_snapshot_update",
        "price_type": "regular_session_last",
    }


def collect_quote(settings, symbol, *, client, quote_reader=_primary_quote):
    fallbacks = []
    try:
        data = quote_reader(settings, symbol)
        if _number(data.get("last")) is None or float(data["last"]) <= 0:
            raise ValueError("primary_quote_invalid")
        return _section(
            "quote",
            "常规时段报价",
            "market_snapshot",
            symbol,
            {**data, "fallbacks": []},
            provider="futu",
        )
    except Exception as exc:  # a quote read has no financial side effect
        fallbacks.append({"provider": "futu", "code": _reason(exc)})
    try:
        rows = client.request("quote", symbol)
        row = next(x for x in rows if x.get("symbol") == symbol)
        last = _number(row.get("last", row.get("last_done")))
        if last is None or last <= 0:
            raise ValueError("quote_invalid")
        currency = {"US": "USD", "HK": "HKD", "SH": "CNY", "SZ": "CNY", "SG": "SGD"}[
            symbol.rsplit(".", 1)[1]
        ]
        data = {
            "symbol": symbol,
            "last": last,
            "currency": currency,
            "as_of": row.get("timestamp"),
            "price_type": "regular_session_last",
            "pre_market": row.get("pre_market", row.get("pre_market_quote")),
            "post_market": row.get("post_market", row.get("post_market_quote")),
            "overnight": row.get("overnight", row.get("overnight_quote")),
            "fallbacks": fallbacks,
        }
        return _section("quote", "常规时段报价", "quote", symbol, data)
    except Exception as exc:
        fallbacks.append({"provider": "longbridge", "code": _reason(exc)})
        return _section(
            "quote",
            "常规时段报价",
            "quote",
            symbol,
            {"last": None, "fallbacks": fallbacks},
            reason=_reason(exc),
        )


def collect_company(settings, symbol, *, client=None, quote_reader=_primary_quote) -> dict:
    symbol = normalize_longbridge_symbol(symbol)
    client = client or LongbridgeClient()
    sections = [collect_quote(settings, symbol, client=client, quote_reader=quote_reader)]
    for key, label, operation, params in SECTIONS:
        try:
            raw = client.request(operation, symbol, **params)
            section = _section(key, label, operation, symbol, raw)
        except Exception as exc:
            section = _section(key, label, operation, symbol, None, reason=_reason(exc))
        sections.append(section)
    by_key = {section["key"]: section for section in sections}
    financials = analyze_statements(
        {
            kind: by_key[key]["data"]
            for kind, key in (("IS", "income"), ("BS", "balance"), ("CF", "cashflow"))
        }
    )
    warnings = list(financials.get("warnings", []))
    warnings.append("财报日期与抓取日期不等于完整历史可见性；这些指标尚不能直接用于PIT回测。")
    segment = by_key["segments"].get("data")
    if isinstance(segment, dict):
        try:
            end = date.fromisoformat(str(segment["fp_end"]).replace(".", "-"))
            reported = date.fromisoformat(str(segment["rpt_date"]).replace(".", "-"))
            if reported < end:
                warnings.append(
                    "业务构成来源的披露日期早于报告期末，日期口径待核对，不能用作历史事件信号。"
                )
        except (KeyError, ValueError, TypeError):
            warnings.append("业务构成的报告期或披露日期未完整确认。")
    available = sum(s["status"] == "available" for s in sections)
    status = (
        "available"
        if available == len(sections) and financials["status"] == "ok"
        else "partial"
        if available
        else "failed"
    )
    company = by_key["company"]["data"]
    name = (
        (company.get("name") or company.get("company_name"))
        if isinstance(company, dict)
        else symbol
    )
    summary = [f"取得 {available}/{len(sections)} 项资料；缺失项保留原因。"]
    periods = financials.get("periods") or []
    if periods:
        latest = periods[0]
        summary.append(
            f"财务观察使用 {latest['period']}，报告期末 {latest.get('period_end') or '未确认'}。"
        )
    metrics = {item["key"]: item.get("value") for item in financials.get("metrics", [])}
    growth = metrics.get("revenue_yoy_pct")
    if growth is not None:
        summary.append(
            f"该季度营收比去年同季{'增长' if growth >= 0 else '下降'} {abs(growth):.2f}%，"
            "按原始报表数值重算。"
        )
    margin = metrics.get("gross_margin_pct")
    if margin is not None:
        summary.append(f"该季度毛利率为 {margin:.2f}%；尚未扣除研发、管理、利息和税款。")
    cash_ratio = metrics.get("operating_cash_flow_to_net_income_ratio")
    if cash_ratio is not None:
        summary.append(
            f"同季经营现金流约为净利润的 {cash_ratio * 100:.1f}%；"
            "这是现金与账面利润的对照，不直接判定未来收益。"
        )
    checks = financials.get("checks", [])
    failed_checks = sum(item["status"] == "failed" for item in checks)
    passed_checks = sum(item["status"] == "passed" for item in checks)
    if failed_checks:
        summary.append(f"系统检查发现 {failed_checks} 项财务口径冲突，相关比率已留空。")
    elif passed_checks:
        summary.append(f"已完成 {passed_checks} 项报表一致性检查；未知项另列，不算通过。")
    return CompanyResearchResponse(
        symbol=symbol,
        status=status,
        updated_at=_now(),
        headline=f"{name or symbol} · 公司研究",
        summary=summary,
        sections=sections,
        financials=financials,
        research_ideas=financials.get("research_ideas", []),
        warnings=warnings,
    ).model_dump()


def finish_refresh(settings, symbol, lease, *, client=None, quote_reader=_primary_quote):
    try:
        document = collect_company(settings, symbol, client=client, quote_reader=quote_reader)
        if document["status"] == "failed":
            # Keep failed attempts, but never replace the last useful snapshot.
            _write(
                _directory(settings, symbol) / "attempts" / (_digest(document) + ".json"), document
            )
            raise ValueError("all_company_sources_unavailable")
        return save_snapshot(settings, document)
    except Exception:
        previous = read_company(settings, symbol)
        _write(
            _directory(settings, symbol) / "current.json",
            {
                "symbol": normalize_longbridge_symbol(symbol),
                "status": "failed",
                "snapshot_id": previous["snapshot_id"],
                "error": "资料更新失败，原快照保留；未生成新的研究结论。",
            },
        )
        return read_company(settings, symbol)
    finally:
        lease.close()


def refresh_company(settings, symbol, *, client=None, quote_reader=_primary_quote):
    return finish_refresh(
        settings, symbol, begin_refresh(settings, symbol), client=client, quote_reader=quote_reader
    )
