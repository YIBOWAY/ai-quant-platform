from __future__ import annotations

import hashlib
import json
import math
from datetime import UTC, date, datetime, timedelta

import exchange_calendars
import pandas as pd
import pytest

from quant_system.config.settings import load_settings
from quant_system.execution.account import PaperAccount
from quant_system.execution.assistant_remote import (
    AssistantRemoteError,
    hang_candidate,
    record_verified_candidate,
)
from quant_system.execution.definition_open_prices import DefinitionOpenPriceSource
from quant_system.execution.models import OrderSide
from quant_system.execution.paper_strategy_execution_service import (
    PaperStrategyExecutionError,
    PaperStrategyExecutionService,
)
from quant_system.execution.paper_strategy_signal_service import PaperStrategySignalService
from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
from quant_system.execution.paper_strategy_sleeves import (
    PaperStrategySleeveService,
    SignalStatus,
    SleeveLot,
    StrategyConfig,
    StrategyExecutionPlan,
    StrategySignal,
    StrategySleeve,
    StrategySleeveMode,
)
from quant_system.execution.price_source import PricedQuote, PriceUnavailableError
from quant_system.research.definition_paper import definition_config_fields, definition_orders
from quant_system.research.strategy_definition import StrategyDefinition, StrategyFactor
from quant_system.research.strategy_runtime import decision_for_session, evaluate_definition
from tests.test_assistant_remote import _settings, _strong_returns
from tests.test_paper_strategy_execution import _fill


def definition(**updates):
    values = dict(
        kind="factor_blend",
        title="Frozen blend",
        symbols=["SPY", "QQQ", "IWM"],
        history_start="2025-01-02",
        factors=[
            StrategyFactor(
                factor_id="momentum", lookback=5, direction="higher_is_better", weight=2
            ),
            StrategyFactor(
                factor_id="volatility", lookback=5, direction="lower_is_better", weight=-0.5
            ),
        ],
        top_n=2,
        max_weight_per_symbol=0.4,
        min_order_value=25,
    )
    values.update(updates)
    return StrategyDefinition(**values)


def config_for(recipe):
    return StrategyConfig.create(name=recipe.title, **definition_config_fields(recipe))


@pytest.fixture
def prices():
    days = exchange_calendars.get_calendar("XNYS").sessions_in_range("2025-01-02", "2026-09-09")
    rows = []
    for index, day in enumerate(days):
        for offset, symbol in enumerate(["SPY", "QQQ", "IWM"]):
            price = 100 + index * (offset + 1) * 0.05 + math.sin(index / (offset + 2))
            rows.append(
                dict(
                    timestamp=day,
                    symbol=symbol,
                    open=price,
                    high=price + 1,
                    low=price - 1,
                    close=price,
                    volume=1000000 + index,
                    provider="futu",
                    interval="1d",
                    price_adjustment="qfq",
                )
            )
    return pd.DataFrame(rows)


class History:
    def __init__(self, prices):
        self.prices = prices
        self.calls = []

    def fetch_ohlcv(self, symbols, *, start, end, interval="1d"):
        self.calls.append(dict(symbols=symbols, start=start, end=end, interval=interval))
        # Deliberately return future data: the service must enforce the cutoff.
        return self.prices.loc[self.prices.symbol.isin(symbols)].copy()


class FilteringHistory(History):
    def fetch_ohlcv(self, symbols, *, start, end, interval="1d"):
        frame = super().fetch_ohlcv(symbols, start=start, end=end, interval=interval)
        stamps = pd.to_datetime(frame.timestamp, utc=True)
        return frame.loc[stamps.between(pd.Timestamp(start, tz="UTC"), pd.Timestamp(end, tz="UTC"))]


def test_recursive_macd_uses_frozen_origin_in_history_and_real_filtering_provider(
    tmp_path,
    monkeypatch,
):
    from tests.test_strategy_definition_runtime import prices_for

    recipe = definition(
        history_start="2020-01-02",
        top_n=1,
        factors=[StrategyFactor(factor_id="macd", lookback=100, direction="higher_is_better")],
    )
    prices = prices_for(recipe.symbols, start=recipe.history_start, end="2026-09-08")
    prices[["open", "close"]] = 100.0
    old_shock = (prices.symbol == "QQQ") & (prices.timestamp < "2023-01-03")
    prices.loc[old_shock, ["open", "close"]] = 1000.0
    service, sleeve, config, account, _ = signal_fixture(tmp_path, monkeypatch, prices, recipe)
    provider = FilteringHistory(prices)
    monkeypatch.setattr(
        "quant_system.execution.paper_strategy_signal_service.build_ohlcv_provider",
        lambda *_args, **_kwargs: (provider, "futu"),
    )
    historical = evaluate_definition(prices, recipe, "2026-09-04", "2026-09-08")
    assert historical["status"] == "available", historical.get("reason")
    expected = next(row for row in historical["signals"] if row["signal_date"] == "2026-09-03")
    signal = service.generate_daily_signal(
        sleeve=sleeve,
        config=config,
        account=account,
        signal_date="2026-09-04",
        persist=False,
    )
    assert signal.status == SignalStatus.GENERATED, signal.warnings
    assert provider.calls[-1]["start"] == "2020-01-02"
    assert signal.target_weights == expected["targets"] == {"QQQ": 0.4}
    assert signal.metadata["scores"] == expected["scores"]

    # The former 800-day fetch loses a 2023 shock even though the MACD formation
    # window is complete, changing the chosen symbol. A different origin is a
    # different definition, not an interchangeable warmup approximation.
    cut = pd.Timestamp("2026-09-03", tz="UTC") - pd.Timedelta(days=800)
    truncated = prices.loc[prices.timestamp >= cut]
    changed_origin = definition(
        history_start=truncated.timestamp.min().date().isoformat(),
        top_n=1,
        factors=recipe.factors,
    )
    wrong = decision_for_session(truncated, changed_origin, "2026-09-03")
    assert wrong["targets"] != expected["targets"]
    assert recipe.content_digest != changed_origin.content_digest
    provider.prices = truncated
    incomplete = service.generate_daily_signal(
        sleeve=sleeve,
        config=config,
        account=account,
        signal_date="2026-09-04",
        persist=False,
    )
    assert incomplete.status == SignalStatus.DATA_UNAVAILABLE
    assert incomplete.proposed_orders == []
    assert "benchmark_calendar_incomplete" in incomplete.warnings[-1]


def signal_fixture(tmp_path, monkeypatch, prices, recipe, *, cash=10000, lots=()):
    history = History(prices)
    monkeypatch.setattr(
        "quant_system.execution.paper_strategy_signal_service.build_ohlcv_provider",
        lambda *_args, **_kwargs: (history, "futu"),
    )
    config = config_for(recipe)
    storage = PaperStrategySleeveStorage(tmp_path)
    sleeve = StrategySleeve.create(
        config=config, mode=StrategySleeveMode.ALLOCATED, allocated_cash=10000
    )
    sleeve.cash = cash
    storage.save_sleeve_lots(
        sleeve.sleeve_id,
        [
            SleeveLot.create(
                sleeve_id=sleeve.sleeve_id,
                symbol=symbol,
                quantity=quantity,
                avg_cost=100,
                source="test",
            )
            for symbol, quantity in lots
        ],
    )
    service = PaperStrategySignalService(storage=storage, settings=load_settings())
    return service, sleeve, config, PaperAccount.open_new(), history


@pytest.mark.parametrize(
    ("frequency", "decision_date", "due"),
    [
        ("daily", "2026-09-03", True),
        ("weekly", "2026-09-03", False),
        ("weekly", "2026-09-04", True),
        ("monthly", "2026-08-28", False),
        ("monthly", "2026-08-31", True),
    ],
)
def test_paper_uses_same_decision_and_completed_session(
    tmp_path,
    monkeypatch,
    prices,
    frequency,
    decision_date,
    due,
):
    recipe = definition(rebalance=frequency)
    service, sleeve, config, account, history = signal_fixture(
        tmp_path, monkeypatch, prices, recipe
    )
    signal = service.generate_daily_signal(
        sleeve=sleeve,
        config=config,
        account=account,
        signal_date=(date.fromisoformat(decision_date) + timedelta(days=1)).isoformat(),
        persist=False,
    )
    expected = decision_for_session(prices, recipe, decision_date, current_weights={})
    assert signal.status == SignalStatus.GENERATED, signal.warnings
    assert signal.target_weights == (expected["targets"] or {})
    assert signal.metadata["scores"] == expected["scores"]
    assert signal.metadata["rebalance_due"] is due
    assert signal.metadata["definition_digest"] == recipe.content_digest
    assert signal.data_as_of == decision_date
    assert history.calls[0]["end"] == decision_date
    assert history.calls[0]["start"] == recipe.history_start
    assert signal.metadata["history_start"] == recipe.history_start
    if not due:
        assert signal.proposed_orders == []


def test_empty_targets_exit_owned_lots_but_none_holds():
    recipe = definition(min_order_value=0)
    arguments = dict(
        definition=recipe, holdings={"SPY": 10}, cash=100, prices={"SPY": 120}, account_id="default"
    )
    assert definition_orders(**arguments, targets=None) == []
    orders = definition_orders(**arguments, targets={})
    assert len(orders) == 1
    assert orders[0]["side"] == "sell"
    assert orders[0]["estimated_quantity"] == 10


def test_signal_clears_positions_and_passes_real_current_weights(tmp_path, monkeypatch, prices):
    recipe = definition(min_order_value=0)
    service, sleeve, config, account, _history = signal_fixture(
        tmp_path,
        monkeypatch,
        prices,
        recipe,
        cash=8000,
        lots=[("SPY", 10)],
    )
    received = {}

    def decision(_prices, _definition, decision_session, current_weights):
        received.update(current_weights)
        return dict(
            signal_date=decision_session,
            trade_date="2026-09-04",
            targets={},
            rebalance_due=True,
            ready=True,
            reason=None,
            scores=[],
            definition_digest=recipe.content_digest,
        )

    monkeypatch.setattr("quant_system.research.strategy_runtime.decision_for_session", decision)
    signal = service.generate_daily_signal(
        sleeve=sleeve, config=config, account=account, signal_date="2026-09-04", persist=False
    )
    assert 0 < received["SPY"] < 1
    assert signal.target_weights == {}
    assert signal.proposed_orders[0]["estimated_quantity"] == 10


def test_missing_unheld_pool_price_matches_historical_kernel(tmp_path, monkeypatch, prices):
    missing = prices.loc[
        ~((prices.symbol == "QQQ") & (prices.timestamp == pd.Timestamp("2026-09-03")))
    ]
    recipe = definition()
    service, sleeve, config, account, _ = signal_fixture(tmp_path, monkeypatch, missing, recipe)
    signal = service.generate_daily_signal(
        sleeve=sleeve, config=config, account=account, signal_date="2026-09-04", persist=False
    )
    historical = evaluate_definition(
        missing,
        recipe,
        "2026-09-04",
        "2026-09-08",
        initial_cash=10000,
    )
    assert historical["status"] == "available", historical.get("reason")
    decision = next(row for row in historical["signals"] if row["signal_date"] == "2026-09-03")
    assert signal.status == SignalStatus.GENERATED, signal.warnings
    assert signal.target_weights == decision["targets"] == {"SPY": 0.4, "IWM": 0.4}
    assert signal.metadata["scores"] == decision["scores"]
    assert signal.metadata["eligible_symbols"] == decision["eligible_symbols"]
    assert {order["symbol"] for order in signal.proposed_orders} == {"SPY", "IWM"}


@pytest.mark.parametrize(("symbol", "lots"), [("SPY", []), ("QQQ", [("QQQ", 10)])])
def test_missing_benchmark_or_held_price_remains_unavailable(
    tmp_path,
    monkeypatch,
    prices,
    symbol,
    lots,
):
    missing = prices.loc[
        ~((prices.symbol == symbol) & (prices.timestamp == pd.Timestamp("2026-09-03")))
    ]
    service, sleeve, config, account, _ = signal_fixture(
        tmp_path,
        monkeypatch,
        missing,
        definition(),
        lots=lots,
    )
    signal = service.generate_daily_signal(
        sleeve=sleeve,
        config=config,
        account=account,
        signal_date="2026-09-04",
        persist=False,
    )
    assert signal.status == SignalStatus.DATA_UNAVAILABLE
    assert signal.proposed_orders == []
    assert "strategy_definition_decision_prices_missing" in signal.warnings[-1]


def test_selected_price_is_required_even_if_kernel_returns_unpriced_target(
    tmp_path,
    monkeypatch,
    prices,
):
    missing = prices.loc[
        ~((prices.symbol == "QQQ") & (prices.timestamp == pd.Timestamp("2026-09-03")))
    ]
    recipe = definition()
    service, sleeve, config, account, _ = signal_fixture(tmp_path, monkeypatch, missing, recipe)
    monkeypatch.setattr(
        "quant_system.research.strategy_runtime.decision_for_session",
        lambda *_args, **_kwargs: dict(
            ready=True,
            targets={"QQQ": 0.4},
            rebalance_due=True,
            scores=[],
        ),
    )
    signal = service.generate_daily_signal(
        sleeve=sleeve,
        config=config,
        account=account,
        signal_date="2026-09-04",
        persist=False,
    )
    assert signal.status == SignalStatus.DATA_UNAVAILABLE
    assert signal.proposed_orders == []
    assert "strategy_definition_selected_prices_missing" in signal.warnings[-1]


def test_config_freezes_full_weights_and_rejects_drift():
    recipe = definition(rebalance="monthly")
    config = config_for(recipe)
    assert config.weights == {"momentum": 2, "volatility": -0.5}
    assert config.top_n == 2 and config.rebalance_frequency == "monthly"
    assert config.max_weight_per_symbol == 0.4 and config.min_order_value == 25
    assert config.strategy_definition["initial_cash"] == 100000
    assert "strategy_definition" in StrategyConfig.TRADING_LOGIC_FIELDS
    with pytest.raises(ValueError, match="strategy_definition_config_mismatch"):
        config.new_version(top_n=1)
    raw = config.model_dump(mode="json")
    raw["strategy_definition"]["min_order_value"] = 9
    with pytest.raises(ValueError, match="strategy_content_digest_mismatch"):
        StrategyConfig.model_validate(raw)
    with pytest.raises(ValueError, match="strategy_whole_share_paper_unsupported"):
        config_for(definition(whole_share_orders=True))


def test_source_fingerprint_drift_rejected():
    recipe = definition()
    raw = recipe.model_dump(mode="json")
    raw["source_fingerprints"]["research/strategy_runtime.py"] = "0" * 64
    raw["content_digest"] = ""
    # A deliberately re-digested altered binding must still match current source.
    changed = StrategyDefinition.model_validate(raw)
    with pytest.raises(ValueError, match="strategy_algorithm_source_mismatch"):
        config_for(changed)


def record_definition(tmp_path, settings, recipe, *, universe=None):
    from tests.test_validation_receipts import sealed_validation

    path = tmp_path / "definition.json"
    path.write_text(json.dumps(recipe.model_dump(mode="json")), encoding="utf-8")
    _, receipt_sha = sealed_validation(
        tmp_path / "validations" / "validation-sealed",
        recipe.content_digest,
        hashlib.sha256(b"sealed-test-comparison").hexdigest(),
    )
    return record_verified_candidate(
        settings,
        candidate_id="definition-test",
        objective="sealed-test",
        source="strategy_definition",
        source_digest=hashlib.sha256(path.read_bytes()).hexdigest(),
        source_path=str(path),
        factor_id="definition_" + recipe.content_digest[:24],
        universe=list(recipe.symbols) if universe is None else universe,
        comparison_digest=hashlib.sha256(b"sealed-test-comparison").hexdigest(),
        daily_returns=_strong_returns(),
        turnover_period=1.0,
        verification_receipt_digest=receipt_sha,
    )


def record_fundable_definition(tmp_path, settings, recipe):
    """Artificial bound originals for these two real financial-consumer tests.

    Twelve declared input windows form a complete family. The frozen recipe is
    retained verbatim; these arrays test binding/transactions, not strategy alpha.
    No DSR, quality, archive resolver or account implementation is replaced.
    """
    from quant_system.research import validation_receipts
    from quant_system.research.evaluation_service import _hash
    from quant_system.research.gate_v2.active_returns import recompute_active_returns
    from quant_system.research.trials import ResearchTrial, TrialsLedger
    from tests.gate_v2_fixtures import platform_result
    from tests.test_capital_evidence import write
    from tests.test_validation_receipts import sealed_validation

    directory = tmp_path / "strategy_library" / ("strategy-" + recipe.content_digest[:24])
    path = directory / "definition.json"
    source_sha = write(path, recipe.model_dump(mode="json"))
    comparison_digest = hashlib.sha256(b"artificial-bound-comparison").hexdigest()
    trials = []
    selected = None
    for index in range(12):
        returns = (
            [0.003 + 0.001 * math.sin(day) for day in range(252)]
            if index == 0
            else [0.00002 * index + 0.005 * math.sin(day + index) for day in range(252)]
        )
        payload = platform_result(
            equity_returns=returns, benchmark_returns=[0.0001] * 252, initial_cash=10000,
            start=(date(2025, 1, 2) + timedelta(days=index * 7)).isoformat(),
        )
        payload.update(
            definition=recipe.model_dump(mode="json"), definition_digest=recipe.content_digest,
            source="futu", price_adjustment="qfq", frequency="daily",
            metrics={"turnover": 1.0},
            profile={"id": f"artificial-window-{index}", "symbols": list(recipe.symbols),
                     "benchmark_symbol": recipe.benchmark_symbol},
        )
        run = directory / "validations" / f"validation-artificial-{index}"
        receipt_path, _ = sealed_validation(run, recipe.content_digest, comparison_digest)
        result_sha = write(run / "platform-result.json", payload)
        qlib = json.loads((run / "qlib-replay.json").read_text())
        qlib["source"]["platform_result_sha256"] = result_sha
        write(run / "qlib-replay.json", qlib)
        analysis = json.loads((run / "signal-analysis.json").read_text())
        analysis["source"]["result_sha256"] = result_sha
        write(run / "signal-analysis.json", analysis)
        validation = json.loads(receipt_path.read_text())
        validation["receipts"] = validation_receipts.receipt_bindings(run)
        validation_sha = write(receipt_path, validation)
        active = recompute_active_returns(payload["curve"], initial_cash=10000)
        trials.append(ResearchTrial.record(
            kind="platform_backtest", subject=f"artificial-window-{index}",
            universe=recipe.symbols, daily_returns=active["equity_returns"],
            window_start=active["dates"][0], window_end=active["dates"][-1],
            source="artificial_bridge_fixture",
            metadata={"run_id": f"artificial-bridge-{index}",
                      "strategy_definition_digest": recipe.content_digest,
                      "equity_curve_digest": _hash(payload["curve"])},
        ))
        if index == 0:
            selected = (active, validation_sha)
    TrialsLedger(tmp_path / "trials").append_many(trials)
    active, receipt_sha = selected
    return record_verified_candidate(
        settings, candidate_id="definition-funded-fixture", objective="artificial frozen recipe",
        source="strategy_definition", source_digest=source_sha, source_path=str(path),
        factor_id="definition_" + recipe.content_digest[:24], universe=list(recipe.symbols),
        comparison_digest=comparison_digest, daily_returns=active["equity_returns"],
        return_dates=active["dates"], turnover_period=1.0,
        verification_receipt_digest=receipt_sha,
    )


def test_candidate_hang_keeps_recipe_and_fixed_allocation(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "quant_system.research.definition_paper.definition_schedule_available", lambda: True
    )
    settings = _settings(tmp_path, monkeypatch)
    recipe = definition(rebalance="weekly")
    candidate = record_fundable_definition(tmp_path, settings, recipe)
    receipt = hang_candidate(
        settings,
        candidate_id=candidate["candidate_id"],
        expected_source_digest=candidate["source_digest"],
    )
    assert receipt["dsr"]["passed"] is True and receipt["dsr"]["n_trials"] == 12
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    sleeve = storage.load_sleeve(receipt["sleeve_id"])
    config = storage.load_strategy_config(sleeve.strategy_config_id)
    assert config.strategy_definition == recipe.model_dump(mode="json")
    assert config.weights == {"momentum": 2, "volatility": -0.5}
    assert config.top_n == 2 and config.rebalance_frequency == "weekly"
    assert sleeve.initial_allocated_cash == 10000
    assert sleeve.metadata["reference_initial_cash"] == 100000
    assert sleeve.metadata["automation_source"] == "d34"
    again = hang_candidate(
        settings,
        candidate_id=candidate["candidate_id"],
        expected_source_digest=candidate["source_digest"],
    )
    assert again["already_hung"] is True


def test_definition_candidate_rejects_universe_mismatch(tmp_path, monkeypatch):
    with pytest.raises(AssistantRemoteError, match="strategy_definition_universe_mismatch"):
        record_definition(
            tmp_path, _settings(tmp_path, monkeypatch), definition(), universe=["SPY"]
        )


def test_same_candidate_id_cannot_reuse_different_validation(tmp_path, monkeypatch):
    settings = _settings(tmp_path, monkeypatch)
    recipe = definition()
    first = record_definition(tmp_path, settings, recipe)
    with pytest.raises(AssistantRemoteError, match="candidate_validation_changed"):
        record_verified_candidate(
            settings,
            candidate_id=first["candidate_id"],
            objective="sealed changed validation",
            source="strategy_definition",
            source_digest=first["source_digest"],
            source_path=first["source_path"],
            factor_id=first["factor_id"],
            universe=first["universe"],
            comparison_digest="b" * 64,
            daily_returns=[-0.01] * 100,
            turnover_period=1,
        )


def test_definition_hang_recovers_same_allocation_after_book_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "quant_system.research.definition_paper.definition_schedule_available", lambda: True
    )
    import quant_system.execution.assistant_remote as remote

    settings = _settings(tmp_path, monkeypatch)
    candidate = record_fundable_definition(tmp_path, settings, definition(rebalance="monthly"))
    original = remote.save_book
    calls = 0

    def fail_once(settings, book):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("sealed book write failure")
        return original(settings, book)

    monkeypatch.setattr(remote, "save_book", fail_once)
    kwargs = dict(
        candidate_id=candidate["candidate_id"], expected_source_digest=candidate["source_digest"]
    )
    with pytest.raises(AssistantRemoteError, match="hang_book_persist_failed"):
        hang_candidate(settings, **kwargs)
    storage = PaperStrategySleeveStorage(tmp_path / "api_runs")
    pending = storage.list_sleeves()
    assert len(pending) == 1 and pending[0].status.value == "paused"
    recovered = hang_candidate(settings, **kwargs)
    assert recovered["sleeve_id"] == pending[0].sleeve_id
    sleeves = storage.list_sleeves()
    assert len(sleeves) == 1 and sleeves[0].initial_allocated_cash == 10000
    assert sleeves[0].status.value == "running"
    config = storage.load_strategy_config(sleeves[0].strategy_config_id)
    assert config.weights == {"momentum": 2, "volatility": -0.5}
    assert config.rebalance_frequency == "monthly"
    from quant_system.execution.account_storage import PaperAccountStorage

    account = PaperAccountStorage(tmp_path / "api_runs").load()
    assert sum(row.kind == "sleeve_cash_allocated" for row in account.ledger) == 1


class OpenPrices:
    def __init__(self, values, *, kind="futu_daily_open"):
        self.values, self.kind = values, kind

    def get_prices(self, symbols, *, target_date):
        return {
            symbol: PricedQuote(
                symbol=symbol,
                price=self.values[symbol],
                source="futu",
                price_kind=self.kind,
                as_of=target_date + "T09:30:00-04:00",
            )
            for symbol in symbols
        }


def execution_fixture(tmp_path):
    recipe = definition(max_weight_per_symbol=0.5, min_order_value=0)
    config = config_for(recipe)
    storage = PaperStrategySleeveStorage(tmp_path)
    storage.save_strategy_config(config)
    account = PaperAccount.open_new(initial_cash=100000)
    sleeve = PaperStrategySleeveService(storage).create_sleeve(
        account,
        config=config,
        mode=StrategySleeveMode.ALLOCATED,
        allocated_cash=10000,
        metadata={"definition_digest": recipe.content_digest},
    )
    account.apply_fill(
        _fill("SPY", OrderSide.BUY, 20, 100),
        source=f"strategy:{sleeve.sleeve_id}",
        price_kind="fixture",
    )
    sleeve.cash = 8000
    account.sleeve_cash[sleeve.sleeve_id] = 8000
    storage.save_sleeve(sleeve)
    storage.save_sleeve_lots(
        sleeve.sleeve_id,
        [
            SleeveLot.create(
                sleeve_id=sleeve.sleeve_id,
                symbol="SPY",
                quantity=20,
                avg_cost=100,
                source="fixture",
            )
        ],
    )
    targets = {"SPY": 0.5, "QQQ": 0.5}
    signal = StrategySignal.create(
        sleeve=sleeve,
        signal_date="2026-09-05",
        data_provider="futu",
        data_as_of="2026-09-04",
        target_weights=targets,
        proposed_orders=definition_orders(
            definition=recipe,
            holdings={"SPY": 20},
            cash=8000,
            targets=targets,
            prices={"SPY": 100, "QQQ": 100},
            account_id=account.account_id,
        ),
        metadata=dict(
            definition_digest=recipe.content_digest,
            signal_date="2026-09-04",
            trade_date="2026-09-08",
            targets=targets,
            ready=True,
            rebalance_due=True,
        ),
    )
    storage.append_signal(signal)
    plan = StrategyExecutionPlan.create(
        account=account, sleeve=sleeve, signal=signal, target_date="2026-09-07"
    )
    storage.append_execution(plan)
    return recipe, storage, account, sleeve, plan


def test_execution_rebudgets_at_real_open_and_preserves_journal(tmp_path):
    recipe, storage, account, sleeve, plan = execution_fixture(tmp_path)
    assert plan.target_date == "2026-09-08"  # Labor Day never becomes a fake open.
    calls = []
    service = PaperStrategyExecutionService(
        storage=storage,
        price_source=None,
        definition_open_price_source=OpenPrices({"SPY": 200, "QQQ": 100}),
        execution_policy_guard=lambda _a, _s, _p, orders: calls.append(orders),
        commission_bps=1,
        slippage_bps=5,
    )
    executed = service.execute_plan(account, sleeve=sleeve, plan=plan)
    assert calls and executed.metadata["sizing_basis"] == "session_open_equity"
    # Open equity is $12k, so SPY target is $6k, buying ten shares rather than
    # reusing the previous close's $3k buy notional (15 shares at this open).
    spy_fill = next(fill for fill in executed.fills if fill.symbol == "SPY")
    cost_multiplier = 1.0005 * 1.0001
    expected_spy_quantity = (8000 - 6000 * cost_multiplier) / (200 * cost_multiplier)
    assert spy_fill.quantity == pytest.approx(expected_spy_quantity)
    assert next(fill for fill in executed.fills if fill.symbol == "QQQ").quantity == 60
    assert spy_fill.price == pytest.approx(200 * 1.0005)
    assert all(fill.price_kind == "futu_daily_open" for fill in executed.fills)
    assert sleeve.cash >= 0
    journal = storage.load_pending_execution_journals()
    assert (
        len(journal) == 1
        and journal[0]["after_execution"]["metadata"]["definition_digest"] == recipe.content_digest
    )


@pytest.mark.parametrize("failure", ["snapshot", "missing", "digest", "metadata_removed", "cost"])
def test_definition_execution_does_not_downgrade_or_bypass(tmp_path, failure):
    _recipe, storage, account, sleeve, plan = execution_fixture(tmp_path)
    before = account.model_dump(mode="json")
    if failure == "digest":
        sleeve.metadata["definition_digest"] = "0" * 64
    if failure == "metadata_removed":
        sleeve.metadata = {}
    service = PaperStrategyExecutionService(
        storage=storage,
        price_source=None,
        definition_open_price_source=OpenPrices(
            {"SPY": 200, "QQQ": 100},
            kind="futu_snapshot" if failure == "snapshot" else "futu_daily_open",
        ),
        commission_bps=2 if failure == "cost" else 1,
        slippage_bps=5,
    )
    if failure == "missing":
        service.definition_open_price_source.get_prices = lambda *_args, **_kwargs: {}
    with pytest.raises(PaperStrategyExecutionError):
        service.execute_plan(account, sleeve=sleeve, plan=plan)
    assert account.model_dump(mode="json") == before
    assert storage.load_pending_execution_journals() == []


@pytest.mark.parametrize("opening_price", [100, 200])
def test_empty_estimate_still_has_real_open_rebalance_plan(tmp_path, monkeypatch, opening_price):
    from zoneinfo import ZoneInfo

    from quant_system.d34 import paper_cycle

    recipe, storage, account, sleeve, _old_plan = execution_fixture(tmp_path)
    targets = {"SPY": 0.2}
    signal = StrategySignal.create(
        sleeve=sleeve,
        signal_date="2026-09-09",
        data_provider="futu",
        data_as_of="2026-09-08",
        target_weights=targets,
        proposed_orders=[],
        metadata=dict(
            definition_digest=recipe.content_digest,
            signal_date="2026-09-08",
            trade_date="2026-09-09",
            targets=targets,
            ready=True,
            rebalance_due=True,
            rebalance_required=True,
        ),
    )
    storage.append_signal(signal)
    # Use the actual scheduler-to-plan boundary with sealed account/market fixtures.
    monkeypatch.setattr(paper_cycle, "_d34_running_sleeves", lambda _storage: [sleeve])

    class ScheduledRunner:
        def create_execution_once(self, sleeve_id, signal_id, *, target_date, metadata):
            assert sleeve_id == sleeve.sleeve_id and signal_id == signal.signal_id
            return PaperStrategySleeveService(storage).create_execution_plan(
                account, sleeve=sleeve, signal=signal, target_date=target_date, metadata=metadata,
            )

    cycle = paper_cycle.run_d34_paper_cycle(
        now=datetime(2026, 9, 9, 6, 15, tzinfo=ZoneInfo("Asia/Shanghai")),
        sleeve_storage=storage, runner=ScheduledRunner(),
    )
    assert cycle["executions_created"] == 1
    plan = storage.latest_execution_for_signal(sleeve.sleeve_id, signal.signal_id)
    assert plan.orders == [] and plan.status.value == "pending"
    account_before = account.model_dump(mode="json")
    policy_calls = []
    service = PaperStrategyExecutionService(
        storage=storage,
        price_source=None,
        definition_open_price_source=OpenPrices({"SPY": opening_price}),
        execution_policy_guard=lambda _a, _s, _p, orders: policy_calls.append(orders),
        commission_bps=1,
        slippage_bps=5,
    )
    result = service.execute_plan(account, sleeve=sleeve, plan=plan)
    assert len(policy_calls) == 1
    if opening_price == 100:
        assert result.status.value == "skipped"
        assert result.fills == []
        assert result.metadata["skip_reason"] == "no_rebalance_orders_at_open"
        assert account.model_dump(mode="json") == account_before
        assert storage.load_pending_execution_journals() == []
    else:
        assert result.status.value == "filled"
        assert result.fills[0].side == "sell"
        assert result.fills[0].quantity == 8


def test_open_price_reader_uses_session_open_and_strict_provenance(monkeypatch, prices):
    history = History(prices)
    monkeypatch.setattr(
        "quant_system.execution.definition_open_prices.build_ohlcv_provider",
        lambda *_args, **_kwargs: (history, "futu"),
    )
    source = DefinitionOpenPriceSource(clock=lambda: datetime(2026, 9, 8, 14, tzinfo=UTC))
    quotes = source.get_prices(["SPY"], target_date="2026-09-08")
    assert quotes["SPY"].price_kind == "futu_daily_open"
    assert history.calls[-1]["start"] == history.calls[-1]["end"] == "2026-09-08"
    before_open = DefinitionOpenPriceSource(clock=lambda: datetime(2026, 9, 8, 13, tzinfo=UTC))
    with pytest.raises(PriceUnavailableError, match="open_not_available"):
        before_open.get_prices(["SPY"], target_date="2026-09-08")
    history.prices = prices.assign(price_adjustment="raw")
    with pytest.raises(PriceUnavailableError, match="provenance_invalid"):
        source.get_prices(["SPY"], target_date="2026-09-08")


class FlakyOpenPrices:
    """Sealed transient open-price outage, then the real session open."""

    def __init__(self, values, *, failures_left: int) -> None:
        self.values = values
        self.failures_left = failures_left
        self.calls = 0

    def get_prices(self, symbols, *, target_date):
        self.calls += 1
        if self.failures_left > 0:
            self.failures_left -= 1
            raise PriceUnavailableError("strategy_definition_open_missing")
        return {
            symbol: PricedQuote(
                symbol=symbol,
                price=self.values[symbol],
                source="futu",
                price_kind="futu_daily_open",
                as_of=target_date + "T09:30:00-04:00",
            )
            for symbol in symbols
        }


def test_definition_open_outage_retries_and_fills_at_real_open(tmp_path):
    _recipe, storage, account, sleeve, plan = execution_fixture(tmp_path)
    source = FlakyOpenPrices({"SPY": 200, "QQQ": 100}, failures_left=1)
    sleeps: list[float] = []

    executed = PaperStrategyExecutionService(
        storage=storage,
        price_source=None,
        definition_open_price_source=source,
        commission_bps=1,
        slippage_bps=5,
        price_retry_backoff_seconds=30.0,
        sleep_func=sleeps.append,
    ).execute_plan(account, sleeve=sleeve, plan=plan)

    assert executed.status.value == "filled"
    assert source.calls == 2
    assert sleeps == [30.0]
    retry = executed.metadata["price_unavailable_retry"]
    assert [(row["attempt"], row["code"]) for row in retry["attempts"]] == [
        (1, "strategy_definition_open_data_unavailable"),
    ]
    assert all(fill.price_kind == "futu_daily_open" for fill in executed.fills)


def test_definition_open_outage_exhausts_retries_then_blocks_without_mutation(tmp_path):
    _recipe, storage, account, sleeve, plan = execution_fixture(tmp_path)
    before = account.model_dump(mode="json")
    source = FlakyOpenPrices({"SPY": 200, "QQQ": 100}, failures_left=99)
    sleeps: list[float] = []

    with pytest.raises(
        PaperStrategyExecutionError, match="strategy_definition_open_data_unavailable"
    ):
        PaperStrategyExecutionService(
            storage=storage,
            price_source=None,
            definition_open_price_source=source,
            commission_bps=1,
            slippage_bps=5,
            price_retry_backoff_seconds=30.0,
            sleep_func=sleeps.append,
        ).execute_plan(account, sleeve=sleeve, plan=plan)

    assert source.calls == 3
    assert sleeps == [30.0, 30.0]
    reloaded = storage.load_executions(sleeve.sleeve_id)[0]
    assert reloaded.status.value == "blocked"
    assert reloaded.blocked_reason == "strategy_definition_open_data_unavailable"
    assert reloaded.fills == []
    assert len(reloaded.metadata["price_unavailable_retry"]["attempts"]) == 2
    assert account.model_dump(mode="json") == before
    assert storage.load_pending_execution_journals() == []


def test_definition_open_outage_blocked_plan_expires_to_missed_window(tmp_path):
    _recipe, storage, account, sleeve, plan = execution_fixture(tmp_path)
    before = account.model_dump(mode="json")
    service = PaperStrategyExecutionService(
        storage=storage,
        price_source=None,
        definition_open_price_source=FlakyOpenPrices({"SPY": 200, "QQQ": 100}, failures_left=99),
        commission_bps=1,
        slippage_bps=5,
        sleep_func=lambda _seconds: None,
    )
    with pytest.raises(
        PaperStrategyExecutionError, match="strategy_definition_open_data_unavailable"
    ):
        service.execute_plan(account, sleeve=sleeve, plan=plan)

    assert service.mark_missed_window(plan, processing_date="2026-09-09") is True

    reloaded = storage.load_executions(sleeve.sleeve_id)[0]
    assert reloaded.status.value == "missed_window"
    assert reloaded.blocked_reason == "strategy_definition_open_data_unavailable"
    assert reloaded.metadata["missed_window"]["previous_status"] == "blocked"
    assert reloaded.fills == []
    assert account.model_dump(mode="json") == before


def test_historical_model_context_cannot_reach_signal_decision_or_execution(
    tmp_path, monkeypatch, prices
):
    """Artificial source change; assert actual consumer boundaries, no real market claims."""
    from quant_system.research import strategy_definition as module
    from quant_system.research.fingerprint_grading import frozen_definition_identity

    recipe = definition()
    service, sleeve, config, account, history = signal_fixture(
        tmp_path, monkeypatch, prices, recipe
    )
    _, storage, exec_account, exec_sleeve, plan = execution_fixture(
        tmp_path / 'execution'
    )
    original_digest = module._file_digest
    monkeypatch.setattr(module, '_file_digest', lambda p: 'e' * 64
                        if str(p).endswith('/research/strategy_runtime.py') else original_digest(p))
    historical = frozen_definition_identity(recipe)
    historical_config = StrategyConfig.frozen_for_replacement(config.model_dump(mode='json'))
    with pytest.raises(ValueError, match='strategy_algorithm_source_mismatch'):
        decision_for_session(prices, historical, '2026-09-03', current_weights={})
    signal = service.generate_daily_signal(
        sleeve=sleeve, config=historical_config, account=account,
        signal_date='2026-09-04', persist=False,
    )
    assert signal.status == SignalStatus.INVALID and signal.proposed_orders == []
    assert not history.calls
    assert any('strategy_algorithm_source_mismatch' in warning for warning in signal.warnings)
    historical_exec_config = storage.load_frozen_strategy_config(
        exec_sleeve.strategy_config_id, version=exec_sleeve.strategy_config_version
    )
    executor = PaperStrategyExecutionService(
        storage=storage, price_source=None,
        definition_open_price_source=OpenPrices({'SPY': 200, 'QQQ': 100}),
        commission_bps=1, slippage_bps=5,
    )
    before = exec_account.model_dump(mode='json')
    with pytest.raises(PaperStrategyExecutionError, match='strategy_algorithm_source_mismatch'):
        executor._definition_binding(sleeve=exec_sleeve, plan=plan, config=historical_exec_config)
    assert exec_account.model_dump(mode='json') == before
