from pathlib import Path


def test_backtest_form_exposes_order_execution_constraints() -> None:
    form = Path("src/frontend/components/forms/BacktestForm.tsx").read_text(
        encoding="utf-8"
    )

    minimum_order_schema = form.split("min_order_value: z.coerce", 1)[1].split(
        "whole_share_orders:", 1
    )[0]
    assert ".number({ invalid_type_error: text.errorInvalidNumber })" in minimum_order_schema
    assert ".nonnegative(text.errorNonNegativeNumber)" in minimum_order_schema
    assert "whole_share_orders: z.boolean()" in form
    assert 'form.register("min_order_value", { valueAsNumber: true })' in form
    assert 'form.register("whole_share_orders")' in form
