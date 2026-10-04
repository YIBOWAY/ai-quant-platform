"""The recompute envelope: rebuild every sub-verdict, or fail verification."""

from __future__ import annotations

import copy

from quant_system.research import gate_v2 as g
from quant_system.research.gate_v2.verdict import verify_verdict_integrity_v2
from tests.gate_v2_fixtures import (
    digest_of_universe,
    family_from_payloads,
    platform_result,
    resolver_for,
)


def _record():
    payloads = [
        platform_result(
            equity_returns=[0.0015 * ((index + offset) % 7 - 3) for index in range(260)],
            benchmark_returns=[0.0] * 260,
        )
        for offset in range(12)
    ]
    candidate = platform_result(
        equity_returns=[0.0012 * ((index % 5) - 1) for index in range(260)],
        benchmark_returns=[0.0] * 260,
    )
    return g.evaluate_gate_v2(
        curve_rows=candidate["curve"],
        initial_cash=candidate["evaluation_initial_cash"],
        universe_digest=digest_of_universe(),
        trials_rows=family_from_payloads(payloads),
        curve_resolver=resolver_for(payloads),
        v1_passed=True,
    )


def test_a_fresh_record_verifies() -> None:
    assert verify_verdict_integrity_v2(_record()) is True


def test_tampering_embedded_input_metadata_fails_verification() -> None:
    """The inputs metadata the recompute never re-derives (universe_digest,
    initial_cash, benchmark_symbol, definition_digest) is covered by the
    envelope digest, so editing one alone is detected."""

    for key, value in (
        ("universe_digest", "0" * 64),
        ("initial_cash", 1.0),
        ("benchmark_symbol", "QQQ"),
        ("definition_digest", "f" * 64),
    ):
        record = _record()
        record["inputs"][key] = value
        assert verify_verdict_integrity_v2(record) is False, key


def test_tampering_the_returns_digest_fails_verification() -> None:
    record = copy.deepcopy(_record())
    record["inputs"]["returns_digest"] = "0" * 64
    assert verify_verdict_integrity_v2(record) is False


def test_tampering_the_active_series_fails_verification() -> None:
    record = copy.deepcopy(_record())
    record["inputs"]["active_returns"][0] = 9.99
    assert verify_verdict_integrity_v2(record) is False


def test_tampering_the_family_digest_fails_verification() -> None:
    record = copy.deepcopy(_record())
    record["family"]["family_digest"] = "0" * 64
    assert verify_verdict_integrity_v2(record) is False


def test_tampering_a_family_member_sharpe_fails_verification() -> None:
    record = copy.deepcopy(_record())
    record["family"]["members"][0]["recomputed_sharpe"] = 9.99
    assert verify_verdict_integrity_v2(record) is False


def test_tampering_the_health_block_fails_verification() -> None:
    record = copy.deepcopy(_record())
    record["health"]["max_drawdown"]["value"] = -1.0
    assert verify_verdict_integrity_v2(record) is False


def test_tampering_the_dsr_value_fails_verification() -> None:
    record = copy.deepcopy(_record())
    record["dsr"]["value"] = 0.999999
    assert verify_verdict_integrity_v2(record) is False


def test_tampering_the_grade_fails_verification() -> None:
    record = copy.deepcopy(_record())
    record["grade"] = {"grade": g.GRADE_SUPPORTED, "reasons": []}
    assert verify_verdict_integrity_v2(record) is False


def test_the_record_is_observation_only_and_non_authoritative() -> None:
    record = _record()
    assert record["mode"] == "parallel_observe_only"
    assert record["authoritative"] is False
    assert record["tier_recommendation"]["tier_source"] == "program_rule"
    assert record["formula"] == "bailey_lopez_de_prado_2014"


def test_the_code_fingerprint_covers_the_new_sources() -> None:
    sources = g.gate_v2_sources()
    for name in ("verdict.py", "family.py", "fingerprint_grading.py"):
        assert name in sources
    assert all(len(value) == 64 for value in sources.values())


# --- G5: fields the recompute alone could not see --------------------------


def _record_with_increment():
    payloads = [
        platform_result(
            equity_returns=[0.0015 * ((index + offset) % 7 - 3) for index in range(260)],
            benchmark_returns=[0.0] * 260,
        )
        for offset in range(12)
    ]
    candidate = platform_result(
        equity_returns=[0.0012 * ((index % 5) - 1) for index in range(260)],
        benchmark_returns=[0.0] * 260,
    )
    baseline = [0.0005 * ((index % 9) - 4) for index in range(260)]
    augmented = [value + 0.0012 for value in baseline]
    return g.evaluate_gate_v2(
        curve_rows=candidate["curve"],
        initial_cash=candidate["evaluation_initial_cash"],
        universe_digest=digest_of_universe(),
        trials_rows=family_from_payloads(payloads),
        curve_resolver=resolver_for(payloads),
        increment_objective={"baseline": baseline, "augmented": augmented},
        v1_passed=True,
    )


def test_an_applicable_increment_record_verifies_including_its_bootstrap() -> None:
    record = _record_with_increment()
    assert record["upgrade"]["applicable"] is True
    assert record["upgrade"]["bootstrap"]["status"] == "ready"
    assert verify_verdict_integrity_v2(record) is True


def test_tampering_the_upgrade_bootstrap_fails_verification() -> None:
    record = copy.deepcopy(_record_with_increment())
    record["upgrade"]["bootstrap"]["ci95_low"] = 999.0
    assert verify_verdict_integrity_v2(record) is False


def test_tampering_the_upgrade_acceptance_fails_verification() -> None:
    record = copy.deepcopy(_record_with_increment())
    record["upgrade"]["upgrade_accepted"] = not record["upgrade"]["upgrade_accepted"]
    assert verify_verdict_integrity_v2(record) is False


def test_tampering_an_unused_config_key_fails_verification() -> None:
    """``config_version`` never feeds a recomputed block, so only the digest sees it."""
    record = copy.deepcopy(_record())
    record["config"]["config_version"] = "tampered"
    assert verify_verdict_integrity_v2(record) is False


def test_tampering_the_tier_cash_fails_verification() -> None:
    record = copy.deepcopy(_record())
    record["tier_recommendation"]["allocated_cash"] = 999.0
    assert verify_verdict_integrity_v2(record) is False


def test_a_digest_consistent_cash_forgery_still_fails_verification() -> None:
    """Even re-sealing the envelope cannot relabel the tier's capital."""
    record = copy.deepcopy(_record())
    record["tier_recommendation"]["allocated_cash"] = 999.0
    record["envelope_digest"] = g.envelope_digest(record)
    assert verify_verdict_integrity_v2(record) is False


def test_tampering_the_parallel_verdict_fails_verification() -> None:
    record = copy.deepcopy(_record())
    record["verdict_parallel"]["v2_passed"] = not record["verdict_parallel"]["v2_passed"]
    assert verify_verdict_integrity_v2(record) is False


def test_the_documented_boundary_the_code_block_is_provenance_not_evidence() -> None:
    """Boundary: ``code`` is a disk-relative source hash and is outside the digest."""
    record = copy.deepcopy(_record())
    before = g.envelope_digest(record)
    record["code"] = {"gate_v2_sources": {}, "v2_code_digest": "0" * 64}
    assert g.envelope_digest(record) == before
