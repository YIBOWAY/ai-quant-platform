from pathlib import Path

API_TYPES = Path("src/frontend/lib/api.ts")
ACCOUNT_TRADE_PANEL = Path("src/frontend/components/forms/AccountTradePanel.tsx")
PENDING_CANCEL_BUTTON = Path(
    "src/frontend/components/forms/PendingOrderCancelButton.tsx"
)


def test_paper_account_mutations_use_shared_response_types() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")
    trade_panel = ACCOUNT_TRADE_PANEL.read_text(encoding="utf-8")
    cancel_button = PENDING_CANCEL_BUTTON.read_text(encoding="utf-8")

    for type_name in [
        "PaperAccountOrderOutcome",
        "PaperAccountOrderResponse",
        "PaperAccountOrdersProcessResponse",
        "PaperAccountRebalanceResponse",
    ]:
        assert f"export type {type_name}" in api_types

    for local_type in [
        "type OrderResult =",
        "type ProcessPendingResult =",
        "type RebalanceResult =",
        "type CancelPendingOrderResult =",
    ]:
        assert local_type not in trade_panel
        assert local_type not in cancel_button

    assert "apiPost<PaperAccountOrderResponse>" in trade_panel
    assert "apiPost<PaperAccountOrdersProcessResponse>" in trade_panel
    assert "apiPost<PaperAccountRebalanceResponse>" in trade_panel
    assert "apiPost<PaperAccountResponse>" in trade_panel
    assert "apiPost<PaperAccountOrderResponse>" in cancel_button
    assert '"@/lib/api"' in trade_panel
    assert '"@/lib/api"' in cancel_button


def test_shared_paper_account_mutation_types_include_backend_fields() -> None:
    api_types = API_TYPES.read_text(encoding="utf-8")

    for field in [
        "order_id?: string | null;",
        "requested_quantity: number;",
        "filled_quantity: number;",
        "price?: number | null;",
        "price_kind?: string | null;",
        "rejected_reason?: string | null;",
        "account: PaperAccountResponse;",
        "orders: PaperAccountOrderOutcome[];",
        "target_weights: Record<string, number>;",
        "rebalance: PaperAccountRebalanceSummary;",
    ]:
        assert field in api_types
