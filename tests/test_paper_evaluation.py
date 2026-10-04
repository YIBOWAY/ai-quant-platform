from __future__ import annotations

import copy
import json
import math

import pandas as pd
import pytest

from quant_system.config.settings import Settings
from quant_system.d34.hung_sleeve_effect import build_hung_sleeve_effect
from quant_system.execution.account import PaperAccount
from quant_system.execution.paper_strategy_sleeve_storage import PaperStrategySleeveStorage
from quant_system.execution.paper_strategy_sleeves import (
    SleeveLot,
    StrategyExecutionFill,
    StrategyExecutionPlan,
    StrategyExecutionStatus,
    StrategySignal,
    StrategySleeve,
)
from quant_system.research import paper_evaluation as evaluation


@pytest.fixture
def settings(tmp_path):
    value = Settings()
    value.data.data_dir = tmp_path
    return value


def _one_committed_fill(settings):
    """Isolated journal fixture, not a trade or a simulated observation cycle."""
    storage = PaperStrategySleeveStorage(settings.data.data_dir / "api_runs")
    before = StrategySleeve(
        sleeve_id="sleeve-test",
        strategy_config_id="strategy-test",
        strategy_config_version=1,
        mode="allocated",
        initial_allocated_cash=1000,
        cash=1000,
        created_at="2026-08-18T00:00:00Z",
        metadata={"automation_source": "d34", "candidate_id": "candidate-test"},
    )
    after = before.model_copy(update={"cash": 899.0})
    signal = StrategySignal(
        signal_id="signal-test",
        sleeve_id=before.sleeve_id,
        strategy_config_id=before.strategy_config_id,
        strategy_config_version=1,
        signal_date="2026-08-19",
        data_provider="futu",
        target_weights={"SPY": 0.1},
    )
    fill = StrategyExecutionFill(
        fill_id="fill-test",
        symbol="SPY",
        side="buy",
        quantity=1,
        price=100,
        gross_value=100,
        price_kind="futu_snapshot",
        metadata={
            "commission": 1.0,
            "commission_bps": 1,
            "slippage_bps": 5,
            "estimated_cost": 999.0,
        },
    )
    pending = StrategyExecutionPlan(
        execution_id="execution-test",
        sleeve_id=before.sleeve_id,
        account_id="default",
        signal_id=signal.signal_id,
        strategy_config_id=before.strategy_config_id,
        strategy_config_version=1,
        target_date="2026-08-19",
        created_at="2026-08-19T00:00:00Z",
        updated_at="2026-08-19T00:00:00Z",
    )
    filled = pending.model_copy(update={"status": StrategyExecutionStatus.FILLED, "fills": [fill]})
    lot = SleeveLot(
        lot_id="lot-test",
        sleeve_id=before.sleeve_id,
        symbol="SPY",
        quantity=1,
        avg_cost=100,
        source="test",
    )
    account = PaperAccount.open_new(initial_cash=1000)
    storage.save_sleeve(after)
    storage.save_sleeve_lots(before.sleeve_id, [lot])
    storage.append_signal(signal)
    storage.save_executions(before.sleeve_id, [filled])
    payload = {
        "journal_version": 1,
        "created_at": "2026-08-19T00:00:00Z",
        "account_id": "default",
        "sleeve_id": before.sleeve_id,
        "execution_id": filled.execution_id,
        "before_account": account.model_dump(mode="json"),
        "after_account": account.model_dump(mode="json"),
        "before_sleeve": before.model_dump(mode="json"),
        "after_sleeve": after.model_dump(mode="json"),
        "before_lots": [],
        "after_lots": [lot.model_dump(mode="json")],
        "before_execution": pending.model_dump(mode="json"),
        "after_execution": filled.model_dump(mode="json"),
    }
    storage.save_execution_journal_pending(
        sleeve_id=before.sleeve_id,
        execution_id=filled.execution_id,
        payload=payload,
    )
    storage.commit_execution_journal(sleeve_id=before.sleeve_id, execution_id=filled.execution_id)
    return storage


class TestOnlyPriceProvider:
    provider_name = "futu"

    def fetch_ohlcv(self, symbols, *, start, end, interval):
        return pd.DataFrame(
            [
                {
                    "symbol": symbol,
                    "timestamp": pd.Timestamp("2026-08-19", tz="UTC"),
                    "close": 102.0,
                    "provider": "futu",
                    "interval": "1d",
                    "price_adjustment": "qfq",
                }
                for symbol in symbols
            ]
        )


class TestOnlyModel:
    __test__ = False
    model = "grok-4.6"
    reasoning_effort = "xhigh"

    def __init__(self, *, error=False, payload=None):
        self.calls = 0
        self.error = error
        self.payload = payload

    def _chat_json(self, messages):
        self.calls += 1
        if self.error:
            raise RuntimeError("private provider details must not be saved")
        return self.payload or {
            "summary": "有真实成交记录，但观察期不足，尚不能评判长期表现。[coverage]",
            "observations": ["已列出实际支付的佣金。[costs]"],
            "explanations": ["费用直接扣减资金，但不能把全部损益归因为费用。[costs]"],
            "limitations": ["未保存完整预测分数，无法判断预测能力是否下降。[prediction]"],
        }


@pytest.mark.parametrize("code, explanation", [
    ("paper_analysis_missing_fact_reference", "缺少可核对的事实引用"),
    ("paper_analysis_unsupported_prediction_or_sharpe", "包含没有数据支持的预测能力或夏普率判断"),
    ("paper_evaluation_model_mismatch", "模型或思考程度与设置不一致"),
])
def test_model_validation_failure_explains_reason_without_leaking_or_retrying(
    settings, monkeypatch, code, explanation
):
    _one_committed_fill(settings)
    _price_patch(monkeypatch)

    class InvalidModel(TestOnlyModel):
        def _chat_json(self, messages):
            self.calls += 1
            raise ValueError(code)

    client = InvalidModel()
    result = evaluation.refresh_paper_evaluation(settings, client=client)
    assert result["status"] == "failed" and result["analysis"] is None
    assert explanation in result["error"]
    assert result["facts"]["period"]["observation_count"] == 1
    evaluation.refresh_paper_evaluation(settings, client=client)
    assert client.calls == 1


def _price_patch(monkeypatch):
    monkeypatch.setattr(
        evaluation, "build_ohlcv_provider", lambda *a, **k: (TestOnlyPriceProvider(), "futu")
    )


def _files(path):
    return {
        str(item.relative_to(path)): item.read_bytes() for item in path.rglob("*") if item.is_file()
    }


def test_old_generic_model_failure_remains_failed_and_unchanged_on_read(settings, monkeypatch):
    _one_committed_fill(settings)
    _price_patch(monkeypatch)
    document = evaluation.refresh_paper_evaluation(settings, client=TestOnlyModel(error=True))
    document["error"] = "模拟运行 AI 解读未生成：ValueError；已保留程序计算的事实。"
    path = evaluation._cache_dir(settings) / "latest.json"
    evaluation._write(path, document)
    before = path.read_bytes()
    monkeypatch.setattr(
        evaluation, "build_ohlcv_provider", lambda *a, **k: pytest.fail("read fetched")
    )
    shown = evaluation.read_paper_evaluation(settings)
    assert shown["status"] == "failed" and shown["analysis"] is None
    assert "旧记录未保存具体原因" in shown["error"]
    assert shown["facts"] == document["facts"]
    assert path.read_bytes() == before


def test_no_observations_never_call_price_or_model(settings, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("No observations must not require a market provider")

    monkeypatch.setattr(evaluation, "build_ohlcv_provider", forbidden)
    model = TestOnlyModel()
    result = evaluation.refresh_paper_evaluation(settings, client=model)
    assert result["status"] == "unavailable"
    assert result["analysis"] is None
    assert result["as_of"] is None
    assert model.calls == 0
    assert not (settings.data.data_dir / "api_runs").exists()


def test_real_journal_reader_commission_not_estimated_cost_no_fake_sharpe(settings, monkeypatch):
    storage = _one_committed_fill(settings)
    _price_patch(monkeypatch)
    before = _files(storage.root_dir)
    result = evaluation.refresh_paper_evaluation(settings, client=TestOnlyModel())
    facts = result["facts"]
    assert result["status"] == "partial"
    assert facts["metrics"]["commission_usd"] == 1
    assert facts["metrics"]["fill_notional_usd"] == 100
    assert facts["metrics"]["commission_drag_pct"] == pytest.approx(1 / 1001 * 100)
    assert facts["metrics"]["turnover"] == pytest.approx(100 / 1001)
    assert facts["metrics"]["slippage_usd"] is None
    assert facts["metrics"]["daily_sharpe"] is None
    assert facts["metrics"]["sleeve_return_pct"] == pytest.approx(0.1)
    assert facts["metrics"]["return_method"] == "net_profit_over_allocated_capital"
    assert facts["metrics"]["net_profit_usd"] == 1.0
    assert facts["metrics"]["allocated_cash_usd"] == 1000.0
    assert facts["metrics"]["observation_return_pct"] == 0.0
    assert facts["prediction_decay"]["status"] == "unavailable"
    assert facts["signal_health"]["filled_execution_ids"] == ["execution-test"]
    assert before == _files(storage.root_dir)


def test_missing_committed_journal_fails_without_market_or_model(settings, monkeypatch):
    storage = _one_committed_fill(settings)
    storage.execution_journal_committed_path("sleeve-test", "execution-test").unlink()
    model = TestOnlyModel()
    monkeypatch.setattr(
        evaluation,
        "build_ohlcv_provider",
        lambda *a, **k: pytest.fail("Must fail before market IO"),
    )
    result = evaluation.refresh_paper_evaluation(settings, client=model)
    assert result["status"] == "unavailable"
    assert result["error"]
    assert result["facts"]["period"]["observation_count"] == 0
    assert model.calls == 0


def test_success_cache_reused_and_get_does_not_refresh(settings, monkeypatch):
    _one_committed_fill(settings)
    _price_patch(monkeypatch)
    model = TestOnlyModel()
    first = evaluation.refresh_paper_evaluation(settings, client=model)
    second = evaluation.refresh_paper_evaluation(settings, client=model)
    assert first == second
    assert first["analysis"]["model"] == "grok-4.6"
    assert first["analysis"]["reasoning_effort"] == "xhigh"
    assert model.calls == 1
    before = _files(settings.data.data_dir)
    monkeypatch.setattr(evaluation, "build_paper_facts", lambda *a: pytest.fail("GET is read-only"))
    assert evaluation.read_paper_evaluation(settings) == first
    assert before == _files(settings.data.data_dir)


def test_changed_input_failure_never_relabels_old_analysis(settings, monkeypatch):
    _one_committed_fill(settings)
    _price_patch(monkeypatch)
    first = evaluation.refresh_paper_evaluation(settings, client=TestOnlyModel())
    next_facts = copy.deepcopy(first["facts"])
    next_facts["signal_health"]["latest_signal_date"] = "2026-08-20"
    monkeypatch.setattr(evaluation, "build_paper_facts", lambda *a: next_facts)
    failing = TestOnlyModel(error=True)
    failed = evaluation.refresh_paper_evaluation(settings, client=failing)
    assert failed["status"] == "failed"
    assert failed["analysis"] is None
    assert failed["input_digest"] != first["input_digest"]
    assert "private provider" not in failed["error"]
    assert evaluation.read_paper_evaluation(settings) == failed
    assert evaluation.refresh_paper_evaluation(settings, client=failing) == failed
    assert failing.calls == 1
    assert (settings.data.data_dir / "paper_evaluations" / f"{first['input_digest']}.json").exists()


@pytest.mark.parametrize(
    "summary",
    [
        "预测能力已经下降。[prediction]",
        "夏普率是 2.5。[performance]",
        "已经观察到变化。[madeup]",
        "没有任何来源引用。",
    ],
)
def test_unsupported_prediction_sharpe_or_reference_rejected(settings, monkeypatch, summary):
    _one_committed_fill(settings)
    _price_patch(monkeypatch)
    raw = TestOnlyModel()._chat_json([{"content": ""}])
    raw["summary"] = summary
    result = evaluation.refresh_paper_evaluation(settings, client=TestOnlyModel(payload=raw))
    assert result["status"] == "failed"
    assert result["analysis"] is None


def test_corrupt_cache_is_visible_and_read_does_not_repair(settings, monkeypatch):
    path = settings.data.data_dir / "paper_evaluations" / "latest.json"
    path.parent.mkdir()
    path.write_text('{"status":"ready"}')
    before = path.read_bytes()
    monkeypatch.setattr(evaluation, "build_paper_facts", lambda *a: pytest.fail("Must not refresh"))
    assert evaluation.read_paper_evaluation(settings)["status"] == "failed"
    assert path.read_bytes() == before


def test_previous_return_method_stays_historical_without_a_model_call(settings, monkeypatch):
    path = settings.data.data_dir / "paper_evaluations" / "latest.json"
    path.parent.mkdir()
    path.write_text(json.dumps({"status": "partial", "facts": {
        "schema_version": "paper_evaluation_v1",
    }}))
    before = path.read_bytes()
    monkeypatch.setattr(evaluation, "build_paper_facts", lambda *a: pytest.fail("Pure read"))
    result = evaluation.read_paper_evaluation(settings)
    assert result["status"] == "unavailable"
    assert "旧摘要保留为历史" in result["error"]
    assert result["analysis"] is None
    assert path.read_bytes() == before


def test_unclosed_fill_keeps_fill_count_without_false_changed_read_error(settings, monkeypatch):
    from datetime import UTC, datetime

    _one_committed_fill(settings)
    _price_patch(monkeypatch)
    original = evaluation.build_effect_from_storage
    monkeypatch.setattr(evaluation, "build_effect_from_storage", lambda **kwargs: original(
        **kwargs, now=datetime(2026, 8, 19, 15, tzinfo=UTC),
    ))
    model = TestOnlyModel()
    result = evaluation.refresh_paper_evaluation(settings, client=model)
    facts = result["facts"]
    assert facts["period"]["observation_count"] == 1
    assert facts["period"]["closed_observation_count"] == 0
    assert facts["period"]["requested_as_of"] == "2026-08-18"
    assert facts["error"] == "awaiting_completed_session"
    assert model.calls == 0


@pytest.mark.parametrize("last_day,comparable", [("2026-08-21", True), ("2026-08-25", False)])
def test_window_changes_use_disjoint_not_cumulative_periods(
    settings, monkeypatch, last_day, comparable
):
    _one_committed_fill(settings)
    _price_patch(monkeypatch)
    dates = ["2026-08-19", "2026-08-20", last_day]
    marks = [
        {"date": day, "sleeve_equity": equity, "fill_notional": gross, "cost": cost, "filled": True}
        for day, equity, gross, cost in zip(
            dates, [1000, 1100, 1000], [900, 200, 100], [9, 2, 1], strict=True
        )
    ]
    effect = build_hung_sleeve_effect(hung_count=1, marks=marks)
    monkeypatch.setattr(evaluation, "collect_official_marks", lambda **k: (1, marks))
    monkeypatch.setattr(evaluation, "build_effect_from_storage", lambda **k: effect)
    facts = evaluation.build_paper_facts(settings)
    comparison = facts["window_comparison"]
    assert facts["metrics"]["commission_usd"] == 12
    assert facts["metrics"]["observed_max_drawdown_pct"] == pytest.approx(100 / 1100 * 100)
    assert comparison["previous"]["commission_usd"] == 2
    assert comparison["current"]["commission_usd"] == 1
    assert comparison["previous"]["fill_notional_usd"] == 200
    assert comparison["current"]["fill_notional_usd"] == 100
    if comparable:
        assert comparison["status"] == "available"
        assert comparison["changes"]["commission_usd"] == -1
        assert comparison["changes"]["turnover"] == pytest.approx(100 / 1100 - 200 / 1000)
    else:
        assert comparison["status"] == "not_comparable"
        assert comparison["changes"] is None


def test_sleeve_nav_leg_gets_an_active_metrics_block_against_spy(settings, monkeypatch):
    """SF2: the paper sleeve evaluation must emit the active-return sibling block.

    The observation journal is real per-session NAV marks plus SPY closes, i.e.
    the two legs exist; the block must come out of ``build_paper_facts`` rather
    than being skipped as "no continuous daily NAV".
    """
    _one_committed_fill(settings)
    _price_patch(monkeypatch)
    days = pd.bdate_range("2026-01-02", periods=140)
    position = pd.Series(range(len(days)), dtype="float64")
    reference = 0.0008 + 0.004 * (position / 5.0).apply(math.sin)
    strategy = reference + 0.0004 + 0.001 * ((position % 2) * 2 - 1)
    nav = 1000.0 * (1.0 + strategy).cumprod()
    spy = 500.0 * (1.0 + reference).cumprod()
    dates = [day.date().isoformat() for day in days]
    marks = [
        {
            "date": day,
            "sleeve_equity": float(equity),
            "fill_notional": 0.0,
            "cost": 0.0,
            "filled": True,
            "allocated_cash": 1000.0,
            "covered_sleeve_count": 1,
        }
        for day, equity in zip(dates, nav.to_numpy(), strict=True)
    ]
    spy_closes = {day: float(close) for day, close in zip(dates, spy.to_numpy(), strict=True)}
    effect = build_hung_sleeve_effect(hung_count=1, marks=marks, spy_closes=spy_closes)
    monkeypatch.setattr(evaluation, "collect_official_marks", lambda **k: (1, marks))
    monkeypatch.setattr(evaluation, "build_effect_from_storage", lambda **k: effect)

    facts = evaluation.build_paper_facts(settings)
    block = facts["active_metrics"]
    assert block["status"] == "ready"
    assert block["vs_benchmark"]["benchmark_symbol"] == "SPY"
    assert block["vs_peer"] is None
    assert block["n_observations"] == len(dates)
    assert block["vs_benchmark"]["block_bootstrap"]["nominal_coverage"] == 0.95
    # The sleeve NAV leg tracks SPY one-for-one here, so beta is ~1 and the
    # active leg is the added constant, not a fabricated number.
    assert block["vs_benchmark"]["beta_alpha"]["beta"] == pytest.approx(1.0, abs=0.05)
    assert block["vs_benchmark"]["active_return"]["daily_mean"] == pytest.approx(0.0004, rel=0.05)
    json.dumps(block, allow_nan=False)
    # The empty document keeps the key so consumers never see a shifted shape.
    assert "active_metrics" in evaluation._empty_facts()


def test_wrong_model_fails_without_calling_it(settings, monkeypatch):
    _one_committed_fill(settings)
    _price_patch(monkeypatch)
    model = TestOnlyModel()
    model.model = "different-model"
    result = evaluation.refresh_paper_evaluation(settings, client=model)
    assert result["status"] == "failed"
    assert result["analysis"] is None
    assert model.calls == 0


def test_cache_identity_rejects_changed_facts(settings, monkeypatch):
    _one_committed_fill(settings)
    _price_patch(monkeypatch)
    result = evaluation.refresh_paper_evaluation(settings, client=TestOnlyModel())
    path = settings.data.data_dir / "paper_evaluations" / "latest.json"
    result["facts"]["metrics"]["commission_usd"] = 10000
    path.write_text(json.dumps(result))
    assert evaluation.read_paper_evaluation(settings)["status"] == "failed"


@pytest.mark.parametrize(
    "state,error,expected",
    [
        ("partial", None, 0),
        ("unavailable", None, 0),
        ("failed", "model unavailable", 1),
        ("unavailable", "journal unavailable", 1),
    ],
)
def test_independent_cli_reports_status_without_running_archive(
    monkeypatch, capsys, state, error, expected
):
    result = {
        "status": state,
        "as_of": None,
        "input_digest": "test-digest",
        "analysis": None,
        "error": error,
    }
    monkeypatch.setattr(evaluation, "load_settings", lambda: object())
    monkeypatch.setattr(evaluation, "refresh_paper_evaluation", lambda _: result)
    assert evaluation.main() == expected
    output = json.loads(capsys.readouterr().out)
    assert output["paper_evaluation_status"] == state
    assert output["error"] == error


def test_one_unverifiable_sleeve_leaves_every_other_sleeve_readable(settings, monkeypatch):
    """A sleeve in an unproven replacement state degrades its own row only."""
    storage = _one_committed_fill(settings)
    healthy = storage.load_sleeve("sleeve-test")
    storage.save_sleeve(
        healthy.model_copy(
            deep=True,
            update={
                "sleeve_id": "sleeve-broken",
                "strategy_config_id": "strategy-broken",
                "strategy_config_version": 2,
                "cash": healthy.initial_allocated_cash,
                "metadata": {
                    **healthy.metadata,
                    "replacement_committed_id": "replacement-" + "a" * 24,
                    "current_version_observation_start": "2026-08-20T00:00:00Z",
                },
            },
        )
    )
    _price_patch(monkeypatch)
    facts = evaluation.build_paper_facts(settings)
    assert facts["error"] is None and facts["metrics"]
    rows = {row["sleeve_id"]: row for row in facts["sleeves"]}
    assert set(rows) == {"sleeve-test", "sleeve-broken"}
    assert rows["sleeve-test"]["signal_count"] == 1
    assert "version_scope_status" not in rows["sleeve-test"]
    assert rows["sleeve-broken"]["version_scope_status"] == "unverifiable"
    assert "replacement_history_unverified" in rows["sleeve-broken"]["version_scope_reason"]
    degraded = rows["sleeve-broken"]["current_version_performance"]
    assert degraded["status"] == "unverifiable" and degraded["reason"]
    assert "version_scope" not in rows["sleeve-broken"]
