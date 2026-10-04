"""Artificial old-format originals; no market, current qualification or ledger writes."""

import copy
import hashlib
import json
import math

import pandas as pd
import pytest

from quant_system.research.evaluation_service import _hash
from quant_system.research.gate_v2.family import ArchivedCurveResolver
from quant_system.research.strategy_definition import _digest
from quant_system.research.trials import ResearchTrial

FEE = "无杠杆、无做空；单边佣金1bp、滑点5bp，现金利息为0，未模拟税收和额外冲击。"
DATA = "Futu 1d QFQ不保证含分红再投资的总回报；无外汇转换，所有标的采用美元报价。"


def originals(
    tmp_path, kind="study", *, content_id=True, history_start=False, study_initial_cash=100000.0
):
    initial = study_initial_cash if kind == "study" else 10000.0
    dates = pd.bdate_range("2023-01-03", periods=65)
    prices = pd.DataFrame(
        [
            {
                "symbol": symbol,
                "timestamp": date.tz_localize("UTC"),
                "open": 100 + i + offset,
                "close": 101 + i + offset,
                "provider": "futu",
                "price_adjustment": "qfq",
                "interval": "1d",
            }
            for symbol, offset in (("AAA", 0), ("SPY", 10))
            for i, date in enumerate(dates)
        ]
    )
    profile = {
        "id": "old-artificial",
        "symbols": ["AAA"],
        "benchmark_symbol": "SPY",
        "limitations": [FEE, DATA],
    }
    raw = {
        "schema_version": 1,
        "kind": "factor_blend",
        "title": "old artificial",
        "symbols": ["AAA"],
        "benchmark_symbol": "SPY",
        "provider": "futu",
        "price_adjustment": "qfq",
        "interval": "1d",
        "calendar": "NYSE",
        "execution_price": "next_open",
        "cash_rule": "unallocated_cash_zero_interest",
        "commission_bps": 1.0,
        "slippage_bps": 5.0,
        "source_fingerprints": {"old/source.py": "a" * 64},
        "profile_snapshot": None,
    }
    if history_start:
        raw["history_start"] = "2022-01-01"
    raw["content_digest"] = _digest({k: v for k, v in raw.items() if k != "title"})
    cash, held, trades, curve = initial, 0.0, [], []
    benchmark_qty = initial / (110 * 1.0005 * 1.0001)
    benchmark_commission = benchmark_qty * 110 * 1.0005 * 0.0001
    for i, date in enumerate(dates):
        qty = 10.0 if i == 0 else 5.0 if i in {20, 40} else 0.0
        if qty:
            side = "buy" if i == 0 else "sell"
            sign = 1 if side == "buy" else -1
            requested = 100 + i
            price = requested * (1 + sign * 0.0005)
            fee = qty * price * 0.0001
            trades.append(
                {
                    "date": date.strftime("%Y-%m-%d"),
                    "symbol": "AAA",
                    "side": side,
                    "quantity": qty,
                    "requested_price": requested,
                    "fill_price": price,
                    "commission": fee,
                }
            )
            cash -= sign * qty * price + fee
            held += sign * qty
        curve.append(
            {
                "date": date.strftime("%Y-%m-%d"),
                "equity": cash + held * (101 + i),
                "benchmark": benchmark_qty * (111 + i),
            }
        )
    payload = {
        "profile": profile,
        "source": "futu",
        "price_adjustment": "qfq",
        "frequency": "daily",
        "curve": curve,
        "trades": trades,
        "start": curve[0]["date"],
        "end": curve[-1]["date"],
        "costs": {
            "commission_bps": 1.0,
            "slippage_bps": 5.0,
            "cash_interest_rate": 0.0,
            "commission": sum(t["commission"] for t in trades),
            "slippage": sum(
                t["quantity"] * abs(t["fill_price"] - t["requested_price"]) for t in trades
            ),
        },
        "benchmark_costs": {
            "commission_bps": 1.0,
            "slippage_bps": 5.0,
            "cash_interest_rate": 0.0,
            "commission": benchmark_commission,
            "slippage": benchmark_qty * 110 * 0.0005,
        },
    }
    if kind == "study":
        run = tmp_path / "strategy_studies/runs/study-artificial"
    else:
        run = tmp_path / "strategy_library/strategy-old/validations/validation-old"
        payload.update(
            definition=raw, definition_digest=raw["content_digest"], evaluation_initial_cash=initial
        )
    run.mkdir(parents=True)
    prices.to_parquet(run / "prices.parquet", index=False)
    prices_sha = hashlib.sha256((run / "prices.parquet").read_bytes()).hexdigest()
    if kind == "study":
        run_id = "recorded-study-" + _hash(
            {"profile": profile, "prices": prices_sha, "curve": curve}
        )
        (run / "report.json").write_text(
            json.dumps({"source": {"prices_sha256": prices_sha}, "results": [payload]})
        )
    else:
        (run / "platform-result.json").write_text(json.dumps(payload))
        result_sha = hashlib.sha256((run / "platform-result.json").read_bytes()).hexdigest()
        run_id = "definition-validation-" + _hash(
            {
                "definition": raw["content_digest"],
                "prices": prices_sha,
                "start": payload["start"],
                "end": payload["end"],
                "cash": 10000,
            }
        )
        if not content_id:
            run_id = "validation-old"
        (run / "validation.json").write_text(
            json.dumps({"run_id": "validation-old", "definition_digest": raw["content_digest"]})
        )
        (run / "qlib-replay.json").write_text(
            json.dumps(
                {
                    "status": "available",
                    "definition_digest": raw["content_digest"],
                    "source": {"platform_result_sha256": result_sha, "prices_sha256": prices_sha},
                }
            )
        )
    previous = initial
    values = []
    for row in curve:
        values.append(row["equity"] / previous - 1)
        previous = row["equity"]
    trial = ResearchTrial.record(
        kind="platform_backtest",
        subject=profile["id"],
        universe=["AAA"],
        daily_returns=values,
        window_start=payload["start"],
        window_end=payload["end"],
        source="futu",
        metadata={
            "run_id": run_id,
            "strategy_definition_digest": raw["content_digest"] if kind != "study" else None,
        },
    ).model_dump(mode="json")
    return trial, payload, run


def recover(tmp_path, row):
    from quant_system.research.legacy_family_evidence import recover_legacy_family_contract

    resolver = ArchivedCurveResolver(tmp_path, trusted_trials=[row])
    payload = resolver.legacy(row)
    return None if payload is None else recover_legacy_family_contract(tmp_path, row, payload)


@pytest.mark.parametrize(
    "kind,content_id,history_start",
    [
        ("study", True, False),
        ("definition", True, False),
        ("definition", False, False),
        ("definition", True, True),
    ],
)
def test_original_contract_can_be_recovered_without_current_definition_defaults(
    tmp_path, kind, content_id, history_start
):
    row, _, _ = originals(tmp_path, kind, content_id=content_id, history_start=history_start)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    result = recover(tmp_path, row)
    assert "family_contract" in result, result.get("legacy_contract_reason")
    assert result["family_contract"]["cost_definition"] == {
        "model": "proportional_bps",
        "commission_bps": 1.0,
        "slippage_bps": 5.0,
        "cash_interest": 0.0,
    }
    assert result["family_evidence"]["trial_digest"] == _hash(row)
    assert result["family_evidence"]["reconstruction"]["max_nav_error_usd"] <= 1e-7
    assert result["evaluation_initial_cash"] == pytest.approx(100000 if kind == "study" else 10000)
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}


@pytest.mark.parametrize(
    "fault",
    [
        "cost_claim",
        "fill_fee",
        "fill_price",
        "nav_path",
        "missing_contract",
        "benchmark",
        "missing_prices",
    ],
)
def test_study_fields_cannot_be_resealed_to_escape_original_accounting(tmp_path, fault):
    row, payload, run = originals(tmp_path)
    if fault == "cost_claim":
        payload["costs"]["commission_bps"] = 0
    elif fault == "fill_fee":
        payload["trades"][0]["commission"] = 0
    elif fault == "fill_price":
        payload["trades"][0]["fill_price"] += 0.1
    elif fault == "nav_path":
        payload["trades"][0]["quantity"] += 1
    elif fault == "missing_contract":
        payload["profile"]["limitations"] = []
    elif fault == "benchmark":
        payload["profile"]["benchmark_symbol"] = "AAA"
    else:
        (run / "prices.parquet").unlink()
    document = json.loads((run / "report.json").read_text())
    document["results"][0] = payload
    (run / "report.json").write_text(json.dumps(document))
    result = recover(tmp_path, row)
    assert result is None or "family_contract" not in result


@pytest.mark.parametrize("content_id", [True, False])
def test_definition_cost_reseal_cannot_escape_ledger_bound_original_digest(tmp_path, content_id):
    row, payload, run = originals(tmp_path, "definition", content_id=content_id)
    raw = copy.deepcopy(payload["definition"])
    raw["commission_bps"] = 0
    raw["content_digest"] = _digest(
        {k: v for k, v in raw.items() if k not in {"title", "content_digest"}}
    )
    payload.update(definition=raw, definition_digest=raw["content_digest"])
    (run / "platform-result.json").write_text(json.dumps(payload))
    for name in ("validation.json", "qlib-replay.json"):
        doc = json.loads((run / name).read_text())
        doc["definition_digest"] = raw["content_digest"]
        if name == "qlib-replay.json":
            doc["source"]["platform_result_sha256"] = hashlib.sha256(
                (run / "platform-result.json").read_bytes()
            ).hexdigest()
        (run / name).write_text(json.dumps(doc))
    result = recover(tmp_path, row)
    assert result is None or "family_contract" not in result


def test_same_benchmark_symbol_does_not_prove_a_net_benchmark(tmp_path):
    row, payload, run = originals(tmp_path, "definition")
    for i, mark in enumerate(payload["curve"]):
        mark["benchmark"] = 10000 * (111 + i) / 111  # gross, first-close normalization
    (run / "platform-result.json").write_text(json.dumps(payload))
    qlib = json.loads((run / "qlib-replay.json").read_text())
    qlib["source"]["platform_result_sha256"] = hashlib.sha256(
        (run / "platform-result.json").read_bytes()
    ).hexdigest()
    (run / "qlib-replay.json").write_text(json.dumps(qlib))
    result = recover(tmp_path, row)
    assert result["legacy_contract_reason"] == "legacy_family_benchmark_not_proven_net_buy_and_hold"
    assert "family_contract" not in result


@pytest.mark.parametrize("kind", ["study", "definition"])
def test_recovered_original_is_consumable_by_actual_strict_family_projection(tmp_path, kind):
    from quant_system.research.gate_v2.family import project_family_v2
    from quant_system.research.legacy_family_evidence import recover_legacy_family_contract

    row, _, _ = originals(tmp_path, kind)
    archived = ArchivedCurveResolver(tmp_path, trusted_trials=[row])

    def recovered(trial):
        return recover_legacy_family_contract(tmp_path, trial, archived.legacy(trial))

    payload = recovered(row)
    family = project_family_v2(
        trials_rows=[row],
        universe_digest=row["universe_digest"],
        compatibility_contract=payload["family_contract"],
        curve_resolver=archived,
        legacy_resolver=recovered,
    )
    assert family["n_trials"] == 1 and family["excluded"] == []
    assert family["evidence_state"] == "insufficient_members"
    assert family["members"][0]["trial_id"] == row["trial_id"]


@pytest.mark.parametrize("symbol", ["AAA", "SPY"])
@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_later_used_close_must_be_finite_even_with_valid_original_hashes(tmp_path, symbol, bad):
    row, payload, run = originals(tmp_path)
    prices = pd.read_parquet(run / "prices.parquet")
    day = pd.Timestamp(payload["curve"][1]["date"], tz="UTC")
    prices.loc[(prices.symbol == symbol) & (prices.timestamp == day), "close"] = bad
    prices.to_parquet(run / "prices.parquet", index=False)
    price_sha = hashlib.sha256((run / "prices.parquet").read_bytes()).hexdigest()
    row["metadata"]["run_id"] = "recorded-study-" + _hash(
        {"profile": payload["profile"], "prices": price_sha, "curve": payload["curve"]}
    )
    (run / "report.json").write_text(
        json.dumps({"source": {"prices_sha256": price_sha}, "results": [payload]})
    )
    result = recover(tmp_path, row)
    assert result is not None, "the artificial SHA/run identity must reach actual accounting"
    assert result.get("legacy_contract_reason") == "legacy_family_used_price_invalid"
    assert "family_contract" not in result


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_accounting_rejects_nonfinite_later_raw_benchmark_mark(tmp_path, bad):
    from quant_system.research.legacy_family_evidence import _accounting

    _, payload, run = originals(tmp_path)
    payload["curve"][1]["benchmark"] = bad
    with pytest.raises(ValueError, match="benchmark_mark_invalid"):
        _accounting(payload, pd.read_parquet(run / "prices.parquet"), 100000.0, 1.0, 5.0)


def test_nan_quote_for_unheld_asset_after_liquidation_is_not_invented_exposure(tmp_path):
    row, payload, run = originals(tmp_path)
    prices = pd.read_parquet(run / "prices.parquet")
    day = pd.Timestamp(payload["curve"][-1]["date"], tz="UTC")
    prices.loc[(prices.symbol == "AAA") & (prices.timestamp == day), "close"] = float("nan")
    prices.to_parquet(run / "prices.parquet", index=False)
    price_sha = hashlib.sha256((run / "prices.parquet").read_bytes()).hexdigest()
    row["metadata"]["run_id"] = "recorded-study-" + _hash(
        {"profile": payload["profile"], "prices": price_sha, "curve": payload["curve"]}
    )
    (run / "report.json").write_text(
        json.dumps({"source": {"prices_sha256": price_sha}, "results": [payload]})
    )
    result = recover(tmp_path, row)
    assert "family_contract" in result, result.get("legacy_contract_reason")


@pytest.mark.parametrize("direction", [-1, 1])
def test_recovered_cash_basis_survives_actual_family_and_verdict_verification(tmp_path, direction):
    from quant_system.research.capital_evidence import CurrentFamilyResolver
    from quant_system.research.gate_v2.family import verify_legacy_member
    from quant_system.research.gate_v2.verdict import evaluate_gate_v2, verify_verdict_v2

    # Explicit artificial +/- 8 ULP starting capital. Old archives omit the
    # field; the exact ledger/terminal-NAV reconstruction must drive both paths.
    initial = 100000.0 + direction * 8 * math.ulp(100000.0)
    row, _, run = originals(tmp_path, study_initial_cash=initial)
    before = {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    resolver = CurrentFamilyResolver(tmp_path, trusted_trials=[row])
    archived = resolver.archived.legacy(row)
    payload = resolver.legacy(row)
    assert "evaluation_initial_cash" not in archived
    assert archived["legacy_evidence"]["initial_cash"] == 100000.0
    assert direction * (payload["evaluation_initial_cash"] - 100000.0) > 0
    assert "family_contract" in payload, payload.get("legacy_contract_reason")
    gate = evaluate_gate_v2(
        curve_rows=payload["curve"],
        initial_cash=payload["evaluation_initial_cash"],
        universe_digest=row["universe_digest"],
        benchmark_symbol="SPY",
        trials_rows=[row],
        curve_resolver=resolver,
        legacy_resolver=resolver.legacy,
        compatibility_contract=payload["family_contract"],
    )
    assert gate["family"]["n_trials"] == 1 and gate["family"]["excluded"] == []
    assert verify_verdict_v2(
        gate, trusted_trials=[row], curve_resolver=resolver, legacy_resolver=resolver.legacy
    )
    member = gate["family"]["members"][0]
    assert verify_legacy_member(member, resolver.legacy)
    assert member["legacy_evidence"]["initial_cash"] == payload["evaluation_initial_cash"]
    assert member["legacy_evidence"]["archived_reader_initial_cash"] == 100000.0
    assert member["legacy_evidence"]["original_trial"] == row
    assert member["legacy_evidence"]["files"] == archived["legacy_evidence"]["files"]
    assert gate["tier_recommendation"]["tier"] == "T0"  # Integrity is not qualification.
    assert before == {str(p): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}

    # The derived basis is authenticated by fresh original resolution, not a
    # tolerance on the saved statistic or permission to rewrite old defaults.
    changed = copy.deepcopy(member)
    changed["legacy_evidence"]["initial_cash"] = 100000.0
    assert not verify_legacy_member(changed, resolver.legacy)
    (run / "report.json").write_bytes((run / "report.json").read_bytes() + b" ")
    assert not verify_verdict_v2(
        gate, trusted_trials=[row], curve_resolver=resolver, legacy_resolver=resolver.legacy
    )
