from pathlib import Path


def test_backtest_form_exposes_order_execution_constraints() -> None:
    form = Path("src/frontend/components/forms/BacktestForm.tsx").read_text(
        encoding="utf-8"
    )

    assert "min_order_value: z.coerce.number().nonnegative()" in form
    assert "whole_share_orders: z.boolean()" in form
    assert 'form.register("min_order_value", { valueAsNumber: true })' in form
    assert 'form.register("whole_share_orders")' in form
