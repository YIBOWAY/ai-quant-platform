"""Artificial deterministic examples for the frozen 2026-10-03 family contract."""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from quant_system.research.evaluation_service import _hash
from quant_system.research.gate_v2 import family as f
from quant_system.research.trials import ResearchTrial, TrialsLedger, universe_digest
from tests.gate_v2_fixtures import platform_result


def contract():
    return {
        "schema": "research_family_compatibility/v1",
        "return_definition": "arithmetic_net_active",
        "benchmark": {"symbol": "SPY", "method": "net_buy_and_hold"},
        "frequency": "daily",
        "cost_definition": {
            "model": "proportional_bps",
            "commission_bps": 1.0,
            "slippage_bps": 5.0,
            "cash_interest": 0.0,
        },
        "market_data_contract": {
            "provider": "futu",
            "price_adjustment": "qfq",
            "currency": "USD",
            "bar": "1d",
        },
    }


def example(
    i=0,
    *,
    kind="platform_backtest",
    universe=("AAA", "BBB"),
    start="2020-01-02",
    direction="momentum",
):
    returns = [0.0001 * i + 0.002 * ((j % 5) - 2) for j in range(240)]
    payload = platform_result(equity_returns=returns, benchmark_returns=[0.0001] * 240, start=start)
    payload["family_contract"] = contract()
    row = ResearchTrial.record(
        kind=kind,
        subject="artificial",
        universe=universe,
        daily_returns=returns,
        window_start=payload["curve"][0]["date"],
        window_end=payload["curve"][-1]["date"],
        source="artificial_fixture",
        metadata={
            "run_id": f"trial-{i}-{start}",
            "strategy_definition_digest": f"d-{i}",
            "equity_curve_digest": _hash(payload["curve"]),
            "family_contract_digest": _hash(payload["family_contract"]),
            "research_direction": direction,
        },
    )
    return row, payload


def project(pairs, *, expected=None, scope_tag="strategy_hypothesis"):
    payloads = {row.trial_id: payload for row, payload in pairs}
    return f.project_family_v2(
        trials_rows=[row for row, _ in pairs],
        universe_digest=universe_digest(["AAA", "BBB"]),
        curve_resolver=lambda row: payloads.get(row.trial_id),
        compatibility_contract=expected or contract(),
        scope_tag=scope_tag,
    )


def test_other_universes_cannot_change_family_statistics_coverage_or_digest():
    same = [example(i) for i in range(12)]
    before = project(same)
    others = [
        example(i + 30, universe=["ZZZ"], kind=k)
        for i, k in enumerate(["platform_backtest", "d34_experiment", "qlib_backtest"])
    ]
    after = project(same + [(row, None) for row, _ in others])
    for key in [
        "family_digest",
        "members",
        "excluded",
        "n_trials",
        "recomputed_sharpes",
        "coverage_shortfall",
        "evidence_state",
        "trusted",
    ]:
        assert after[key] == before[key]
    assert {r["reason"] for r in after["out_of_scope"]} == {"universe_mismatch"}


@pytest.mark.parametrize("kind", ["d34_experiment", "qlib_backtest", "experiment", "factor_lab"])
def test_compatible_genuine_other_kinds_are_included(kind):
    row, payload = example(kind=kind)
    value = project([(row, payload)])
    assert value["n_trials"] == 1
    assert value["members"][0]["kind"] == kind
    assert value["members"][0]["trial_digest"] == _hash(row.model_dump(mode="json"))


@pytest.mark.parametrize("kind", ["d34_experiment", "qlib_backtest"])
def test_same_universe_missing_evidence_is_gap_not_discarded(kind):
    row, _ = example(kind=kind)
    value = project([(row, None)])
    assert value["coverage_shortfall"] == 1
    assert value["evidence_state"] == "incomplete_evidence"
    assert value["excluded"][0]["reason"] == "curve_unresolved"
    assert not value["trusted"] and not value["out_of_scope"]


@pytest.mark.parametrize(
    "field",
    ["return_definition", "benchmark", "frequency", "cost_definition", "market_data_contract"],
)
def test_known_incompatible_contract_has_specific_reason(field):
    row, payload = example()
    changed = copy.deepcopy(contract())
    replacements = {
        "return_definition": "net_total",
        "benchmark": {"symbol": "QQQ", "method": "net_buy_and_hold"},
        "frequency": "monthly",
        "cost_definition": {**changed["cost_definition"], "commission_bps": 2},
        "market_data_contract": {**changed["market_data_contract"], "provider": "tiingo"},
    }
    changed[field] = replacements[field]
    payload["family_contract"] = changed
    row = row.model_copy(
        update={"metadata": {**row.metadata, "family_contract_digest": _hash(changed)}}
    )
    result = project([(row, payload)])
    assert result["excluded"] == []
    assert result["out_of_scope"][0]["reason"] == f"incompatible_{field}"


@pytest.mark.parametrize(
    "mutation,reason",
    [
        ("curve", "curve_digest_mismatch"),
        ("contract", "family_contract_digest_mismatch"),
        ("missing_contract", "family_contract_missing"),
        ("wrong_window", "trial_curve_identity_mismatch"),
    ],
)
def test_missing_altered_or_misbound_evidence_is_a_gap(mutation, reason):
    row, payload = example()
    if mutation == "curve":
        payload["curve"][0]["equity"] += 1
    elif mutation == "contract":
        payload["family_contract"]["benchmark"]["symbol"] = "QQQ"
    elif mutation == "missing_contract":
        del payload["family_contract"]
    else:
        row = row.model_copy(update={"window_start": "2019-01-01"})
    result = project([(row, payload)])
    assert result["excluded"][0]["reason"] == reason
    assert result["coverage_shortfall"] == 1
    assert result["out_of_scope"] == []


@pytest.mark.parametrize(
    "count,state",
    [
        (0, "empty"),
        (1, "insufficient_members"),
        (2, "insufficient_members"),
        (3, "small_family"),
        (9, "small_family"),
        (10, "complete"),
    ],
)
def test_explicit_family_states_keep_original_member_floors(count, state):
    result = project([example(i) for i in range(count)])
    assert result["evidence_state"] == state
    assert result["n_trials"] == count
    if count == 0:
        assert not result["trusted"]


def test_direction_label_and_scope_tag_never_reset_the_family():
    pairs = [example(i) for i in range(12)]
    first = project(pairs)
    second = project(pairs, scope_tag="renamed_direction")
    assert second["family_digest"] == first["family_digest"]
    assert second["n_trials"] == first["n_trials"] == 12


def test_same_input_replay_idempotent_and_different_window_retained(tmp_path):
    row, payload = example()
    later, later_payload = example(start="2021-01-04")
    ledger = TrialsLedger(tmp_path)
    ledger.append(row)
    original = ledger.path.read_bytes()
    ledger.append(row.model_copy(update={"ts": "2030-01-01"}))
    assert ledger.path.read_bytes() == original
    ledger.append(later)
    assert len(ledger.list()) == 2
    assert project([(row, payload), (later, later_payload)])["n_trials"] == 2
    with pytest.raises(ValueError, match="trial_run_id_conflict"):
        ledger.append(row.model_copy(update={"total_return": row.total_return + 0.01}))


def test_exact_duplicate_input_rows_do_not_inflate_in_memory_family():
    pair = example()
    assert project([pair, pair])["n_trials"] == 1


def test_same_id_different_row_fails_closed():
    row, payload = example()
    with pytest.raises(ValueError, match="family_trial_identity_conflict"):
        project([(row, payload), (row.model_copy(update={"total_return": 9.0}), payload)])


def test_explicit_archive_evidence_supports_qlib_without_fabricated_definition(tmp_path):
    row, payload = example(kind="qlib_backtest")
    payload.update(
        schema="research_family_curve/v1",
        trial_identity={
            key: getattr(row, key)
            for key in [
                "kind",
                "subject",
                "universe_digest",
                "window_start",
                "window_end",
                "n_periods",
            ]
        },
        run_id=row.metadata["run_id"],
        input_identity={"prices_sha256": "a" * 64},
    )
    path = tmp_path / "qlib/family.json"
    path.parent.mkdir()
    path.write_text(json.dumps(payload))
    metadata = {
        **row.metadata,
        "family_evidence_path": "qlib/family.json",
        "family_evidence_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    }
    metadata.pop("strategy_definition_digest")
    row = row.model_copy(update={"metadata": metadata})
    resolver = f.ArchivedCurveResolver(tmp_path, trusted_trials=[row])
    result = f.project_family_v2(
        trials_rows=[row],
        universe_digest=row.universe_digest,
        curve_resolver=resolver,
        compatibility_contract=contract(),
    )
    assert result["n_trials"] == 1
    assert (
        result["members"][0]["evidence"]["files"][str(path)] == metadata["family_evidence_sha256"]
    )
    path.write_text(path.read_text() + " ")
    rejected = f.project_family_v2(
        trials_rows=[row],
        universe_digest=row.universe_digest,
        curve_resolver=resolver,
        compatibility_contract=contract(),
    )
    assert rejected["n_trials"] == 0 and rejected["coverage_shortfall"] == 1


def test_contract_is_derived_from_frozen_result_and_definition_not_current_constants():
    row, payload = example()
    del payload["family_contract"]
    payload.update(
        profile={"benchmark_symbol": "SPY"},
        frequency="daily",
        source="futu",
        price_adjustment="qfq",
        definition={"benchmark_symbol": "SPY", "commission_bps": 1, "slippage_bps": 5},
    )
    assert f.compatibility_contract_from_result(payload) == contract()
    payload["definition"]["commission_bps"] = 2
    assert f.compatibility_contract_from_result(payload)["cost_definition"]["commission_bps"] == 2
    del payload["definition"]["commission_bps"]
    with pytest.raises(ValueError, match="family_cost_contract_missing"):
        f.compatibility_contract_from_result(payload)


@pytest.mark.parametrize(
    "change", ["duplicate_date", "out_of_order", "negative_equity", "bad_date"]
)
def test_rebound_malformed_calendar_or_nav_does_not_become_a_member(change):
    row, payload = example()
    if change == "duplicate_date":
        payload["curve"][1]["date"] = payload["curve"][0]["date"]
    elif change == "out_of_order":
        payload["curve"][1], payload["curve"][2] = payload["curve"][2], payload["curve"][1]
    elif change == "negative_equity":
        payload["curve"][-1]["equity"] = -1
        row = row.model_copy(update={"total_return": -1.00001})
    else:
        payload["curve"][1]["date"] = "01/03/2020"
    row = row.model_copy(
        update={"metadata": {**row.metadata, "equity_curve_digest": _hash(payload["curve"])}}
    )
    result = project([(row, payload)])
    assert result["n_trials"] == 0
    assert result["excluded"][0]["reason"] == "family_curve_invalid"


def test_terminal_total_loss_is_retained_as_evidence_not_cleaned_away():
    row, payload = example()
    payload["curve"][-1]["equity"] = 0
    row = row.model_copy(
        update={
            "total_return": -1,
            "metadata": {**row.metadata, "equity_curve_digest": _hash(payload["curve"])},
        }
    )
    result = project([(row, payload)])
    assert result["n_trials"] == 1


def test_no_contract_path_preserves_historical_rule_and_digest():
    row, payload = example()
    foreign, _ = example(1, universe=["ZZZ"])
    kwargs = dict(
        trials_rows=[row, foreign],
        universe_digest=row.universe_digest,
        curve_resolver=lambda ignored: payload,
    )
    old = f._project_family_legacy(**kwargs)
    result = f.project_family_v2(**kwargs)
    assert result == old
    assert "rule_version" not in result
    assert result["family_digest"] == _hash(f.family_digest_payload(result))


def test_net_total_family_uses_actual_equity_without_fabricating_benchmark():
    row, payload = example(kind="d34_experiment")
    total_contract = contract()
    total_contract.update(
        return_definition="net_total_return", benchmark={"symbol": None, "method": "none"}
    )
    payload["family_contract"] = total_contract
    for mark in payload["curve"]:
        del mark["benchmark"]
        del mark["peer"]
    row = row.model_copy(
        update={
            "metadata": {
                **row.metadata,
                "equity_curve_digest": _hash(payload["curve"]),
                "family_contract_digest": _hash(total_contract),
            }
        }
    )
    result = project([(row, payload)], expected=total_contract)
    assert result["n_trials"] == 1
    assert result["members"][0]["recomputed_sharpe"] == pytest.approx(row.sharpe, abs=1e-12)
    assert result["members"][0]["return_definition"] == "net_total_return"
    active_family = project([(row, payload)])
    assert active_family["n_trials"] == 0 and active_family["excluded"] == []
    assert active_family["out_of_scope"][0]["reason"] == "incompatible_return_definition"


def test_owner_derived_curve_binding_can_support_legacy_d34_without_rewriting_row(tmp_path):
    row, payload = example(kind="d34_experiment")
    row = row.model_copy(update={"metadata": {"run_id": row.metadata["run_id"]}})
    original = row.model_dump(mode="json")
    source = tmp_path / "original-trial.json"
    source.write_text(json.dumps(original))
    payload["family_evidence"] = {
        "adapter": "owner_original_trial/v1",
        "trial_digest": _hash(original),
        "curve_digest": _hash(payload["curve"]),
        "files": {str(source): hashlib.sha256(source.read_bytes()).hexdigest()},
    }
    assert project([(row, payload)])["n_trials"] == 1
    assert row.model_dump(mode="json") == original
    payload["family_evidence"]["trial_digest"] = "0" * 64
    assert project([(row, payload)])["n_trials"] == 0


def test_identical_curves_from_distinct_definitions_resolve_without_overwriting(tmp_path):
    from quant_system.research.strategy_definition import StrategyDefinition, StrategyFactor

    pairs = []
    for i in range(2):
        row, payload = example(i=0)
        recipe = StrategyDefinition(
            kind="factor_blend",
            title="Artificial strategy",
            symbols=["AAA", "BBB"],
            history_start="2019-01-01",
            top_n=i + 1,
            factors=[
                StrategyFactor(
                    factor_id="momentum", lookback=5, direction="higher_is_better", weight=1
                )
            ],
        )
        payload.pop("family_contract")
        payload.update(
            definition=recipe.model_dump(mode="json"),
            definition_digest=recipe.content_digest,
            profile={"benchmark_symbol": "SPY"},
            frequency="daily",
            source="futu",
            price_adjustment="qfq",
        )
        row = row.model_copy(
            update={
                "trial_id": f"bound-{i}",
                "metadata": {
                    "run_id": f"run-{i}",
                    "strategy_definition_digest": recipe.content_digest,
                    "equity_curve_digest": _hash(payload["curve"]),
                },
            }
        )
        directory = tmp_path / f"strategy_library/strategy-{i}/validations/validation-original"
        directory.mkdir(parents=True)
        (directory / "platform-result.json").write_text(json.dumps(payload))
        (directory / "validation.json").write_text(
            json.dumps({"definition_digest": recipe.content_digest})
        )
        pairs.append((row, payload))
    resolver = f.ArchivedCurveResolver(tmp_path, trusted_trials=[r for r, _ in pairs])
    result = f.project_family_v2(
        trials_rows=[r for r, _ in pairs],
        universe_digest=pairs[0][0].universe_digest,
        curve_resolver=resolver,
        compatibility_contract=contract(),
    )
    assert result["n_trials"] == 2 and not result["excluded"]
    for row, payload in pairs:
        assert resolver(row)["definition_digest"] == payload["definition_digest"]


@pytest.mark.parametrize(
    "change,reason",
    [
        ("cash", "family_initial_cash_missing"),
        ("kind", "trial_kind_invalid"),
    ],
)
def test_missing_cash_and_unknown_kind_cannot_claim_compatible_proof(change, reason):
    row, payload = example()
    if change == "cash":
        payload.pop("evaluation_initial_cash")
    else:
        row = row.model_copy(update={"kind": "not_a_research_trial"})
    result = project([(row, payload)])
    assert result["excluded"][0]["reason"] == reason
