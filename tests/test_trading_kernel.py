from __future__ import annotations

import math

import pytest

from quant_system.trading_kernel import (
    Side,
    apply_fill_to_portfolio,
    plan_rebalance,
    roll_position_on_fill,
)


# --------------------------------------------------------------------------- #
# plan_rebalance — order generation rules                                       #
# --------------------------------------------------------------------------- #
def test_plan_rebalance_keeps_order_at_min_value_boundary() -> None:
    # Ported from tests/test_order_generation_threshold_alignment.py: a delta
    # that lands exactly on min_order_value must still produce one BUY.
    intents = plan_rebalance(
        holdings={},
        target_weights={"SPY": 0.1},
        prices={"SPY": 100.0},
        equity=1_000.0,
        min_order_value=100.0,
    )
    assert len(intents) == 1
    assert intents[0].side == Side.BUY
    assert intents[0].symbol == "SPY"
    assert intents[0].quantity == pytest.approx(1.0)


def test_plan_rebalance_rebalances_to_targets_and_closes_unselected() -> None:
    # Ported from test_backtest_strategy_orders: holding AAPL, target SPY only.
    intents = plan_rebalance(
        holdings={"AAPL": 5.0},
        target_weights={"SPY": 1.0},
        prices={"SPY": 100.0, "AAPL": 100.0},
        equity=1_000.0,
        min_order_value=1.0,
    )
    by_symbol = {intent.symbol: intent for intent in intents}
    assert set(by_symbol) == {"SPY", "AAPL"}
    assert by_symbol["AAPL"].side == Side.SELL
    assert by_symbol["AAPL"].quantity == pytest.approx(5.0)
    assert by_symbol["SPY"].side == Side.BUY
    assert by_symbol["SPY"].quantity == pytest.approx(10.0)


def test_plan_rebalance_can_floor_orders_to_whole_shares() -> None:
    intents = plan_rebalance(
        holdings={},
        target_weights={"SPY": 1.0},
        prices={"SPY": 100.0},
        equity=1_050.0,
        min_order_value=1.0,
        whole_share=True,
    )
    assert len(intents) == 1
    assert intents[0].side == Side.BUY
    assert intents[0].quantity == pytest.approx(10.0)


def test_plan_rebalance_whole_share_below_min_value_drops_order() -> None:
    # Floored quantity * price falls under min_order_value -> dropped by the
    # second (post-floor) min-order-value gate.
    intents = plan_rebalance(
        holdings={},
        target_weights={"SPY": 1.0},
        prices={"SPY": 100.0},
        equity=150.0,
        min_order_value=120.0,
        whole_share=True,
    )
    assert intents == []


def test_plan_rebalance_symbol_order_is_sorted_union_with_indices() -> None:
    # Deterministic sorted(set(holdings) | set(targets)) symbol order, and the
    # 1-based symbol_index covers skipped symbols too (backtest order-id parity).
    intents = plan_rebalance(
        holdings={"ZZZ": 1.0, "AAPL": 1.0},
        target_weights={"MSFT": 0.5, "AAPL": 0.5},
        prices={"AAPL": 100.0, "MSFT": 100.0, "ZZZ": 100.0},
        equity=10_000.0,
    )
    # Sorted union: AAPL(1), MSFT(2), ZZZ(3). AAPL already roughly at target may
    # still trade; assert indices reflect sorted position regardless of skips.
    index_by_symbol = {intent.symbol: intent.symbol_index for intent in intents}
    assert index_by_symbol["MSFT"] == 2
    assert index_by_symbol["ZZZ"] == 3
    # Symbols appear in sorted order when sells_first is False (default).
    assert [intent.symbol for intent in intents] == sorted(
        intent.symbol for intent in intents
    )


def test_plan_rebalance_sells_first_orders_sells_before_buys() -> None:
    intents = plan_rebalance(
        holdings={"AAPL": 500.0},
        target_weights={"MSFT": 1.0},
        prices={"AAPL": 100.0, "MSFT": 100.0},
        equity=50_000.0,
        sells_first=True,
    )
    assert intents[0].symbol == "AAPL"
    assert intents[0].side == Side.SELL
    assert any(
        intent.symbol == "MSFT" and intent.side == Side.BUY for intent in intents
    )
    # All sells precede all buys.
    sides = [intent.side for intent in intents]
    assert sides == sorted(sides, key=lambda s: 0 if s == Side.SELL else 1)


def test_plan_rebalance_default_order_is_not_sells_first() -> None:
    # Without sells_first, emitted symbols keep the sorted-union order even when
    # a sell and a buy are both present (backtest behavior).
    intents = plan_rebalance(
        holdings={"ZZZ": 500.0},
        target_weights={"AAA": 1.0},
        prices={"AAA": 100.0, "ZZZ": 100.0},
        equity=50_000.0,
    )
    assert [intent.symbol for intent in intents] == ["AAA", "ZZZ"]


@pytest.mark.parametrize(
    "bad_prices",
    [
        {},  # missing entirely
        {"QQQ": 0.0},  # non-positive
        {"QQQ": -1.0},  # negative
        {"QQQ": float("nan")},  # non-finite
        {"QQQ": float("inf")},  # non-finite
    ],
)
def test_plan_rebalance_rejects_missing_or_invalid_prices(bad_prices) -> None:
    # Unified strict rejection (the execution path's rule): missing, <=0, or
    # non-finite prices for any held/targeted symbol abort the whole plan.
    with pytest.raises(ValueError, match="missing order generation price for QQQ"):
        plan_rebalance(
            holdings={},
            target_weights={"QQQ": 0.5},
            prices={"SPY": 100.0, **bad_prices},
            equity=100_000.0,
        )


def test_plan_rebalance_min_quantity_floor_skips_dust() -> None:
    # min_quantity reproduces the persistent-account 1e-9 dust floor. A holding
    # exactly at target yields ~0 delta and must be skipped.
    intents = plan_rebalance(
        holdings={"AAPL": 100.0},
        target_weights={"AAPL": 1.0},
        prices={"AAPL": 100.0},
        equity=10_000.0,
        min_quantity=1e-9,
    )
    assert intents == []


def test_plan_rebalance_max_weight_cap_scales_down() -> None:
    # max_weight_per_symbol clamps a target weight before sizing.
    uncapped = plan_rebalance(
        holdings={},
        target_weights={"SPY": 1.0},
        prices={"SPY": 100.0},
        equity=10_000.0,
    )
    capped = plan_rebalance(
        holdings={},
        target_weights={"SPY": 1.0},
        prices={"SPY": 100.0},
        equity=10_000.0,
        max_weight_per_symbol=0.5,
    )
    assert uncapped[0].quantity == pytest.approx(100.0)
    assert capped[0].quantity == pytest.approx(50.0)


def test_plan_rebalance_sector_cap_scales_sector_group() -> None:
    # Two symbols in one sector exceeding the sector cap are scaled down
    # proportionally; the freed weight is not redistributed.
    intents = plan_rebalance(
        holdings={},
        target_weights={"AAA": 0.5, "BBB": 0.5},
        prices={"AAA": 100.0, "BBB": 100.0},
        equity=10_000.0,
        sector_cap=0.6,
        sector_map={"AAA": "TECH", "BBB": "TECH"},
    )
    by_symbol = {intent.symbol: intent.quantity for intent in intents}
    # Sector total 1.0 -> scaled to 0.6 -> each 0.3 -> 30 shares at $100 on $10k.
    assert by_symbol["AAA"] == pytest.approx(30.0)
    assert by_symbol["BBB"] == pytest.approx(30.0)


def test_plan_rebalance_no_caps_is_noop_passthrough() -> None:
    # When both caps are unset the weight map is untouched (default stream).
    intents = plan_rebalance(
        holdings={},
        target_weights={"SPY": 0.4, "QQQ": 0.6},
        prices={"SPY": 100.0, "QQQ": 100.0},
        equity=10_000.0,
    )
    by_symbol = {intent.symbol: intent.quantity for intent in intents}
    assert by_symbol["SPY"] == pytest.approx(40.0)
    assert by_symbol["QQQ"] == pytest.approx(60.0)


def test_order_intent_to_side_value_roundtrips_strenum() -> None:
    # Neutral Side maps cleanly to the value used by both OrderSide enums.
    assert Side.BUY.value == "buy"
    assert Side.SELL.value == "sell"


# --------------------------------------------------------------------------- #
# accounting — apply_fill_to_portfolio (Portfolio / PaperPortfolio math)        #
# --------------------------------------------------------------------------- #
class _Fill:
    """Minimal fill-like object matching the Portfolio fill duck-type."""

    def __init__(self, symbol, side, quantity, gross_value, commission, fill_price=0.0):
        self.symbol = symbol
        self.side = side
        self.quantity = quantity
        self.gross_value = gross_value
        self.commission = commission
        self.fill_price = fill_price


def test_apply_fill_to_portfolio_buy_then_sell() -> None:
    positions: dict[str, float] = {}
    cash = 1_000.0
    positions, cash = apply_fill_to_portfolio(
        positions,
        cash,
        _Fill("aapl", Side.BUY, 5.0, 500.0, 1.0),
    )
    assert positions == {"AAPL": 5.0}
    assert cash == pytest.approx(1_000.0 - 500.0 - 1.0)

    positions, cash = apply_fill_to_portfolio(
        positions,
        cash,
        _Fill("AAPL", Side.SELL, 5.0, 510.0, 1.0),
    )
    # Position fully closed and dropped (|qty| < 1e-10).
    assert positions == {}
    assert cash == pytest.approx(1_000.0 - 500.0 - 1.0 + 510.0 - 1.0)


def test_apply_fill_to_portfolio_drops_dust_position() -> None:
    positions = {"AAPL": 5.0}
    positions, cash = apply_fill_to_portfolio(
        positions,
        0.0,
        _Fill("AAPL", Side.SELL, 5.0 - 1e-12, 0.0, 0.0),
    )
    assert "AAPL" not in positions


def test_apply_fill_to_portfolio_does_not_mutate_input() -> None:
    positions = {"AAPL": 5.0}
    new_positions, _ = apply_fill_to_portfolio(
        positions,
        0.0,
        _Fill("AAPL", Side.BUY, 1.0, 100.0, 0.0),
    )
    # The pure helper returns a fresh mapping; the caller's dict is untouched.
    assert positions == {"AAPL": 5.0}
    assert new_positions == {"AAPL": 6.0}


# --------------------------------------------------------------------------- #
# accounting — roll_position_on_fill (PaperAccount avg_cost / realized_pnl)      #
# --------------------------------------------------------------------------- #
def test_roll_position_on_fill_buy_rolls_average_cost() -> None:
    new_qty, new_avg, realized, cash_delta = roll_position_on_fill(
        side=Side.BUY,
        position_quantity=10.0,
        position_avg_cost=50.0,
        fill_quantity=10.0,
        fill_price=60.0,
        gross_value=600.0,
        commission=5.0,
    )
    # total basis = 10*50 + 600 + 5 = 1105 over 20 shares.
    assert new_qty == pytest.approx(20.0)
    assert new_avg == pytest.approx(1_105.0 / 20.0)
    assert realized == pytest.approx(0.0)
    assert cash_delta == pytest.approx(-(600.0 + 5.0))


def test_roll_position_on_fill_sell_realizes_pnl() -> None:
    new_qty, new_avg, realized, cash_delta = roll_position_on_fill(
        side=Side.SELL,
        position_quantity=10.0,
        position_avg_cost=50.0,
        fill_quantity=4.0,
        fill_price=60.0,
        gross_value=240.0,
        commission=2.0,
    )
    # realized = 4*(60-50) - 2 = 38; avg_cost of remaining shares unchanged.
    assert new_qty == pytest.approx(6.0)
    assert new_avg == pytest.approx(50.0)
    assert realized == pytest.approx(38.0)
    assert cash_delta == pytest.approx(240.0 - 2.0)


def test_roll_position_on_fill_buy_from_flat_sets_avg_cost() -> None:
    new_qty, new_avg, realized, _ = roll_position_on_fill(
        side=Side.BUY,
        position_quantity=0.0,
        position_avg_cost=0.0,
        fill_quantity=10.0,
        fill_price=100.0,
        gross_value=1_000.0,
        commission=0.0,
    )
    assert new_qty == pytest.approx(10.0)
    assert new_avg == pytest.approx(100.0)
    assert realized == pytest.approx(0.0)


# --------------------------------------------------------------------------- #
# purity guard — the kernel must not import I/O / broker / provider modules     #
# --------------------------------------------------------------------------- #
def test_trading_kernel_is_pure_no_io_imports() -> None:
    import quant_system.trading_kernel as kernel
    import quant_system.trading_kernel.accounting as accounting
    import quant_system.trading_kernel.models as models
    import quant_system.trading_kernel.weights as weights

    forbidden = (
        "futu",
        "broker",
        "paper_broker",
        "provider",
        "price_source",
        "storage",
        "account_storage",
        "requests",
        "httpx",
    )
    for module in (kernel, accounting, models, weights):
        source = module.__file__
        with open(source, encoding="utf-8") as handle:
            text = handle.read()
        for token in forbidden:
            assert (
                f"import {token}" not in text and f"from {token}" not in text
            ), f"{source} unexpectedly references {token!r}"
        # No quant_system provider / execution-broker / storage imports either.
        assert "provider_factory" not in text, source
        assert "paper_broker" not in text, source
        assert math is math  # keep flake quiet about unused import
