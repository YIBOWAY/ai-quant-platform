from __future__ import annotations

from pathlib import Path

import pytest

from quant_system.ops.common import ReleaseOperationError
from quant_system.ops.postgres_suite import _safe_test_environment, parse_pytest_junit


def test_required_pg_manifest_records_audited_retirement_without_count_padding():
    from quant_system.ops.postgres_population import (
        ADDED_PG_MARKED_NODES,
        LEGACY_MINIMUM_PG_MARKED_TESTS,
        REQUIRED_PG_MARKED_NODES,
        RETIRED_PG_MARKED_NODES,
    )
    from quant_system.ops.postgres_suite import MINIMUM_PG_MARKED_TESTS

    required, added, retired = map(
        set, (REQUIRED_PG_MARKED_NODES, ADDED_PG_MARKED_NODES, RETIRED_PG_MARKED_NODES)
    )
    assert len(required) == len(REQUIRED_PG_MARKED_NODES) == 238
    assert len(added) == 33 and len(retired) == 40
    assert not required & retired and added <= required
    assert len((required - added) | retired) == LEGACY_MINIMUM_PG_MARKED_TESTS == 245
    assert len(required) == MINIMUM_PG_MARKED_TESTS
    assert {
        "tests.test_agent_workspace::test_submit_action_document_path_and_unsupported_kind",
        "tests.test_hermes_workflow_binding::test_legacy_event_append_only_function_drift_fails_closed_and_replay_restores_it",
        "tests.test_local_research_resource_postgres::test_migration_034_and_physical_chat_wrapper_converge_to_one_candidate",
    } <= required


def _run_population_fixture(tmp_path, monkeypatch, cases, *, required, stdout=b""):
    import subprocess

    from quant_system.ops import postgres_suite as suite

    def run(argv, **kwargs):
        path = Path(argv[argv.index("--junitxml") + 1])
        write_junit(path, cases)
        return subprocess.CompletedProcess(argv, 0, stdout, b"")

    monkeypatch.setattr(suite.subprocess, "run", run)
    return suite._run_pytest(
        python=Path("/test-only-python"),
        repository_root=tmp_path,
        env={"TMPDIR": str(tmp_path / "tmp"), "XDG_CACHE_HOME": str(tmp_path / "cache")},
        arguments=("-m", "pg"),
        log_path=tmp_path / "marked.log",
        minimum_tests=len(required),
        required_nodes=required,
    )


def test_pg_required_node_cannot_be_replaced_by_unrelated_tests_even_if_count_is_sufficient(
    tmp_path, monkeypatch
):
    with pytest.raises(ReleaseOperationError, match="required.*missing"):
        _run_population_fixture(
            tmp_path,
            monkeypatch,
            '<testcase classname="tests.test_a" name="one"/>'
            '<testcase classname="tests.test_extra" name="replacement"/>',
            required=("tests.test_a::one", "tests.test_a::two"),
        )


def test_pg_required_nodes_allow_additions_and_record_expected_manifest(tmp_path, monkeypatch):
    import json
    import xml.etree.ElementTree as ET

    from quant_system.ops.postgres_population import REQUIRED_PG_MARKED_NODES

    # Use the exact JUnit namespace of all 238 real required nodes, including
    # parametrized SQL/JSON IDs. These are synthetic test outcomes, not a PG run.
    cases = []
    for node in REQUIRED_PG_MARKED_NODES:
        classname, name = node.split("::", 1)
        cases.append(
            ET.tostring(ET.Element("testcase", classname=classname, name=name), encoding="unicode")
        )
    cases.append('<testcase classname="tests.test_extra" name="extra"/>')
    result = _run_population_fixture(
        tmp_path, monkeypatch, "".join(cases), required=REQUIRED_PG_MARKED_NODES
    )
    expected = json.loads(Path(result["required_manifest_path"]).read_text())
    assert expected["required_node_ids"] == list(REQUIRED_PG_MARKED_NODES)
    assert expected["minimum_tests"] == 238
    assert result["required_coverage"]["extra_nodes"] == ["tests.test_extra::extra"]


def test_duplicate_required_manifest_is_invalid(tmp_path, monkeypatch):
    with pytest.raises(ReleaseOperationError, match="required.*duplicat"):
        _run_population_fixture(
            tmp_path,
            monkeypatch,
            '<testcase classname="tests.test_a" name="one"/>',
            required=("tests.test_a::one", "tests.test_a::one"),
        )


@pytest.mark.parametrize("outcome", ["failure", "error", "skipped", 'skipped type="pytest.xfail"'])
def test_required_nodes_keep_zero_failure_and_skip_policy(tmp_path, monkeypatch, outcome):
    with pytest.raises(ReleaseOperationError, match="unexpected outcomes"):
        _run_population_fixture(
            tmp_path,
            monkeypatch,
            f'<testcase classname="tests.test_a" name="one"><{outcome}/></testcase>',
            required=("tests.test_a::one",),
        )


def test_required_nodes_keep_xpass_rejection(tmp_path, monkeypatch):
    with pytest.raises(ReleaseOperationError, match="unexpected xpass"):
        _run_population_fixture(
            tmp_path,
            monkeypatch,
            '<testcase classname="tests.test_a" name="one"/>',
            required=("tests.test_a::one",),
            stdout=b"XPASS",
        )


def write_junit(path: Path, cases: str) -> None:
    path.write_text(
        f'<?xml version="1.0" encoding="utf-8"?>'
        f"<testsuites><testsuite>{cases}</testsuite></testsuites>",
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


def test_pg_environment_forwards_only_explicit_verified_hqa_checkout(tmp_path, monkeypatch):
    hqa = tmp_path / "hqa-checkout"
    (hqa / "hqa").mkdir(parents=True)
    (hqa / "scripts").mkdir()
    (hqa / "hqa/chat_research_cli.py").write_text("# sealed path probe\n")
    (hqa / "scripts/install.sh").write_text("# sealed path probe\n")
    monkeypatch.setenv("QS_TEST_HQA_ROOT", str(hqa))
    monkeypatch.setenv("OPENAI_API_KEY", "not-forwarded")
    monkeypatch.setenv("GROK_API_KEY", "not-forwarded")
    monkeypatch.setenv("QS_DATABASE_URL", "not-forwarded")
    env = _safe_test_environment(
        repository_root=tmp_path,
        database_url="postgresql://127.0.0.1/agent_v02_test_tmp",
        process_root=tmp_path / "process",
    )
    assert env["QS_TEST_HQA_ROOT"] == str(hqa.resolve())
    assert not {"OPENAI_API_KEY", "GROK_API_KEY", "QS_DATABASE_URL"}.intersection(env)
    assert env["QS_TEST_DATABASE_URL"] == "postgresql://127.0.0.1/agent_v02_test_tmp"
    monkeypatch.delenv("QS_TEST_HQA_ROOT")
    without_override = _safe_test_environment(
        repository_root=tmp_path,
        database_url="postgresql://127.0.0.1/agent_v02_test_tmp",
        process_root=tmp_path / "process",
    )
    assert "QS_TEST_HQA_ROOT" not in without_override


@pytest.mark.parametrize("path_kind", ["relative", "missing"])
def test_pg_environment_rejects_invalid_explicit_hqa_path(tmp_path, monkeypatch, path_kind):
    value = "relative-hqa" if path_kind == "relative" else str(tmp_path / "missing-hqa")
    monkeypatch.setenv("QS_TEST_HQA_ROOT", value)
    with pytest.raises(ReleaseOperationError, match="HQA test checkout"):
        _safe_test_environment(
            repository_root=tmp_path,
            database_url="postgresql://127.0.0.1/agent_v02_test_tmp",
            process_root=tmp_path / "process",
        )
