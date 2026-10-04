"""Financial diagnostics must preserve the provider's gaps and fiscal periods."""

import json
from copy import deepcopy
from datetime import date

import pytest

from quant_system.research.company_financials import analyze_statements

AS_OF = date(2026, 9, 12)


def row(year=2027, quarter=2, end="2026-07-26", reported="2026-08-26", **values):
    return {
        "ff_year": year,
        "ff_period": str(quarter),
        "report_txt": f"Q{quarter} {year}",
        "fp_end": end,
        "rpt_date": reported,
        "fields": [
            {"field": field, "value": str(value), "name": field, "yoy": 0.17896}
            for field, value in values.items()
        ],
    }


def statement(*rows, currency="USD", report="qf"):
    return {"currency": currency, "report": report, "list": list(rows)}


def statements():
    return {
        "IS": statement(row(total_rev=200, gp=120, cost_rev=80, ni=50)),
        "BS": statement(
            row(total_assets=400, total_liab=100, total_equity=300, total_ca=80, total_cl=40)
        ),
        "CF": statement(row(cash_oper=75, ni_cf=50)),
    }


def metrics(result):
    return {item["key"]: item for item in result["metrics"]}


def checks(result):
    return {item["key"]: item for item in result["checks"]}


def test_three_aligned_statements_produce_explicit_quarter_metrics_without_mutating_input():
    data = statements()
    before = deepcopy(data)
    result = analyze_statements(data, as_of=AS_OF)
    latest = result["periods"][0]
    assert latest["fiscal_year"] == 2027  # A company's fiscal year is not today's year.
    assert latest["period"] == "FY2027Q2"
    assert latest["quarter"] == 2
    assert latest["period_end"] == "2026-07-26"
    assert latest["reported_at"] == "2026-08-26"
    assert result["currency"] == "USD"
    values = metrics(result)
    assert values["gross_margin_pct"]["value"] == 60
    assert values["net_margin_pct"]["value"] == 25
    assert values["debt_to_assets_pct"]["value"] == 25
    assert values["current_ratio"]["value"] == 2
    assert values["quarterly_gross_profit_to_assets_pct"]["value"] == 30
    assert values["operating_cash_flow_to_net_income_ratio"]["value"] == 1.5
    assert checks(result)["balance_sheet_equation:FY2027Q2"]["status"] == "passed"
    assert checks(result)["gross_profit_equation:FY2027Q2"]["status"] == "passed"
    assert data == before
    assert all(idea["status"] == "observation_only" for idea in result["research_ideas"])
    assert all(idea["required_data"] for idea in result["research_ideas"])
    assert "TTM" not in values["quarterly_gross_profit_to_assets_pct"]["label"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("data", [{}, {"IS": None, "BS": None, "CF": None}, {"ALL": {}}])
def test_empty_or_all_response_is_unavailable_and_not_zero_filled(data):
    result = analyze_statements(data, as_of=AS_OF)
    assert result["status"] == "unavailable"
    assert result["periods"] == []
    assert result["currency"] is None
    assert result["research_ideas"] == []
    assert result["warnings"]
    assert all(metric["value"] is None and metric["reason"] for metric in result["metrics"])


def test_yoy_is_recomputed_from_same_fiscal_quarter_and_qoq_across_year_boundary():
    data = {
        "IS": statement(
            row(total_rev=205.851, gp=100, cost_rev=105.851, ni=20),
            row(2026, 2, "2025-07-27", "2025-08-27", total_rev=100),
            row(2027, 1, "2026-04-26", "2026-05-20", total_rev=174.602),
            row(2026, 4, "2026-01-25", "2026-02-25", total_rev=160),
            row(2026, 3, "2025-10-26", "2025-11-19", total_rev=130),
        )
    }
    result = analyze_statements(data, as_of=AS_OF)
    values = metrics(result)
    assert values["revenue_yoy_pct"]["value"] == pytest.approx(105.851)
    assert values["revenue_qoq_pct"]["value"] == pytest.approx((205.851 / 174.602 - 1) * 100)
    assert result["periods"][1]["revenue_qoq_pct"] == pytest.approx((174.602 / 160 - 1) * 100)
    assert [p["quarter"] for p in result["periods"]] == [2, 1, 4, 3, 2]


def test_missing_quarter_never_compares_to_the_next_available_row():
    data = {
        "IS": statement(
            row(total_rev=200),
            row(2026, 4, "2026-01-25", "2026-02-25", total_rev=100),
        )
    }
    result = analyze_statements(data, as_of=AS_OF)
    values = metrics(result)
    assert values["revenue_qoq_pct"]["value"] is None
    assert values["revenue_yoy_pct"]["value"] is None
    assert all("ttm" not in metric["key"].lower() for metric in result["metrics"])


def test_conflicting_duplicate_period_is_rejected_without_picking_first_or_last():
    data = statements()
    data["IS"]["list"].append(row(total_rev=999, gp=120, cost_rev=80, ni=50))
    for rows in (data["IS"]["list"], list(reversed(data["IS"]["list"]))):
        data["IS"]["list"] = rows
        result = analyze_statements(data, as_of=AS_OF)
        assert result["status"] == "invalid"
        assert result["periods"][0]["revenue"] is None
        assert metrics(result)["gross_margin_pct"]["value"] is None
        assert any("重复" in message for message in result["warnings"])


def test_identical_duplicate_period_is_only_counted_once():
    data = statements()
    data["IS"]["list"].append(deepcopy(data["IS"]["list"][0]))
    result = analyze_statements(data, as_of=AS_OF)
    assert len(result["periods"]) == 1
    assert metrics(result)["gross_margin_pct"]["value"] == 60


@pytest.mark.parametrize(
    "end,reported",
    [
        ("2026-02-30", "2026-08-26"),
        ("2026-07-26", "not-a-date"),
        ("2026-07-26", "2026-09-13"),
        ("2026-09-13", "2026-09-14"),
        ("2026-07-26", "2026-07-25"),
    ],
)
def test_invalid_or_unavailable_dates_do_not_enter_periods(end, reported):
    result = analyze_statements(
        {"IS": statement(row(end=end, reported=reported, total_rev=200))}, as_of=AS_OF
    )
    assert result["periods"] == []
    assert result["status"] == "invalid"
    assert all(item["value"] is None for item in result["metrics"])


@pytest.mark.parametrize(
    "field,value", [("currency", "HKD"), ("fp_end", "2026-07-25"), ("rpt_date", "2026-08-25")]
)
def test_cross_statement_currency_and_dates_must_match_exactly(field, value):
    data = statements()
    if field == "currency":
        data["BS"][field] = value
    else:
        data["BS"]["list"][0][field] = value
    result = analyze_statements(data, as_of=AS_OF)
    assert result["status"] == "invalid"
    assert result["periods"][0]["assets"] is None
    assert metrics(result)["quarterly_gross_profit_to_assets_pct"]["value"] is None
    assert metrics(result)["gross_margin_pct"]["value"] == 60


@pytest.mark.parametrize("value", ["", "NaN", "Infinity", "-Infinity", None, True, "garbage"])
def test_missing_and_non_finite_values_are_never_zero(value):
    data = statements()
    data["IS"]["list"][0]["fields"][0]["value"] = value
    result = analyze_statements(data, as_of=AS_OF)
    assert result["periods"][0]["revenue"] is None
    assert metrics(result)["gross_margin_pct"]["value"] is None
    assert metrics(result)["gross_margin_pct"]["reason"]
    json.dumps(result, allow_nan=False)


def test_zero_denominators_and_loss_have_explicit_missing_ratios():
    data = {
        "IS": statement(row(total_rev=0, gp=0, cost_rev=0, ni=-5)),
        "BS": statement(row(total_assets=0, total_liab=0, total_equity=0, total_ca=10, total_cl=0)),
        "CF": statement(row(cash_oper=10, ni_cf=-5)),
    }
    result = analyze_statements(data, as_of=AS_OF)
    for item in result["metrics"]:
        assert item["value"] is None
        assert item["reason"]


def test_failed_reconciliation_suppresses_affected_ratios():
    data = statements()
    data["IS"]["list"][0] = row(total_rev=200, cost_rev=90, gp=120, ni=50)
    data["BS"]["list"][0] = row(
        total_assets=400, total_liab=100, total_equity=250, total_ca=80, total_cl=40
    )
    result = analyze_statements(data, as_of=AS_OF)
    values = metrics(result)
    assert result["status"] == "invalid"
    assert checks(result)["balance_sheet_equation:FY2027Q2"]["status"] == "failed"
    assert checks(result)["gross_profit_equation:FY2027Q2"]["status"] == "failed"
    for key in (
        "gross_margin_pct",
        "net_margin_pct",
        "debt_to_assets_pct",
        "quarterly_gross_profit_to_assets_pct",
    ):
        assert values[key]["value"] is None
        assert values[key]["reason"]


@pytest.mark.parametrize("report,cf_income", [("cumul", 50), ("qf", 100), ("qf", None)])
def test_unclear_or_cumulative_cash_flow_is_not_divided_by_quarterly_income(report, cf_income):
    data = statements()
    data["CF"] = statement(row(cash_oper=75, ni_cf=cf_income), report=report)
    result = analyze_statements(data, as_of=AS_OF)
    item = metrics(result)["operating_cash_flow_to_net_income_ratio"]
    assert item["value"] is None
    assert item["reason"]


def test_net_income_does_not_silently_mix_parent_attributable_with_consolidated_cash_flow():
    data = statements()
    data["IS"]["list"][0] = row(total_rev=200, cost_rev=80, gp=120, ni_company=50)
    result = analyze_statements(data, as_of=AS_OF)
    assert result["periods"][0]["net_income"] is None
    assert metrics(result)["operating_cash_flow_to_net_income_ratio"]["value"] is None


def test_no_currency_or_unsupported_report_basis_cannot_produce_amounts():
    for data in (
        {"IS": statement(row(total_rev=200), currency="")},
        {"IS": statement(row(total_rev=200), report="af")},
    ):
        result = analyze_statements(data, as_of=AS_OF)
        assert result["periods"] == []
        assert all(item["value"] is None for item in result["metrics"])


def test_overflowing_arithmetic_stays_json_safe():
    data = {
        "IS": statement(
            row(total_rev="1e308", gp="1e308", ni=1),
            row(2026, 2, "2025-07-27", "2025-08-27", total_rev="1e-308"),
        )
    }
    result = analyze_statements(data, as_of=AS_OF)
    assert metrics(result)["revenue_yoy_pct"]["value"] is None
    assert metrics(result)["gross_margin_pct"]["value"] == 100
    json.dumps(result, allow_nan=False)


def test_growth_rejects_fiscal_labels_with_impossible_date_spacing():
    data = {
        "IS": statement(
            row(total_rev=200),
            row(2027, 1, "2025-04-26", "2025-05-20", total_rev=100),
            row(2026, 2, "2024-07-27", "2024-08-27", total_rev=100),
        )
    }
    result = analyze_statements(data, as_of=AS_OF)
    assert metrics(result)["revenue_qoq_pct"]["value"] is None
    assert metrics(result)["revenue_yoy_pct"]["value"] is None
    assert "跨度" in metrics(result)["revenue_qoq_pct"]["reason"]


def test_real_provider_rounding_difference_is_explicitly_tolerated_without_changing_values():
    data = {
        "IS": statement(
            row(total_rev=96221000000, gp=72142000000, cost_rev=24079000000, ni=59688000000)
        ),
        "BS": statement(
            row(total_assets=320272000000, total_liab=91288000000, total_equity=228984000000)
        ),
        "CF": statement(row(cash_oper=24077000000, ni_cf=59689000000)),
    }
    result = analyze_statements(data, as_of=AS_OF)
    check = checks(result)["cash_flow_period_basis:FY2027Q2"]
    assert check["status"] == "passed"
    assert "0.1%" in check["message"]
    assert result["periods"][0]["net_income"] == 59688000000
    assert metrics(result)["operating_cash_flow_to_net_income_ratio"]["value"] == pytest.approx(
        24077000000 / 59688000000
    )
