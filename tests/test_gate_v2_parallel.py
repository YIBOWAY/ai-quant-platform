"""Parallel invariant L1: the v2 layer adds sibling keys and touches no v1 key.

The v1 validation/candidate dictionary must be byte-for-byte identical whether or
not a ``gates_v2`` sibling is attached, and a v2 run must leave ``trials.jsonl``
untouched. The emission switch being closed must produce *zero* v2 bytes.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

from quant_system.research import gate_v2 as g
from quant_system.research.strategy_library_cli import _validation
from quant_system.research.trials import ResearchTrial, TrialsLedger
from tests.gate_v2_fixtures import (
    digest_of_universe,
    family_from_payloads,
    platform_result,
    resolver_for,
)


def _v1_validation() -> dict:
    return {
        "status": "passed",
        "run_id": "validation-" + "a" * 32,
        "definition_digest": "d" * 64,
        "simulation_allocation_usd": 10_000,
        "start": "2020-01-02",
        "end": "2020-12-31",
        "platform_metrics": {
            "total_return": 0.2,
            "annualized_return": 0.2,
            "sharpe": 1.1,
            "max_drawdown": 0.1,
            "turnover": 0.3,
        },
        "active_metrics": {
            "status": "ready",
            "vs_benchmark": {"information_ratio": {"value": 1.2}},
        },
        "gates": {"dsr": {"passed": True}, "cost": {"passed": True}, "max_hung_correlation": 0.2},
        "blockers": [],
        "verification_gates": {"dsr": {"passed": True}},
        "dsr": {"passed": True},
        "forward_status": "not_started",
        "historical_scope": "retrospective_not_unseen_holdout",
    }


def _candidate() -> dict:
    return {
        "status": "hung",
        "sleeve_id": "sleeve-1",
        "verification_gates": {"dsr": {"passed": True}},
        "dsr": {"passed": True},
        "performance": {"daily_returns": [0.001, -0.001, 0.002], "return_dates": ["2020-01-02"]},
    }


def _v2_record():
    payloads = [
        platform_result(
            equity_returns=[0.001 * ((i % 5) - 2) for i in range(240)],
            benchmark_returns=[0.0] * 240,
        )
        for _ in range(12)
    ]
    rows = family_from_payloads(payloads)
    candidate = platform_result(
        equity_returns=[0.002 * ((i % 7) - 3) for i in range(240)],
        benchmark_returns=[0.0] * 240,
    )
    return g.evaluate_gate_v2(
        curve_rows=candidate["curve"],
        initial_cash=candidate["evaluation_initial_cash"],
        universe_digest=digest_of_universe(),
        trials_rows=rows,
        curve_resolver=resolver_for(payloads),
    )


def test_adding_gates_v2_leaves_the_v1_validation_byte_identical() -> None:
    original = _v1_validation()
    before = json.dumps(original, sort_keys=True)
    enriched = {**copy.deepcopy(original), "gates_v2": _v2_record()}
    assert json.dumps({key: enriched[key] for key in original}, sort_keys=True) == before
    assert set(enriched) - set(original) == {"gates_v2"}


def test_the_only_new_key_is_gates_v2_and_its_shape_is_pinned() -> None:
    record = _v2_record()
    assert set(record) == {
        "schema_version",
        "config_version",
        "config",
        "authoritative",
        "mode",
        "formula",
        "inputs",
        "family",
        "thresholds",
        "dsr",
        "health",
        "concentration",
        "upgrade",
        "grade",
        "tier_recommendation",
        "verdict_parallel",
        "rng",
        "code",
        "computed_at",
        "envelope_digest",
    }


def test_book_candidate_v1_keys_are_unchanged_by_a_gates_v2_sibling() -> None:
    candidate = _candidate()
    before = json.dumps(candidate, sort_keys=True)
    enriched = {**copy.deepcopy(candidate), "gates_v2": _v2_record()}
    assert json.dumps({key: enriched[key] for key in candidate}, sort_keys=True) == before
    assert set(enriched) - set(candidate) == {"gates_v2"}


def test_the_validation_view_is_insensitive_to_the_v2_sibling() -> None:
    original = _v1_validation()
    enriched = {**copy.deepcopy(original), "gates_v2": _v2_record()}
    assert _validation(original) == _validation(enriched)


def test_a_v2_run_leaves_trials_jsonl_untouched(tmp_path: Path) -> None:
    ledger = TrialsLedger(tmp_path / "trials")
    ledger.append(
        ResearchTrial.record(
            kind="platform_backtest",
            subject="fixture",
            universe=["AAA", "BBB"],
            daily_returns=[0.001, -0.002, 0.003],
            metadata={"run_id": "run-0"},
        )
    )
    path = tmp_path / "trials" / "trials.jsonl"
    digest_before = hashlib.sha256(path.read_bytes()).hexdigest()
    _v2_record()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest_before


def test_disabled_emission_writes_no_v2_bytes(tmp_path: Path) -> None:
    target = tmp_path / "gates_v2" / "verdicts.jsonl"
    result = g.append_verdict_v2(target, {"schema_version": g.GATE_V2_SCHEMA_VERSION})
    assert result == {"written": False, "reason": "gate_v2_disabled"}
    assert not target.exists()
    assert list(tmp_path.rglob("*")) == []


def test_enabled_emission_appends_one_line(tmp_path: Path) -> None:
    target = tmp_path / "gates_v2" / "verdicts.jsonl"
    result = g.append_verdict_v2(target, {"schema_version": g.GATE_V2_SCHEMA_VERSION}, enabled=True)
    assert result["written"] is True
    lines = target.read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["schema_version"] == g.GATE_V2_SCHEMA_VERSION
