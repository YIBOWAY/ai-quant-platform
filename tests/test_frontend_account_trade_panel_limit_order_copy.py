from pathlib import Path


def test_account_trade_panel_explains_limit_orders_are_not_queued() -> None:
    source = Path("src/frontend/components/forms/AccountTradePanel.tsx").read_text(
        encoding="utf-8"
    )

    assert "not queued" in source
    assert "不会挂单" in source
