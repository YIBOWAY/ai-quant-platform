from pathlib import Path


def test_paper_trading_panels_distinguish_offline_from_empty() -> None:
    page = Path("src/frontend/app/paper-trading/page.tsx").read_text(encoding="utf-8")

    assert "const accountDown = Boolean(account.apiError);" in page
    assert "const ledgerDown = Boolean(ledger.apiError);" in page
    assert "accountDown={accountDown}" in page
    assert "ledgerDown={ledgerDown}" in page
    assert "text.holdingsUnavailable" in page
    assert "text.ledgerUnavailable" in page


def test_position_map_uses_activity_api_error_for_account_down_state() -> None:
    page = Path("src/frontend/app/position-map/page.tsx").read_text(encoding="utf-8")

    assert "const accountDown = Boolean(activity.apiError || account.apiError);" in page
