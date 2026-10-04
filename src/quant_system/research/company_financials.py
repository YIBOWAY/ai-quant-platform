"""Read-only diagnostics over Longbridge's separate quarterly IS/BS/CF payloads.

No provider calls, persistence, candidate creation, or trading happens here. Fiscal
year labels are independent of calendar years. Values stay in original currency
units; a percent is 100 times the underlying ratio. Provider ``yoy`` fields are
deliberately ignored. This snapshot is not a point-in-time backtest dataset.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

_KINDS = ("IS", "BS", "CF")
_NAMES = {"IS": "利润表", "BS": "资产负债表", "CF": "现金流量表"}
_FIELDS = {
    "IS": ("total_rev", "rev", "gp", "cost_rev", "ni", "ni_company"),
    "BS": ("total_assets", "total_liab", "total_equity", "total_ca", "total_cl"),
    "CF": ("cash_oper", "ni_cf"),
}
_AMOUNTS = {
    "revenue": ("IS", ("total_rev", "rev")),
    "gross_profit": ("IS", ("gp",)),
    "net_income": ("IS", ("ni",)),
    "assets": ("BS", ("total_assets",)),
    "liabilities": ("BS", ("total_liab",)),
    "equity": ("BS", ("total_equity",)),
    "operating_cash_flow": ("CF", ("cash_oper",)),
    "cost_of_revenue": ("IS", ("cost_rev",)),
    "current_assets": ("BS", ("total_ca",)),
    "current_liabilities": ("BS", ("total_cl",)),
    "cash_flow_net_income": ("CF", ("ni_cf",)),
}
_METRICS = (
    ("revenue_yoy_pct", "营收同比", "pct", "(本季营收 / 上一财年同季营收 - 1) × 100"),
    ("revenue_qoq_pct", "营收环比", "pct", "(本季营收 / 上一财政季度营收 - 1) × 100"),
    ("gross_margin_pct", "单季毛利率", "pct", "本季毛利润 / 本季营收 × 100"),
    ("net_margin_pct", "单季净利率", "pct", "本季合并净利润 / 本季营收 × 100"),
    ("debt_to_assets_pct", "期末资产负债率", "pct", "期末总负债 / 期末总资产 × 100"),
    ("current_ratio", "期末流动比率", "ratio", "期末流动资产 / 期末流动负债"),
    (
        "quarterly_gross_profit_to_assets_pct",
        "单季毛利润 / 期末资产",
        "pct",
        "本季毛利润 / 同季期末总资产 × 100（未经年化）",
    ),
    (
        "operating_cash_flow_to_net_income_ratio",
        "单季经营现金流 / 净利润",
        "ratio",
        "本季经营现金流 / 本季合并净利润（净利润须为正，现金流须确认单季口径）",
    ),
)
_TOLERANCE = "容差为比较金额的0.1%，至少1个原币单位"


@dataclass(frozen=True)
class _Row:
    fiscal_year: int
    quarter: int
    end: date
    reported: date
    currency: str
    values: dict[str, float | None]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None


def _date(value: Any) -> date | None:
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _fiscal(row: dict) -> tuple[int, int] | None:
    year, quarter = str(row.get("ff_year", "")), str(row.get("ff_period", ""))
    if not re.fullmatch(r"\d{4}", year) or not re.fullmatch(r"[1-4]", quarter):
        return None
    if int(year) < 1:
        return None
    return int(year), int(quarter)


def _label(key: tuple[int, int]) -> str:
    return f"FY{key[0]}Q{key[1]}"


def _close(left: float, right: float) -> bool:
    return (
        math.isfinite(left)
        and math.isfinite(right)
        and math.isclose(left, right, rel_tol=0.001, abs_tol=1.0)
    )


def _check(checks: list[dict], key: str, status: str, message: str) -> None:
    checks.append({"key": key, "status": status, "message": message})


def _failure(checks: list[dict], warnings: list[str], key: str, message: str) -> None:
    _check(checks, key, "failed", message)
    warnings.append(message)


def _parse_row(
    row: dict,
    kind: str,
    key: tuple[int, int],
    currency: str,
    as_of: date,
    checks: list[dict],
    warnings: list[str],
) -> _Row | None:
    period = _label(key)
    end, reported = _date(row.get("fp_end")), _date(row.get("rpt_date"))
    if end is None or reported is None or end > reported or reported > as_of:
        _failure(
            checks,
            warnings,
            f"period_dates:{kind}:{period}",
            f"{period}{_NAMES[kind]}日期无效、公布早于期末，或尚未在观察日公布；已排除。",
        )
        return None
    if row.get("currency", currency) != currency:
        _failure(
            checks,
            warnings,
            f"row_currency:{kind}:{period}",
            f"{period}{_NAMES[kind]}币种与报表币种冲突；已排除。",
        )
        return None
    # The numeric year is a fiscal label, so FY2027 can validly end in 2026.
    report_text = str(row.get("report_txt", ""))
    label_match = re.fullmatch(r"Q([1-4])\s+(\d{4})", report_text)
    if label_match and (int(label_match[2]), int(label_match[1])) != key:
        _failure(
            checks,
            warnings,
            f"period_label:{kind}:{period}",
            f"{period}{_NAMES[kind]}财政季度标记冲突；已排除。",
        )
        return None
    fields = row.get("fields")
    if not isinstance(fields, list):
        _failure(
            checks,
            warnings,
            f"fields:{kind}:{period}",
            f"{period}{_NAMES[kind]}缺少有效字段列表；已排除。",
        )
        return None
    values: dict[str, float | None] = {}
    invalid: set[str] = set()
    conflicts: set[str] = set()
    for item in fields:
        if not isinstance(item, dict) or item.get("field") not in _FIELDS[kind]:
            continue
        field = item["field"]
        value = _number(item.get("value"))
        if value is None:
            invalid.add(field)
        if field in values and values[field] != value:
            conflicts.add(field)
        values[field] = value
    for field in conflicts:
        values[field] = None
        _failure(
            checks,
            warnings,
            f"field_conflict:{kind}:{period}:{field}",
            f"{period}{_NAMES[kind]}字段{field}重复且冲突；该字段留空。",
        )
    if invalid:
        message = f"{period}{_NAMES[kind]}部分字段缺失或数值无效，已保留空值。"
        _check(checks, f"field_values:{kind}:{period}", "unknown", message)
        warnings.append(message)
    return _Row(*key, end, reported, currency, values)


def _parse_statements(
    statements: dict,
    as_of: date,
    checks: list[dict],
    warnings: list[str],
) -> dict[str, dict[tuple[int, int], _Row]]:
    parsed: dict[str, dict[tuple[int, int], _Row]] = {kind: {} for kind in _KINDS}
    for kind in _KINDS:
        payload = statements.get(kind)
        if not isinstance(payload, dict) or not payload.get("list"):
            message = f"{_NAMES[kind]}未返回数据。"
            _check(checks, f"statement_available:{kind}", "unknown", message)
            warnings.append(message)
            continue
        if not isinstance(payload["list"], list):
            _failure(
                checks,
                warnings,
                f"statement_shape:{kind}",
                f"{_NAMES[kind]}返回的期间列表格式无效。",
            )
            continue
        currency = payload.get("currency")
        if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
            _failure(
                checks,
                warnings,
                f"statement_currency:{kind}",
                f"{_NAMES[kind]}缺少有效币种；金额未参与计算。",
            )
            continue
        if payload.get("report") != "qf":
            _failure(
                checks,
                warnings,
                f"statement_basis:{kind}",
                f"{_NAMES[kind]}未明确返回qf单季报表；未与季度金额混算。",
            )
            continue
        groups: dict[tuple[int, int], list[dict]] = {}
        for row in payload["list"]:
            key = _fiscal(row) if isinstance(row, dict) else None
            if key is None:
                _failure(
                    checks,
                    warnings,
                    f"fiscal_period:{kind}",
                    f"{_NAMES[kind]}有无法识别的财政年度或季度；已排除。",
                )
                continue
            groups.setdefault(key, []).append(row)
        for key, group in groups.items():
            rows = [_parse_row(row, kind, key, currency, as_of, checks, warnings) for row in group]
            if len(rows) > 1 and (None in rows or any(row != rows[0] for row in rows[1:])):
                _failure(
                    checks,
                    warnings,
                    f"duplicate_period:{kind}:{_label(key)}",
                    f"{_label(key)}{_NAMES[kind]}存在重复冲突期间；整期该报表已排除。",
                )
                continue
            if rows[0] is not None:
                parsed[kind][key] = rows[0]
    return parsed


def _amount(rows: dict[str, _Row], name: str) -> float | None:
    kind, fields = _AMOUNTS[name]
    row = rows.get(kind)
    if row is None:
        return None
    return next((row.values[field] for field in fields if row.values.get(field) is not None), None)


def _equation(
    amounts: dict,
    fields: tuple[str, str, str],
    *,
    subtract: bool,
    key: str,
    period: str,
    name: str,
    checks: list[dict],
    warnings: list[str],
) -> str:
    left, right_a, right_b = (amounts[field] for field in fields)
    if left is None or right_a is None or right_b is None:
        _check(checks, f"{key}:{period}", "unknown", f"{period}{name}缺少可用字段，未能核对。")
        return "unknown"
    right = right_a - right_b if subtract else right_a + right_b
    if _close(left, right):
        _check(checks, f"{key}:{period}", "passed", f"{period}{name}通过；{_TOLERANCE}。")
        return "passed"
    _failure(
        checks,
        warnings,
        f"{key}:{period}",
        f"{period}{name}不一致；{_TOLERANCE}，依赖这些字段的比率留空。",
    )
    return "failed"


def _ratio(
    amounts: dict,
    numerator: str,
    denominator: str,
    scale: int,
    invalid: set[str],
) -> tuple[float | None, str | None]:
    if {numerator, denominator} & invalid:
        return None, "依赖字段未通过勾稽检查。"
    top, bottom = amounts[numerator], amounts[denominator]
    if top is None or bottom is None:
        return None, "缺少同期间、同币种的有效字段。"
    if bottom <= 0:
        return None, "分母为零或负值，此比率不适用。"
    value = (top / bottom) * scale
    if not math.isfinite(value):
        return None, "计算结果超出有效数值范围。"
    return value, None


def _growth(
    current: dict,
    previous: dict | None,
    invalid: dict[tuple[int, int], set[str]],
    current_key: tuple[int, int],
    previous_key: tuple[int, int],
) -> tuple[float | None, str | None]:
    if previous is None:
        return None, "未返回可对齐的上一年同季或上一财政季度营收。"
    days = (
        date.fromisoformat(current["period_end"]) - date.fromisoformat(previous["period_end"])
    ).days
    same_quarter = current_key[1] == previous_key[1]
    lower, upper = (330, 400) if same_quarter else (60, 120)
    if not lower <= days <= upper:
        return None, "报表期末日期跨度与所标财政季度不符，增长率留空。"
    if "revenue" in invalid[current_key] or "revenue" in invalid[previous_key]:
        return None, "营收相关勾稽检查失败，增长率留空。"
    values = {"current": current["revenue"], "previous": previous["revenue"]}
    value, reason = _ratio(values, "current", "previous", 1, set())
    if value is None:
        return None, reason
    growth = (value - 1) * 100
    return (growth, None) if math.isfinite(growth) else (None, "计算结果超出有效数值范围。")


def analyze_statements(statements: dict[str, dict | None], *, as_of: date | None = None) -> dict:
    """Align and diagnose up to five quarterly periods without filling missing data.

    ``as_of`` excludes not-yet-published rows, but does not recreate their original
    publication versions. Equal fiscal labels require identical end/report dates
    and currency. Conflicting duplicates are rejected rather than arbitrarily
    choosing a revision. Reconciliation tolerates relative 0.1% or one currency
    unit, whichever is larger. Cash-flow ratios additionally require CF ``ni_cf``
    to agree with consolidated IS ``ni``; ``qf`` alone is not sufficient evidence.
    """
    cutoff = as_of or date.today()
    checks: list[dict] = []
    warnings: list[str] = []
    parsed = _parse_statements(statements, cutoff, checks, warnings)
    currencies = {row.currency for rows in parsed.values() for row in rows.values()}
    currency = next((row.currency for rows in parsed.values() for row in rows.values()), None)
    if len(currencies) > 1:
        _failure(
            checks,
            warnings,
            "currency_alignment",
            "三表币种不一致；只保留优先可用报表的币种，其他币种已排除，未做汇率换算。",
        )
    elif currency:
        _check(checks, "currency_alignment", "passed", f"可用报表币种一致：{currency}。")
    parsed = {
        kind: {key: row for key, row in rows.items() if row.currency == currency}
        for kind, rows in parsed.items()
    }
    keys = sorted({key for rows in parsed.values() for key in rows}, reverse=True)[:5]
    periods: dict[tuple[int, int], dict] = {}
    invalid: dict[tuple[int, int], set[str]] = {}
    ratios: dict[tuple[int, int], dict[str, tuple[float | None, str | None]]] = {}
    previous_end: date | None = None
    for key in keys:
        period = _label(key)
        rows = {kind: parsed[kind][key] for kind in _KINDS if key in parsed[kind]}
        anchor = next(iter(rows.values()))
        for kind, row in list(rows.items()):
            if (row.end, row.reported) != (anchor.end, anchor.reported):
                _failure(
                    checks,
                    warnings,
                    f"period_alignment:{kind}:{period}",
                    f"{period}{_NAMES[kind]}期末或公布日期与同季基准不一致；已排除。",
                )
                del rows[kind]
        if previous_end is not None and anchor.end >= previous_end:
            _failure(
                checks,
                warnings,
                f"period_order:{period}",
                f"{period}的期末日期与财政季度先后顺序冲突；已排除。",
            )
            continue
        previous_end = anchor.end
        amounts = {name: _amount(rows, name) for name in _AMOUNTS}
        bad: set[str] = set()
        if (
            _equation(
                amounts,
                ("assets", "liabilities", "equity"),
                subtract=False,
                key="balance_sheet_equation",
                period=period,
                name="资产等于负债加权益",
                checks=checks,
                warnings=warnings,
            )
            == "failed"
        ):
            bad.update(("assets", "liabilities", "equity"))
        if (
            _equation(
                amounts,
                ("gross_profit", "revenue", "cost_of_revenue"),
                subtract=True,
                key="gross_profit_equation",
                period=period,
                name="营收减成本等于毛利润",
                checks=checks,
                warnings=warnings,
            )
            == "failed"
        ):
            bad.update(("gross_profit", "revenue", "cost_of_revenue"))
        cash_basis = "unknown"
        if amounts["cash_flow_net_income"] is not None and amounts["net_income"] is not None:
            cash_basis = (
                "passed"
                if _close(
                    amounts["cash_flow_net_income"],
                    amounts["net_income"],
                )
                else "failed"
            )
        message = {
            "passed": f"{period}CF与IS的净利润相符，支持同季口径；{_TOLERANCE}。",
            "unknown": f"{period}缺少CF或IS合并净利润，现金流单季口径未确认。",
            "failed": f"{period}CF与IS净利润不一致，现金流可能为累计或不同口径；比率留空。",
        }[cash_basis]
        _check(checks, f"cash_flow_period_basis:{period}", cash_basis, message)
        if cash_basis != "passed":
            warnings.append(message)
        period_ratios = {
            "gross_margin_pct": _ratio(amounts, "gross_profit", "revenue", 100, bad),
            "net_margin_pct": _ratio(amounts, "net_income", "revenue", 100, bad),
            "debt_to_assets_pct": _ratio(amounts, "liabilities", "assets", 100, bad),
            "current_ratio": _ratio(amounts, "current_assets", "current_liabilities", 1, bad),
            "quarterly_gross_profit_to_assets_pct": _ratio(
                amounts,
                "gross_profit",
                "assets",
                100,
                bad,
            ),
            "operating_cash_flow_to_net_income_ratio": (
                _ratio(amounts, "operating_cash_flow", "net_income", 1, bad)
                if cash_basis == "passed"
                else (None, "现金流的单季口径未确认或与利润表冲突。")
            ),
        }
        if (
            amounts["net_income"] is None
            and "IS" in rows
            and rows["IS"].values.get("ni_company") is not None
        ):
            message = "缺少合并净利润ni；归母净利润ni_company不直接替代合并口径。"
            warnings.append(f"{period}{message}")
            period_ratios["net_margin_pct"] = (None, message)
            period_ratios["operating_cash_flow_to_net_income_ratio"] = (None, message)
        periods[key] = {
            "period": period,
            "fiscal_year": key[0],
            "quarter": key[1],
            "period_end": anchor.end.isoformat(),
            "reported_at": anchor.reported.isoformat(),
            **{
                name: amounts[name]
                for name in _AMOUNTS
                if name
                not in (
                    "cost_of_revenue",
                    "current_assets",
                    "current_liabilities",
                    "cash_flow_net_income",
                )
            },
            "gross_margin_pct": period_ratios["gross_margin_pct"][0],
            "net_margin_pct": period_ratios["net_margin_pct"][0],
        }
        invalid[key], ratios[key] = bad, period_ratios
    for key, current in periods.items():
        previous_quarter = (key[0], key[1] - 1) if key[1] > 1 else (key[0] - 1, 4)
        previous_year = (key[0] - 1, key[1])
        for metric, previous in (
            ("revenue_yoy_pct", previous_year),
            ("revenue_qoq_pct", previous_quarter),
        ):
            ratios[key][metric] = _growth(current, periods.get(previous), invalid, key, previous)
            current[metric] = ratios[key][metric][0]
    latest_key = next(iter(periods), None)
    latest_ratios = ratios.get(latest_key, {})
    metrics = []
    for key, label, unit, formula in _METRICS:
        value, reason = latest_ratios.get(key, (None, "没有可用的季度报表。"))
        metrics.append(
            {
                "key": key,
                "label": label,
                "value": value,
                "unit": unit,
                "period": _label(latest_key) if latest_key else None,
                "formula": formula,
                "reason": reason,
            }
        )
    ideas = []
    idea_fields = {
        "revenue_yoy_pct": ["本季营收", "上一财年同季营收", "公布日期"],
        "gross_margin_pct": ["本季毛利润", "本季营收", "公布日期"],
        "quarterly_gross_profit_to_assets_pct": ["本季毛利润", "同季期末总资产", "公布日期"],
        "operating_cash_flow_to_net_income_ratio": ["单季经营现金流", "同季合并净利润", "公布日期"],
    }
    for metric in metrics:
        if metric["key"] in idea_fields and metric["value"] is not None:
            ideas.append(
                {
                    "key": metric["key"],
                    "title": f"观察{metric['label']}",
                    "formula": metric["formula"],
                    "required_data": idea_fields[metric["key"]],
                    "status": "observation_only",
                    "reason": (
                        "当前报表支持该观察值；尚无历史版本、跨公司排序或收益验证，不生成回测因子。"
                    ),
                }
            )
    warnings.append("报表为当前返回版本；公布日期过滤不等于历史版本还原。单季观察值未经年化。")
    failed = any(check["status"] == "failed" for check in checks)
    status = (
        "invalid"
        if failed
        else (
            "unavailable"
            if not periods
            else ("partial" if any(metric["value"] is None for metric in metrics) else "ok")
        )
    )
    return {
        "status": status,
        "currency": currency if periods else None,
        "periods": list(periods.values()),
        "metrics": metrics,
        "checks": checks,
        "warnings": list(dict.fromkeys(warnings)),
        "research_ideas": ideas,
    }
