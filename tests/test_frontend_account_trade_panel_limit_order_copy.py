from pathlib import Path


def test_account_trade_panel_explains_limit_orders_can_stay_pending() -> None:
    source = Path("src/frontend/components/forms/AccountTradePanel.tsx").read_text(
        encoding="utf-8"
    )

    assert "stays pending" in source
    assert "保留为待处理" in source
