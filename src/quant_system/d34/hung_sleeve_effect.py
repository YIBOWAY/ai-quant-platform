"""Read-only valuation of official sleeves from committed fill journals.

A day counts only with a real fill: fill_notional > 0 or filled is true.
Account inventory, manual lots, and fossil marks are never performance.
Daily prices may mark existing holdings without inventing a fill/observation.
Simple profit / contributed capital is explicitly not a time-weighted return.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Mapping
from datetime import UTC, date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from quant_system.execution.account import PaperAccount
from quant_system.execution.paper_strategy_sleeves import (
    SleeveLot,
    StrategyExecutionPlan,
    StrategySleeve,
)

EMPTY_EFFECT_LABEL_ZH = "已挂 {hung_count} 条 · 观察日 0 · 等第一个观察夜"
_MARKET_TIMEZONE = ZoneInfo("America/New_York")


def _allocation_session(created_at: datetime) -> str:
    """First exchange close that includes the persisted sleeve allocation time."""
    import exchange_calendars as xcals
    import pandas as pd

    calendar = xcals.get_calendar("XNYS")
    session = calendar.date_to_session(
        pd.Timestamp(created_at.astimezone(_MARKET_TIMEZONE).date()), direction="next",
    )
    if pd.Timestamp(created_at) > calendar.session_close(session):
        session = calendar.next_session(session)
    return session.date().isoformat()


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in {float("inf"), float("-inf")}:
        return None
    return number


def _mapping_fill_cost(fill: Mapping[str, Any]) -> float | None:
    direct = _finite(fill.get("cost"))
    if direct is not None:
        return direct
    metadata = fill.get("metadata")
    if not isinstance(metadata, Mapping):
        return None
    if "commission" in metadata:
        return _finite(metadata.get("commission"))
    return _finite(metadata.get("estimated_cost"))


def _fill_commission(fill: Any) -> float:
    metadata = fill.metadata or {}
    if "commission" not in metadata:
        raise ValueError("committed_effect_state_unavailable")
    commission = _finite(metadata.get("commission"))
    if commission is None or commission < 0:
        raise ValueError("committed_effect_state_unavailable")
    return commission


def _aware_datetime(value: Any) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("committed_effect_state_unavailable") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("committed_effect_state_unavailable")
    return parsed.astimezone(UTC)


def _sleeve_financial_state(sleeve: StrategySleeve) -> tuple[Any, ...]:
    return (
        sleeve.sleeve_id,
        sleeve.account_id,
        sleeve.strategy_config_id,
        sleeve.strategy_config_version,
        sleeve.mode,
        float(sleeve.initial_allocated_cash),
        float(sleeve.cash),
        sleeve.created_at,
        sleeve.metadata,
    )


def _sleeve_identity(sleeve: StrategySleeve) -> tuple[Any, ...]:
    financial = _sleeve_financial_state(sleeve)
    return (*financial[:6], *financial[7:])


def _lot_documents(lots: list[SleeveLot]) -> list[dict[str, Any]]:
    return sorted(
        (lot.model_dump(mode="json") for lot in lots),
        key=lambda row: (str(row["symbol"]), str(row["lot_id"])),
    )


def _verified_replacement_transition(**kwargs) -> bool:
    """Only a checked, terminal lifecycle journal may explain an identity change."""
    try:
        from quant_system.execution.strategy_replacement import replacement_transition_verified

        return replacement_transition_verified(**kwargs)
    except (ImportError, OSError, ValueError, KeyError, TypeError):
        return False


def _same_committed_financial_chain(
    *, sleeve_storage, before_sleeve, after_sleeve, before_lots, after_lots,
) -> bool:
    if _lot_documents(before_lots) != _lot_documents(after_lots):
        return False
    before = _sleeve_financial_state(before_sleeve)
    after = _sleeve_financial_state(after_sleeve)
    if before == after:
        return True
    # Version and metadata may change only through a verified replacement or
    # abort. Cash, capital, ownership, config identity and creation never change.
    if any(before[index] != after[index] for index in (0, 1, 2, 4, 5, 6, 7)):
        return False
    return _verified_replacement_transition(
        storage=sleeve_storage, before_sleeve=before_sleeve, after_sleeve=after_sleeve,
        before_lots=before_lots, after_lots=after_lots,
    )


def _lot_quantities(lots: list[SleeveLot]) -> dict[str, float]:
    quantities: dict[str, float] = defaultdict(float)
    for lot in lots:
        quantities[lot.symbol.upper()] += float(lot.quantity)
    return dict(quantities)


def _validate_fill_transition(
    *,
    before_sleeve: StrategySleeve,
    after_sleeve: StrategySleeve,
    before_lots: list[SleeveLot],
    after_lots: list[SleeveLot],
    execution: StrategyExecutionPlan,
) -> None:
    expected_cash = float(before_sleeve.cash)
    expected_quantities = _lot_quantities(before_lots)
    for fill in execution.fills:
        gross = _finite(fill.gross_value)
        quantity = _finite(fill.quantity)
        if gross is None or gross < 0 or quantity is None or quantity <= 0:
            raise ValueError("committed_effect_state_unavailable")
        commission = _fill_commission(fill)
        symbol = fill.symbol.upper()
        side = str(fill.side).lower().strip()
        if side == "buy":
            expected_cash -= gross + commission
            expected_quantities[symbol] = expected_quantities.get(symbol, 0.0) + quantity
        elif side == "sell":
            expected_cash += gross - commission
            expected_quantities[symbol] = expected_quantities.get(symbol, 0.0) - quantity
        else:
            raise ValueError("committed_effect_state_unavailable")
    expected_cash = max(expected_cash, 0.0)
    if not math.isclose(expected_cash, float(after_sleeve.cash), abs_tol=1e-6):
        raise ValueError("committed_effect_state_unavailable")
    actual_quantities = _lot_quantities(after_lots)
    symbols = set(expected_quantities) | set(actual_quantities)
    if any(expected_quantities.get(symbol, 0.0) < -1e-9 for symbol in symbols):
        raise ValueError("committed_effect_state_unavailable")
    if any(
        not math.isclose(
            max(expected_quantities.get(symbol, 0.0), 0.0),
            actual_quantities.get(symbol, 0.0),
            abs_tol=1e-9,
        )
        for symbol in symbols
    ):
        raise ValueError("committed_effect_state_unavailable")


def _rebase(values: list[float]) -> list[float]:
    first = next((item for item in values if item > 0), None)
    if first is None:
        return []
    return [round(((item / first) - 1.0) * 100.0, 10) for item in values]


def build_hung_sleeve_effect(
    *,
    hung_count: int,
    marks: list[Mapping[str, Any]],
    spy_closes: Mapping[str, Any] | None = None,
    account_equity: Any | None = None,
    account_positions: Any | None = None,
    fossil_marks: Any | None = None,
) -> dict[str, Any]:
    del account_equity, account_positions, fossil_marks
    funding_expected = any("allocated_cash" in item for item in marks)
    official = []
    for item in marks:
        day = str(item.get("date") or "").strip()
        equity = _finite(item.get("sleeve_equity"))
        fill_notional = abs(_finite(item.get("fill_notional")) or 0.0)
        filled = item.get("filled") is True or fill_notional > 0
        if not day or not (filled or item.get("valuation") is True):
            continue
        official.append(
            {
                "date": day,
                "sleeve_equity": equity if equity is not None and equity > 0 else None,
                "fill_notional": fill_notional,
                "cost": abs(_finite(item.get("cost")) or 0.0),
                "filled": filled,
                "allocated_cash": _finite(item.get("allocated_cash")),
                "covered_sleeve_count": item.get("covered_sleeve_count"),
            }
        )
    official.sort(key=lambda row: row["date"])
    fill_days = [row["date"] for row in official if row["filled"]]
    if hung_count <= 0 or not official:
        return {
            "hung_count": hung_count,
            "observation_day_count": 0,
            "empty": True,
            "empty_label_zh": EMPTY_EFFECT_LABEL_ZH.format(hung_count=max(hung_count, 0)),
            "sleeve_return_pct": None,
            "spy_return_pct": None,
            "sleeve_equity": None,
            "sleeve_equity_status": "empty",
            "sleeve_equity_reason": None,
            "spy_status": "empty",
            "spy_reason": None,
            "price_source": None,
            "turnover": None,
            "cost_drag_pct": None,
            "series": [],
            "as_of": None,
            "last_fill_date": None,
            "valuation_day_count": 0,
            "covered_sleeve_count": 0,
            "allocated_cash": None,
            "net_profit_usd": None,
            "return_method": "unavailable",
            "return_reason": "no_committed_fills",
            "observation_return_pct": None,
        }

    sleeve_values = [row["sleeve_equity"] for row in official]
    valid_indices = [i for i, value in enumerate(sleeve_values) if value is not None]
    latest_index = valid_indices[-1] if valid_indices else None
    latest = official[latest_index] if latest_index is not None else None
    sleeve_available = latest is not None
    funding_available = all(
        row["allocated_cash"] is not None and row["allocated_cash"] > 0 for row in official
    )
    sleeve_pcts: list[float | None]
    if not fill_days:
        sleeve_pcts = [None] * len(official)
        return_method = "unavailable"
        return_reason = "no_committed_fills"
    elif funding_available:
        sleeve_pcts = [
            ((row["sleeve_equity"] - row["allocated_cash"]) / row["allocated_cash"]) * 100
            if row["sleeve_equity"] is not None else None
            for row in official
        ]
        return_method = "net_profit_over_allocated_capital"
        return_reason = None
    elif not funding_expected and hung_count == 1 and len(valid_indices) == len(official):
        # Compatibility for explicitly supplied single-sleeve historical marks.
        # Storage-backed paths always provide checked capital provenance.
        sleeve_pcts = _rebase([float(value) for value in sleeve_values])  # type: ignore[arg-type]
        return_method = "first_mark_return"
        return_reason = None
    else:
        sleeve_pcts = [None] * len(official)
        return_method = "unavailable"
        return_reason = "allocation_evidence_unavailable"
    spy_map = spy_closes or {}
    spy_values = [_finite(spy_map.get(row["date"])) for row in official]
    spy_pcts: list[float | None]
    if all(value is not None and value > 0 for value in spy_values):
        spy_pcts = _rebase([float(value) for value in spy_values])  # type: ignore[arg-type]
    else:
        spy_pcts = [None] * len(official)
    start_equity = float(sleeve_values[0]) if sleeve_values[0] is not None else None
    latest_allocated = latest["allocated_cash"] if latest and funding_available else None
    observation_return = None
    if (
        fill_days and latest is not None and start_equity
        and ((hung_count == 1 and not funding_expected) or (funding_available and
             len({row["allocated_cash"] for row in official}) == 1))
    ):
        observation_return = (latest["sleeve_equity"] / start_equity - 1) * 100
    turnover = (
        sum(row["fill_notional"] for row in official[:latest_index + 1]) / start_equity
        if start_equity is not None and latest_index is not None
        else None
    )
    cost_drag_pct = (
        (sum(row["cost"] for row in official[:latest_index + 1]) / start_equity) * 100.0
        if start_equity is not None and latest_index is not None
        else None
    )
    series = [
        {
            "date": row["date"],
            "sleeve_equity": row["sleeve_equity"],
            "sleeve_pct": sleeve_pcts[index],
            "spy_close": spy_values[index],
            "spy_pct": spy_pcts[index],
            "allocated_cash": row["allocated_cash"],
            "net_profit_usd": row["sleeve_equity"] - row["allocated_cash"]
            if funding_available and row["sleeve_equity"] is not None else None,
            "covered_sleeve_count": row["covered_sleeve_count"],
            "filled": row["filled"],
        }
        for index, row in enumerate(official)
    ]
    return {
        "hung_count": hung_count,
        "observation_day_count": len(fill_days),
        "empty": False,
        "empty_label_zh": None,
        "sleeve_return_pct": sleeve_pcts[latest_index] if latest_index is not None else None,
        "spy_return_pct": spy_pcts[latest_index]
        if fill_days and latest_index is not None else None,
        "sleeve_equity": latest["sleeve_equity"] if latest else None,
        "sleeve_equity_status": "available" if sleeve_available else "unavailable",
        "sleeve_equity_reason": None if sleeve_available else "strategy_price_unavailable",
        "spy_status": (
            "available"
            if fill_days and latest_index is not None and spy_pcts[latest_index] is not None
            else "unavailable"
        ),
        "spy_reason": (
            None
            if fill_days and latest_index is not None and spy_pcts[latest_index] is not None
            else "strategy_valuation_date_unavailable" if latest_index is None
            else "spy_price_unavailable"
        ),
        "price_source": None,
        "turnover": turnover,
        "cost_drag_pct": cost_drag_pct,
        "series": series,
        "as_of": latest["date"] if latest else None,
        "last_fill_date": fill_days[-1] if fill_days else None,
        "valuation_day_count": len(valid_indices),
        "covered_sleeve_count": latest["covered_sleeve_count"] if latest else 0,
        "allocated_cash": latest_allocated,
        "net_profit_usd": latest["sleeve_equity"] - latest_allocated
        if latest is not None and latest_allocated is not None else None,
        "return_method": return_method,
        "return_reason": return_reason,
        "observation_return_pct": observation_return,
    }


def _official_sleeves(sleeve_storage: Any) -> list[StrategySleeve]:
    return [
        sleeve
        for sleeve in sleeve_storage.list_sleeves()
        if (getattr(sleeve, "metadata", None) or {}).get("fossil") is not True
        and (getattr(sleeve, "metadata", None) or {}).get("official_observation") is not False
        and str((getattr(sleeve, "metadata", None) or {}).get("automation_source", "")) == "d34"
    ]


def _canonical_date(value: Any) -> str:
    text = str(value or "").strip()
    parsed = date.fromisoformat(text)
    if text != parsed.isoformat():
        raise ValueError("effect dates must use YYYY-MM-DD")
    return text


def _committed_states(
    *,
    sleeve_storage: Any,
    sleeves: list[StrategySleeve],
) -> list[dict[str, Any]]:
    states: list[dict[str, Any]] = []
    for sleeve in sleeves:
        executions = list(sleeve_storage.load_executions(sleeve.sleeve_id))
        execution_ids: set[str] = set()
        for execution in executions:
            status = getattr(execution.status, "value", execution.status)
            if status != "filled" or not execution.fills:
                continue
            if execution.execution_id in execution_ids:
                raise ValueError("committed_effect_state_unavailable")
            execution_ids.add(execution.execution_id)
            path = sleeve_storage.execution_journal_committed_path(
                sleeve.sleeve_id,
                execution.execution_id,
            )
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                before_account = PaperAccount.model_validate(payload["before_account"])
                after_account = PaperAccount.model_validate(payload["after_account"])
                before_sleeve = StrategySleeve.model_validate(payload["before_sleeve"])
                after_sleeve = StrategySleeve.model_validate(payload["after_sleeve"])
                before_lots = [
                    SleeveLot.model_validate(row) for row in payload["before_lots"]
                ]
                after_lots = [SleeveLot.model_validate(row) for row in payload["after_lots"]]
                before_execution = StrategyExecutionPlan.model_validate(
                    payload["before_execution"]
                )
                after_execution = StrategyExecutionPlan.model_validate(
                    payload["after_execution"]
                )
            except (KeyError, OSError, TypeError, ValueError) as exc:
                raise ValueError("committed_effect_state_unavailable") from exc
            if (
                payload.get("journal_version") != 1
                or isinstance(payload.get("journal_version"), bool)
                or payload.get("account_id") != sleeve.account_id
                or payload.get("sleeve_id") != sleeve.sleeve_id
                or payload.get("execution_id") != execution.execution_id
                or before_account.account_id != sleeve.account_id
                or after_account.account_id != sleeve.account_id
                or before_sleeve.sleeve_id != sleeve.sleeve_id
                or after_sleeve.sleeve_id != sleeve.sleeve_id
                or _sleeve_identity(before_sleeve) != _sleeve_identity(after_sleeve)
                or before_execution.execution_id != execution.execution_id
                or before_execution.sleeve_id != sleeve.sleeve_id
                or before_execution.account_id != sleeve.account_id
                or before_execution.strategy_config_id != before_sleeve.strategy_config_id
                or before_execution.strategy_config_version
                != before_sleeve.strategy_config_version
                or after_execution.strategy_config_id != after_sleeve.strategy_config_id
                or after_execution.strategy_config_version != after_sleeve.strategy_config_version
                or after_execution != execution
                or after_execution.target_date is None
                or any(
                    lot.sleeve_id != sleeve.sleeve_id
                    or lot.account_id != sleeve.account_id
                    for lot in [*before_lots, *after_lots]
                )
            ):
                raise ValueError("committed_effect_state_unavailable")
            _aware_datetime(payload.get("created_at"))
            _aware_datetime(after_execution.updated_at)
            _validate_fill_transition(
                before_sleeve=before_sleeve,
                after_sleeve=after_sleeve,
                before_lots=before_lots,
                after_lots=after_lots,
                execution=after_execution,
            )
            states.append(
                {
                    "date": _canonical_date(after_execution.target_date),
                    "updated_at": _aware_datetime(after_execution.updated_at),
                    "sleeve_id": sleeve.sleeve_id,
                    "cash": float(after_sleeve.cash),
                    "lots": after_lots,
                    "fills": list(after_execution.fills),
                    "is_observation": True,
                    "before_sleeve": before_sleeve,
                    "before_lots": before_lots,
                    "after_sleeve": after_sleeve,
                    "after_lots": after_lots,
                }
            )
    states = sorted(
        states,
        key=lambda item: (item["date"], item["updated_at"], item["sleeve_id"]),
    )
    for sleeve in sleeves:
        sleeve_states = [state for state in states if state["sleeve_id"] == sleeve.sleeve_id]
        for previous, current in zip(
            sleeve_states,
            sleeve_states[1:],
            strict=False,
        ):
            if not _same_committed_financial_chain(
                sleeve_storage=sleeve_storage,
                before_sleeve=previous['after_sleeve'], after_sleeve=current['before_sleeve'],
                before_lots=previous['after_lots'], after_lots=current['before_lots'],
            ):
                raise ValueError("committed_effect_state_unavailable")
        if sleeve_states:
            latest = sleeve_states[-1]
            current_lots = sleeve_storage.load_sleeve_lots(sleeve.sleeve_id)
            if not _same_committed_financial_chain(
                sleeve_storage=sleeve_storage,
                before_sleeve=latest['after_sleeve'], after_sleeve=sleeve,
                before_lots=latest['after_lots'], after_lots=current_lots,
            ):
                raise ValueError("committed_effect_state_unavailable")
    seeds: list[dict[str, Any]] = []
    for sleeve in sleeves:
        sleeve_states = [state for state in states if state["sleeve_id"] == sleeve.sleeve_id]
        if sleeve_states:
            first = sleeve_states[0]
            seed_sleeve = first["before_sleeve"]
            seed_lots = first["before_lots"]
        else:
            seed_sleeve = sleeve
            seed_lots = sleeve_storage.load_sleeve_lots(sleeve.sleeve_id)
            if seed_lots or not math.isclose(
                float(sleeve.cash),
                float(sleeve.initial_allocated_cash),
                abs_tol=1e-6,
            ):
                raise ValueError("committed_effect_state_unavailable")
        created_at = _aware_datetime(seed_sleeve.created_at)
        seeds.append(
            {
                "date": _allocation_session(created_at),
                "updated_at": created_at,
                "sleeve_id": sleeve.sleeve_id,
                "cash": float(seed_sleeve.cash),
                "lots": seed_lots,
                "fills": [],
                "is_observation": False,
                "allocated_cash": (
                    float(seed_sleeve.initial_allocated_cash)
                    if not seed_lots and math.isclose(
                        float(seed_sleeve.cash), float(seed_sleeve.initial_allocated_cash),
                        abs_tol=1e-6,
                    ) else None
                ),
                "before_sleeve": seed_sleeve,
                "before_lots": seed_lots,
                "after_sleeve": seed_sleeve,
                "after_lots": seed_lots,
            }
        )
    return sorted(
        [*seeds, *states],
        key=lambda item: (item["date"], item["updated_at"], item["sleeve_id"]),
    )


def _filled_observation_days(
    *,
    sleeve_storage: Any,
    sleeves: list[StrategySleeve],
) -> list[str]:
    days: set[str] = set()
    for sleeve in sleeves:
        for execution in sleeve_storage.load_executions(sleeve.sleeve_id):
            status = getattr(execution.status, "value", execution.status)
            if status == "filled" and execution.fills and execution.target_date:
                days.add(_canonical_date(execution.target_date))
    return sorted(days)


def _unavailable_effect(
    *,
    hung_count: int,
    days: list[str],
    reason: str,
    price_source: str | None,
) -> dict[str, Any]:
    if not days:
        report = build_hung_sleeve_effect(hung_count=hung_count, marks=[])
        report["price_source"] = None
        return report
    return {
        "hung_count": hung_count,
        "observation_day_count": len(days),
        "empty": False,
        "empty_label_zh": None,
        "sleeve_return_pct": None,
        "spy_return_pct": None,
        "sleeve_equity": None,
        "sleeve_equity_status": "unavailable",
        "sleeve_equity_reason": reason,
        "spy_status": "unavailable",
        "spy_reason": reason,
        "price_source": price_source,
        "turnover": None,
        "cost_drag_pct": None,
        "series": [
            {
                "date": day,
                "sleeve_equity": None,
                "sleeve_pct": None,
                "spy_close": None,
                "spy_pct": None,
            }
            for day in days
        ],
    }


def _fetch_closes(
    *,
    price_provider: Any,
    symbols: list[str],
    days: list[str],
    end: str | None = None,
) -> dict[str, dict[str, float]]:
    if not symbols or not days:
        return {}
    if str(getattr(price_provider, "provider_name", "")).lower() != "futu":
        raise ValueError("untrusted_effect_price_provenance")
    frame = price_provider.fetch_ohlcv(
        symbols,
        start=min(days),
        end=end or max(days),
        interval="1d",
    )
    required_columns = {
        "timestamp",
        "symbol",
        "close",
        "provider",
        "interval",
        "price_adjustment",
    }
    if not required_columns.issubset(set(frame.columns)):
        raise ValueError("untrusted_effect_price_provenance")
    result: dict[str, dict[str, float]] = defaultdict(dict)
    requested_symbols = {symbol.upper() for symbol in symbols}
    requested_start = date.fromisoformat(min(days))
    requested_end = date.fromisoformat(end or max(days))
    seen: set[tuple[str, str]] = set()
    for row in frame.to_dict(orient="records"):
        symbol = str(row.get("symbol") or "").upper().strip()
        timestamp = _aware_datetime(row.get("timestamp"))
        day = timestamp.date().isoformat()
        close = _finite(row.get("close"))
        identity = (symbol, day)
        if (
            symbol not in requested_symbols
            or str(row.get("provider") or "").lower() != "futu"
            or str(row.get("interval") or "").lower() != "1d"
            or str(row.get("price_adjustment") or "").lower() != "qfq"
            or not requested_start <= timestamp.date() <= requested_end
            or close is None
            or close <= 0
            or identity in seen
        ):
            raise ValueError("untrusted_effect_price_provenance")
        seen.add(identity)
        if end is not None or day in days:
            result[symbol][day] = close
    return dict(result)


def _marks_from_committed_states(
    *,
    states: list[dict[str, Any]],
    closes: Mapping[str, Mapping[str, Any]],
    valuation_days: list[str] | None = None,
) -> list[dict[str, Any]]:
    states_by_sleeve: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for state in states:
        states_by_sleeve[state["sleeve_id"]].append(state)
    marks: list[dict[str, Any]] = []
    fill_days = {state["date"] for state in states if state.get("is_observation") is True}
    for day in sorted(fill_days | set(valuation_days or [])):
        equity = 0.0
        equity_available = True
        allocated_cash = 0.0
        funding_available = True
        covered_sleeve_count = 0
        for sleeve_states in states_by_sleeve.values():
            candidates = [state for state in sleeve_states if state["date"] <= day]
            if not candidates:
                continue
            covered_sleeve_count += 1
            seed_capital = _finite(sleeve_states[0].get("allocated_cash"))
            if seed_capital is None or seed_capital <= 0:
                funding_available = False
            else:
                allocated_cash += seed_capital
            state = candidates[-1]
            market_value = 0.0
            for lot in state["lots"]:
                close = _finite((closes.get(lot.symbol.upper()) or {}).get(day))
                if close is None or close <= 0:
                    equity_available = False
                    break
                market_value += float(lot.quantity) * close
            equity += float(state["cash"]) + market_value
        day_states = [
            state
            for state in states
            if state["date"] == day and state.get("is_observation") is True
        ]
        fills = [fill for state in day_states for fill in state["fills"]]
        marks.append(
            {
                "date": day,
                "sleeve_equity": equity if equity_available and equity > 0 else None,
                "fill_notional": sum(abs(float(fill.gross_value)) for fill in fills),
                "cost": sum(
                    abs(_fill_commission(fill))
                    for fill in fills
                ),
                "filled": bool(fills),
                "valuation": True,
                "allocated_cash": allocated_cash if funding_available else None,
                "covered_sleeve_count": covered_sleeve_count,
            }
        )
    return marks


def collect_official_marks(
    *,
    sleeve_storage: Any,
    price_closes: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[int, list[dict[str, Any]]]:
    sleeves = _official_sleeves(sleeve_storage)
    states = _committed_states(sleeve_storage=sleeve_storage, sleeves=sleeves)
    return len(sleeves), _marks_from_committed_states(
        states=states,
        closes=price_closes or {},
    )

def build_effect_from_storage(
    *,
    sleeve_storage: Any,
    price_provider: Any | None = None,
    price_source: str | None = None,
    spy_closes: Mapping[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    sleeves = _official_sleeves(sleeve_storage)
    filled_days = _filled_observation_days(
        sleeve_storage=sleeve_storage,
        sleeves=sleeves,
    )
    try:
        states = _committed_states(sleeve_storage=sleeve_storage, sleeves=sleeves)
    except ValueError as exc:
        return _unavailable_effect(
            hung_count=len(sleeves),
            days=filled_days,
            reason=str(exc),
            price_source=None,
        )
    days = filled_days
    # Query prices through the most recent completed XNYS session, not the last
    # trade. Reading a price never appends an execution or observation record.
    valuation_end = None
    expected_valuation_days: set[str] = set()
    if sleeves:
        import exchange_calendars as xcals
        import pandas as pd

        clock = _aware_datetime(now) if now is not None else datetime.now(UTC)
        calendar = xcals.get_calendar("XNYS")
        session = calendar.date_to_session(
            pd.Timestamp(clock.astimezone(_MARKET_TIMEZONE).date()), direction="previous",
        )
        if calendar.session_close(session) > pd.Timestamp(clock):
            session = calendar.previous_session(session)
        valuation_end = session.date().isoformat()
        days = [day for day in filled_days if day <= valuation_end]
        if not filled_days:
            days = [state["date"] for state in states if state["date"] <= valuation_end]
        if days:
            expected_valuation_days = {
                session.date().isoformat()
                for session in calendar.sessions_in_range(min(days), valuation_end)
            }
    symbols = sorted(
        {
            lot.symbol.upper()
            for state in states
            for lot in state["lots"]
        }
    )
    price_closes: dict[str, dict[str, float]] = {}
    resolved_spy = dict(spy_closes or {})
    if price_provider is not None and days and symbols:
        try:
            price_closes = _fetch_closes(
                price_provider=price_provider,
                symbols=symbols,
                days=days,
                end=valuation_end,
            )
        except Exception:  # noqa: BLE001 - report remains explicit unavailable
            price_closes = {}
        if not resolved_spy:
            try:
                resolved_spy = _fetch_closes(
                    price_provider=price_provider,
                    symbols=["SPY"],
                    days=days,
                    end=valuation_end,
                ).get("SPY", {})
            except Exception:  # noqa: BLE001 - SPY must not erase sleeve NAV
                resolved_spy = {}
    returned_days = {day for values in price_closes.values() for day in values}
    last_returned = max(returned_days | set(days), default="")
    if not symbols:
        last_returned = valuation_end or last_returned
    valuation_days = sorted(
        {day for day in expected_valuation_days if day <= last_returned} | returned_days
    )
    marks = _marks_from_committed_states(
        states=[state for state in states if valuation_end and state["date"] <= valuation_end],
        closes=price_closes, valuation_days=valuation_days,
    )
    report = build_hung_sleeve_effect(
        hung_count=len(sleeves),
        marks=marks,
        spy_closes=resolved_spy,
    )
    report["observation_day_count"] = len(filled_days)
    report["last_fill_date"] = filled_days[-1] if filled_days else None
    if report["empty"] and filled_days:
        report["sleeve_equity_status"] = "unavailable"
        report["sleeve_equity_reason"] = "awaiting_completed_session"
        report["empty_label_zh"] = (
            f"已记录 {len(filled_days)} 个成交日；等待交易日收盘后的真实估值。"
        )
    report["requested_as_of"] = valuation_end
    report["valuation_status"] = (
        "complete" if valuation_end and report.get("as_of") == valuation_end
        and expected_valuation_days.issubset({
            mark["date"] for mark in marks if mark["sleeve_equity"] is not None
        })
        else "partial" if report.get("as_of") else "unavailable"
    )
    report["current_allocated_cash"] = sum(float(s.initial_allocated_cash) for s in sleeves)
    report["missing_valuation_dates"] = sorted(expected_valuation_days - {
        mark["date"] for mark in marks if mark["sleeve_equity"] is not None
    })
    report["allocation_time_source"] = "committed_seed_sleeve.created_at"
    # The label must say which price source actually fed the marks. An outage
    # or a never-built provider must not leave an untouched "futu:qfq" claim.
    if sleeves and not symbols:
        report["price_source"] = "none_needed"
    elif not days:
        report["price_source"] = None
    elif price_closes:
        report["price_source"] = price_source
    else:
        report["price_source"] = "unavailable"
    return report


def marks_from_official_observations(
    observations: list[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Keep filled official hung-sleeve rows; drop fossils and inventory."""
    marks: list[dict[str, Any]] = []
    for item in observations:
        sleeve = item.get("sleeve") if isinstance(item.get("sleeve"), Mapping) else {}
        metadata = sleeve.get("metadata") if isinstance(sleeve, Mapping) else {}
        if not isinstance(metadata, Mapping):
            metadata = {}
        if metadata.get("fossil") is True or metadata.get("official_observation") is False:
            continue
        signal = item.get("signal") if isinstance(item.get("signal"), Mapping) else {}
        day = str((signal or {}).get("signal_date") or item.get("date") or "").strip()
        fill_notional = 0.0
        cost = 0.0
        filled = False
        executions = item.get("executions")
        if isinstance(executions, list):
            for execution in executions:
                if not isinstance(execution, Mapping):
                    continue
                status = str(execution.get("status") or "").lower()
                if status != "filled":
                    continue
                filled = True
                for fill in execution.get("fills") or []:
                    if not isinstance(fill, Mapping):
                        continue
                    gross = _finite(fill.get("gross_value"))
                    if gross is not None:
                        fill_notional += abs(gross)
                    fill_cost = _mapping_fill_cost(fill)
                    if fill_cost is not None:
                        cost += abs(fill_cost)
        equity = _finite(item.get("sleeve_equity"))
        if equity is None and filled:
            equity = _finite((sleeve or {}).get("cash"))
        if not day or equity is None or not filled:
            continue
        marks.append(
            {
                "date": day,
                "sleeve_equity": equity,
                "fill_notional": fill_notional,
                "cost": cost,
                "filled": True,
            }
        )
    return marks


__all__ = [
    "EMPTY_EFFECT_LABEL_ZH",
    "build_effect_from_storage",
    "build_hung_sleeve_effect",
    "collect_official_marks",
    "marks_from_official_observations",
]
