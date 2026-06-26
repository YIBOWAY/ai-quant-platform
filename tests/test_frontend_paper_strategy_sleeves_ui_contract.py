from pathlib import Path


API_TYPES = Path("src/frontend/lib/api.ts")
PAPER_TRADING_PAGE = Path("src/frontend/app/paper-trading/page.tsx")
SLEEVES_PANEL = Path("src/frontend/components/forms/PaperStrategySleevesPanel.tsx")
ACCOUNT_TRADE_PANEL = Path("src/frontend/components/forms/AccountTradePanel.tsx")


def test_frontend_exposes_strategy_sleeve_api_contract() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")

    for type_name in [
        "PaperStrategyConfigResponse",
        "PaperStrategyConfigMutationResponse",
        "PaperStrategyConfigsResponse",
        "PaperStrategySleeveResponse",
        "PaperStrategySleeveMutationResponse",
        "PaperStrategySleevesResponse",
        "PaperStrategySignalResponse",
        "PaperStrategySignalMutationResponse",
        "PaperStrategySleeveDetailResponse",
    ]:
        assert f"export type {type_name}" in api_types

    for getter in [
        "getPaperStrategyConfigs",
        "getPaperStrategySleeves",
        "getPaperStrategySleeveDetail",
    ]:
        assert f"export function {getter}" in api_types


def test_paper_trading_page_mounts_strategy_sleeves_workspace() -> None:
    page = PAPER_TRADING_PAGE.read_text(encoding="utf-8")

    assert "PaperStrategySleevesPanel" in page
    assert "getPaperStrategyConfigs()" in page
    assert "getPaperStrategySleeves()" in page
    assert "getPaperStrategySleeveDetail" in page
    assert "strategyConfigs.apiError" in page
    assert "strategySleeves.apiError" in page


def test_strategy_sleeves_panel_is_signal_first_without_auto_fill_language() -> None:
    panel = SLEEVES_PANEL.read_text(encoding="utf-8")

    assert "Signals are generated here; fills remain manual" in panel
    assert "成交仍然不会自动发生" in panel
    assert 'apiPost<PaperStrategySignalMutationResponse>' in panel
    assert '"/api/paper/strategy-sleeves"' in panel
    assert "allocated_cash: mode === \"allocated\" ? allocatedCash : 0" in panel
    assert "auto-fill" not in panel.lower()
    assert "automatic execution" not in panel.lower()


def test_legacy_rebalance_is_labeled_as_full_account_advanced_path() -> None:
    trade_panel = ACCOUNT_TRADE_PANEL.read_text(encoding="utf-8")

    assert "Advanced Full-Account Rebalance" in trade_panel
    assert "高级全账户再平衡" in trade_panel
    assert '"/api/paper/account/rebalance"' in trade_panel
    assert "Strategy Sleeves use the separate signal panel" in trade_panel
    assert "策略袖珍仓请使用独立信号面板" in trade_panel
