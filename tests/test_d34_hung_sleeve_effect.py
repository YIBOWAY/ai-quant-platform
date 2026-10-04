from __future__ import annotations

import json

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from quant_system.api.server import create_app
from quant_system.d34.hung_sleeve_effect import (
    EMPTY_EFFECT_LABEL_ZH,
    build_effect_from_storage,
    build_hung_sleeve_effect,
)
from quant_system.execution.account import PaperAccount
from quant_system.execution.paper_strategy_sleeve_storage import (
    PaperStrategySleeveStorage,
)
from quant_system.execution.paper_strategy_sleeves import (
    SleeveLot,
    StrategyExecutionFill,
    StrategyExecutionPlan,
    StrategyExecutionStatus,
    StrategySignal,
    StrategySleeve,
    StrategySleeveMode,
)


class _SameDayCloseProvider:
    provider_name = "futu"

    def fetch_ohlcv(
        self,
        symbols: list[str],
        *,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        closes = {"NVDA": 217.56, "SPY": 769.06}
        return pd.DataFrame(
            [
                {
                    "timestamp": pd.Timestamp("2026-08-19", tz="UTC"),
                    "symbol": symbol,
                    "close": closes[symbol],
                    "provider": "futu",
                    "interval": "1d",
                    "price_adjustment": "qfq",
                }
                for symbol in symbols
            ]
        )


class _SpyUnavailableProvider(_SameDayCloseProvider):
    def fetch_ohlcv(
        self,
        symbols: list[str],
        *,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        if symbols == ["SPY"]:
            raise RuntimeError("benchmark unavailable")
        return super().fetch_ohlcv(
            symbols,
            start=start,
            end=end,
            interval=interval,
        )


class _StrategyPriceUnavailableProvider(_SameDayCloseProvider):
    def fetch_ohlcv(
        self,
        symbols: list[str],
        *,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        if symbols != ["SPY"]:
            raise RuntimeError("strategy price unavailable")
        return super().fetch_ohlcv(
            symbols,
            start=start,
            end=end,
            interval=interval,
        )


class _TwoDayCloseProvider(_SameDayCloseProvider):
    def fetch_ohlcv(
        self,
        symbols: list[str],
        *,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        closes = {
            ("NVDA", "2026-08-19"): 217.56,
            ("NVDA", "2026-08-20"): 220.0,
            ("SPY", "2026-08-19"): 769.06,
            ("SPY", "2026-08-20"): 770.0,
        }
        return pd.DataFrame(
            [
                {
                    "timestamp": pd.Timestamp(day, tz="UTC"),
                    "symbol": symbol,
                    "close": closes[(symbol, day)],
                    "provider": "futu",
                    "interval": "1d",
                    "price_adjustment": "qfq",
                }
                for symbol in symbols
                for day in ("2026-08-19", "2026-08-20")
            ]
        )


class _InvalidProvenanceProvider(_SameDayCloseProvider):
    def __init__(self, failure: str) -> None:
        self.failure = failure

    def fetch_ohlcv(
        self,
        symbols: list[str],
        *,
        start: str,
        end: str,
        interval: str = "1d",
    ) -> pd.DataFrame:
        frame = super().fetch_ohlcv(
            symbols,
            start=start,
            end=end,
            interval=interval,
        )
        if self.failure == "provider":
            frame["provider"] = "sample"
        elif self.failure == "adjustment":
            frame["price_adjustment"] = "raw"
        elif self.failure == "duplicate":
            frame = pd.concat([frame, frame.iloc[[0]]], ignore_index=True)
        return frame


def _live_first_fill_storage(
    tmp_path,
    *,
    commission: float = 0.990495,
    estimated_cost: float | None = None,
) -> PaperStrategySleeveStorage:
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    before_sleeve = StrategySleeve(
        sleeve_id="sleeve-live-first-fill",
        account_id="default",
        strategy_config_id="strategy-config-live-first-fill",
        strategy_config_version=1,
        mode=StrategySleeveMode.ALLOCATED,
        initial_allocated_cash=10_000.0,
        cash=10_000.0,
        created_at="2026-08-18T07:42:47Z",
        updated_at="2026-08-18T07:42:47Z",
        metadata={"automation_source": "d34", "official_observation": True},
    )
    after_sleeve = before_sleeve.model_copy(
        update={"cash": 10_000.0 - 9_904.95 - commission},
        deep=True,
    )
    signal = StrategySignal(
        signal_id="signal-live-first-fill",
        sleeve_id=after_sleeve.sleeve_id,
        strategy_config_id=after_sleeve.strategy_config_id,
        strategy_config_version=after_sleeve.strategy_config_version,
        signal_date="2026-08-19",
        generated_at="2026-08-18T22:15:01Z",
        data_provider="futu",
        data_as_of="2026-08-18T00:00:00Z",
        target_weights={"NVDA": 0.99},
        proposed_orders=[],
        status="generated",
    )
    fill = StrategyExecutionFill(
        fill_id="strategy-fill-live-first-fill",
        symbol="NVDA",
        side="buy",
        quantity=45.57629148938717,
        price=217.3268091,
        gross_value=9_904.95,
        price_kind="futu_snapshot",
        filled_at="2026-08-19T14:25:03Z",
        metadata={
            "commission": commission,
            "commission_bps": 1.0,
            "slippage_bps": 5.0,
            **(
                {"estimated_cost": estimated_cost}
                if estimated_cost is not None
                else {}
            ),
        },
    )
    before_execution = StrategyExecutionPlan(
        execution_id="strategy-exec-live-first-fill",
        sleeve_id=after_sleeve.sleeve_id,
        account_id="default",
        signal_id=signal.signal_id,
        strategy_config_id=after_sleeve.strategy_config_id,
        strategy_config_version=after_sleeve.strategy_config_version,
        target_date="2026-08-19",
        created_at="2026-08-18T22:15:02Z",
        updated_at="2026-08-18T22:15:02Z",
        status="pending",
    )
    after_execution = before_execution.model_copy(
        update={
            "status": StrategyExecutionStatus.FILLED,
            "updated_at": "2026-08-19T14:25:03Z",
            "fills": [fill],
        },
        deep=True,
    )
    after_lots = [
        SleeveLot(
            lot_id="lot-live-first-fill",
            sleeve_id=after_sleeve.sleeve_id,
            symbol="NVDA",
            quantity=fill.quantity,
            avg_cost=217.2182,
            source=f"strategy:{after_sleeve.sleeve_id}",
        )
    ]
    account = PaperAccount.open_new(initial_cash=1_000_000.0)
    storage.save_sleeve(after_sleeve)
    storage.save_sleeve_lots(after_sleeve.sleeve_id, after_lots)
    storage.append_signal(signal)
    storage.save_executions(after_sleeve.sleeve_id, [after_execution])
    storage.save_execution_journal_pending(
        sleeve_id=after_sleeve.sleeve_id,
        execution_id=after_execution.execution_id,
        payload={
            "journal_version": 1,
            "created_at": "2026-08-19T14:25:03Z",
            "account_id": "default",
            "sleeve_id": after_sleeve.sleeve_id,
            "execution_id": after_execution.execution_id,
            "before_account": account.model_dump(mode="json"),
            "after_account": account.model_dump(mode="json"),
            "before_sleeve": before_sleeve.model_dump(mode="json"),
            "after_sleeve": after_sleeve.model_dump(mode="json"),
            "before_lots": [],
            "after_lots": [lot.model_dump(mode="json") for lot in after_lots],
            "before_execution": before_execution.model_dump(mode="json"),
            "after_execution": after_execution.model_dump(mode="json"),
        },
    )
    storage.commit_execution_journal(
        sleeve_id=after_sleeve.sleeve_id,
        execution_id=after_execution.execution_id,
    )
    return storage


def _add_late_first_fill_sleeve(
    storage: PaperStrategySleeveStorage,
    *,
    created_at: str = "2026-08-18T07:42:47Z",
) -> None:
    source_path = storage.execution_journal_committed_path(
        "sleeve-live-first-fill",
        "strategy-exec-live-first-fill",
    )
    source = source_path.read_text(encoding="utf-8")
    replacements = {
        "sleeve-live-first-fill": "sleeve-late-first-fill",
        "strategy-config-live-first-fill": "strategy-config-late-first-fill",
        "signal-live-first-fill": "signal-late-first-fill",
        "strategy-exec-live-first-fill": "strategy-exec-late-first-fill",
        "strategy-fill-live-first-fill": "strategy-fill-late-first-fill",
        "lot-live-first-fill": "lot-late-first-fill",
    }
    for before, after in replacements.items():
        source = source.replace(before, after)
    payload = json.loads(source)
    payload["created_at"] = "2026-08-20T14:25:03Z"
    for key in ("before_sleeve", "after_sleeve"):
        payload[key]["created_at"] = created_at
    for key in ("before_execution", "after_execution"):
        payload[key]["target_date"] = "2026-08-20"
        payload[key]["created_at"] = "2026-08-19T22:15:02Z"
    payload["before_execution"]["updated_at"] = "2026-08-19T22:15:02Z"
    payload["after_execution"]["updated_at"] = "2026-08-20T14:25:03Z"
    payload["after_execution"]["fills"][0]["filled_at"] = "2026-08-20T14:25:03Z"
    after_sleeve = StrategySleeve.model_validate(payload["after_sleeve"])
    after_lots = [SleeveLot.model_validate(row) for row in payload["after_lots"]]
    after_execution = StrategyExecutionPlan.model_validate(payload["after_execution"])
    signal = StrategySignal(
        signal_id="signal-late-first-fill",
        sleeve_id=after_sleeve.sleeve_id,
        strategy_config_id=after_sleeve.strategy_config_id,
        strategy_config_version=after_sleeve.strategy_config_version,
        signal_date="2026-08-20",
        generated_at="2026-08-19T22:15:01Z",
        data_provider="futu",
        data_as_of="2026-08-19T00:00:00Z",
        target_weights={"NVDA": 0.99},
        proposed_orders=[],
        status="generated",
    )
    storage.save_sleeve(after_sleeve)
    storage.save_sleeve_lots(after_sleeve.sleeve_id, after_lots)
    storage.append_signal(signal)
    storage.save_executions(after_sleeve.sleeve_id, [after_execution])
    storage.save_execution_journal_pending(
        sleeve_id=after_sleeve.sleeve_id,
        execution_id=after_execution.execution_id,
        payload=payload,
    )
    storage.commit_execution_journal(
        sleeve_id=after_sleeve.sleeve_id,
        execution_id=after_execution.execution_id,
    )


def _append_second_fill(storage: PaperStrategySleeveStorage) -> None:
    before_sleeve = storage.load_sleeve("sleeve-live-first-fill")
    before_lots = storage.load_sleeve_lots(before_sleeve.sleeve_id)
    signal = StrategySignal(
        signal_id="signal-live-second-fill",
        sleeve_id=before_sleeve.sleeve_id,
        strategy_config_id=before_sleeve.strategy_config_id,
        strategy_config_version=before_sleeve.strategy_config_version,
        signal_date="2026-08-20",
        generated_at="2026-08-19T22:15:01Z",
        data_provider="futu",
        data_as_of="2026-08-19T00:00:00Z",
        target_weights={"NVDA": 0.5},
        proposed_orders=[],
        status="generated",
    )
    fill = StrategyExecutionFill(
        fill_id="strategy-fill-live-second-fill",
        symbol="NVDA",
        side="sell",
        quantity=22.57629148938717,
        price=220.0,
        gross_value=4_966.784127665177,
        price_kind="futu_snapshot",
        filled_at="2026-08-20T14:25:03Z",
        metadata={"commission": 0.4966784127665177},
    )
    before_execution = StrategyExecutionPlan(
        execution_id="strategy-exec-live-second-fill",
        sleeve_id=before_sleeve.sleeve_id,
        account_id="default",
        signal_id=signal.signal_id,
        strategy_config_id=before_sleeve.strategy_config_id,
        strategy_config_version=before_sleeve.strategy_config_version,
        target_date="2026-08-20",
        created_at="2026-08-19T22:15:02Z",
        updated_at="2026-08-19T22:15:02Z",
        status="pending",
    )
    after_execution = before_execution.model_copy(
        update={
            "status": StrategyExecutionStatus.FILLED,
            "updated_at": "2026-08-20T14:25:03Z",
            "fills": [fill],
        },
        deep=True,
    )
    after_sleeve = before_sleeve.model_copy(
        update={"cash": 5_060.346954252412},
        deep=True,
    )
    after_lots = [
        before_lots[0].model_copy(update={"quantity": 23.0}, deep=True)
    ]
    account = PaperAccount.open_new(initial_cash=1_000_000.0)
    storage.save_sleeve(after_sleeve)
    storage.save_sleeve_lots(after_sleeve.sleeve_id, after_lots)
    storage.append_signal(signal)
    storage.save_executions(
        after_sleeve.sleeve_id,
        [*storage.load_executions(after_sleeve.sleeve_id), after_execution],
    )
    storage.save_execution_journal_pending(
        sleeve_id=after_sleeve.sleeve_id,
        execution_id=after_execution.execution_id,
        payload={
            "journal_version": 1,
            "created_at": "2026-08-20T14:25:03Z",
            "account_id": "default",
            "sleeve_id": after_sleeve.sleeve_id,
            "execution_id": after_execution.execution_id,
            "before_account": account.model_dump(mode="json"),
            "after_account": account.model_dump(mode="json"),
            "before_sleeve": before_sleeve.model_dump(mode="json"),
            "after_sleeve": after_sleeve.model_dump(mode="json"),
            "before_lots": [lot.model_dump(mode="json") for lot in before_lots],
            "after_lots": [lot.model_dump(mode="json") for lot in after_lots],
            "before_execution": before_execution.model_dump(mode="json"),
            "after_execution": after_execution.model_dump(mode="json"),
        },
    )
    storage.commit_execution_journal(
        sleeve_id=after_sleeve.sleeve_id,
        execution_id=after_execution.execution_id,
    )


def test_first_fill_nav_uses_committed_cash_plus_lots_at_same_day_close(
    tmp_path,
) -> None:
    report = build_effect_from_storage(
        sleeve_storage=_live_first_fill_storage(tmp_path),
        price_provider=_SameDayCloseProvider(),
        price_source="futu:qfq",
    )

    assert report["sleeve_equity"] == pytest.approx(10_009.637481431073)
    assert report["series"] == [
        {
            "date": "2026-08-19",
            "sleeve_equity": pytest.approx(10_009.637481431073),
            "sleeve_pct": pytest.approx(0.09637481431073),
            "spy_close": 769.06,
            "spy_pct": 0.0,
            "allocated_cash": 10_000,
            "net_profit_usd": pytest.approx(9.637481431073),
            "covered_sleeve_count": 1,
            "filled": True,
        }
    ]
    assert report["observation_return_pct"] == 0.0
    assert report["return_method"] == "net_profit_over_allocated_capital"


def test_new_allocation_is_not_investment_profit() -> None:
    report = build_hung_sleeve_effect(
        hung_count=2,
        marks=[
            {"date": "2026-08-19", "sleeve_equity": 10_000, "filled": True,
             "allocated_cash": 10_000, "covered_sleeve_count": 1},
            {"date": "2026-09-10", "sleeve_equity": 20_000, "filled": True,
             "allocated_cash": 20_000, "covered_sleeve_count": 2},
        ],
    )
    assert report["sleeve_return_pct"] == 0.0
    assert report["net_profit_usd"] == 0.0
    assert report["allocated_cash"] == 20_000


def test_multiple_sleeves_without_funding_evidence_keep_return_unknown() -> None:
    report = build_hung_sleeve_effect(
        hung_count=2,
        marks=[
            {"date": "2026-08-19", "sleeve_equity": 10_000, "filled": True},
            {"date": "2026-09-10", "sleeve_equity": 20_000, "filled": True},
        ],
    )
    assert report["sleeve_equity"] == 20_000
    assert report["sleeve_return_pct"] is None
    assert report["return_reason"] == "allocation_evidence_unavailable"


def test_non_trade_day_prices_extend_valuation_not_fill_count(tmp_path) -> None:
    storage = _live_first_fill_storage(tmp_path)
    report = build_effect_from_storage(
        sleeve_storage=storage,
        price_provider=_TwoDayCloseProvider(),
        price_source="futu:qfq",
    )
    assert report["as_of"] == "2026-08-20"
    assert report["last_fill_date"] == "2026-08-19"
    assert report["observation_day_count"] == 1
    assert report["valuation_day_count"] == 2
    assert report["covered_sleeve_count"] == 1
    assert report["sleeve_equity"] == pytest.approx(
        94.05950500000108 + 45.57629148938717 * 220.0
    )
    assert report["valuation_status"] == "partial"
    assert "2026-08-21" in report["missing_valuation_dates"]


def test_missing_interior_price_session_is_visible_not_interpolated(tmp_path) -> None:
    from datetime import UTC, datetime

    class GappedPrices(_TwoDayCloseProvider):
        def fetch_ohlcv(self, symbols, **kwargs):
            frame = super().fetch_ohlcv(symbols, **kwargs)
            frame.loc[frame.timestamp == pd.Timestamp("2026-08-20", tz="UTC"), "timestamp"] = (
                pd.Timestamp("2026-08-21", tz="UTC")
            )
            return frame

    report = build_effect_from_storage(
        sleeve_storage=_live_first_fill_storage(tmp_path), price_provider=GappedPrices(),
        now=datetime(2026, 8, 22, tzinfo=UTC),
    )
    assert report["as_of"] == "2026-08-21"
    assert report["valuation_status"] == "partial"
    assert report["missing_valuation_dates"] == ["2026-08-20"]
    gap = next(row for row in report["series"] if row["date"] == "2026-08-20")
    assert gap["sleeve_equity"] is None
    assert gap["sleeve_pct"] is None
    assert gap["filled"] is False


def test_committed_journal_new_cash_sleeve_does_not_create_return_or_fill(tmp_path) -> None:
    storage = _live_first_fill_storage(tmp_path, commission=0)
    sleeve = storage.list_sleeves()[0]
    storage.save_sleeve(sleeve.model_copy(update={
        "sleeve_id": "new-cash-only-sleeve", "cash": 10_000,
        "created_at": "2026-08-20T00:00:00Z",
    }))
    before = {str(path): path.read_bytes() for path in storage.root_dir.rglob("*")
              if path.is_file()}

    class FlatPrices(_TwoDayCloseProvider):
        def fetch_ohlcv(self, symbols, **kwargs):
            frame = super().fetch_ohlcv(symbols, **kwargs)
            frame.loc[frame.symbol == "NVDA", "close"] = 9904.95 / 45.57629148938717
            frame.loc[frame.symbol == "SPY", "close"] = 100
            return frame

    report = build_effect_from_storage(sleeve_storage=storage, price_provider=FlatPrices())
    assert report["sleeve_return_pct"] == pytest.approx(0)
    assert report["net_profit_usd"] == pytest.approx(0)
    assert report["allocated_cash"] == 20_000
    assert report["covered_sleeve_count"] == 2
    assert report["observation_day_count"] == 1
    assert report["valuation_day_count"] == 2
    assert report["observation_return_pct"] is None
    assert before == {str(path): path.read_bytes() for path in storage.root_dir.rglob("*")
                      if path.is_file()}


def test_missing_seed_principal_disables_even_single_sleeve_return() -> None:
    report = build_hung_sleeve_effect(hung_count=1, marks=[
        {"date": "2026-08-19", "sleeve_equity": 10000, "allocated_cash": None,
         "filled": True},
        {"date": "2026-08-20", "sleeve_equity": 11000, "allocated_cash": None,
         "valuation": True},
    ])
    assert report["sleeve_equity"] == 11000
    assert report["sleeve_return_pct"] is None
    assert report["net_profit_usd"] is None
    assert report["observation_return_pct"] is None


def test_spy_ends_on_last_valid_strategy_valuation() -> None:
    report = build_hung_sleeve_effect(hung_count=1, marks=[
        {"date": day, "sleeve_equity": equity, "allocated_cash": 100,
         "filled": True}
        for day, equity in zip(["2026-08-19", "2026-08-20", "2026-08-21"],
                               [100, 110, None], strict=True)
    ], spy_closes={"2026-08-19": 100, "2026-08-20": 110, "2026-08-21": 120})
    assert report["as_of"] == "2026-08-20"
    assert report["spy_return_pct"] == pytest.approx(10)


def test_costs_and_turnover_end_at_same_valid_nav_date() -> None:
    report = build_hung_sleeve_effect(hung_count=1, marks=[
        {"date": "2026-08-19", "sleeve_equity": 100, "allocated_cash": 100,
         "filled": True, "cost": 1, "fill_notional": 50},
        {"date": "2026-08-20", "sleeve_equity": None, "allocated_cash": 100,
         "filled": True, "cost": 3, "fill_notional": 90},
    ])
    assert report["as_of"] == "2026-08-19"
    assert report["observation_day_count"] == 2
    assert report["cost_drag_pct"] == 1
    assert report["turnover"] == 0.5


def test_paper_review_excludes_costs_of_todays_unclosed_second_fill(tmp_path, monkeypatch) -> None:
    from datetime import UTC, datetime

    from quant_system.config.settings import Settings
    from quant_system.research import paper_evaluation

    storage = _live_first_fill_storage(tmp_path)
    _append_second_fill(storage)
    settings = Settings()
    settings.data.data_dir = tmp_path
    monkeypatch.setattr(paper_evaluation, "build_ohlcv_provider",
                        lambda *a, **kw: (_SameDayCloseProvider(), "futu"))
    monkeypatch.setattr(paper_evaluation, "build_effect_from_storage", lambda **kw:
                        build_effect_from_storage(**kw, now=datetime(2026, 8, 20, 15, tzinfo=UTC)))
    facts = paper_evaluation.build_paper_facts(settings)
    assert facts["period"]["observation_count"] == 2
    assert facts["period"]["closed_observation_count"] == 1
    assert facts["metrics"]["cost_as_of"] == facts["as_of"] == "2026-08-19"
    assert facts["metrics"]["commission_usd"] == pytest.approx(0.990495)
    assert facts["metrics"]["fill_notional_usd"] == pytest.approx(9904.95)


def test_intraday_fill_cannot_force_an_unclosed_daily_bar(tmp_path) -> None:
    from datetime import UTC, datetime

    report = build_effect_from_storage(
        sleeve_storage=_live_first_fill_storage(tmp_path),
        price_provider=_SameDayCloseProvider(), now=datetime(2026, 8, 19, 15, tzinfo=UTC),
    )
    assert report["requested_as_of"] == "2026-08-18"
    assert report["as_of"] != "2026-08-19"
    assert report["observation_day_count"] == 1
    assert not any(row["date"] == "2026-08-19" for row in report["series"])
    assert report["valuation_status"] == "unavailable"
    assert "等待交易日收盘" in report["empty_label_zh"]


def test_cash_only_sleeve_has_valuation_not_trading_performance(tmp_path) -> None:
    from datetime import UTC, datetime

    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    storage.save_sleeve(StrategySleeve(
        sleeve_id="cash-only", strategy_config_id="cash-config", mode="allocated",
        strategy_config_version=1,
        initial_allocated_cash=10_000, cash=10_000, created_at="2026-08-18T08:00:00Z",
        metadata={"automation_source": "d34", "official_observation": True},
    ))
    report = build_effect_from_storage(
        sleeve_storage=storage, now=datetime(2026, 8, 20, 22, tzinfo=UTC),
    )
    assert report["sleeve_equity"] == 10_000
    assert report["as_of"] == "2026-08-20"
    assert report["covered_sleeve_count"] == 1
    assert report["observation_day_count"] == 0
    assert report["sleeve_return_pct"] is None
    assert report["price_source"] == "none_needed"


def test_equivalent_instants_use_same_last_complete_session(tmp_path) -> None:
    from datetime import datetime

    storage = _live_first_fill_storage(tmp_path)
    ends = [build_effect_from_storage(
        sleeve_storage=storage, price_provider=_SameDayCloseProvider(),
        now=datetime.fromisoformat(clock),
    )["requested_as_of"] for clock in ("2026-08-20T18:00:00+00:00", "2026-08-21T02:00:00+08:00")]
    assert ends == ["2026-08-19", "2026-08-19"]


def test_actual_fill_commission_and_marked_nav_drive_cost_and_turnover(tmp_path) -> None:
    report = build_effect_from_storage(
        sleeve_storage=_live_first_fill_storage(tmp_path),
        price_provider=_SameDayCloseProvider(),
        price_source="futu:qfq",
    )

    assert report["turnover"] == pytest.approx(0.9895413313791872)
    assert report["cost_drag_pct"] == pytest.approx(0.009895413313791871)
    assert report["turnover"] < 1.0
    assert report["cost_drag_pct"] > 0.0


def test_filled_execution_without_committed_state_fails_closed(tmp_path) -> None:
    storage = _live_first_fill_storage(tmp_path)
    storage.execution_journal_committed_path(
        "sleeve-live-first-fill",
        "strategy-exec-live-first-fill",
    ).unlink()

    report = build_effect_from_storage(
        sleeve_storage=storage,
        price_provider=_SameDayCloseProvider(),
        price_source="futu:qfq",
    )

    assert report["observation_day_count"] == 1
    assert report["empty"] is False
    assert report["sleeve_equity"] is None
    assert report["sleeve_equity_status"] == "unavailable"
    assert report["sleeve_equity_reason"] == "committed_effect_state_unavailable"
    assert report["series"] == [
        {
            "date": "2026-08-19",
            "sleeve_equity": None,
            "sleeve_pct": None,
            "spy_close": None,
            "spy_pct": None,
        }
    ]


def test_committed_cash_tamper_fails_state_transition_validation(tmp_path) -> None:
    storage = _live_first_fill_storage(tmp_path)
    path = storage.execution_journal_committed_path(
        "sleeve-live-first-fill",
        "strategy-exec-live-first-fill",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["after_sleeve"]["cash"] = 5_000.0
    path.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")

    report = build_effect_from_storage(
        sleeve_storage=storage,
        price_provider=_SameDayCloseProvider(),
        price_source="futu:qfq",
    )

    assert report["sleeve_equity_status"] == "unavailable"
    assert report["sleeve_equity_reason"] == "committed_effect_state_unavailable"
    assert report["sleeve_equity"] is None


def test_spy_failure_is_explicit_without_erasing_sleeve_nav(tmp_path) -> None:
    report = build_effect_from_storage(
        sleeve_storage=_live_first_fill_storage(tmp_path),
        price_provider=_SpyUnavailableProvider(),
        price_source="futu:qfq",
    )

    assert report["sleeve_equity_status"] == "available"
    assert report["sleeve_equity"] == pytest.approx(10_009.637481431073)
    assert report["spy_status"] == "unavailable"
    assert report["spy_reason"] == "spy_price_unavailable"
    assert report["spy_return_pct"] is None
    assert report["series"][0]["spy_close"] is None


def test_missing_strategy_price_never_falls_back_to_current_cash(tmp_path) -> None:
    report = build_effect_from_storage(
        sleeve_storage=_live_first_fill_storage(tmp_path),
        price_provider=_StrategyPriceUnavailableProvider(),
        price_source="futu:qfq",
    )

    assert report["observation_day_count"] == 1
    assert report["empty"] is False
    assert report["sleeve_equity"] is None
    assert report["sleeve_equity_status"] == "unavailable"
    assert report["sleeve_equity_reason"] == "strategy_price_unavailable"
    assert report["turnover"] is None
    assert report["spy_status"] == "unavailable"
    assert report["spy_reason"] == "strategy_valuation_date_unavailable"
    assert report["series"][0]["spy_close"] == 769.06


@pytest.mark.parametrize("failure", ["provider", "adjustment", "duplicate"])
def test_untrusted_price_provenance_is_rejected(tmp_path, failure: str) -> None:
    report = build_effect_from_storage(
        sleeve_storage=_live_first_fill_storage(tmp_path),
        price_provider=_InvalidProvenanceProvider(failure),
        price_source="futu:qfq",
    )

    assert report["sleeve_equity_status"] == "unavailable"
    assert report["sleeve_equity_reason"] == "strategy_price_unavailable"
    assert report["sleeve_equity"] is None


def test_each_historical_day_uses_its_own_committed_after_state(tmp_path) -> None:
    storage = _live_first_fill_storage(tmp_path)
    _append_second_fill(storage)

    report = build_effect_from_storage(
        sleeve_storage=storage,
        price_provider=_TwoDayCloseProvider(),
        price_source="futu:qfq",
    )

    assert [point["date"] for point in report["series"]] == [
        "2026-08-19",
        "2026-08-20",
    ]
    assert report["series"][0]["sleeve_equity"] == pytest.approx(
        10_009.637481431073
    )
    assert report["series"][1]["sleeve_equity"] == pytest.approx(
        10_120.346954252412
    )


def test_staggered_first_fills_keep_all_existing_sleeve_seed_cash(tmp_path) -> None:
    storage = _live_first_fill_storage(tmp_path)
    _add_late_first_fill_sleeve(storage)

    report = build_effect_from_storage(
        sleeve_storage=storage,
        price_provider=_TwoDayCloseProvider(),
        price_source="futu:qfq",
    )

    assert report["hung_count"] == 2
    assert report["observation_day_count"] == 2
    assert report["series"][0]["sleeve_equity"] == pytest.approx(
        20_009.637481431073
    )
    assert report["series"][1]["sleeve_equity"] == pytest.approx(
        2 * (94.05950500000108 + 45.57629148938717 * 220.0)
    )


def test_allocation_before_us_close_counts_despite_next_shanghai_day(tmp_path) -> None:
    storage = _live_first_fill_storage(tmp_path)
    _add_late_first_fill_sleeve(
        storage,
        created_at="2026-08-19T17:00:00Z",
    )

    report = build_effect_from_storage(
        sleeve_storage=storage,
        price_provider=_TwoDayCloseProvider(),
        price_source="futu:qfq",
    )

    assert report["series"][0]["date"] == "2026-08-19"
    assert report["series"][0]["sleeve_equity"] == pytest.approx(
        20_009.637481431073
    )


@pytest.mark.parametrize(("created_at", "expected"), [
    ("2026-08-19T19:59:00Z", "2026-08-19"),
    ("2026-08-19T20:01:00Z", "2026-08-20"),
    ("2026-12-01T20:59:00Z", "2026-12-01"),
    ("2026-12-01T21:01:00Z", "2026-12-02"),
])
def test_allocation_cutoff_uses_summer_and_winter_exchange_close(created_at, expected) -> None:
    from datetime import datetime

    from quant_system.d34.hung_sleeve_effect import _allocation_session

    assert _allocation_session(datetime.fromisoformat(created_at)) == expected


def test_hung_effect_api_returns_nav_cost_and_spy_without_writing(
    tmp_path,
    monkeypatch,
) -> None:
    _live_first_fill_storage(tmp_path)
    monkeypatch.setattr(
        "quant_system.api.routes.paper.build_ohlcv_provider",
        lambda settings, requested: (_SameDayCloseProvider(), "futu"),
    )
    client = TestClient(create_app(output_dir=tmp_path))
    before = {
        str(path.relative_to(tmp_path)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(tmp_path.rglob("*"))
        if path.is_file()
    }

    response = client.get("/api/paper/strategy-sleeves/hung-effect")

    assert response.status_code == 200
    payload = response.json()
    assert payload["sleeve_equity"] == pytest.approx(10_009.637481431073)
    assert payload["turnover"] == pytest.approx(0.9895413313791872)
    assert payload["cost_drag_pct"] == pytest.approx(0.009895413313791871)
    assert payload["spy_status"] == "available"
    assert payload["series"][0]["spy_close"] == 769.06
    assert payload["price_source"] == "futu:qfq"
    after = {
        str(path.relative_to(tmp_path)): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in sorted(tmp_path.rglob("*"))
        if path.is_file()
    }
    assert after == before


def test_zero_observation_days_is_honest_empty_and_not_zero_percent() -> None:
    report = build_hung_sleeve_effect(
        hung_count=1,
        marks=[],
        spy_closes={},
        account_equity=1_075_468.0,
        fossil_marks=[{"date": "2026-08-10", "sleeve_equity": 50_000.0}],
    )

    assert report["hung_count"] == 1
    assert report["observation_day_count"] == 0
    assert report["empty"] is True
    assert report["empty_label_zh"] == "已挂 1 条 · 观察日 0 · 等第一个观察夜"
    assert report["sleeve_return_pct"] is None
    assert report["spy_return_pct"] is None
    assert report["turnover"] is None
    assert report["cost_drag_pct"] is None
    assert report["series"] == []
    assert "0%" not in report["empty_label_zh"]
    assert report["empty_label_zh"] == EMPTY_EFFECT_LABEL_ZH.format(hung_count=1)


def test_account_inventory_and_fossils_do_not_become_sleeve_performance() -> None:
    report = build_hung_sleeve_effect(
        hung_count=1,
        marks=[],
        spy_closes={"2026-08-18": 500.0, "2026-08-19": 510.0},
        account_equity=1_075_468.0,
        account_positions=[{"symbol": "NVDA", "quantity": 100, "market_value": 20_000.0}],
        fossil_marks=[{"date": "2026-08-18", "sleeve_equity": 12_000.0}],
    )

    assert report["empty"] is True
    assert report["sleeve_return_pct"] is None
    assert report["observation_day_count"] == 0
    assert report["series"] == []


def test_signal_day_without_fill_is_not_an_observation_day() -> None:
    """2026-08-19 live sample: 06:15 created a signal, 0 fills, hung-effect must stay empty."""
    today = {
        "date": "2026-08-19",
        "sleeve_equity": 10_000.0,
        "fill_notional": 0.0,
        "cost": 0.0,
    }
    report = build_hung_sleeve_effect(
        hung_count=1,
        marks=[today],
        spy_closes={"2026-08-19": 500.0},
        account_equity=1_075_468.0,
    )
    assert report["empty"] is True
    assert report["observation_day_count"] == 0
    assert report["series"] == []
    assert report["sleeve_return_pct"] is None
    assert report["empty_label_zh"] == EMPTY_EFFECT_LABEL_ZH.format(hung_count=1)

    from quant_system.d34.hung_sleeve_effect import marks_from_official_observations

    marks = marks_from_official_observations(
        [
            {
                "date": "2026-08-19",
                "sleeve_equity": 10_000.0,
                "sleeve": {
                    "cash": 10_000.0,
                    "metadata": {"automation_source": "d34", "official_observation": True},
                },
                "signal": {"signal_date": "2026-08-19"},
                "executions": [
                    {"status": "created", "fills": []},
                ],
            }
        ]
    )
    assert marks == []


def test_official_filled_mark_counts_even_when_notional_is_zero() -> None:
    report = build_hung_sleeve_effect(
        hung_count=1,
        marks=[
            {
                "date": "2026-08-20",
                "sleeve_equity": 10_000.0,
                "fill_notional": 0.0,
                "filled": True,
                "cost": 0.0,
            }
        ],
    )
    assert report["empty"] is False
    assert report["observation_day_count"] == 1
    assert report["series"][0]["date"] == "2026-08-20"


def test_two_observation_marks_rebase_first_day_to_zero_and_keep_spy() -> None:
    report = build_hung_sleeve_effect(
        hung_count=1,
        marks=[
            {
                "date": "2026-08-20",
                "sleeve_equity": 10_000.0,
                "fill_notional": 9_900.0,
                "cost": 5.94,
            },
            {
                "date": "2026-08-21",
                "sleeve_equity": 10_100.0,
                "fill_notional": 500.0,
                "cost": 0.3,
            },
        ],
        spy_closes={"2026-08-20": 500.0, "2026-08-21": 505.0},
        account_equity=1_075_468.0,
    )

    assert report["empty"] is False
    assert report["observation_day_count"] == 2
    assert report["sleeve_return_pct"] == 1.0
    assert report["spy_return_pct"] == 1.0
    assert report["series"][0]["date"] == "2026-08-20"
    assert report["series"][0]["sleeve_pct"] == 0.0
    assert report["series"][0]["spy_pct"] == 0.0
    assert report["series"][1]["sleeve_pct"] == 1.0
    assert report["series"][1]["spy_pct"] == 1.0
    assert report["turnover"] == 1.04
    assert round(report["cost_drag_pct"], 4) == 0.0624
    assert report["empty_label_zh"] is None


def test_marks_from_official_observations_drop_fossils() -> None:
    from quant_system.d34.hung_sleeve_effect import marks_from_official_observations

    marks = marks_from_official_observations(
        [
            {
                "date": "2026-08-20",
                "sleeve_equity": 10_000.0,
                "sleeve": {"metadata": {"fossil": True}},
                "signal": {"signal_date": "2026-08-20"},
                "executions": [],
            },
            {
                "date": "2026-08-21",
                "sleeve_equity": 10_050.0,
                "sleeve": {"metadata": {"automation_source": "d34"}},
                "signal": {"signal_date": "2026-08-21"},
                "executions": [
                    {
                        "status": "filled",
                        "fills": [{"gross_value": 1000.0, "cost": 0.6}],
                    }
                ],
            },
        ]
    )
    assert [item["date"] for item in marks] == ["2026-08-21"]
    assert marks[0]["fill_notional"] == 1000.0
    assert marks[0]["cost"] == 0.6


def test_legacy_observation_mapper_reads_actual_fill_commission() -> None:
    from quant_system.d34.hung_sleeve_effect import marks_from_official_observations

    marks = marks_from_official_observations(
        [
            {
                "sleeve_equity": 10_000.0,
                "sleeve": {"metadata": {"automation_source": "d34"}},
                "signal": {"signal_date": "2026-08-19"},
                "executions": [
                    {
                        "status": "filled",
                        "fills": [
                            {
                                "gross_value": 9_904.95,
                                "metadata": {"commission": 0.990495},
                            }
                        ],
                    }
                ],
            }
        ]
    )

    assert marks[0]["cost"] == pytest.approx(0.990495)


def test_zero_commission_does_not_fall_through_to_estimated_cost() -> None:
    from quant_system.d34.hung_sleeve_effect import marks_from_official_observations

    marks = marks_from_official_observations(
        [
            {
                "sleeve_equity": 10_000.0,
                "sleeve": {"metadata": {"automation_source": "d34"}},
                "signal": {"signal_date": "2026-08-19"},
                "executions": [
                    {
                        "status": "filled",
                        "fills": [
                            {
                                "gross_value": 1_000.0,
                                "metadata": {
                                    "commission": 0.0,
                                    "estimated_cost": 6.0,
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    )

    assert marks[0]["cost"] == 0.0


def test_committed_zero_commission_is_not_replaced_by_estimated_cost(tmp_path) -> None:
    report = build_effect_from_storage(
        sleeve_storage=_live_first_fill_storage(
            tmp_path,
            commission=0.0,
            estimated_cost=6.0,
        ),
        price_provider=_SameDayCloseProvider(),
        price_source="futu:qfq",
    )

    assert report["cost_drag_pct"] == 0.0


class _RaisingProvider:
    provider_name = "futu"

    def fetch_ohlcv(self, *args, **kwargs):
        raise RuntimeError("simulated provider outage")


def test_price_source_label_is_unavailable_when_fetch_raises(tmp_path) -> None:
    """The label must not assert a price source that produced nothing."""
    report = build_effect_from_storage(
        sleeve_storage=_live_first_fill_storage(tmp_path),
        price_provider=_RaisingProvider(),
        price_source="futu:qfq",
    )
    assert report["observation_day_count"] == 1
    assert report["sleeve_equity"] is None
    assert report["price_source"] == "unavailable"


def test_price_source_label_is_unavailable_when_provider_never_built(
    tmp_path,
) -> None:
    report = build_effect_from_storage(
        sleeve_storage=_live_first_fill_storage(tmp_path),
        price_provider=None,
        price_source=None,
    )
    assert report["observation_day_count"] == 1
    assert report["price_source"] == "unavailable"
