"""Family projection: explicit membership, exclusions with reasons, two families.

The regression pin here is the *initial cash trap*: a serialized curve is funded
from ``evaluation_initial_cash`` (commonly 100_000), never the 10_000 validation
allocation. A wrong constant shows up as a ~10x first return.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from quant_system.research import gate_v2 as g
from quant_system.research.evaluation_service import _hash
from quant_system.research.trials import TrialsLedger, universe_digest
from tests.gate_v2_fixtures import (
    DEFAULT_UNIVERSE,
    digest_of_universe,
    family_from_payloads,
    platform_result,
    resolver_for,
    trial_row,
)


def _payload(seed: int = 0, periods: int = 240) -> dict:
    returns = [0.001 * (((index + seed) % 7) - 3) for index in range(periods)]
    return platform_result(equity_returns=returns, benchmark_returns=[0.0] * periods)


def _project(rows, resolver):
    return g.project_family_v2(
        trials_rows=rows,
        universe_digest=digest_of_universe(),
        curve_resolver=resolver,
    )


def test_verified_platform_backtests_become_members() -> None:
    payloads = [_payload(index) for index in range(3)]
    rows = family_from_payloads(payloads)
    family = _project(rows, resolver_for(payloads))
    assert family["n_trials"] == 3
    assert all(member["curve_digest_verified"] for member in family["members"])
    assert family["coverage_shortfall"] == 0.0
    assert family["trusted"] is True


def test_non_platform_kinds_are_out_of_scope_not_family_members() -> None:
    payloads = [_payload(0)]
    rows = [
        trial_row(
            trial_id="p",
            kind="platform_backtest",
            metadata={
                "strategy_definition_digest": "d",
                "equity_curve_digest": _hash(payloads[0]["curve"]),
            },
        ),
        trial_row(trial_id="q", kind="qlib_backtest", n_periods=240),
        trial_row(trial_id="f", kind="factor_lab", n_periods=240),
    ]
    family = _project(rows, resolver_for(payloads))
    assert family["n_trials"] == 1
    assert {item["reason"] for item in family["out_of_scope"]} == {"kind_excluded"}
    assert family["excluded"] == []


def test_each_membership_failure_lands_in_excluded_with_a_reason() -> None:
    payload = _payload(1)
    good = trial_row(
        trial_id="ok",
        metadata={
            "strategy_definition_digest": "d",
            "equity_curve_digest": _hash(payload["curve"]),
        },
        n_periods=240,
    )
    no_digest = trial_row(trial_id="no-digest", n_periods=240)
    wrong_universe = trial_row(
        trial_id="other-universe",
        universe=["ZZZ"],
        n_periods=240,
        metadata={"strategy_definition_digest": "d"},
    )
    short = trial_row(trial_id="short", n_periods=10, metadata={"strategy_definition_digest": "d"})
    unresolved = trial_row(
        trial_id="unresolved", n_periods=240, metadata={"strategy_definition_digest": "d"}
    )
    family = _project([good, no_digest, wrong_universe, short, unresolved], resolver_for([payload]))
    reasons = {item["run_id"]: item["reason"] for item in family["excluded"]}
    assert reasons == {
        "no-digest": "definition_digest_missing",
        "other-universe": "universe_mismatch",
        "short": "short_window",
        "unresolved": "curve_unresolved",
    }
    assert family["n_trials"] == 1
    assert family["coverage_shortfall"] > 0.0
    assert family["trusted"] is False


def test_a_curve_whose_digest_does_not_match_is_excluded() -> None:
    payload = _payload(2)
    digest = _hash(payload["curve"])
    tampered = {
        "curve": [
            {**payload["curve"][0], "equity": payload["curve"][0]["equity"] + 1.0},
            *payload["curve"][1:],
        ],
        "evaluation_initial_cash": payload["evaluation_initial_cash"],
    }
    row = trial_row(
        trial_id="tampered",
        n_periods=240,
        metadata={"strategy_definition_digest": "d", "equity_curve_digest": digest},
    )
    family = g.project_family_v2(
        trials_rows=[row],
        universe_digest=digest_of_universe(),
        curve_resolver=lambda ignored: tampered,
    )
    assert family["n_trials"] == 0
    assert family["excluded"][0]["reason"] == "curve_digest_mismatch"


def test_shortfall_budget_flips_trusted() -> None:
    payloads = [_payload(index) for index in range(3)]
    rows = family_from_payloads(payloads)
    rows.append(trial_row(trial_id="bad", n_periods=240))
    family = _project(rows, resolver_for(payloads))
    assert family["n_trials"] == 3
    assert family["coverage_shortfall"] == 0.25
    assert family["trusted"] is True  # at the budget, not over it
    rows.append(trial_row(trial_id="bad2", n_periods=240))
    family2 = _project(rows, resolver_for(payloads))
    assert family2["coverage_shortfall"] > 0.25
    assert family2["trusted"] is False


def test_first_return_uses_the_evaluation_initial_cash_not_the_validation_allocation() -> None:
    periods = 60
    equity_returns = [0.05] + [0.0] * (periods - 1)
    benchmark_returns = [0.02] + [0.0] * (periods - 1)
    payload = platform_result(
        equity_returns=equity_returns, benchmark_returns=benchmark_returns, initial_cash=100_000.0
    )
    active = g.recompute_active_returns(
        payload["curve"], initial_cash=payload["evaluation_initial_cash"]
    )
    assert abs(active["equity_returns"][0] - 0.05) < 1e-12  # funded from 100_000, not 10_000
    assert abs(active["active_returns"][0] - 0.03) < 1e-12
    wrong = g.recompute_active_returns(payload["curve"], initial_cash=10_000.0)
    assert abs(wrong["equity_returns"][0] - 0.05) > 1.0  # a 10x first return is the tell


def test_two_families_map_different_membership_sets() -> None:
    payloads = [_payload(index) for index in range(3)]
    rows = family_from_payloads(payloads)
    rows.append(
        trial_row(
            trial_id="qlib",
            kind="qlib_backtest",
            daily_returns=[0.001 * ((index % 7) - 3) for index in range(240)],
        )
    )
    with tempfile.TemporaryDirectory() as directory:
        ledger = TrialsLedger(Path(directory) / "trials")
        ledger.append_many(rows)
        v1_family = ledger.trial_sharpes(universe=universe_digest(list(DEFAULT_UNIVERSE)))
    family = _project(rows, resolver_for(payloads))
    assert len(v1_family) > family["n_trials"]  # v1 counts the qlib row
    assert family["n_trials"] == 3


def test_family_key_separates_scope() -> None:
    assert (
        g.project_family_v2(
            trials_rows=[], universe_digest="abc", curve_resolver=lambda row: None
        )["family_key"]
        == "abc|strategy_hypothesis"
    )
    assert (
        g.project_family_v2(
            trials_rows=[],
            universe_digest="abc",
            scope_tag="diagnostic",
            curve_resolver=lambda row: None,
        )["family_key"]
        == "abc|diagnostic"
    )
