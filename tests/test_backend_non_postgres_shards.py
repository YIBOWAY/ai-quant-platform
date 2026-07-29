from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "backend_non_postgres_gate.py"
EXPECTED_INNER_SANDBOX_NODE_IDS = (
    "tests/test_agent_v02_release_ops_restart_zero.py::"
    "test_zero_effect_crash_after_route_leaves_claim_and_retry_never_routes",
    "tests/test_agent_v02_release_ops_restart_zero.py::"
    "test_zero_effect_concurrent_same_id_routes_exactly_once",
    "tests/test_agent_v02_release_ops_restart_zero.py::"
    "test_zero_effect_postflight_rejects_repository_or_runtime_drift_without_receipt[platform]",
    "tests/test_agent_v02_release_ops_restart_zero.py::"
    "test_zero_effect_postflight_rejects_repository_or_runtime_drift_without_receipt[hqa]",
    "tests/test_agent_v02_release_ops_restart_zero.py::"
    "test_zero_effect_postflight_rejects_repository_or_runtime_drift_without_receipt"
    "[platform_runtime]",
    "tests/test_agent_v02_release_ops_restart_zero.py::"
    "test_zero_effect_changed_same_id_request_fails_closed_without_route",
    "tests/test_agent_v02_zero_effect_hardening.py::"
    "test_zero_effect_real_route_runs_in_confined_child_and_replays",
    "tests/test_agent_v02_zero_effect_hardening.py::"
    "test_zero_effect_cross_state_directories_have_distinct_idempotency_identity",
    "tests/test_agent_v02_zero_effect_hardening.py::"
    "test_zero_effect_real_sigkill_after_route_never_retries",
    "tests/test_agent_v02_zero_effect_hardening.py::"
    "test_zero_effect_receipt_fsync_mutation_prevents_authoritative_seal",
    "tests/test_agent_v02_zero_effect_hardening.py::"
    "test_zero_effect_concurrent_processes_execute_real_route_exactly_once",
    "tests/test_agent_v02_zero_effect_hardening.py::"
    "test_zero_effect_postflight_drift_fails_before_receipt",
    "tests/test_agent_v02_zero_effect_hardening.py::"
    "test_zero_effect_changed_same_identity_request_fails_before_observation",
)


def _gate_helper():
    spec = importlib.util.spec_from_file_location(
        "backend_non_postgres_gate_shard_repairs",
        HELPER,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_inner_sandbox_partition_is_exact_and_disjoint() -> None:
    helper = _gate_helper()
    collected = (
        "tests/test_before.py::test_before",
        *EXPECTED_INNER_SANDBOX_NODE_IDS,
        "tests/test_after.py::test_after",
    )

    general, inner = helper.partition_collected_node_ids(
        collected,
        helper.INNER_SANDBOX_NODE_IDS,
    )

    assert helper.INNER_SANDBOX_NODE_IDS == EXPECTED_INNER_SANDBOX_NODE_IDS
    assert general == (
        "tests/test_before.py::test_before",
        "tests/test_after.py::test_after",
    )
    assert inner == EXPECTED_INNER_SANDBOX_NODE_IDS
    assert set(general).isdisjoint(inner)
    assert set(general) | set(inner) == set(collected)


def test_collection_parser_requires_one_exact_unique_nodeid_document() -> None:
    helper = _gate_helper()
    node_ids = (
        "tests/test_one.py::test_one",
        "tests/test_two.py::test_two[value]",
    )
    output = (
        "pytest collection prelude\n"
        f"{helper.COLLECTION_PREFIX}{json.dumps(node_ids)}\n"
        "2 tests collected\n"
    ).encode()

    assert helper.parse_collected_node_ids(output) == node_ids

    for invalid_output in (
        b"2 tests collected\n",
        (
            f"{helper.COLLECTION_PREFIX}{json.dumps(node_ids)}\n"
            f"{helper.COLLECTION_PREFIX}{json.dumps(node_ids)}\n"
        ).encode(),
        f"{helper.COLLECTION_PREFIX}{json.dumps((node_ids[0], node_ids[0]))}\n".encode(),
        f"{helper.COLLECTION_PREFIX}{json.dumps(('outside.py::test_one',))}\n".encode(),
    ):
        with pytest.raises(helper.GateError, match="pytest_collection_invalid"):
            helper.parse_collected_node_ids(invalid_output)


def test_inner_shard_launcher_denies_parent_inet_sockets(tmp_path: Path) -> None:
    helper = _gate_helper()
    socket_test = tmp_path / "test_socket_guard.py"
    socket_test.write_text(
        """
import socket

import pytest


def test_inet_socket_is_denied():
    with pytest.raises(PermissionError, match="Gate 2 inner shard"):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("127.0.0.1", 9))
""".lstrip(),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            helper.INNER_SHARD_SOURCE,
            "-q",
            "-p",
            "no:cacheprovider",
            str(socket_test),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout


def test_inner_shard_launcher_ignores_ambient_pytest_addopts(tmp_path: Path) -> None:
    helper = _gate_helper()
    selected_test = tmp_path / "test_selected.py"
    selected_test.write_text(
        """
def test_selected():
    assert True
""".lstrip(),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            helper.INNER_SHARD_SOURCE,
            "-q",
            "-p",
            "no:cacheprovider",
            str(selected_test),
        ],
        cwd=ROOT,
        env={
            **os.environ,
            "PYTEST_ADDOPTS": "-k ambient_selector_would_drop_test",
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "1 passed" in completed.stdout


def test_collection_launcher_reports_exact_selected_nodeids() -> None:
    helper = _gate_helper()
    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-B",
            "-c",
            helper.COLLECTION_SOURCE,
            "--collect-only",
            "-q",
            "--strict-config",
            "--strict-markers",
            "-p",
            "no:cacheprovider",
            "-m",
            "not pg and not futu_opend and not provider and not network",
            "tests/test_agent_v02_release_ops_restart_zero.py",
            "tests/test_agent_v02_zero_effect_hardening.py",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
    )

    assert completed.returncode == 0, completed.stdout + completed.stderr
    collected = helper.parse_collected_node_ids(completed.stdout)
    assert len(collected) == 34
    assert set(EXPECTED_INNER_SANDBOX_NODE_IDS).issubset(collected)


def test_shard_commands_apply_only_one_macos_sandbox_layer(tmp_path: Path) -> None:
    helper = _gate_helper()
    sandbox_exec = Path("/usr/bin/sandbox-exec")
    python = tmp_path / "venv" / "bin" / "python"
    transient_paths = helper._transient_paths(tmp_path / "runtime")
    output = tmp_path / "evidence"

    commands = helper.build_pytest_shard_commands(
        sandbox_exec=sandbox_exec,
        python=python,
        transient_paths=transient_paths,
        output=output,
        marker_expression="not pg and not futu_opend and not provider and not network",
        inner_sandbox_node_ids=EXPECTED_INNER_SANDBOX_NODE_IDS,
    )

    assert commands["collection"][:3] == (
        str(sandbox_exec),
        "-p",
        helper.SANDBOX_PROFILE,
    )
    assert commands["general"][:3] == commands["collection"][:3]
    assert str(sandbox_exec) not in commands["inner_sandbox"]
    assert helper.INNER_SHARD_SOURCE in commands["inner_sandbox"]
    assert {
        argument.removeprefix("--deselect=")
        for argument in commands["general"]
        if argument.startswith("--deselect=")
    } == set(EXPECTED_INNER_SANDBOX_NODE_IDS)
    assert all(
        node_id in commands["inner_sandbox"]
        for node_id in EXPECTED_INNER_SANDBOX_NODE_IDS
    )
    assert commands["general"][-1] == (
        f"--junitxml={output / 'pytest-backend-non-postgres.junit.xml'}"
    )
    assert commands["inner_sandbox"][-1] == (
        f"--junitxml={output / 'pytest-backend-non-postgres-inner-sandbox.junit.xml'}"
    )


def test_combined_shard_result_requires_exact_collection_counts() -> None:
    helper = _gate_helper()
    collected = (
        "tests/test_general.py::test_general",
        EXPECTED_INNER_SANDBOX_NODE_IDS[0],
    )
    general, inner = helper.partition_collected_node_ids(
        collected,
        (EXPECTED_INNER_SANDBOX_NODE_IDS[0],),
    )
    general_result = {
        "failed": 0,
        "passed": 1,
        "skipped": 0,
        "skip_node_ids": [],
        "total": 1,
    }
    inner_result = {
        "failed": 0,
        "passed": 1,
        "skipped": 0,
        "skip_node_ids": [],
        "total": 1,
    }

    combined = helper.combine_shard_results(
        collected_node_ids=collected,
        general_node_ids=general,
        inner_sandbox_node_ids=inner,
        general_result=general_result,
        inner_sandbox_result=inner_result,
    )

    assert combined == {
        "failed": 0,
        "passed": 2,
        "skipped": 0,
        "skip_node_ids": [],
        "total": 2,
    }

    with pytest.raises(helper.GateError, match="pytest_shard_count_mismatch"):
        helper.combine_shard_results(
            collected_node_ids=collected,
            general_node_ids=general,
            inner_sandbox_node_ids=inner,
            general_result={**general_result, "total": 2, "passed": 2},
            inner_sandbox_result=inner_result,
        )
