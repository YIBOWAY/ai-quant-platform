from __future__ import annotations

from pathlib import Path

import pytest

from quant_system.ops.common import ReleaseOperationError
from quant_system.ops.postgres_suite import parse_pytest_junit


def write_junit(path: Path, cases: str) -> None:
    path.write_text(
        f'<?xml version="1.0" encoding="utf-8"?>'
        f'<testsuites><testsuite>{cases}</testsuite></testsuites>',
        encoding="utf-8",
    )


def test_junit_population_records_exact_nodes_and_outcomes(
    tmp_path: Path,
) -> None:
    path = tmp_path / "pytest.junit.xml"
    write_junit(
        path,
        """
        <testcase classname="tests.test_a" name="test_pass" />
        <testcase classname="tests.test_a" name="test_fail"><failure /></testcase>
        <testcase classname="tests.test_b" name="test_error"><error /></testcase>
        <testcase classname="tests.test_b" name="test_skip"><skipped /></testcase>
        <testcase classname="tests.test_b" name="test_xfail">
          <skipped type="pytest.xfail" />
        </testcase>
        """,
    )

    assert parse_pytest_junit(path) == {
        "errors": 1,
        "failed": 1,
        "node_ids": [
            {"node_id": "tests.test_a::test_fail", "outcome": "failed"},
            {"node_id": "tests.test_a::test_pass", "outcome": "passed"},
            {"node_id": "tests.test_b::test_error", "outcome": "errors"},
            {"node_id": "tests.test_b::test_skip", "outcome": "skipped"},
            {"node_id": "tests.test_b::test_xfail", "outcome": "xfailed"},
        ],
        "passed": 1,
        "skipped": 1,
        "tests": 5,
        "xfailed": 1,
    }


def test_junit_population_rejects_duplicate_or_absent_identity(
    tmp_path: Path,
) -> None:
    duplicate = tmp_path / "duplicate.xml"
    write_junit(
        duplicate,
        """
        <testcase classname="tests.test_a" name="test_same" />
        <testcase classname="tests.test_a" name="test_same" />
        """,
    )
    absent = tmp_path / "absent.xml"
    write_junit(absent, '<testcase classname="tests.test_a" />')

    with pytest.raises(ReleaseOperationError, match="duplicated"):
        parse_pytest_junit(duplicate)
    with pytest.raises(ReleaseOperationError, match="identity is absent"):
        parse_pytest_junit(absent)
