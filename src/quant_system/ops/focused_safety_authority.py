"""Canonical outcome authority for the fixed Agent v0.2 focused-safety suite."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import xml.etree.ElementTree as ET
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal

CONTRACT = "agent-v0.2-focused-safety-evidence/v1"
EXPECTED_COLLECTION_COUNT = 178
EXPECTED_COLLECTION_SHA256 = (
    "9552b35a38c2a22081cc2dc5e48397ee88b6c470b66033dc22828a84b8633a1e"
)
EVIDENCE_ENVIRONMENT_VARIABLE = "QS_AGENT_V02_FOCUSED_SAFETY_EVIDENCE_DIR"
JUNIT_FILE_NAME = "focused-safety.junit.xml"
RECEIPT_FILE_NAME = "focused-safety.receipt.json"
AUTHORITY_EXIT_STATUS = 78

_FUTU_SKIP_NODE_IDS = (
    "tests/test_api_safety.py::"
    "test_futu_skill_mutating_trade_entrypoints_are_disabled",
)
_RELEASE_DATABASE_SKIP_NODE_IDS = (
    "tests/test_hermes_release_authority.py::"
    "test_legacy_release_authority_is_replay_safe_but_not_hardened_ready",
    "tests/test_hermes_release_authority.py::"
    "test_one_active_release_and_first_action_receipt_are_frozen",
    "tests/test_hermes_release_authority.py::"
    "test_release_authority_requires_the_constrained_runtime_role",
    "tests/test_hermes_release_authority.py::"
    "test_release_stamp_cutover_idempotency_and_restart_visibility",
    "tests/test_hermes_release_authority.py::"
    "test_rollback_remains_callable_and_facts_are_append_only",
    "tests/test_hermes_release_authority.py::"
    "test_two_authority_instances_cannot_open_two_active_releases",
    "tests/test_release_authority_hardening.py::"
    "test_020_is_replay_safe_ready_and_refuses_future_schema_downgrade",
    "tests/test_release_authority_hardening.py::"
    "test_candidate_open_and_public_cutover_race_has_exactly_one_winner",
    "tests/test_release_authority_hardening.py::"
    "test_concurrent_acceptance_waits_for_paper_mutation_and_fails_closed",
    "tests/test_release_authority_hardening.py::"
    "test_concurrent_cutover_and_paper_mutation_finishes_fail_closed",
    "tests/test_release_authority_hardening.py::"
    "test_every_paper_authority_insert_update_delete_advances_the_epoch",
    "tests/test_release_authority_hardening.py::"
    "test_paper_mutation_after_cutover_closes_effective_release_gate",
    "tests/test_release_authority_hardening.py::"
    "test_paper_mutation_after_evidence_prevents_candidate_acceptance",
    "tests/test_release_authority_hardening.py::"
    "test_post_release_managed_session_binds_accepted_candidate",
    "tests/test_release_authority_hardening.py::"
    "test_public_cutover_refuses_an_open_replacement_candidate",
    "tests/test_release_authority_hardening.py::"
    "test_release_close_serializes_with_conversation_turn_insert",
    "tests/test_release_authority_hardening.py::"
    "test_release_command_trigger_rejects_session_from_prior_accepted_candidate",
    "tests/test_release_authority_hardening.py::"
    "test_runtime_cannot_forge_release_rows_and_legitimate_path_survives",
)
_PAPER_GATE_DATABASE_SKIP_NODE_IDS = (
    "tests/test_paper_gate_authority.py::"
    "test_action_digest_conflict_and_expired_lease_recover_as_unknown",
    "tests/test_paper_gate_authority.py::"
    "test_completion_contract_accepts_canonical_revision_promotion_id",
    "tests/test_paper_gate_authority.py::"
    "test_completion_contract_accepts_exact_research_claim_lineage_v2",
    "tests/test_paper_gate_authority.py::"
    "test_completion_contract_rejects_partial_research_claim_lineage_v2",
    "tests/test_paper_gate_authority.py::"
    "test_definitive_port_outcome_unknown_is_durable",
    "tests/test_paper_gate_authority.py::"
    "test_durable_gate_chain_calls_exact_hqa_ports_and_replays_after_restart",
    "tests/test_paper_gate_authority.py::"
    "test_gate1_source_evidence_is_exact_workspace_bound_and_rehashed",
    "tests/test_paper_gate_authority.py::"
    "test_gate2_rejection_preserves_continuation_identity_for_restart_show",
    "tests/test_paper_gate_authority.py::"
    "test_hqa_receipt_cannot_substitute_hermes_session_id",
    "tests/test_paper_gate_authority.py::"
    "test_malformed_post_mutation_receipt_is_unknown_and_never_retried",
    "tests/test_paper_gate_authority.py::"
    "test_post_hqa_success_finalize_failure_is_durable_unknown_on_restart",
    "tests/test_paper_gate_authority.py::"
    "test_registration_requires_exact_ready_platform_managed_session",
    "tests/test_paper_gate_authority.py::"
    "test_runtime_security_rejects_admin_or_migrator_connection",
    "tests/test_paper_gate_authority.py::"
    "test_schema_readiness_fails_closed_on_security_drift"
    "[ALTER POLICY v4r_root_scope ON quant_system.agent_v02_paper_gate_actions "
    "USING (true) WITH CHECK (true)]",
    "tests/test_paper_gate_authority.py::"
    "test_schema_readiness_fails_closed_on_security_drift"
    "[ALTER TABLE quant_system.agent_v02_paper_gate_actions DROP CONSTRAINT "
    "agent_v02_paper_gate_actions_action_state_check]",
    "tests/test_paper_gate_authority.py::"
    "test_schema_readiness_fails_closed_on_security_drift"
    "[ALTER TABLE quant_system.agent_v02_paper_gate_actions DROP CONSTRAINT "
    "agent_v02_paper_gate_actions_pkey]",
    "tests/test_paper_gate_authority.py::"
    "test_schema_readiness_fails_closed_on_security_drift"
    "[ALTER TABLE quant_system.agent_v02_paper_gate_challenges ALTER COLUMN "
    "platform_session_id DROP NOT NULL]",
    "tests/test_paper_gate_authority.py::"
    "test_schema_readiness_fails_closed_on_security_drift"
    "[CREATE OR REPLACE FUNCTION "
    "quant_system.require_agent_v02_paper_gate_ready_session() RETURNS trigger "
    "LANGUAGE plpgsql STABLE SECURITY INVOKER AS 'BEGIN RETURN NEW; END;']",
    "tests/test_paper_gate_authority.py::"
    "test_schema_readiness_fails_closed_on_security_drift"
    "[DROP INDEX quant_system.ux_agent_v02_paper_gate_single_action]",
    "tests/test_paper_gate_authority.py::"
    "test_schema_readiness_fails_closed_on_security_drift"
    "[DROP TRIGGER trg_agent_v02_paper_gate_ready_session ON "
    "quant_system.agent_v02_paper_gate_challenges]",
)

AUTHORIZED_SKIP_REASONS: Mapping[str, str] = MappingProxyType(
    {
        **dict.fromkeys(
            _FUTU_SKIP_NODE_IDS,
            "local futuapi skill is not installed under .agents",
        ),
        **dict.fromkeys(
            _RELEASE_DATABASE_SKIP_NODE_IDS,
            "set QS_TEST_DATABASE_URL to run PostgreSQL integration tests",
        ),
        **dict.fromkeys(
            _PAPER_GATE_DATABASE_SKIP_NODE_IDS,
            "set a PostgreSQL test admin URL for paper Gate tests",
        ),
    }
)

FocusedOutcome = Literal[
    "passed",
    "failed",
    "error",
    "skipped",
    "xfailed",
    "xpassed",
]
_OUTCOMES = frozenset(
    {
        "passed",
        "failed",
        "error",
        "skipped",
        "xfailed",
        "xpassed",
    }
)


class FocusedSafetyAuthorityError(RuntimeError):
    """One stable, non-secret focused-safety authority failure."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class FocusedSafetyExpectation:
    """Exact collection and expected non-pass outcomes for one suite."""

    collection_count: int
    collection_sha256: str
    skip_reasons: tuple[tuple[str, str], ...]
    xfail_reasons: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class FocusedTestResult:
    """Canonical terminal outcome for one exact pytest node."""

    node_id: str
    outcome: FocusedOutcome
    reason: str = ""


@dataclass(frozen=True)
class FocusedSafetyEvidence:
    """Deterministic JUnit and receipt bytes."""

    junit: bytes
    receipt: bytes


PRODUCTION_EXPECTATION = FocusedSafetyExpectation(
    collection_count=EXPECTED_COLLECTION_COUNT,
    collection_sha256=EXPECTED_COLLECTION_SHA256,
    skip_reasons=tuple(sorted(AUTHORIZED_SKIP_REASONS.items())),
    xfail_reasons=(),
)


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collection_sha256(node_ids: tuple[str, ...]) -> str:
    """Hash the sorted exact collection without collapsing parametrized nodes."""

    return hashlib.sha256(_canonical_json_bytes(sorted(node_ids))).hexdigest()


def _mapping(
    entries: tuple[tuple[str, str], ...],
    *,
    invalid_code: str,
) -> dict[str, str]:
    result: dict[str, str] = {}
    for node_id, reason in entries:
        if (
            not isinstance(node_id, str)
            or not node_id.startswith("tests/")
            or "::" not in node_id
            or not isinstance(reason, str)
            or not reason.strip()
            or node_id in result
        ):
            raise FocusedSafetyAuthorityError(invalid_code)
        result[node_id] = reason
    return result


def _validated_collection(
    expectation: FocusedSafetyExpectation,
    node_ids: tuple[str, ...],
) -> tuple[str, ...]:
    if (
        isinstance(expectation.collection_count, bool)
        or not isinstance(expectation.collection_count, int)
        or expectation.collection_count < 1
        or len(expectation.collection_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expectation.collection_sha256)
    ):
        raise FocusedSafetyAuthorityError("focused_safety_expectation_invalid")
    if (
        not node_ids
        or len(set(node_ids)) != len(node_ids)
        or any(
            not isinstance(node_id, str)
            or not node_id.startswith("tests/")
            or "::" not in node_id
            for node_id in node_ids
        )
    ):
        raise FocusedSafetyAuthorityError("focused_safety_collection_invalid")
    if len(node_ids) < expectation.collection_count:
        raise FocusedSafetyAuthorityError("focused_safety_population_shrunk")
    if (
        len(node_ids) != expectation.collection_count
        or collection_sha256(node_ids) != expectation.collection_sha256
    ):
        raise FocusedSafetyAuthorityError("focused_safety_population_substituted")
    return tuple(sorted(node_ids))


def _validated_results(
    *,
    collected: tuple[str, ...],
    results: tuple[FocusedTestResult, ...],
) -> tuple[FocusedTestResult, ...]:
    if len(results) != len(collected):
        raise FocusedSafetyAuthorityError("focused_safety_result_population_mismatch")
    result_by_node: dict[str, FocusedTestResult] = {}
    for result in results:
        if (
            not isinstance(result, FocusedTestResult)
            or result.node_id in result_by_node
            or result.outcome not in _OUTCOMES
            or not isinstance(result.reason, str)
        ):
            raise FocusedSafetyAuthorityError("focused_safety_result_invalid")
        if result.outcome == "passed" and result.reason:
            raise FocusedSafetyAuthorityError("focused_safety_result_invalid")
        if result.outcome != "passed" and not result.reason.strip():
            if result.outcome == "skipped":
                raise FocusedSafetyAuthorityError("focused_safety_skip_reason_empty")
            if result.outcome == "xfailed":
                raise FocusedSafetyAuthorityError("focused_safety_xfail_reason_empty")
            raise FocusedSafetyAuthorityError("focused_safety_result_reason_empty")
        result_by_node[result.node_id] = result
    if set(result_by_node) != set(collected):
        raise FocusedSafetyAuthorityError("focused_safety_result_identity_mismatch")
    return tuple(result_by_node[node_id] for node_id in collected)


def _validate_non_pass_authority(
    *,
    expectation: FocusedSafetyExpectation,
    results: tuple[FocusedTestResult, ...],
) -> None:
    expected_skips = _mapping(
        expectation.skip_reasons,
        invalid_code="focused_safety_skip_expectation_invalid",
    )
    expected_xfails = _mapping(
        expectation.xfail_reasons,
        invalid_code="focused_safety_xfail_expectation_invalid",
    )
    observed_skips = {
        result.node_id: result.reason
        for result in results
        if result.outcome == "skipped"
    }
    observed_xfails = {
        result.node_id: result.reason
        for result in results
        if result.outcome == "xfailed"
    }
    if observed_skips != expected_skips:
        raise FocusedSafetyAuthorityError("focused_safety_skip_authority_mismatch")
    if observed_xfails != expected_xfails or any(
        result.outcome == "xpassed" for result in results
    ):
        raise FocusedSafetyAuthorityError("focused_safety_xfail_authority_mismatch")


def _counts(results: tuple[FocusedTestResult, ...]) -> dict[str, int]:
    return {
        "errors": sum(result.outcome == "error" for result in results),
        "failed": sum(result.outcome == "failed" for result in results),
        "passed": sum(result.outcome == "passed" for result in results),
        "skipped": sum(result.outcome == "skipped" for result in results),
        "total": len(results),
        "xfailed": sum(result.outcome == "xfailed" for result in results),
        "xpassed": sum(result.outcome == "xpassed" for result in results),
    }


def _node_document(result: FocusedTestResult) -> dict[str, str]:
    document = {
        "node_id": result.node_id,
        "outcome": result.outcome,
    }
    if result.reason:
        document["reason"] = result.reason
    return document


def _canonical_junit(
    results: tuple[FocusedTestResult, ...],
    counts: Mapping[str, int],
) -> bytes:
    root = ET.Element(
        "testsuite",
        {
            "errors": str(counts["errors"]),
            "failures": str(counts["failed"] + counts["xpassed"]),
            "name": "agent-v0.2-focused-safety",
            "skipped": str(counts["skipped"] + counts["xfailed"]),
            "tests": str(counts["total"]),
            "xfailed": str(counts["xfailed"]),
            "xpassed": str(counts["xpassed"]),
        },
    )
    for result in results:
        path, name = result.node_id.split("::", 1)
        testcase = ET.SubElement(
            root,
            "testcase",
            {
                "classname": path.removesuffix(".py").replace("/", "."),
                "name": name,
                "node_id": result.node_id,
                "outcome": result.outcome,
            },
        )
        if result.outcome in {"skipped", "xfailed"}:
            ET.SubElement(
                testcase,
                "skipped",
                {
                    "message": result.reason,
                    "type": "xfail" if result.outcome == "xfailed" else "skip",
                },
            )
        elif result.outcome in {"failed", "xpassed"}:
            ET.SubElement(
                testcase,
                "failure",
                {
                    "message": result.reason,
                    "type": "xpass" if result.outcome == "xpassed" else "failure",
                },
            )
        elif result.outcome == "error":
            ET.SubElement(
                testcase,
                "error",
                {
                    "message": result.reason,
                    "type": "error",
                },
            )
    rendered = ET.tostring(root, encoding="unicode", short_empty_elements=True)
    return ET.canonicalize(xml_data=rendered, with_comments=False).encode("utf-8")


def _render_evidence(
    *,
    expectation: FocusedSafetyExpectation,
    collected: tuple[str, ...],
    results: tuple[FocusedTestResult, ...],
    authority_errors: tuple[str, ...] = (),
) -> FocusedSafetyEvidence:
    counts = _counts(results)
    junit = _canonical_junit(results, counts)
    verdict = (
        "passed"
        if not authority_errors
        and counts["failed"] == 0
        and counts["errors"] == 0
        and counts["xpassed"] == 0
        else "failed"
    )
    document = {
        "artifacts": {
            "junit": {
                "bytes": len(junit),
                "path": JUNIT_FILE_NAME,
                "sha256": hashlib.sha256(junit).hexdigest(),
            }
        },
        "authority": {
            "authorized_skip_count": len(expectation.skip_reasons),
            "authorized_xfail_count": len(expectation.xfail_reasons),
            "collection_count": len(collected),
            "collection_sha256": collection_sha256(collected),
            "expected_collection_count": expectation.collection_count,
            "expected_collection_sha256": expectation.collection_sha256,
            "implementation_sha256": _sha256_file(Path(__file__).resolve()),
        },
        "authority_errors": list(authority_errors),
        "contract": CONTRACT,
        "counts": counts,
        "node_outcomes": [_node_document(result) for result in results],
        "verdict": verdict,
    }
    return FocusedSafetyEvidence(
        junit=junit,
        receipt=_canonical_json_bytes(document),
    )


def build_focused_safety_evidence(
    *,
    expectation: FocusedSafetyExpectation,
    collected_node_ids: tuple[str, ...],
    results: tuple[FocusedTestResult, ...],
) -> FocusedSafetyEvidence:
    """Validate exact identities and produce deterministic evidence."""

    collected = _validated_collection(expectation, collected_node_ids)
    validated_results = _validated_results(
        collected=collected,
        results=results,
    )
    _validate_non_pass_authority(
        expectation=expectation,
        results=validated_results,
    )
    return _render_evidence(
        expectation=expectation,
        collected=collected,
        results=validated_results,
    )


@dataclass
class _PytestRunState:
    evidence_dir: Path
    collected: tuple[str, ...] = ()
    authority_error: FocusedSafetyAuthorityError | None = None
    reports: dict[str, dict[str, Any]] = field(default_factory=dict)


_PYTEST_STATE: _PytestRunState | None = None


def _require_repository_module_binding() -> None:
    installed = Path(__file__).resolve()
    repository = (
        Path.cwd()
        / "src"
        / "quant_system"
        / "ops"
        / "focused_safety_authority.py"
    )
    for path in (installed, repository):
        if path.is_symlink() or not path.is_file():
            raise FocusedSafetyAuthorityError(
                "focused_safety_authority_module_unsafe"
            )
        info = path.stat()
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise FocusedSafetyAuthorityError(
                "focused_safety_authority_module_unsafe"
            )
    if _sha256_file(installed) != _sha256_file(repository):
        raise FocusedSafetyAuthorityError(
            "focused_safety_authority_module_mismatch"
        )


def _require_evidence_directory(config: Any) -> Path:
    raw = os.environ.get(EVIDENCE_ENVIRONMENT_VARIABLE)
    basetemp = getattr(config.option, "basetemp", None)
    if not raw or basetemp is None:
        raise FocusedSafetyAuthorityError("focused_safety_evidence_path_missing")
    evidence_dir = Path(raw)
    expected = Path(f"{Path(str(basetemp))}.focused-safety-evidence")
    if (
        not evidence_dir.is_absolute()
        or evidence_dir != expected
        or evidence_dir != Path(os.path.normpath(evidence_dir))
        or evidence_dir.is_symlink()
    ):
        raise FocusedSafetyAuthorityError("focused_safety_evidence_path_invalid")
    if evidence_dir.exists():
        info = evidence_dir.stat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o022
            or any(evidence_dir.iterdir())
        ):
            raise FocusedSafetyAuthorityError("focused_safety_evidence_directory_unsafe")
    else:
        evidence_dir.mkdir(mode=0o700)
    return evidence_dir


def pytest_configure(config: Any) -> None:
    """Initialize the one-shot evidence directory before collection."""

    global _PYTEST_STATE  # noqa: PLW0603 - pytest module plugin lifecycle
    try:
        _require_repository_module_binding()
        evidence_dir = _require_evidence_directory(config)
    except FocusedSafetyAuthorityError as exc:
        import pytest

        raise pytest.UsageError(exc.code) from exc
    _PYTEST_STATE = _PytestRunState(evidence_dir=evidence_dir)


def pytest_collection_modifyitems(
    session: Any,
    config: Any,
    items: list[Any],
) -> None:
    """Reject a substituted collection before any test body executes."""

    del session, config
    if _PYTEST_STATE is None:
        return
    _PYTEST_STATE.collected = tuple(sorted(item.nodeid for item in items))
    try:
        _validated_collection(PRODUCTION_EXPECTATION, _PYTEST_STATE.collected)
    except FocusedSafetyAuthorityError as exc:
        _PYTEST_STATE.authority_error = exc
        items.clear()


def pytest_runtest_logreport(report: Any) -> None:
    """Retain phase reports until one terminal outcome can be classified."""

    if _PYTEST_STATE is None:
        return
    _PYTEST_STATE.reports.setdefault(report.nodeid, {})[report.when] = report


def _skip_reason(report: Any) -> str:
    was_xfail = getattr(report, "wasxfail", None)
    if isinstance(was_xfail, str) and was_xfail.strip():
        return was_xfail.strip()
    longrepr = getattr(report, "longrepr", None)
    if isinstance(longrepr, tuple) and len(longrepr) >= 3:
        reason = str(longrepr[2]).strip()
    else:
        reason = str(longrepr or "").strip()
    prefix = "Skipped: "
    if reason.startswith(prefix):
        reason = reason[len(prefix) :].strip()
    return reason


def _classify_report(
    node_id: str,
    phases: Mapping[str, Any],
) -> FocusedTestResult:
    setup = phases.get("setup")
    call = phases.get("call")
    teardown = phases.get("teardown")
    if setup is not None and setup.failed:
        return FocusedTestResult(node_id, "error", "pytest setup failed")
    if teardown is not None and teardown.failed:
        return FocusedTestResult(node_id, "error", "pytest teardown failed")
    if setup is not None and setup.skipped:
        outcome = "xfailed" if getattr(setup, "wasxfail", None) else "skipped"
        return FocusedTestResult(node_id, outcome, _skip_reason(setup))
    if call is None:
        return FocusedTestResult(node_id, "error", "pytest call report absent")
    was_xfail = getattr(call, "wasxfail", None)
    if was_xfail and call.skipped:
        return FocusedTestResult(node_id, "xfailed", _skip_reason(call))
    if was_xfail and call.passed:
        return FocusedTestResult(node_id, "xpassed", str(was_xfail).strip())
    if call.failed:
        return FocusedTestResult(node_id, "failed", "pytest call failed")
    if call.skipped:
        return FocusedTestResult(node_id, "skipped", _skip_reason(call))
    if call.passed:
        return FocusedTestResult(node_id, "passed")
    return FocusedTestResult(node_id, "error", "pytest outcome unavailable")


def _authority_failure_evidence(
    state: _PytestRunState,
    error: FocusedSafetyAuthorityError,
    *,
    results: tuple[FocusedTestResult, ...] | None = None,
) -> FocusedSafetyEvidence:
    if results is None:
        results = tuple(
            FocusedTestResult(
                node_id=node_id,
                outcome="error",
                reason=error.code,
            )
            for node_id in state.collected
        )
    return _render_evidence(
        expectation=PRODUCTION_EXPECTATION,
        collected=state.collected,
        results=results,
        authority_errors=(error.code,),
    )


def _write_exclusive(directory: Path, name: str, payload: bytes) -> None:
    directory_descriptor = os.open(
        directory,
        os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
    )
    try:
        descriptor = os.open(
            name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=directory_descriptor,
        )
        try:
            view = memoryview(payload)
            while view:
                written = os.write(descriptor, view)
                view = view[written:]
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _emit_paths(session: Any, state: _PytestRunState, verdict: str) -> None:
    reporter = session.config.pluginmanager.getplugin("terminalreporter")
    lines = (
        f"agent_v02_focused_safety_junit={state.evidence_dir / JUNIT_FILE_NAME}",
        f"agent_v02_focused_safety_receipt={state.evidence_dir / RECEIPT_FILE_NAME}",
        f"agent_v02_focused_safety_verdict={verdict}",
    )
    if reporter is None:
        for line in lines:
            print(line)
        return
    reporter.ensure_newline()
    for line in lines:
        reporter.write_line(line)


def pytest_sessionfinish(session: Any, exitstatus: int) -> None:
    """Seal exact terminal identities and force authority failures nonzero."""

    del exitstatus
    state = _PYTEST_STATE
    if state is None:
        return
    authority_error = state.authority_error
    if authority_error is None:
        results = tuple(
            _classify_report(node_id, state.reports.get(node_id, {}))
            for node_id in state.collected
        )
        try:
            evidence = build_focused_safety_evidence(
                expectation=PRODUCTION_EXPECTATION,
                collected_node_ids=state.collected,
                results=results,
            )
        except FocusedSafetyAuthorityError as exc:
            authority_error = exc
            evidence = _authority_failure_evidence(
                state,
                exc,
                results=results,
            )
    else:
        evidence = _authority_failure_evidence(state, authority_error)

    _write_exclusive(state.evidence_dir, JUNIT_FILE_NAME, evidence.junit)
    _write_exclusive(state.evidence_dir, RECEIPT_FILE_NAME, evidence.receipt)
    document = json.loads(evidence.receipt)
    verdict = str(document["verdict"])
    if authority_error is not None:
        session.exitstatus = AUTHORITY_EXIT_STATUS
    elif verdict != "passed" and session.exitstatus == 0:
        session.exitstatus = 1
    _emit_paths(session, state, verdict)


__all__ = [
    "AUTHORIZED_SKIP_REASONS",
    "EXPECTED_COLLECTION_COUNT",
    "EXPECTED_COLLECTION_SHA256",
    "FocusedSafetyAuthorityError",
    "FocusedSafetyEvidence",
    "FocusedSafetyExpectation",
    "FocusedTestResult",
    "build_focused_safety_evidence",
    "collection_sha256",
]
