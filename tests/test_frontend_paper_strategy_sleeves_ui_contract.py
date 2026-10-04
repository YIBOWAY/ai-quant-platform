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
    assert "AssistantRemotePanel" not in page
    assert "getPaperStrategyConfigs()" in page
    assert "getPaperStrategySleeves()" in page
    assert "getPaperStrategySleeveDetail" in page
    assert "strategyConfigs.apiError" in page
    assert "strategySleeves.apiError" in page


def test_paper_trading_page_fetches_details_for_all_strategy_sleeves() -> None:
    page = PAPER_TRADING_PAGE.read_text(encoding="utf-8")

    assert "getPaperStrategySleeveDetail(sleeve.sleeve_id)" in page
    assert ".slice(0, 6)" not in page


def test_strategy_sleeves_panel_says_hung_sleeves_can_fill() -> None:
    panel = SLEEVES_PANEL.read_text(encoding="utf-8")

    assert "Enabled allocated sleeves can fill and record P&L while live stays off" in panel
    assert "启用模拟运行的划拨仓可以成交并记录盈亏；实盘仍关闭" in panel
    assert "apiPost<PaperStrategySignalMutationResponse>" in panel
    assert '"/api/paper/strategy-sleeves"' in panel
    assert 'allocated_cash: mode === "allocated" ? allocatedCash : 0' in panel
    assert "fills remain manual" not in panel
    assert "成交仍然不会自动发生" not in panel


def test_strategy_sleeves_panel_processes_due_pending_execution_not_latest_only() -> None:
    panel = SLEEVES_PANEL.read_text(encoding="utf-8")

    assert "duePendingExecution" in panel
    assert "latestDuePendingExecution" in panel
    assert "localIsoDate" in panel
    assert 'latestExecution?.status === "pending"' not in panel


def test_strategy_sleeves_panel_does_not_label_sleeves_with_wrong_config_version() -> None:
    panel = SLEEVES_PANEL.read_text(encoding="utf-8")

    assert "config?.version === sleeve.strategy_config_version" in panel
    assert "boundConfig" in panel


def test_strategy_sleeves_panel_collapses_and_separates_official_from_history() -> None:
    panel = SLEEVES_PANEL.read_text(encoding="utf-8")

    assert "partitionStrategySleeves(sleeves)" in panel
    assert "officialSleeves" in panel
    assert "pendingSleeves" in panel
    assert "manualSleeves" in panel
    assert "historicalSleeves" in panel
    assert "正式模拟策略" in panel
    assert "待恢复启用" in panel
    assert "手动实验仓" in panel
    assert "历史测试仓" in panel
    assert "策略净值未计算" in panel
    assert 'data-paper-strategy-sleeves="collapsed-by-default"' in panel
    assert "allocatedTotal" not in panel
    assert "officialInitialCash" in panel
    assert "officialAvailableCash" in panel
    assert 'runtimeDetails: "运行详情 / 操作"' in panel
    assert "signalStatusLabel(latestSignal.status, locale)" in panel
    assert "executionStatusLabel(latestExecution.status, locale)" in panel
    assert "executionWindowLabel(latestExecution.execution_window, locale)" in panel


def test_legacy_rebalance_is_labeled_as_full_account_advanced_path() -> None:
    trade_panel = ACCOUNT_TRADE_PANEL.read_text(encoding="utf-8")

    assert "Advanced: Full-Account Rebalance (not a sleeve)" in trade_panel
    assert "高级：全账户再平衡（非策略仓）" in trade_panel
    assert '"/api/paper/account/rebalance"' in trade_panel
    assert "Strategy Sleeves use the separate signal panel" in trade_panel
    assert "策略仓请使用独立信号面板" in trade_panel
    assert "not a liquidation button or a new sleeve" in trade_panel
    assert "它不是清仓按钮，也不是新建策略仓" in trade_panel
