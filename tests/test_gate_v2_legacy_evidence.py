from __future__ import annotations

import copy
import json

import pandas as pd
import pytest

from quant_system.research.evaluation_service import _hash
from quant_system.research.gate_v2.family import (
    ArchivedCurveResolver,
    project_family_v2,
    verify_legacy_member,
)
from quant_system.research.gate_v2.verdict import (
    envelope_digest,
    evaluate_gate_v2,
    verify_verdict_integrity_v2,
    verify_verdict_v2,
)
from quant_system.research.trials import ResearchTrial


def archived_study(tmp_path):
    run = tmp_path / "strategy_studies" / "runs" / "study-original"
    run.mkdir(parents=True)
    prices = run / "prices.parquet"
    prices.write_bytes(b"sealed fixture prices")
    import hashlib

    prices_digest = hashlib.sha256(prices.read_bytes()).hexdigest()
    dates = pd.bdate_range("2023-01-02", periods=260)
    curve = [
        {
            "date": day.strftime("%Y-%m-%d"),
            "equity": 100000 * (1.001 + (i % 3) * 0.0001) ** i,
            "benchmark": 100000 * 1.0004**i,
        }
        for i, day in enumerate(dates)
    ]
    payload = {
        "profile": {"id": "fixture", "symbols": ["AAPL", "MSFT"]},
        "source": "futu",
        "price_adjustment": "qfq",
        "curve": curve,
        "start": curve[0]["date"],
        "end": curve[-1]["date"],
    }
    run_id = "recorded-study-" + _hash(
        {"profile": payload["profile"], "prices": prices_digest, "curve": curve}
    )
    values = pd.Series([row["equity"] for row in curve])
    returns = values.div(values.shift(1).fillna(100000)).sub(1).tolist()
    trial = ResearchTrial.record(
        kind="platform_backtest",
        subject="fixture",
        universe=["AAPL", "MSFT"],
        daily_returns=returns,
        window_start=curve[0]["date"],
        window_end=curve[-1]["date"],
        source="futu",
        metadata={
            "run_id": run_id,
            "strategy_definition_digest": None,
            "membership_mode": "static_snapshot",
        },
    )
    report = {"source": {"prices_sha256": prices_digest}, "results": [payload]}
    (run / "report.json").write_text(json.dumps(report))
    return trial.model_dump(mode="json"), payload, run


def test_exact_legacy_study_enters_family_without_minting_definition(tmp_path):
    row, payload, _ = archived_study(tmp_path)
    original = copy.deepcopy(row)
    resolver = ArchivedCurveResolver(tmp_path, trusted_trials=[row])
    family = project_family_v2(
        trials_rows=[row],
        universe_digest=row["universe_digest"],
        curve_resolver=resolver,
        legacy_resolver=resolver.legacy,
    )
    assert family["n_trials"] == 1 and family["trusted"]
    assert family["members"][0]["legacy_evidence"]["type"] == "recorded_study"
    assert row == original and row["metadata"]["strategy_definition_digest"] is None
    verdict = evaluate_gate_v2(
        curve_rows=payload["curve"],
        initial_cash=100000,
        universe_digest=row["universe_digest"],
        trials_rows=[row],
        curve_resolver=resolver,
        legacy_resolver=resolver.legacy,
    )
    assert verify_verdict_v2(
        verdict, trusted_trials=[row], curve_resolver=resolver, legacy_resolver=resolver.legacy
    )
    assert not verify_verdict_v2(verdict)


def test_archived_curve_mutation_or_missing_proof_cannot_be_verified(tmp_path):
    row, payload, run = archived_study(tmp_path)
    resolver = ArchivedCurveResolver(tmp_path, trusted_trials=[row])
    verdict = evaluate_gate_v2(
        curve_rows=payload["curve"],
        initial_cash=100000,
        universe_digest=row["universe_digest"],
        trials_rows=[row],
        curve_resolver=resolver,
        legacy_resolver=resolver.legacy,
    )
    report = json.loads((run / "report.json").read_text())
    report["results"][0]["curve"][-1]["equity"] += 1
    (run / "report.json").write_text(json.dumps(report))
    assert not verify_verdict_v2(
        verdict, trusted_trials=[row], curve_resolver=resolver, legacy_resolver=resolver.legacy
    )
    untouched = project_family_v2(
        trials_rows=[row], universe_digest=row["universe_digest"], curve_resolver=resolver
    )
    assert untouched["n_trials"] == 0


@pytest.mark.parametrize("field", ["trial_id", "run_id"])
def test_disclosed_b28_invented_member_identity_is_rejected(tmp_path, field):
    row, payload, _ = archived_study(tmp_path)
    resolver = ArchivedCurveResolver(tmp_path, trusted_trials=[row])
    family = project_family_v2(
        trials_rows=[row],
        universe_digest=row["universe_digest"],
        curve_resolver=resolver,
        legacy_resolver=resolver.legacy,
    )
    member = copy.deepcopy(family["members"][0])
    member[field] = "invented"
    assert not verify_legacy_member(member, resolver.legacy)


def test_disclosed_b28_proof_stripping_cannot_downgrade_auth_verification(tmp_path):
    row, payload, _ = archived_study(tmp_path)
    resolver = ArchivedCurveResolver(tmp_path, trusted_trials=[row])
    record = evaluate_gate_v2(
        curve_rows=payload["curve"],
        initial_cash=100000,
        universe_digest=row["universe_digest"],
        trials_rows=[row],
        curve_resolver=resolver,
        legacy_resolver=resolver.legacy,
    )
    for member in record["family"]["members"]:
        member.pop("legacy_evidence", None)
    family = record["family"]
    family["family_digest"] = _hash(
        {key: family[key] for key in ("members", "excluded", "coverage_shortfall", "family_key")}
    )
    record["dsr"]["family_digest"] = family["family_digest"]
    record["envelope_digest"] = envelope_digest(record)
    # Preserve the disclosed distinction: a self-consistent forgery can pass
    # mathematics, but cannot pass the caller-owned evidence check.
    assert verify_verdict_integrity_v2(record)
    assert not verify_verdict_v2(record)
    assert not verify_verdict_v2(
        record, trusted_trials=[row], curve_resolver=resolver, legacy_resolver=resolver.legacy
    )
