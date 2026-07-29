from __future__ import annotations

import hashlib
import json
import shlex
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from quant_system.ops import focused_safety_authority as authority_module
from quant_system.ops.focused_safety_authority import (
    AUTHORIZED_SKIP_REASONS,
    EXPECTED_COLLECTION_COUNT,
    EXPECTED_COLLECTION_SHA256,
    FocusedSafetyAuthorityError,
    FocusedSafetyExpectation,
    FocusedTestResult,
    build_focused_safety_evidence,
    collection_sha256,
)
from tests.test_agent_v02_focused_safety_wrapper import (
    _invoke,
    _release_fixture,
)


def _small_expectation() -> FocusedSafetyExpectation:
    node_ids = (
        "tests/test_one.py::test_pass",
        "tests/test_two.py::test_skip",
    )
    return FocusedSafetyExpectation(
        collection_count=len(node_ids),
        collection_sha256=collection_sha256(node_ids),
        skip_reasons=(
            ("tests/test_two.py::test_skip", "database intentionally unavailable"),
        ),
        xfail_reasons=(),
    )


def _small_results() -> tuple[FocusedTestResult, ...]:
    return (
        FocusedTestResult(
            node_id="tests/test_one.py::test_pass",
            outcome="passed",
        ),
        FocusedTestResult(
            node_id="tests/test_two.py::test_skip",
            outcome="skipped",
            reason="database intentionally unavailable",
        ),
    )


def test_focused_safety_evidence_is_canonical_and_identity_complete() -> None:
    expectation = _small_expectation()
    node_ids = tuple(result.node_id for result in _small_results())

    first = build_focused_safety_evidence(
        expectation=expectation,
        collected_node_ids=node_ids,
        results=_small_results(),
    )
    second = build_focused_safety_evidence(
        expectation=expectation,
        collected_node_ids=tuple(reversed(node_ids)),
        results=tuple(reversed(_small_results())),
    )

    assert first.receipt == second.receipt
    assert first.junit == second.junit
    document = json.loads(first.receipt)
    assert document["counts"] == {
        "errors": 0,
        "failed": 0,
        "passed": 1,
        "skipped": 1,
        "total": 2,
        "xfailed": 0,
        "xpassed": 0,
    }
    assert document["authority"]["implementation_sha256"] == hashlib.sha256(
        Path(authority_module.__file__).read_bytes()
    ).hexdigest()
    assert document["node_outcomes"] == [
        {
            "node_id": "tests/test_one.py::test_pass",
            "outcome": "passed",
        },
        {
            "node_id": "tests/test_two.py::test_skip",
            "outcome": "skipped",
            "reason": "database intentionally unavailable",
        },
    ]
    root = ET.fromstring(first.junit)
    assert root.attrib == {
        "errors": "0",
        "failures": "0",
        "name": "agent-v0.2-focused-safety",
        "skipped": "1",
        "tests": "2",
        "xfailed": "0",
        "xpassed": "0",
    }
    assert [
        (case.attrib["node_id"], case.attrib["outcome"])
        for case in root.findall("testcase")
    ] == [
        ("tests/test_one.py::test_pass", "passed"),
        ("tests/test_two.py::test_skip", "skipped"),
    ]


def test_focused_safety_evidence_preserves_every_terminal_outcome_identity() -> None:
    node_ids = (
        "tests/test_outcomes.py::test_error",
        "tests/test_outcomes.py::test_fail",
        "tests/test_outcomes.py::test_pass",
        "tests/test_outcomes.py::test_skip",
        "tests/test_outcomes.py::test_xfail",
    )
    expectation = FocusedSafetyExpectation(
        collection_count=len(node_ids),
        collection_sha256=collection_sha256(node_ids),
        skip_reasons=(("tests/test_outcomes.py::test_skip", "skip reason"),),
        xfail_reasons=(("tests/test_outcomes.py::test_xfail", "xfail reason"),),
    )

    evidence = build_focused_safety_evidence(
        expectation=expectation,
        collected_node_ids=node_ids,
        results=(
            FocusedTestResult(node_ids[0], "error", "setup failed"),
            FocusedTestResult(node_ids[1], "failed", "assertion failed"),
            FocusedTestResult(node_ids[2], "passed"),
            FocusedTestResult(node_ids[3], "skipped", "skip reason"),
            FocusedTestResult(node_ids[4], "xfailed", "xfail reason"),
        ),
    )

    document = json.loads(evidence.receipt)
    assert document["verdict"] == "failed"
    assert document["counts"] == {
        "errors": 1,
        "failed": 1,
        "passed": 1,
        "skipped": 1,
        "total": 5,
        "xfailed": 1,
        "xpassed": 0,
    }
    root = ET.fromstring(evidence.junit)
    assert root.attrib["errors"] == "1"
    assert root.attrib["failures"] == "1"
    assert root.attrib["skipped"] == "2"
    assert {
        testcase.attrib["node_id"]: testcase.attrib["outcome"]
        for testcase in root.findall("testcase")
    } == {
        node_ids[0]: "error",
        node_ids[1]: "failed",
        node_ids[2]: "passed",
        node_ids[3]: "skipped",
        node_ids[4]: "xfailed",
    }


@pytest.mark.parametrize(
    ("node_ids", "results", "code"),
    [
        (
            ("tests/test_two.py::test_skip",),
            (
                FocusedTestResult(
                    node_id="tests/test_two.py::test_skip",
                    outcome="skipped",
                    reason="database intentionally unavailable",
                ),
            ),
            "focused_safety_population_shrunk",
        ),
        (
            (
                "tests/test_one.py::test_pass",
                "tests/test_three.py::test_substituted",
            ),
            (
                FocusedTestResult(
                    node_id="tests/test_one.py::test_pass",
                    outcome="passed",
                ),
                FocusedTestResult(
                    node_id="tests/test_three.py::test_substituted",
                    outcome="skipped",
                    reason="database intentionally unavailable",
                ),
            ),
            "focused_safety_population_substituted",
        ),
        (
            (
                "tests/test_one.py::test_pass",
                "tests/test_two.py::test_skip",
            ),
            (
                FocusedTestResult(
                    node_id="tests/test_one.py::test_pass",
                    outcome="skipped",
                    reason="database intentionally unavailable",
                ),
                FocusedTestResult(
                    node_id="tests/test_two.py::test_skip",
                    outcome="passed",
                ),
            ),
            "focused_safety_skip_authority_mismatch",
        ),
        (
            (
                "tests/test_one.py::test_pass",
                "tests/test_two.py::test_skip",
            ),
            (
                FocusedTestResult(
                    node_id="tests/test_one.py::test_pass",
                    outcome="skipped",
                    reason="new skip",
                ),
                FocusedTestResult(
                    node_id="tests/test_two.py::test_skip",
                    outcome="skipped",
                    reason="database intentionally unavailable",
                ),
            ),
            "focused_safety_skip_authority_mismatch",
        ),
        (
            (
                "tests/test_one.py::test_pass",
                "tests/test_two.py::test_skip",
            ),
            (
                FocusedTestResult(
                    node_id="tests/test_one.py::test_pass",
                    outcome="passed",
                ),
                FocusedTestResult(
                    node_id="tests/test_two.py::test_skip",
                    outcome="skipped",
                    reason="",
                ),
            ),
            "focused_safety_skip_reason_empty",
        ),
        (
            (
                "tests/test_one.py::test_pass",
                "tests/test_two.py::test_skip",
            ),
            (
                FocusedTestResult(
                    node_id="tests/test_one.py::test_pass",
                    outcome="xfailed",
                    reason="new xfail",
                ),
                FocusedTestResult(
                    node_id="tests/test_two.py::test_skip",
                    outcome="skipped",
                    reason="database intentionally unavailable",
                ),
            ),
            "focused_safety_xfail_authority_mismatch",
        ),
    ],
)
def test_focused_safety_authority_rejects_population_or_outcome_drift(
    node_ids: tuple[str, ...],
    results: tuple[FocusedTestResult, ...],
    code: str,
) -> None:
    with pytest.raises(FocusedSafetyAuthorityError) as captured:
        build_focused_safety_evidence(
            expectation=_small_expectation(),
            collected_node_ids=node_ids,
            results=results,
        )

    assert captured.value.code == code


def test_production_focused_safety_authority_freezes_all_39_skip_identities() -> None:
    assert EXPECTED_COLLECTION_COUNT == 178
    assert (
        EXPECTED_COLLECTION_SHA256
        == "9552b35a38c2a22081cc2dc5e48397ee88b6c470b66033dc22828a84b8633a1e"
    )
    assert len(AUTHORIZED_SKIP_REASONS) == 39
    assert len(set(AUTHORIZED_SKIP_REASONS)) == 39
    assert all(node_id.startswith("tests/") for node_id in AUTHORIZED_SKIP_REASONS)
    assert all("::" in node_id for node_id in AUTHORIZED_SKIP_REASONS)
    assert all(reason.strip() for reason in AUTHORIZED_SKIP_REASONS.values())


def test_wrapper_injects_only_the_repository_focused_safety_authority(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("QS_TEST_DATABASE_ADMIN_URL", "postgresql://must-not-run")
    monkeypatch.setenv("QS_TEST_DATABASE_URL", "postgresql://must-not-run")
    wrapper, python, capture = _release_fixture(tmp_path)
    python.write_text(
        "#!/bin/sh\n"
        "{\n"
        '  printf "PLUGIN=%s\\n" "$PYTEST_PLUGINS"\n'
        '  printf "AUTOLOAD=%s\\n" "$PYTEST_DISABLE_PLUGIN_AUTOLOAD"\n'
        '  printf "ADDOPTS=%s\\n" "$PYTEST_ADDOPTS"\n'
        '  printf "EVIDENCE=%s\\n" "$QS_AGENT_V02_FOCUSED_SAFETY_EVIDENCE_DIR"\n'
        '  printf "TEST_DATABASE_ADMIN_URL=%s\\n" '
        '"${QS_TEST_DATABASE_ADMIN_URL-}"\n'
        '  printf "TEST_DATABASE_URL=%s\\n" "${QS_TEST_DATABASE_URL-}"\n'
        f"}} > {shlex.quote(str(capture))}\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    basetemp = tmp_path / "focused-safety-basetemp"

    completed = _invoke(wrapper, python, basetemp)

    assert completed.returncode == 0, completed.stderr
    assert capture.read_text(encoding="utf-8").splitlines() == [
        "PLUGIN=quant_system.ops.focused_safety_authority",
        "AUTOLOAD=1",
        "ADDOPTS=-p no:cacheprovider",
        f"EVIDENCE={basetemp}.focused-safety-evidence",
        "TEST_DATABASE_ADMIN_URL=",
        "TEST_DATABASE_URL=",
    ]
