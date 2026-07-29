#!/usr/bin/env python3
"""Fail-closed orchestration for the Platform non-PostgreSQL backend gate."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tomllib
import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

CONTRACT = "quant-system-backend-non-postgres/v1"
MARKER_EXPRESSION = "not pg and not futu_opend and not provider and not network"
EXPECTED_BRANCH = "codex/agent-v0-2-release"
PUBLICATION_REMOTE = "github"
PUBLICATION_REMOTE_URL = "https://github.com/YIBOWAY/ai-quant-platform.git"
SANDBOX_EXEC = Path("/usr/bin/sandbox-exec")
SANDBOX_PROFILE = "(version 1) (allow default) (deny network*)"
_COMMIT = re.compile(r"^[0-9a-f]{40,64}$")
_FORBIDDEN_XML_DECLARATION = re.compile(r"<!\s*(?:DOCTYPE|ENTITY)", re.IGNORECASE)
_XML_ENCODING = re.compile(
    r"<\?xml\b[^>]*\bencoding\s*=\s*(['\"])([^'\"]+)\1",
    re.IGNORECASE,
)
_MAX_JUNIT_BYTES = 16 * 1024 * 1024
COLLECTION_PREFIX = "GATE2_COLLECTION_NODE_IDS="
COLLECTION_SOURCE = f"""
import json
import sys

import pytest


class ExactCollection:
    def pytest_collection_finish(self, session):
        node_ids = [item.nodeid for item in session.items]
        sys.stdout.write(
            {COLLECTION_PREFIX!r}
            + json.dumps(
                node_ids,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
            )
            + "\\n"
        )
        sys.stdout.flush()


raise SystemExit(pytest.main(["-s", *sys.argv[1:]], plugins=[ExactCollection()]))
"""
INNER_SANDBOX_NODE_IDS = (
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
_NETWORK_DENIAL_SOURCE = r"""
import errno
import socket
import sys

try:
    probe = socket.socket()
    probe.settimeout(0.2)
    probe.connect(("127.0.0.1", 9))
except OSError as exc:
    raise SystemExit(0 if exc.errno in {errno.EACCES, errno.EPERM} else 2)
raise SystemExit(3)
"""
INNER_SHARD_SOURCE = r"""
import socket
import sys


def deny_inet_socket(event, arguments):
    if event not in {"socket.bind", "socket.connect", "socket.sendto"}:
        return
    candidate = arguments[0] if arguments else None
    if getattr(candidate, "family", None) in {socket.AF_INET, socket.AF_INET6}:
        raise PermissionError("Gate 2 inner shard denies INET sockets")


sys.addaudithook(deny_inet_socket)

import pytest

raise SystemExit(pytest.main(sys.argv[1:]))
"""
_PROBE_SOURCE = r"""
import hashlib
import importlib.metadata
import json
import pathlib
import site
import sys

package = __import__("quant_system")
distribution = importlib.metadata.distribution("quant-system")
direct_url_text = distribution.read_text("direct_url.json")
direct_url = json.loads(direct_url_text) if direct_url_text else None
site_paths = [pathlib.Path(value).resolve() for value in site.getsitepackages()]
pth_files = []
for site_path in site_paths:
    for path in sorted(site_path.glob("*.pth")):
        content = path.read_bytes()
        pth_files.append(
            {
                "path": str(path.resolve()),
                "sha256": hashlib.sha256(content).hexdigest(),
                "size_bytes": len(content),
            }
        )
print(
    json.dumps(
        {
            "base_prefix": str(pathlib.Path(sys.base_prefix).resolve()),
            "direct_url": direct_url,
            "distribution_version": distribution.version,
            "prefix": str(pathlib.Path(sys.prefix).resolve()),
            "pth_files": pth_files,
            "quant_system_file": str(pathlib.Path(package.__file__).resolve()),
            "site_packages": [str(value) for value in site_paths],
            "sys_executable": str(pathlib.Path(sys.executable).absolute()),
            "sys_executable_realpath": str(pathlib.Path(sys.executable).resolve()),
            "sys_path": list(sys.path),
            "version": sys.version,
            "version_info": list(sys.version_info[:3]),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
)
"""


class GateError(RuntimeError):
    """The Gate 2 verification contract was not satisfied."""


def _utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _sha256_file(path: Path) -> str:
    info = path.lstat()
    if not stat.S_ISREG(info.st_mode) or stat.S_ISLNK(info.st_mode):
        raise GateError(f"not_regular_file:{path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(128 * 1024), b""):
            digest.update(block)
    after = path.lstat()
    if (
        info.st_dev,
        info.st_ino,
        info.st_size,
        info.st_mtime_ns,
    ) != (
        after.st_dev,
        after.st_ino,
        after.st_size,
        after.st_mtime_ns,
    ):
        raise GateError(f"file_changed_while_hashing:{path.name}")
    return digest.hexdigest()


def _artifact(path: Path) -> dict[str, object]:
    content = path.read_bytes()
    return {
        "path": path.name,
        "sha256": _sha256(content),
        "size_bytes": len(content),
    }


def _write_exclusive(path: Path, content: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    descriptor = -1
    try:
        descriptor = os.open(path, flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            descriptor = -1
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        raise GateError(f"artifact_write_failed:{path.name}") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)


def _canonical_json(document: object) -> bytes:
    return json.dumps(
        document,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _require_helper_path(root: Path) -> dict[str, str]:
    actual = Path(__file__).resolve()
    expected = root / "scripts" / "backend_non_postgres_gate.py"
    if actual != expected:
        raise GateError("helper_path_mismatch")
    return {
        "actual_path": str(actual),
        "expected_path": str(expected),
    }


def _require_public_entrypoint(root: Path, public_entrypoint: str) -> dict[str, str]:
    expected = root / "scripts" / "verify_backend_non_postgres.sh"
    resolved = Path(public_entrypoint).resolve()
    if (
        resolved != expected
        or not expected.is_file()
        or expected.is_symlink()
    ):
        raise GateError("public_entrypoint_mismatch")
    return {
        "argument": public_entrypoint,
        "expected_path": str(expected),
        "resolved_path": str(resolved),
    }


def _load_repository_contract(root: Path) -> tuple[str, tuple[str, ...]]:
    try:
        document = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        table = document["tool"]["quant_system"]["release"]["backend_non_postgres"]
    except (KeyError, OSError, tomllib.TOMLDecodeError, TypeError) as exc:
        raise GateError("repository_contract_invalid") from exc
    if not isinstance(table, dict) or set(table) != {
        "expected_skip_node_ids",
        "marker_expression",
        "python",
    }:
        raise GateError("repository_contract_invalid")
    python = table["python"]
    expression = table["marker_expression"]
    expected = table["expected_skip_node_ids"]
    if (
        python != "3.11"
        or expression != MARKER_EXPRESSION
        or not isinstance(expected, list)
        or any(not isinstance(value, str) or not value for value in expected)
        or len(set(expected)) != len(expected)
    ):
        raise GateError("repository_contract_invalid")
    return expression, tuple(expected)


def describe_contract(
    marker_expression: str,
    expected_skip_node_ids: tuple[str, ...],
) -> dict[str, object]:
    return {
        "artifact_policy": {
            "evidence_output": "sealed-files-only",
            "recursive_cleanup_by_runner": False,
            "transient_root": "checkout/.tmp",
        },
        "branch": EXPECTED_BRANCH,
        "contract": CONTRACT,
        "entrypoint": "scripts/verify_backend_non_postgres.sh",
        "expected_commit_required": True,
        "expected_skip_node_ids": list(expected_skip_node_ids),
        "install": {
            "all_extras": True,
            "environment_location": "checkout",
            "frozen": True,
            "no_editable": True,
            "runner": "uv",
        },
        "python": "3.11",
        "publication_remote": {
            "name": PUBLICATION_REMOTE,
            "url": PUBLICATION_REMOTE_URL,
        },
        "sanitized_environment": {
            "QS_DATABASE_AUTO_MIGRATE": "false",
            "QS_DATABASE_ENABLED": "false",
            "QS_DEFAULT_DATA_PROVIDER": "sample",
            "QS_FUTU_ENABLED": "false",
            "QS_KILL_SWITCH": "true",
            "QS_LIVE_TRADING_ENABLED": "false",
            "QS_TEST_FUTU_OPEND": "0",
            "strategy": "allowlist",
        },
        "suite": {
            "junit_required": True,
            "marker_expression": marker_expression,
            "nonzero_collection_required": True,
            "selector": "tests",
            "strict_markers": True,
            "unexpected_skips_fail": True,
        },
    }


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _skip_node_id(testcase: ET.Element) -> str:
    classname = testcase.attrib.get("classname", "")
    name = testcase.attrib.get("name", "")
    if not classname or not name:
        raise GateError("skipped_testcase_identity_invalid")
    return f"{classname.replace('.', '/')}.py::{name}"


def _declared_count(element: ET.Element, field: str) -> int | None:
    value = element.get(field)
    if value is None:
        return None
    if not value.isascii() or not value.isdigit():
        raise GateError("junit_declared_count_invalid")
    return int(value)


def validate_junit(
    content: bytes,
    *,
    pytest_exit: int,
    expected_skip_node_ids: tuple[str, ...],
) -> dict[str, object]:
    if pytest_exit != 0:
        raise GateError(f"pytest_exit_nonzero:{pytest_exit}")
    if not content or len(content) > _MAX_JUNIT_BYTES:
        raise GateError("junit_empty_or_oversized")
    try:
        xml_text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise GateError("junit_not_utf8") from exc
    if "\x00" in xml_text or _FORBIDDEN_XML_DECLARATION.search(xml_text):
        raise GateError("junit_forbidden_xml")
    encoding = _XML_ENCODING.search(xml_text[:512])
    if encoding is not None and encoding.group(2).lower() not in {"utf-8", "utf8"}:
        raise GateError("junit_not_utf8")
    try:
        root = ET.fromstring(xml_text)
    except (ET.ParseError, ValueError) as exc:
        raise GateError("junit_malformed") from exc
    if _local_name(root.tag) not in {"testsuite", "testsuites"}:
        raise GateError("junit_root_invalid")

    testcases = [
        element for element in root.iter() if _local_name(element.tag) == "testcase"
    ]
    if not testcases:
        raise GateError("junit_zero_collection")

    failures = 0
    errors = 0
    skipped: list[str] = []
    for testcase in testcases:
        outcomes = [
            _local_name(child.tag)
            for child in testcase
            if _local_name(child.tag) in {"error", "failure", "skipped"}
        ]
        if len(outcomes) > 1:
            raise GateError("junit_conflicting_testcase_outcomes")
        outcome = outcomes[0] if outcomes else ""
        failures += int(outcome == "failure")
        errors += int(outcome == "error")
        if outcome == "skipped":
            skipped.append(_skip_node_id(testcase))
        for field, expected_value in {
            "errors": int(outcome == "error"),
            "failures": int(outcome == "failure"),
            "skipped": int(outcome == "skipped"),
        }.items():
            declared = _declared_count(testcase, field)
            if declared is not None and declared != expected_value:
                raise GateError("junit_testcase_count_drift")

    containers = [root]
    containers.extend(
        element
        for element in root.iter()
        if element is not root and _local_name(element.tag) == "testsuite"
    )
    for container in containers:
        descendants = [
            element
            for element in container.iter()
            if _local_name(element.tag) == "testcase"
        ]
        descendant_outcomes = [
            {
                _local_name(child.tag)
                for child in testcase
                if _local_name(child.tag) in {"error", "failure", "skipped"}
            }
            for testcase in descendants
        ]
        expected_counts = {
            "errors": sum(int("error" in outcome) for outcome in descendant_outcomes),
            "failures": sum(int("failure" in outcome) for outcome in descendant_outcomes),
            "skipped": sum(int("skipped" in outcome) for outcome in descendant_outcomes),
            "tests": len(descendants),
        }
        for field, expected_value in expected_counts.items():
            declared = _declared_count(container, field)
            if declared is not None and declared != expected_value:
                raise GateError("junit_container_count_drift")

    expected_skips = sorted(expected_skip_node_ids)
    observed_skips = sorted(skipped)
    if observed_skips != expected_skips:
        raise GateError("junit_skip_set_not_declared")
    failed = failures + errors
    if failed:
        raise GateError(f"junit_failed_testcases:{failed}")
    return {
        "failed": failed,
        "passed": len(testcases) - failed - len(skipped),
        "skipped": len(skipped),
        "skip_node_ids": observed_skips,
        "total": len(testcases),
    }


def partition_collected_node_ids(
    collected_node_ids: tuple[str, ...],
    inner_sandbox_node_ids: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if (
        not collected_node_ids
        or len(set(collected_node_ids)) != len(collected_node_ids)
        or any(
            not node_id.startswith("tests/") or "::" not in node_id
            for node_id in collected_node_ids
        )
    ):
        raise GateError("pytest_collection_invalid")
    if (
        not inner_sandbox_node_ids
        or len(set(inner_sandbox_node_ids)) != len(inner_sandbox_node_ids)
        or any(
            not node_id.startswith("tests/") or "::" not in node_id
            for node_id in inner_sandbox_node_ids
        )
    ):
        raise GateError("pytest_inner_sandbox_partition_invalid")
    collected_set = set(collected_node_ids)
    inner_set = set(inner_sandbox_node_ids)
    if not inner_set.issubset(collected_set):
        raise GateError("pytest_inner_sandbox_node_missing")
    general = tuple(
        node_id for node_id in collected_node_ids if node_id not in inner_set
    )
    if (
        not general
        or set(general) & inner_set
        or set(general) | inner_set != collected_set
        or len(general) + len(inner_sandbox_node_ids) != len(collected_node_ids)
    ):
        raise GateError("pytest_partition_not_exact")
    return general, inner_sandbox_node_ids


def parse_collected_node_ids(content: bytes) -> tuple[str, ...]:
    try:
        lines = content.decode("utf-8").splitlines()
    except UnicodeDecodeError as exc:
        raise GateError("pytest_collection_invalid") from exc
    documents = [
        line.removeprefix(COLLECTION_PREFIX)
        for line in lines
        if line.startswith(COLLECTION_PREFIX)
    ]
    if len(documents) != 1:
        raise GateError("pytest_collection_invalid")
    try:
        document = _strict_json(documents[0].encode("utf-8"))
    except GateError as exc:
        raise GateError("pytest_collection_invalid") from exc
    if (
        not isinstance(document, list)
        or not document
        or any(
            not isinstance(node_id, str)
            or not node_id.startswith("tests/")
            or "::" not in node_id
            for node_id in document
        )
        or len(set(document)) != len(document)
    ):
        raise GateError("pytest_collection_invalid")
    return tuple(document)


def build_pytest_shard_commands(
    *,
    sandbox_exec: Path,
    python: Path,
    transient_paths: dict[str, Path],
    output: Path,
    marker_expression: str,
    inner_sandbox_node_ids: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    outer_sandbox = (str(sandbox_exec), "-p", SANDBOX_PROFILE)
    common_pytest = (
        "-q",
        "-rA",
        "--strict-config",
        "--strict-markers",
        "-p",
        "no:cacheprovider",
        "-m",
        marker_expression,
    )
    collection = (
        *outer_sandbox,
        str(python),
        "-I",
        "-B",
        "-c",
        COLLECTION_SOURCE,
        "--collect-only",
        "-q",
        "--strict-config",
        "--strict-markers",
        "-p",
        "no:cacheprovider",
        "--basetemp",
        str(transient_paths["basetemp"] / "collection"),
        "-m",
        marker_expression,
        "tests",
    )
    general = (
        *outer_sandbox,
        str(python),
        "-I",
        "-B",
        "-m",
        "pytest",
        *common_pytest,
        "--basetemp",
        str(transient_paths["basetemp"] / "general"),
        *(f"--deselect={node_id}" for node_id in inner_sandbox_node_ids),
        "tests",
        f"--junitxml={output / 'pytest-backend-non-postgres.junit.xml'}",
    )
    inner_sandbox = (
        str(python),
        "-I",
        "-B",
        "-c",
        INNER_SHARD_SOURCE,
        *common_pytest,
        "--basetemp",
        str(transient_paths["basetemp"] / "inner-sandbox"),
        *inner_sandbox_node_ids,
        f"--junitxml={output / 'pytest-backend-non-postgres-inner-sandbox.junit.xml'}",
    )
    return {
        "collection": collection,
        "general": general,
        "inner_sandbox": inner_sandbox,
    }


def combine_shard_results(
    *,
    collected_node_ids: tuple[str, ...],
    general_node_ids: tuple[str, ...],
    inner_sandbox_node_ids: tuple[str, ...],
    general_result: dict[str, object],
    inner_sandbox_result: dict[str, object],
) -> dict[str, object]:
    if (
        set(general_node_ids) & set(inner_sandbox_node_ids)
        or set(general_node_ids) | set(inner_sandbox_node_ids)
        != set(collected_node_ids)
        or general_result.get("total") != len(general_node_ids)
        or inner_sandbox_result.get("total") != len(inner_sandbox_node_ids)
    ):
        raise GateError("pytest_shard_count_mismatch")
    combined = {
        field: int(general_result[field]) + int(inner_sandbox_result[field])
        for field in ("failed", "passed", "skipped", "total")
    }
    combined["skip_node_ids"] = sorted(
        [
            *general_result["skip_node_ids"],
            *inner_sandbox_result["skip_node_ids"],
        ]
    )
    if (
        combined["total"] != len(collected_node_ids)
        or combined["failed"] + combined["passed"] + combined["skipped"]
        != combined["total"]
    ):
        raise GateError("pytest_shard_count_mismatch")
    return combined


def _junit(*, outcome: str = "passed") -> bytes:
    child = "" if outcome == "passed" else f"<{outcome}/>"
    return (
        f'<testsuite tests="1" failures="{int(outcome == "failure")}" '
        f'errors="{int(outcome == "error")}" skipped="{int(outcome == "skipped")}">'
        '<testcase classname="tests.test_expected" name="test_declared">'
        f"{child}</testcase></testsuite>"
    ).encode()


def _require_sandbox_exec() -> Path:
    if (
        not SANDBOX_EXEC.is_file()
        or SANDBOX_EXEC.is_symlink()
        or not os.access(SANDBOX_EXEC, os.X_OK)
    ):
        raise GateError("network_sandbox_not_executable")
    return SANDBOX_EXEC


def run_self_test(root: Path) -> dict[str, object]:
    validate_junit(_junit(), pytest_exit=0, expected_skip_node_ids=())
    validate_junit(
        _junit(outcome="skipped"),
        pytest_exit=0,
        expected_skip_node_ids=("tests/test_expected.py::test_declared",),
    )

    rejected: dict[str, str] = {}
    for name, content, pytest_exit in (
        ("pytest_failure", _junit(), 1),
        ("undeclared_skip", _junit(outcome="skipped"), 0),
        ("zero_collection", b"<testsuite tests='0'/>", 0),
    ):
        try:
            validate_junit(
                content,
                pytest_exit=pytest_exit,
                expected_skip_node_ids=(),
            )
        except GateError:
            rejected[name] = "rejected"
        else:
            raise GateError(f"self_test_did_not_fail_closed:{name}")
    sandbox_exec = _require_sandbox_exec()
    sandbox = subprocess.run(
        (
            str(sandbox_exec),
            "-p",
            SANDBOX_PROFILE,
            sys.executable,
            "-I",
            "-B",
            "-c",
            _NETWORK_DENIAL_SOURCE,
        ),
        check=False,
        capture_output=True,
        env={
            "HOME": "/tmp",
            "LANG": "C",
            "LC_ALL": "C",
            "PATH": "/usr/bin:/bin",
            "PYTHONNOUSERSITE": "1",
            "TMPDIR": "/tmp",
        },
    )
    if sandbox.returncode != 0:
        raise GateError("network_sandbox_self_test_failed")
    synthetic_output = root.parent / "gate2-self-test-evidence"
    synthetic_runtime = _checkout_runtime_path(
        root=root,
        output=synthetic_output,
        commit="a" * 40,
    )
    transient_paths = _transient_paths(synthetic_runtime)
    if (
        root / ".tmp" not in synthetic_runtime.parents
        or synthetic_output == synthetic_runtime
        or synthetic_output in synthetic_runtime.parents
        or any(
            path != synthetic_runtime and synthetic_runtime not in path.parents
            for path in transient_paths.values()
        )
    ):
        raise GateError("transient_hygiene_self_test_failed")
    return {
        "cases": {
            "declared_skip": "accepted",
            "network_sandbox": "accepted",
            "nonzero_collection": "accepted",
            **rejected,
            "transient_hygiene": "accepted",
        },
        "contract": CONTRACT,
        "status": "ok",
    }


def _git_environment() -> dict[str, str]:
    return {
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "HOME": "/tmp",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }


def _git_argv(root: Path, *arguments: str) -> list[str]:
    return [
        "/usr/bin/git",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "credential.helper=",
        "-C",
        str(root),
        *arguments,
    ]


def _git_bytes(root: Path, *arguments: str, allow_empty: bool = False) -> bytes:
    completed = subprocess.run(
        _git_argv(root, *arguments),
        check=False,
        capture_output=True,
        env=_git_environment(),
    )
    if completed.returncode != 0 or (not allow_empty and not completed.stdout.strip()):
        raise GateError("git_identity_failed")
    return completed.stdout


def _git_text(root: Path, *arguments: str) -> str:
    return _git_bytes(root, *arguments).decode("utf-8", "strict").strip()


def _require_git_toplevel(root: Path) -> str:
    toplevel = Path(_git_text(root, "rev-parse", "--show-toplevel")).resolve()
    if toplevel != root:
        raise GateError("git_toplevel_mismatch")
    return str(toplevel)


def _git_quiet_clean(root: Path, *arguments: str) -> bool:
    completed = subprocess.run(
        _git_argv(root, *arguments),
        check=False,
        capture_output=True,
        env=_git_environment(),
    )
    if completed.returncode not in {0, 1} or completed.stdout or completed.stderr:
        raise GateError("git_diff_audit_failed")
    return completed.returncode == 0


def _tagged_ls_files(content: bytes) -> tuple[bytes, ...]:
    records = tuple(record for record in content.split(b"\0") if record)
    if not records or any(len(record) < 3 or record[1:2] != b" " for record in records):
        raise GateError("tracked_index_flags_invalid")
    return records


def _tracked_tree_audit(root: Path) -> dict[str, object]:
    verbose = _tagged_ls_files(_git_bytes(root, "ls-files", "-v", "-z"))
    tagged = _tagged_ls_files(_git_bytes(root, "ls-files", "-t", "-z"))
    if len(verbose) != len(tagged):
        raise GateError("tracked_index_flags_invalid")
    assume_unchanged = tuple(
        record for record in verbose if record[:1].decode("ascii").islower()
    )
    skip_worktree = tuple(
        record
        for record in (*verbose, *tagged)
        if record[:1] == b"S"
    )
    if assume_unchanged or skip_worktree:
        raise GateError("tracked_index_flags_hidden")
    unmerged = _git_bytes(root, "ls-files", "-u", "-z", allow_empty=True)
    if unmerged:
        raise GateError("tracked_index_conflicts")
    index_matches_head = _git_quiet_clean(
        root,
        "diff-index",
        "--quiet",
        "--cached",
        "--ignore-submodules=none",
        "HEAD",
        "--",
    )
    worktree_matches_index = _git_quiet_clean(
        root,
        "diff-files",
        "--quiet",
        "--ignore-submodules=none",
        "--",
    )
    return {
        "assume_unchanged_count": 0,
        "conflict_entry_count": 0,
        "index_matches_head": index_matches_head,
        "ls_files_flags_sha256": _sha256(
            b"verbose\0" + b"\0".join(verbose) + b"\0tagged\0" + b"\0".join(tagged)
        ),
        "skip_worktree_count": 0,
        "tracked_path_count": len(verbose),
        "worktree_matches_index": worktree_matches_index,
    }


def _git_identity(root: Path) -> dict[str, object]:
    git_toplevel = _require_git_toplevel(root)
    tracked_tree = _tracked_tree_audit(root)
    status = _git_bytes(
        root,
        "status",
        "--porcelain=v1",
        "-z",
        "--untracked-files=all",
        allow_empty=True,
    )
    tracked_clean = bool(
        tracked_tree["index_matches_head"]
        and tracked_tree["worktree_matches_index"]
    )
    return {
        "branch": _git_text(root, "symbolic-ref", "--short", "HEAD"),
        "clean": status == b"" and tracked_clean,
        "clean_status_sha256": _sha256(status),
        "commit": _git_text(root, "rev-parse", "--verify", "HEAD"),
        "git_toplevel": git_toplevel,
        "publication_remote": PUBLICATION_REMOTE,
        "publication_remote_url": _git_text(
            root,
            "remote",
            "get-url",
            PUBLICATION_REMOTE,
        ),
        "root": str(root),
        "tracked_tree": tracked_tree,
        "tree": _git_text(root, "rev-parse", "--verify", "HEAD^{tree}"),
    }


def _require_expected_commit(root: Path, expected_commit: str | None) -> dict[str, object]:
    if expected_commit is None or _COMMIT.fullmatch(expected_commit) is None:
        raise GateError("expected_commit_invalid")
    if _git_text(root, "rev-parse", "--verify", "HEAD") != expected_commit:
        raise GateError("expected_commit_mismatch")
    identity = _git_identity(root)
    if identity["branch"] != EXPECTED_BRANCH:
        raise GateError("expected_branch_mismatch")
    if identity["publication_remote_url"] != PUBLICATION_REMOTE_URL:
        raise GateError("publication_remote_mismatch")
    if not identity["clean"]:
        raise GateError("checkout_not_clean")
    return identity


def _has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current /= component
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode):
            return True
    return False


def _prepare_output(path: Path, *, root: Path) -> Path:
    if not path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts[1:]):
        raise GateError("output_dir_not_canonical")
    if _has_symlink_component(path):
        raise GateError("output_dir_has_symlink_component")
    resolved = path.resolve()
    if resolved == root or root in resolved.parents:
        raise GateError("output_dir_inside_checkout")
    parent = resolved.parent
    try:
        parent_info = parent.lstat()
    except FileNotFoundError as exc:
        raise GateError("output_dir_parent_missing") from exc
    if (
        not stat.S_ISDIR(parent_info.st_mode)
        or stat.S_ISLNK(parent_info.st_mode)
        or parent_info.st_uid != os.getuid()
        or stat.S_IMODE(parent_info.st_mode) & 0o022
    ):
        raise GateError("output_dir_parent_unsafe")
    try:
        if resolved.exists():
            info = resolved.lstat()
            if (
                not stat.S_ISDIR(info.st_mode)
                or stat.S_ISLNK(info.st_mode)
                or info.st_uid != os.getuid()
                or stat.S_IMODE(info.st_mode) != 0o700
                or any(resolved.iterdir())
            ):
                raise GateError("output_dir_not_empty_private")
        else:
            resolved.mkdir(mode=0o700)
            resolved.chmod(0o700)
    except OSError as exc:
        raise GateError("output_dir_create_failed") from exc
    return resolved


def _private_directory(path: Path) -> Path:
    try:
        path.mkdir(mode=0o700)
    except OSError as exc:
        raise GateError(f"private_directory_create_failed:{path.name}") from exc
    return path


def _checkout_runtime_path(
    *,
    root: Path,
    output: Path,
    commit: str,
) -> Path:
    run_digest = _sha256(f"{commit}\0{output}".encode())[:16]
    return root / ".tmp" / f"backend-non-postgres-{commit[:12]}-{run_digest}"


def _transient_paths(runtime_root: Path) -> dict[str, Path]:
    return {
        "basetemp": runtime_root / "basetemp",
        "home": runtime_root / "home",
        "pycache": runtime_root / "pycache",
        "sandbox_agent_data": runtime_root / "sandbox-agent-data",
        "sandbox_data": runtime_root / "sandbox-data",
        "tmp": runtime_root / "tmp",
        "uv_cache": runtime_root / "uv-cache",
        "venv": runtime_root / "venv",
    }


def _fresh_checkout_runtime(
    *,
    root: Path,
    output: Path,
    commit: str,
) -> tuple[Path, dict[str, Path]]:
    environment_parent = root / ".tmp"
    if environment_parent.exists():
        info = environment_parent.lstat()
        if (
            not stat.S_ISDIR(info.st_mode)
            or stat.S_ISLNK(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) & 0o022
        ):
            raise GateError("checkout_environment_parent_unsafe")
    else:
        environment_parent.mkdir(mode=0o700)
    runtime_root = _checkout_runtime_path(
        root=root,
        output=output,
        commit=commit,
    )
    if runtime_root.exists() or runtime_root.is_symlink():
        raise GateError("checkout_runtime_not_fresh")
    runtime_root.mkdir(mode=0o700)
    runtime_root.chmod(0o700)
    paths = _transient_paths(runtime_root)
    for name, path in paths.items():
        if name != "venv":
            _private_directory(path)
    return runtime_root, paths


def _run_logged(
    *,
    argv: tuple[str, ...],
    cwd: Path,
    env: dict[str, str],
    output: Path,
    name: str,
) -> tuple[subprocess.CompletedProcess[bytes], dict[str, object]]:
    started_at = _utc_now()
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
    )
    completed_at = _utc_now()
    stdout_path = output / f"{name}.stdout.log"
    stderr_path = output / f"{name}.stderr.log"
    _write_exclusive(stdout_path, completed.stdout)
    _write_exclusive(stderr_path, completed.stderr)
    return completed, {
        "argv": list(argv),
        "completed_at": completed_at,
        "exit_code": completed.returncode,
        "started_at": started_at,
        "stderr": _artifact(stderr_path),
        "stdout": _artifact(stdout_path),
        "stdout_stderr_sha256": _sha256(completed.stdout + b"\0" + completed.stderr),
    }


def _strict_json(content: bytes) -> object:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        document: dict[str, object] = {}
        for key, value in pairs:
            if key in document:
                raise GateError("python_probe_duplicate_json_key")
            document[key] = value
        return document

    def reject_constant(_value: str) -> object:
        raise GateError("python_probe_nonfinite_json")

    try:
        return json.loads(
            content.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except GateError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise GateError("python_probe_invalid_json") from exc


def _run_json_probe(
    *,
    argv: tuple[str, ...],
    cwd: Path,
    env: dict[str, str],
    output: Path,
    name: str,
) -> tuple[subprocess.CompletedProcess[bytes], dict[str, object]]:
    started_at = _utc_now()
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
    )
    completed_at = _utc_now()
    stderr_path = output / f"{name}.stderr.log"
    _write_exclusive(stderr_path, completed.stderr)
    return completed, {
        "argv": list(argv),
        "completed_at": completed_at,
        "exit_code": completed.returncode,
        "started_at": started_at,
        "stderr": _artifact(stderr_path),
        "stdout": {
            "embedded_in_receipt": True,
            "sha256": _sha256(completed.stdout),
            "size_bytes": len(completed.stdout),
        },
        "stdout_stderr_sha256": _sha256(completed.stdout + b"\0" + completed.stderr),
    }


def _uv_environment(
    transient_paths: dict[str, Path],
    uv: Path,
) -> dict[str, str]:
    return {
        "HOME": str(transient_paths["home"]),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": f"{uv.parent}:/usr/bin:/bin",
        "TMPDIR": str(transient_paths["tmp"]),
        "UV_CACHE_DIR": str(transient_paths["uv_cache"]),
        "UV_LINK_MODE": "copy",
        "UV_NO_CONFIG": "1",
        "UV_PROJECT_ENVIRONMENT": str(transient_paths["venv"]),
        "UV_PYTHON_DOWNLOADS": "never",
    }


def _test_environment(
    transient_paths: dict[str, Path],
    uv: Path,
    node: Path | None = None,
) -> dict[str, str]:
    venv = transient_paths["venv"]
    path_entries = (
        ([node.parent] if node is not None else [])
        + [venv / "bin", uv.parent, Path("/usr/bin"), Path("/bin")]
    )
    path_entries = list(dict.fromkeys(path_entries))
    return {
        "HOME": str(transient_paths["home"]),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": ":".join(str(path) for path in path_entries),
        "PYTHONNOUSERSITE": "1",
        "PYTHONPYCACHEPREFIX": str(transient_paths["pycache"]),
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "QS_AGENT_OUTPUT_DIR": str(transient_paths["sandbox_agent_data"]),
        "QS_DATABASE_AUTO_MIGRATE": "false",
        "QS_DATABASE_ENABLED": "false",
        "QS_DATA_DIR": str(transient_paths["sandbox_data"]),
        "QS_DRY_RUN": "true",
        "QS_KILL_SWITCH": "true",
        "QS_LIVE_TRADING_ENABLED": "false",
        "QS_LOCAL_MUTATION_ENABLED": "false",
        "QS_PAPER_ACCOUNT_DB_MODE": "file",
        "QS_PAPER_TRADING": "true",
        "QS_TEST_FUTU_OPEND": "0",
        "TMPDIR": str(transient_paths["tmp"]),
    }


def _validate_import_probe(document: object, *, root: Path, venv: Path) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise GateError("python_probe_invalid")
    required = {
        "base_prefix",
        "direct_url",
        "distribution_version",
        "prefix",
        "pth_files",
        "quant_system_file",
        "site_packages",
        "sys_executable",
        "sys_executable_realpath",
        "sys_path",
        "version",
        "version_info",
    }
    if set(document) != required or document["version_info"][:2] != [3, 11]:
        raise GateError("python_probe_invalid")
    prefix = Path(document["prefix"]).resolve()
    executable = Path(document["sys_executable"])
    import_path = Path(document["quant_system_file"]).resolve()
    venv_resolved = venv.resolve()
    source_root = (root / "src").resolve()
    if (
        prefix != venv_resolved
        or not executable.is_absolute()
        or venv_resolved not in executable.parents
        or venv_resolved not in import_path.parents
        or import_path == source_root
        or source_root in import_path.parents
    ):
        raise GateError("python_or_import_not_fresh_noneditable")
    direct_url = document["direct_url"]
    if (
        not isinstance(direct_url, dict)
        or direct_url.get("url") != root.as_uri()
        or not isinstance(direct_url.get("dir_info"), dict)
        or direct_url["dir_info"].get("editable", False) is not False
    ):
        raise GateError("noneditable_direct_url_invalid")
    document["direct_url_validation"] = {
        "editable": False,
        "expected_url": root.as_uri(),
    }
    root_text = str(root)
    for raw_path in document["sys_path"]:
        if raw_path and Path(raw_path).resolve() == source_root:
            raise GateError("source_checkout_on_sys_path")
    for item in document["pth_files"]:
        pth_path = Path(item["path"])
        if root_text.encode() in pth_path.read_bytes():
            raise GateError("checkout_path_in_pth")
    return document


def _input_identity(root: Path) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for relative in (
        "pyproject.toml",
        "uv.lock",
        "scripts/backend_non_postgres_gate.py",
        "scripts/verify_backend_non_postgres.sh",
    ):
        path = root / relative
        result[relative] = {
            "sha256": _sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    return result


def _write_receipt(output: Path, receipt: dict[str, object]) -> Path:
    path = output / "backend-non-postgres-receipt.json"
    _write_exclusive(path, _canonical_json(receipt))
    return path


def run_gate(
    *,
    root: Path,
    output_argument: Path,
    expected_commit: str | None,
    uv_argument: Path | None,
    marker_expression: str,
    expected_skip_node_ids: tuple[str, ...],
    public_entrypoint: str,
    public_argv: tuple[str, ...],
    node_argument: Path | None = None,
    inner_sandbox_node_ids: tuple[str, ...] = (),
) -> dict[str, object]:
    public_entrypoint_binding = _require_public_entrypoint(root, public_entrypoint)
    repository_before = _require_expected_commit(root, expected_commit)
    if (root / ".env").exists() or (root / ".env").is_symlink():
        raise GateError("checkout_env_file_present")
    if sys.version_info[:2] != (3, 11):
        raise GateError("bootstrap_python_not_3_11")
    if uv_argument is None:
        raise GateError("uv_not_found")
    uv = uv_argument.resolve()
    if not uv.is_file() or not os.access(uv, os.X_OK):
        raise GateError("uv_not_executable")
    node: Path | None = None
    if node_argument is not None:
        node = node_argument.resolve()
        if not node.is_file() or not os.access(node, os.X_OK):
            raise GateError("node_not_executable")
    output = _prepare_output(output_argument, root=root)
    runtime_root, transient_paths = _fresh_checkout_runtime(
        root=root,
        output=output,
        commit=str(repository_before["commit"]),
    )
    venv = transient_paths["venv"]
    sandbox_exec = _require_sandbox_exec()
    uv_env = _uv_environment(transient_paths, uv)
    test_env = _test_environment(transient_paths, uv, node)
    inputs_before = _input_identity(root)
    output_info = output.lstat()
    output_parent_info = output.parent.lstat()
    receipt: dict[str, object] = {
        "command": {
            "argv": [public_entrypoint, *public_argv],
            "cwd": str(root),
            "entrypoint_binding": public_entrypoint_binding,
            "environment_strategy": "allowlist",
            "may_touch_database": False,
            "may_touch_network_during_install": True,
            "may_touch_network_during_tests": False,
            "may_touch_provider": False,
            "may_touch_runtime": False,
            "may_touch_trading": False,
        },
        "contract": CONTRACT,
        "environment": {
            "install": uv_env,
            "tests": test_env,
        },
        "evidence_directory": {
            "mode": f"{stat.S_IMODE(output_info.st_mode):03o}",
            "owner_uid": output_info.st_uid,
            "parent_mode": f"{stat.S_IMODE(output_parent_info.st_mode):03o}",
            "parent_owner_uid": output_parent_info.st_uid,
            "path": str(output),
        },
        "expected_skip_node_ids": list(expected_skip_node_ids),
        "fresh_environment": {
            "inside_checkout": True,
            "path": str(venv),
            "preexisting": False,
        },
        "inputs_before": inputs_before,
        "marker_expression": marker_expression,
        "repository_before": repository_before,
        "started_at": _utc_now(),
        "status": "running",
        "transient_runtime": {
            "cleanup_owner": "outer_collector",
            "evidence_artifact": False,
            "paths": {
                name: str(path)
                for name, path in sorted(transient_paths.items())
            },
            "root": str(runtime_root),
            "runner_recursive_cleanup": False,
        },
    }
    error: GateError | None = None
    try:
        uv_version_completed, uv_version = _run_logged(
            argv=(str(uv), "--version"),
            cwd=root,
            env=uv_env,
            output=output,
            name="uv-version",
        )
        receipt["uv"] = {
            **uv_version,
            "realpath": str(uv),
            "sha256": _sha256_file(uv),
        }
        if uv_version_completed.returncode != 0:
            raise GateError("uv_version_failed")

        if node is not None:
            node_version_completed, node_version = _run_logged(
                argv=(str(node), "--version"),
                cwd=root,
                env=test_env,
                output=output,
                name="node-version",
            )
            receipt["node"] = {
                "argument": str(node_argument),
                "realpath": str(node),
                "sha256": _sha256_file(node),
                "version": node_version,
            }
            if node_version_completed.returncode != 0:
                raise GateError("node_version_failed")

        install_completed, install = _run_logged(
            argv=(
                str(uv),
                "sync",
                "--frozen",
                "--no-editable",
                "--all-extras",
                "--python",
                str(Path(sys.executable).resolve()),
            ),
            cwd=root,
            env=uv_env,
            output=output,
            name="uv-sync",
        )
        receipt["install"] = install
        if install_completed.returncode != 0:
            raise GateError(f"uv_sync_failed:{install_completed.returncode}")

        python = venv / "bin" / "python"
        if not python.is_file() or not os.access(python, os.X_OK):
            raise GateError("fresh_python_not_executable")
        probe_completed, probe_record = _run_json_probe(
            argv=(str(python), "-I", "-B", "-c", _PROBE_SOURCE),
            cwd=root,
            env=test_env,
            output=output,
            name="python-import-identity",
        )
        python_record = {
            **probe_record,
            "lock_sha256": inputs_before["uv.lock"]["sha256"],
        }
        receipt["python"] = python_record
        if probe_completed.returncode != 0:
            raise GateError("python_import_probe_failed")
        probe_document = _strict_json(probe_completed.stdout)
        python_record["identity"] = _validate_import_probe(
            probe_document,
            root=root,
            venv=venv,
        )

        inventory_completed, inventory = _run_logged(
            argv=(str(uv), "pip", "freeze", "--strict", "--python", str(python)),
            cwd=root,
            env=uv_env,
            output=output,
            name="dependency-inventory",
        )
        receipt["dependency_inventory"] = inventory
        if inventory_completed.returncode != 0 or not inventory_completed.stdout.strip():
            raise GateError("dependency_inventory_failed")

        sandbox_completed, sandbox_record = _run_logged(
            argv=(
                str(sandbox_exec),
                "-p",
                SANDBOX_PROFILE,
                str(python),
                "-I",
                "-B",
                "-c",
                _NETWORK_DENIAL_SOURCE,
            ),
            cwd=root,
            env=test_env,
            output=output,
            name="network-sandbox-denial",
        )
        receipt["network_sandbox"] = {
            **sandbox_record,
            "executable_sha256": _sha256_file(sandbox_exec),
            "profile": SANDBOX_PROFILE,
        }
        if sandbox_completed.returncode != 0:
            raise GateError("network_sandbox_denial_not_proven")

        if inner_sandbox_node_ids:
            shard_commands = build_pytest_shard_commands(
                sandbox_exec=sandbox_exec,
                python=python,
                transient_paths=transient_paths,
                output=output,
                marker_expression=marker_expression,
                inner_sandbox_node_ids=inner_sandbox_node_ids,
            )
            collection_completed, collection_record = _run_logged(
                argv=shard_commands["collection"],
                cwd=root,
                env=test_env,
                output=output,
                name="pytest-backend-non-postgres-collection",
            )
            pytest_record: dict[str, object] = {
                "collection": collection_record,
                "inner_sandbox_contract": {
                    "macos_outer_sandbox": False,
                    "parent_inet_audit_guard": True,
                    "product_child_macos_sandbox_required": True,
                },
            }
            receipt["pytest"] = pytest_record
            if collection_completed.returncode != 0:
                raise GateError(
                    f"pytest_collection_exit_nonzero:{collection_completed.returncode}"
                )
            collected_node_ids = parse_collected_node_ids(collection_completed.stdout)
            general_node_ids, exact_inner_node_ids = partition_collected_node_ids(
                collected_node_ids,
                inner_sandbox_node_ids,
            )
            expected_skip_set = set(expected_skip_node_ids)
            if not expected_skip_set.issubset(collected_node_ids):
                raise GateError("expected_skip_not_collected")
            general_expected_skips = tuple(
                node_id
                for node_id in expected_skip_node_ids
                if node_id in set(general_node_ids)
            )
            inner_expected_skips = tuple(
                node_id
                for node_id in expected_skip_node_ids
                if node_id in set(exact_inner_node_ids)
            )
            pytest_record["partition"] = {
                "collected": {
                    "count": len(collected_node_ids),
                    "node_ids_sha256": _sha256(
                        _canonical_json(list(collected_node_ids))
                    ),
                },
                "exact_union": True,
                "general": {
                    "count": len(general_node_ids),
                    "node_ids_sha256": _sha256(
                        _canonical_json(list(general_node_ids))
                    ),
                },
                "inner_sandbox": {
                    "count": len(exact_inner_node_ids),
                    "node_ids": list(exact_inner_node_ids),
                    "node_ids_sha256": _sha256(
                        _canonical_json(list(exact_inner_node_ids))
                    ),
                },
                "overlap_count": 0,
            }

            general_completed, general_record = _run_logged(
                argv=shard_commands["general"],
                cwd=root,
                env=test_env,
                output=output,
                name="pytest-backend-non-postgres",
            )
            inner_completed, inner_record = _run_logged(
                argv=shard_commands["inner_sandbox"],
                cwd=root,
                env=test_env,
                output=output,
                name="pytest-backend-non-postgres-inner-sandbox",
            )
            pytest_record["shards"] = {
                "general": general_record,
                "inner_sandbox": inner_record,
            }
            shard_results: dict[str, dict[str, object]] = {}
            shard_errors: list[str] = []
            for (
                shard_name,
                junit_path,
                completed,
                record,
                declared_skips,
            ) in (
                (
                    "general",
                    output / "pytest-backend-non-postgres.junit.xml",
                    general_completed,
                    general_record,
                    general_expected_skips,
                ),
                (
                    "inner_sandbox",
                    output
                    / "pytest-backend-non-postgres-inner-sandbox.junit.xml",
                    inner_completed,
                    inner_record,
                    inner_expected_skips,
                ),
            ):
                if not junit_path.is_file() or junit_path.is_symlink():
                    shard_errors.append(f"{shard_name}:pytest_junit_missing")
                    continue
                junit_path.chmod(0o600)
                record["junit"] = _artifact(junit_path)
                try:
                    shard_result = validate_junit(
                        junit_path.read_bytes(),
                        pytest_exit=completed.returncode,
                        expected_skip_node_ids=declared_skips,
                    )
                except GateError as exc:
                    shard_errors.append(f"{shard_name}:{exc}")
                else:
                    record["result"] = shard_result
                    shard_results[shard_name] = shard_result
            if shard_errors:
                raise GateError(f"pytest_shards_failed:{'|'.join(shard_errors)}")
            pytest_record["result"] = combine_shard_results(
                collected_node_ids=collected_node_ids,
                general_node_ids=general_node_ids,
                inner_sandbox_node_ids=exact_inner_node_ids,
                general_result=shard_results["general"],
                inner_sandbox_result=shard_results["inner_sandbox"],
            )
        else:
            junit_path = output / "pytest-backend-non-postgres.junit.xml"
            pytest_completed, pytest_record = _run_logged(
                argv=(
                    str(sandbox_exec),
                    "-p",
                    SANDBOX_PROFILE,
                    str(python),
                    "-I",
                    "-B",
                    "-m",
                    "pytest",
                    "-q",
                    "-rA",
                    "--strict-config",
                    "--strict-markers",
                    "-p",
                    "no:cacheprovider",
                    "--basetemp",
                    str(transient_paths["basetemp"]),
                    "-m",
                    marker_expression,
                    "tests",
                    f"--junitxml={junit_path}",
                ),
                cwd=root,
                env=test_env,
                output=output,
                name="pytest-backend-non-postgres",
            )
            receipt["pytest"] = pytest_record
            if not junit_path.is_file() or junit_path.is_symlink():
                raise GateError("pytest_junit_missing")
            junit_path.chmod(0o600)
            junit_content = junit_path.read_bytes()
            pytest_record["junit"] = _artifact(junit_path)
            pytest_record["result"] = validate_junit(
                junit_content,
                pytest_exit=pytest_completed.returncode,
                expected_skip_node_ids=expected_skip_node_ids,
            )

        repository_after = _git_identity(root)
        receipt["repository_after"] = repository_after
        receipt["inputs_after"] = _input_identity(root)
        if repository_after != repository_before:
            raise GateError("repository_identity_changed")
        if receipt["inputs_after"] != inputs_before:
            raise GateError("repository_inputs_changed")
        receipt["status"] = "passed"
    except Exception as exc:
        error = (
            exc
            if isinstance(exc, GateError)
            else GateError(f"unexpected_runner_error:{type(exc).__name__}")
        )
        receipt["status"] = "failed"
        receipt["error"] = str(error)
        try:
            receipt["repository_after"] = _git_identity(root)
            receipt["inputs_after"] = _input_identity(root)
        except GateError as identity_exc:
            receipt["post_failure_identity_error"] = str(identity_exc)
    finally:
        receipt["completed_at"] = _utc_now()
        receipt_path = _write_receipt(output, receipt)
    if error is not None:
        raise error
    return {
        "contract": CONTRACT,
        "receipt": str(receipt_path),
        "receipt_sha256": _sha256_file(receipt_path),
        "status": "passed",
    }


def _parse_public_args(argv: tuple[str, ...]) -> argparse.Namespace:
    seen: set[str] = set()
    describe = False
    self_test = False
    output_dir: Path | None = None
    expected_commit: str | None = None
    index = 0
    while index < len(argv):
        token = argv[index]
        value: str | None = None
        if token in {"--node", "--repository-root", "--uv"} or token.startswith(
            ("--node=", "--repository-root=", "--uv=")
        ):
            raise GateError("public_argument_forbidden")
        if token in {"--describe", "--self-test"}:
            name = token
        elif token in {"--output-dir", "--expected-commit"}:
            name = token
            index += 1
            if index >= len(argv) or argv[index].startswith("--"):
                raise GateError("public_arguments_invalid")
            value = argv[index]
        elif token.startswith("--output-dir="):
            name = "--output-dir"
            value = token.partition("=")[2]
        elif token.startswith("--expected-commit="):
            name = "--expected-commit"
            value = token.partition("=")[2]
        else:
            raise GateError("public_arguments_invalid")
        if name in seen:
            raise GateError("public_argument_duplicate")
        seen.add(name)
        if name == "--describe":
            describe = True
        elif name == "--self-test":
            self_test = True
        elif name == "--output-dir":
            if not value:
                raise GateError("public_arguments_invalid")
            output_dir = Path(value)
        else:
            if not value:
                raise GateError("public_arguments_invalid")
            expected_commit = value
        index += 1

    selected_modes = int(describe) + int(self_test) + int(output_dir is not None)
    if selected_modes != 1:
        raise GateError("public_arguments_invalid")
    if (describe or self_test) and expected_commit is not None:
        raise GateError("public_arguments_invalid")
    if output_dir is not None and expected_commit is None:
        raise GateError("public_arguments_invalid")
    return argparse.Namespace(
        describe=describe,
        expected_commit=expected_commit,
        output_dir=output_dir,
        self_test=self_test,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--repository-root", type=Path, required=True)
    parser.add_argument("--uv", type=Path)
    parser.add_argument("--node", type=Path)
    parser.add_argument("--public-entrypoint", required=True)
    parser.add_argument("--public-argv", nargs=argparse.REMAINDER, required=True)
    internal = parser.parse_args()
    public = _parse_public_args(tuple(internal.public_argv))
    internal.describe = public.describe
    internal.expected_commit = public.expected_commit
    internal.output_dir = public.output_dir
    internal.self_test = public.self_test
    internal.public_argv = tuple(internal.public_argv)
    return internal


def main() -> int:
    args = _parse_args()
    root = args.repository_root.resolve()
    _require_helper_path(root)
    _require_git_toplevel(root)
    _require_public_entrypoint(root, args.public_entrypoint)
    if not (root / "pyproject.toml").is_file() or not (root / "uv.lock").is_file():
        raise GateError("repository_root_invalid")
    marker_expression, expected_skip_node_ids = _load_repository_contract(root)
    if args.describe:
        result = describe_contract(marker_expression, expected_skip_node_ids)
    elif args.self_test:
        result = run_self_test(root)
    else:
        if args.node is None:
            raise GateError("node_not_found")
        result = run_gate(
            root=root,
            output_argument=args.output_dir,
            expected_commit=args.expected_commit,
            uv_argument=args.uv,
            marker_expression=marker_expression,
            expected_skip_node_ids=expected_skip_node_ids,
            public_entrypoint=args.public_entrypoint,
            public_argv=args.public_argv,
            node_argument=args.node,
            inner_sandbox_node_ids=INNER_SANDBOX_NODE_IDS,
        )
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except GateError as exc:
        print(f"backend_non_postgres_error={exc}", file=sys.stderr, flush=True)
        raise SystemExit(78) from exc
