"""Sealed price fixtures: no provider, model, account, persistence or scheduler."""

import numpy as np
import pandas as pd
import pytest
from pydantic import ValidationError

from quant_system.research.profile_backtests import run_formula_profile, run_profile
from quant_system.research.strategy_definition import (
    StrategyDefinition,
    StrategyFactor,
    StrategyFormula,
    definition_from_backtest,
    definition_from_study,
    formula_factor_id,
    validate_definition,
)
from quant_system.research.strategy_runtime import (
    _calendar,
    _prepare_context,
    decision_for_session,
    evaluate_definition,
    next_session,
)
from quant_system.research.study_profiles import STOCKS, list_study_profiles


def prices_for(symbols, start="2019-01-02", end="2020-04-07"):
    sessions = pd.to_datetime(
        _calendar(pd.Timestamp(start).year - 1, pd.Timestamp(end).year).sessions_in_range(
            start, end
        ),
        utc=True,
    )
    rows = []
    for number, symbol in enumerate(dict.fromkeys(symbols)):
        prices = 100 * np.exp(np.arange(len(sessions)) * (number + 1) / 10_000)
        for day, price in zip(sessions, prices, strict=True):
            rows.append(
                {
                    "symbol": symbol,
                    "timestamp": day,
                    "open": price,
                    "close": price,
                    "high": price * 1.01,
                    "low": price * 0.99,
                    "volume": 1_000_000,
                    "provider": "futu",
                    "price_adjustment": "qfq",
                    "interval": "1d",
                }
            )
    return pd.DataFrame(rows)


def blend(**updates):
    kwargs = dict(
        kind="factor_blend",
        title="测试组合",
        symbols=["AAPL", "MSFT", "NVDA"],
        history_start="2019-01-02",
        top_n=2,
        normalization="rank",
        factors=[
            StrategyFactor(
                factor_id="momentum", lookback=2, direction="higher_is_better", weight=1
            ),
            StrategyFactor(
                factor_id="volatility", lookback=5, direction="lower_is_better", weight=0.25
            ),
        ],
    )
    kwargs.update(updates)
    return StrategyDefinition(**kwargs)


def test_definition_digest_binds_parameters_and_source_but_not_display_title():
    first = blend()
    renamed = blend(title="换名字")
    assert first.content_digest == renamed.content_digest
    assert blend(rebalance="weekly").content_digest != first.content_digest
    assert blend(max_weight_per_symbol=0.2).content_digest != first.content_digest
    assert blend(min_order_value=5).content_digest != first.content_digest
    assert blend(history_start="2018-01-02").content_digest != first.content_digest
    assert first.factors[0].source_digest
    assert first.source_fingerprints["dependency:exchange_calendars"]
    assert validate_definition(first.model_dump(mode="json")) == first
    with pytest.raises(ValidationError, match="strategy_content_digest_mismatch"):
        StrategyDefinition.model_validate({**first.model_dump(mode="json"), "rebalance": "monthly"})
    profile = list_study_profiles()[0]
    original = definition_from_study({"profile": profile}, history_start="2015-01-01")
    profile["name"] = "仅标题变化"
    assert (
        definition_from_study(
            {"profile": profile},
            history_start="2015-01-01",
        ).content_digest
        == original.content_digest
    )


def test_strict_definition_rejects_extra_unsupported_and_leveraged_recipes():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        blend(leverage=2)
    with pytest.raises(ValidationError):
        blend(target_gross_exposure=1.01)
    with pytest.raises(ValidationError):
        blend(commission_bps=0)
    with pytest.raises(ValidationError, match="extra_forbidden"):
        StrategyFactor(factor_id="momentum", lookback=2, direction="higher_is_better", future=True)
    with pytest.raises(ValueError, match="strategy_sector_constraints_not_supported"):
        definition_from_backtest({"sector_cap": 0.2}, ["AAPL", "MSFT", "NVDA"], "非法")
    with pytest.raises(ValueError, match="strategy_kind_not_supported"):
        definition_from_backtest({"strategy_id": "unsupported"}, ["AAPL", "MSFT", "NVDA"], "非法")
    with pytest.raises(ValueError):
        StrategyFormula(expression="__import__('os').system('false')")


def test_from_backtest_preserves_individual_windows_directions_weights_and_frequency():
    definition = definition_from_backtest(
        {
            "rebalance_frequency": "monthly",
            "top_n": 2,
            "normalization": "rank",
            "max_weight_per_symbol": 0.3,
            "target_gross_exposure": 0.8,
            "factors": [
                {
                    "factor_id": "momentum",
                    "lookback": 7,
                    "direction": "lower_is_better",
                    "weight": 0.8,
                },
                {
                    "factor_id": "volatility",
                    "lookback": 21,
                    "direction": "higher_is_better",
                    "weight": -0.2,
                },
            ],
        },
        ["AAPL", "MSFT", "NVDA"],
        "独立参数",
        history_start="2019-01-02",
    )
    assert definition.rebalance == "monthly"
    assert [factor.lookback for factor in definition.factors] == [7, 21]
    assert definition.factors[0].direction == "lower_is_better"
    assert definition.factors[1].weight == -0.2
    assert definition.max_weight_per_symbol == 0.3
    assert definition.target_gross_exposure == 0.8
    assert definition.history_start == "2019-01-02"


def test_history_origin_is_required_and_never_inferred_from_evaluation_start():
    raw = blend().model_dump(mode="json")
    del raw["history_start"]
    with pytest.raises(ValidationError, match="history_start"):
        StrategyDefinition.model_validate(raw)
    with pytest.raises(ValidationError, match="history_start_invalid"):
        blend(history_start="2024-02-30")
    profile = list_study_profiles()[0]
    with pytest.raises(ValueError, match="strategy_history_start_required"):
        definition_from_study({"profile": profile, "start": "2018-01-01"})
    with pytest.raises(ValueError, match="strategy_history_start_required"):
        definition_from_backtest(
            {"start": "2018-01-01", "factor_ids": ["macd"], "lookback": 100},
            ["AAPL", "MSFT", "NVDA"],
            "缺少实际输入起点",
        )
    loaded = definition_from_study(
        {
            "profile": profile,
            "coverage": {"requested_start": "2018-01-01", "loaded_start": "2015-01-02"},
        }
    )
    assert loaded.history_start == "2015-01-02"


def test_history_truncates_before_recursive_macd_or_wilder_rsi_initialization():
    profile = next(p for p in list_study_profiles() if p["family"] == "rsi_reversion")
    rsi = definition_from_study({"profile": profile}, history_start="2020-01-02")
    macd = blend(
        history_start="2020-01-02",
        symbols=["SPY"],
        top_n=1,
        factors=[StrategyFactor(factor_id="macd", lookback=2, direction="higher_is_better")],
    )
    prices = prices_for([*profile["symbols"], "SPY"], start="2019-01-02", end="2020-04-07")
    before_origin = prices.timestamp < "2020-01-02"
    prices.loc[before_origin, ["open", "close"]] = 10000
    bounded = prices.loc[~before_origin].copy()
    for recipe in (macd, rsi):
        full = _prepare_context(prices, recipe, pd.Timestamp("2020-04-07", tz="UTC"))
        exact = _prepare_context(bounded, recipe, pd.Timestamp("2020-04-07", tz="UTC"))
        key = "rsi" if recipe.kind == "profile" else "scores"
        if key == "rsi":
            pd.testing.assert_series_equal(full[key], exact[key])
        else:
            pd.testing.assert_frame_equal(full[key], exact[key])
        assert full["frame"].timestamp.min() == pd.Timestamp("2020-01-02", tz="UTC")
        with pytest.raises(ValueError, match="benchmark_calendar_incomplete"):
            decision_for_session(
                bounded.loc[bounded.timestamp >= "2020-01-03"],
                recipe,
                "2020-04-07",
            )


@pytest.mark.parametrize("identifier", [profile["id"] for profile in list_study_profiles()])
def test_all_frozen_profiles_retain_existing_trade_and_nav_semantics(identifier):
    profile = next(item for item in list_study_profiles() if item["id"] == identifier)
    prices = prices_for([*profile["symbols"], profile["benchmark_symbol"]], start="2015-01-01")
    if profile["family"] == "rsi_reversion":
        mask = prices.symbol == profile["peer_symbols"][0]
        values = np.r_[np.linspace(100, 200, mask.sum() - 6), [199, 198, 197, 205, 206, 207]]
        prices.loc[mask, ["open", "close"]] = np.column_stack([values, values])
    definition = definition_from_study({"profile": profile}, history_start="2015-01-01")
    expected = run_profile(prices, identifier, start="2020-02-01", end="2020-04-07")
    actual = evaluate_definition(prices, definition, "2020-02-01", "2020-04-07")
    assert expected["status"] == actual["status"] == "available", actual
    assert actual["metrics"] == expected["metrics"]
    assert actual["trades"] == expected["trades"]
    assert actual["curve"] == expected["curve"]
    assert actual["peer_metrics"] == expected["peer_metrics"]
    assert [row["targets"] for row in actual["signals"]] == [
        row["targets"] for row in expected["signals"]
    ]
    assert definition.history_start == "2015-01-01"
    current = {}
    for row in actual["signals"]:
        single = decision_for_session(prices, definition, row["signal_date"], current)
        assert single["targets"] == row["targets"]
        assert single["scores"] == row["scores"]
        if row["targets"] is not None:
            current = row["targets"]


def test_formula_study_preserves_monthly_top5_and_full_formation():
    prices = prices_for([*STOCKS, "SPY"])
    expected = run_formula_profile(
        prices,
        "$close / Ref($close, 20)",
        start="2020-02-01",
        end="2020-04-07",
        proposal_id="one",
        title="冻结公式",
    )
    definition = definition_from_study(expected, history_start="2019-01-02")
    actual = evaluate_definition(prices, definition, "2020-02-01", "2020-04-07")
    assert actual["status"] == "available", actual
    assert (
        definition.kind == "formula" and definition.top_n == 5 and definition.rebalance == "monthly"
    )
    assert definition.formula.eligibility_window == 252
    assert actual["metrics"] == expected["metrics"]
    assert actual["trades"] == expected["trades"]
    hold = decision_for_session(prices, definition, "2020-02-04")
    assert not hold["rebalance_due"] and hold["targets"] is None


@pytest.mark.parametrize("frequency", ["daily", "weekly", "monthly"])
def test_blend_history_and_single_session_share_targets_without_future_prices(frequency):
    definition = blend(
        rebalance=frequency,
        max_weight_per_symbol=0.2,
        target_gross_exposure=0.8,
        history_start="2024-06-03",
    )
    prices = prices_for([*definition.symbols, "SPY"], start="2024-06-03", end="2024-09-10")
    result = evaluate_definition(prices, definition, "2024-08-01", "2024-09-10")
    assert result["status"] == "available", result
    assert result["signals"]
    for signal in result["signals"]:
        cutoff = pd.Timestamp(signal["signal_date"], tz="UTC")
        history = prices.loc[prices.timestamp <= cutoff]
        decision = decision_for_session(history, definition, signal["signal_date"])
        assert decision["targets"] == signal["targets"]
        assert decision["scores"] == signal["scores"]
        assert sum(decision["targets"].values()) <= 0.4 + 1e-10
    changed = prices.copy()
    changed.loc[changed.timestamp > "2024-08-30", ["open", "close"]] = np.nan
    before = decision_for_session(prices, definition, "2024-08-30")
    after = decision_for_session(changed, definition, "2024-08-30")
    assert before == after
    assert before["trade_date"] == "2024-09-03"  # Labor Day is closed.
    if frequency != "daily":
        hold = decision_for_session(prices, definition, "2024-09-03")
        assert hold["targets"] is None and not hold["rebalance_due"]


def test_cash_exit_and_hold_are_distinct_and_missing_data_is_not_filled():
    definition = blend(
        selection="positive_top",
        normalization="zscore",
        history_start="2024-07-01",
    )
    prices = prices_for([*definition.symbols, "SPY"], start="2024-07-01", end="2024-09-10")
    prices[["open", "close"]] = 100.0
    cash = decision_for_session(prices, definition, "2024-08-30", {"AAPL": 0.5})
    assert cash["ready"] and cash["targets"] == {}
    missing = prices.loc[~((prices.symbol == "SPY") & (prices.timestamp == "2024-08-29"))]
    with pytest.raises(ValueError, match="benchmark_session_missing|benchmark_calendar_incomplete"):
        decision_for_session(missing, definition, "2024-08-30")
    missing = prices.loc[~((prices.symbol == "AAPL") & (prices.timestamp == "2024-08-29"))]
    snapshot = decision_for_session(missing, definition, "2024-08-30")
    assert "AAPL" not in snapshot["eligible_symbols"]
    missing_last = prices.loc[~((prices.symbol == "AAPL") & (prices.timestamp == "2024-08-30"))]
    with pytest.raises(ValueError, match="held_symbol_price_missing"):
        decision_for_session(missing_last, definition, "2024-08-30", {"AAPL": 0.5})


def test_full_xnys_calendar_handles_special_closure_without_a_fake_bar():
    assert next_session("2025-01-08") == pd.Timestamp("2025-01-10", tz="UTC")
    definition = blend(history_start="2024-12-02")
    prices = prices_for([*definition.symbols, "SPY"], start="2024-12-02", end="2025-01-13")
    result = evaluate_definition(prices, definition, "2025-01-06", "2025-01-13")
    assert result["status"] == "available", result
    assert "2025-01-09" not in [row["date"] for row in result["curve"]]
    assert (
        next(row for row in result["signals"] if row["signal_date"] == "2025-01-08")["trade_date"]
        == "2025-01-10"
    )


def test_source_mutation_inside_frozen_model_is_rejected():
    definition = blend()
    definition.source_fingerprints["research/strategy_runtime.py"] = "0" * 64
    with pytest.raises(ValueError, match="content_digest_mismatch"):
        validate_definition(definition)


def test_evaluation_cash_scale_does_not_change_frozen_recipe_or_absolute_order_rule():
    profile = next(item for item in list_study_profiles() if item["id"] == "spy_sma10")
    definition = definition_from_study({"profile": profile}, history_start="2019-01-02")
    prices = prices_for(["SPY", "SHY"])
    full = evaluate_definition(prices, definition, "2020-02-01", "2020-04-07")
    small = evaluate_definition(prices, definition, "2020-02-01", "2020-04-07", initial_cash=10_000)
    assert full["status"] == small["status"] == "available"
    assert full["evaluation_initial_cash"] == 100_000
    assert small["evaluation_initial_cash"] == 10_000
    assert small["definition"] == full["definition"]
    assert small["metrics"]["total_return"] == pytest.approx(full["metrics"]["total_return"])
    assert small["costs"]["total"] * 10 == pytest.approx(full["costs"]["total"])
    capped = blend(min_order_value=20_000, history_start="2024-06-03")
    prices = prices_for([*capped.symbols, "SPY"], start="2024-06-03", end="2024-09-10")
    large = evaluate_definition(prices, capped, "2024-08-01", "2024-09-10")
    small = evaluate_definition(prices, capped, "2024-08-01", "2024-09-10", initial_cash=10_000)
    assert large["trade_count"] > 0
    assert small["trade_count"] == 0
    assert small["definition"]["min_order_value"] == 20_000


def formula_factor(expression, *, lookback=3, weight=3):
    return StrategyFactor(
        factor_id=formula_factor_id(expression),
        expression=expression,
        lookback=lookback,
        direction="higher_is_better",
        weight=weight,
    )


def test_formula_component_has_canonical_id_and_compiler_bound_source():
    first = formula_factor("$close / Ref($close, 2)")
    equivalent = formula_factor("($close/Ref($close,2))")
    assert first == equivalent
    assert first.factor_id.startswith("formula_")
    assert first.factor_version == "qlib-expression-v1"
    assert len(first.source_digest) == 64
    with pytest.raises(ValidationError, match="formula_factor_id_mismatch"):
        StrategyFactor(
            factor_id="momentum",
            expression=first.expression,
            lookback=3,
            direction="higher_is_better",
        )
    with pytest.raises(ValidationError, match="lookback_too_short"):
        formula_factor("$close / Ref($close, 2)", lookback=2)
    with pytest.raises(ValidationError, match="source_mismatch"):
        StrategyFactor.model_validate({**first.model_dump(), "source_digest": "0" * 64})
    with pytest.raises(ValueError):
        formula_factor("__import__('os').system('false')")


@pytest.mark.parametrize("normalization", ["rank", "zscore"])
def test_new_formula_combines_with_registered_factor_on_common_samples(normalization):
    expression = "-($close / Ref($close, 2))"
    frozen_formula = formula_factor(expression)
    momentum = StrategyFactor(
        factor_id="momentum", lookback=2, direction="higher_is_better", weight=1
    )
    definition = blend(
        factors=[momentum, frozen_formula],
        top_n=1,
        normalization=normalization,
        max_weight_per_symbol=0.4,
        history_start="2024-06-03",
    )
    prices = prices_for([*definition.symbols, "SPY"], start="2024-06-03", end="2024-09-10")
    result = evaluate_definition(prices, definition, "2024-08-01", "2024-09-10")
    assert result["status"] == "available", result
    first = result["signals"][0]
    # A larger weight on reversal changes selection away from strongest momentum.
    assert first["targets"] == {"AAPL": 0.4}
    assert set(first["scores"][0]["components"]) == {"momentum", frozen_formula.factor_id}
    assert "d34/qlib_expr.py" in definition.source_fingerprints
    for row in (result["signals"][0], result["signals"][-1]):
        cutoff = pd.Timestamp(row["signal_date"], tz="UTC")
        snapshot = decision_for_session(prices.loc[prices.timestamp <= cutoff], definition, cutoff)
        assert snapshot["targets"] == row["targets"]
        assert snapshot["scores"] == row["scores"]
    changed = prices.copy()
    changed.loc[changed.timestamp > first["signal_date"], ["open", "close"]] = np.nan
    assert (
        decision_for_session(changed, definition, first["signal_date"])["scores"] == first["scores"]
    )


def test_formula_component_missing_field_excludes_stock_from_both_normalizations():
    formula = formula_factor("$high / Ref($close, 2)", lookback=5)
    definition = blend(factors=[blend().factors[0], formula], history_start="2024-06-03")
    prices = prices_for([*definition.symbols, "SPY"], start="2024-06-03", end="2024-09-10")
    prices.loc[(prices.symbol == "AAPL") & (prices.timestamp == "2024-08-29"), "high"] = np.nan
    snapshot = decision_for_session(prices, definition, "2024-08-30")
    assert snapshot["eligible_symbols"] == ["MSFT", "NVDA"]
    assert len(snapshot["scores"]) == 2
    with pytest.raises(ValueError, match="study_formula_missing_fields:high"):
        decision_for_session(prices.drop(columns=["high"]), definition, "2024-08-30")
