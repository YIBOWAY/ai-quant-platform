from __future__ import annotations

import importlib.util
import json
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "python_static_gate.py"
RUNNER = ROOT / "scripts" / "verify_python_static.sh"


def _helper():
    spec = importlib.util.spec_from_file_location("python_static_gate_under_test", HELPER)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _repository_identity(root: Path, commit: str) -> dict[str, object]:
    return {
        "branch": "codex/agent-v0-2-release",
        "clean": True,
        "clean_status_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
        "commit": commit,
        "git_toplevel": str(root),
        "publication_remote": "github",
        "publication_remote_url": "https://github.com/YIBOWAY/ai-quant-platform.git",
        "root": str(root),
        "tracked_tree": {
            "assume_unchanged_count": 0,
            "conflict_entry_count": 0,
            "index_matches_head": True,
            "ls_files_flags_sha256": "1" * 64,
            "skip_worktree_count": 0,
            "tracked_path_count": 1200,
            "worktree_matches_index": True,
        },
        "tree": "b" * 40,
    }


def _gate2_receipt(root: Path, evidence: Path, commit: str) -> dict[str, object]:
    helper = _helper()
    scripts = root / "scripts"
    scripts.mkdir(exist_ok=True)
    fixture_content = {
        "pyproject.toml": b"[tool.ruff]\ntarget-version = \"py311\"\n",
        "uv.lock": b"version = 1\n",
        "scripts/backend_non_postgres_gate.py": b"# gate2 helper\n",
        "scripts/verify_backend_non_postgres.sh": b"#!/bin/sh\n",
        "scripts/python_static_gate.py": b"# gate4 helper\n",
        "scripts/verify_python_static.sh": b"#!/bin/sh\n",
        "scripts/verify.sh": b"# verify\n",
    }
    for relative, content in fixture_content.items():
        (root / relative).write_bytes(content)
    runtime = helper.gate2_runtime_path(root=root, evidence=evidence, commit=commit)
    venv = runtime / "venv"
    identity = _repository_identity(root, commit)
    inputs = {
        relative: helper.file_identity(root / relative, relative_to=root)
        for relative in (
            "pyproject.toml",
            "scripts/backend_non_postgres_gate.py",
            "scripts/verify_backend_non_postgres.sh",
            "uv.lock",
        )
    }
    return {
        "contract": "quant-system-backend-non-postgres/v1",
        "evidence_directory": {"path": str(evidence)},
        "fresh_environment": {
            "inside_checkout": True,
            "path": str(venv),
            "preexisting": False,
        },
        "inputs_after": inputs,
        "inputs_before": inputs,
        "python": {
            "identity": {
                "direct_url": {
                    "dir_info": {"editable": False},
                    "url": root.as_uri(),
                },
                "prefix": str(venv),
                "quant_system_file": str(
                    venv / "lib/python3.11/site-packages/quant_system/__init__.py"
                ),
                "sys_executable": str(venv / "bin/python"),
                "sys_executable_realpath": str(venv / "bin/python"),
                "version_info": [3, 11, 15],
            },
            "lock_sha256": inputs["uv.lock"]["sha256"],
        },
        "repository_after": identity,
        "repository_before": identity,
        "status": "passed",
        "transient_runtime": {
            "cleanup_owner": "outer_collector",
            "evidence_artifact": False,
            "paths": {"venv": str(venv)},
            "root": str(runtime),
            "runner_recursive_cleanup": False,
        },
    }


def test_repository_authority_is_the_existing_verify_ruff_surface() -> None:
    helper = _helper()

    authority = helper.load_repository_authority(ROOT)

    assert authority["argv_tail"] == [
        "-m",
        "ruff",
        "check",
        "src/quant_system",
        "tests",
    ]
    assert authority["source"]["path"] == "scripts/verify.sh"
    assert authority["source"]["line_number"] == 28
    assert authority["source"]["line"] == (
        'run_step "Ruff" "$PYTHON_BIN" -m ruff check src/quant_system tests'
    )
    assert authority["ruff_configuration"]["target-version"] == "py311"
    assert authority["ruff_configuration"]["lint"]["select"] == [
        "E",
        "F",
        "I",
        "UP",
        "B",
        "SIM",
    ]


def test_static_environment_is_a_closed_non_product_allowlist(tmp_path: Path) -> None:
    helper = _helper()
    runtime = tmp_path / "gate2-runtime"
    for name in ("home", "tmp", "pycache", "ruff-cache", "venv/bin"):
        (runtime / name).mkdir(parents=True)
    python = runtime / "venv/bin/python"

    environment = helper.static_environment(runtime=runtime, python=python)

    assert environment == {
        "HOME": str(runtime / "home"),
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": f"{python.parent}:/usr/bin:/bin",
        "PYTHONNOUSERSITE": "1",
        "PYTHONPYCACHEPREFIX": str(runtime / "pycache"),
        "RUFF_CACHE_DIR": str(runtime / "ruff-cache"),
        "TMPDIR": str(runtime / "tmp"),
    }
    assert not any(
        key.startswith(("QS_", "FUTU_", "OPENAI_", "ANTHROPIC_"))
        or key in {"DATABASE_URL", "PYTHONPATH"}
        for key in environment
    )


def test_gate2_receipt_binds_exact_runtime_and_current_repository(
    tmp_path: Path,
) -> None:
    helper = _helper()
    root = tmp_path / "release"
    root.mkdir()
    evidence = tmp_path / "gate2"
    evidence.mkdir(mode=0o700)
    commit = "a" * 40
    document = _gate2_receipt(root, evidence, commit)
    receipt = evidence / "backend-non-postgres-receipt.json"
    receipt.write_bytes(helper.canonical_json(document))
    receipt.chmod(0o600)
    runtime = helper.gate2_runtime_path(root=root, evidence=evidence, commit=commit)
    for name in ("home", "tmp", "pycache", "venv/bin"):
        (runtime / name).mkdir(parents=True, exist_ok=True)
    python = runtime / "venv/bin/python"
    python.write_bytes(b"fixture-python")
    python.chmod(0o700)

    binding = helper.validate_gate2_receipt(
        path=receipt,
        root=root,
        expected_commit=commit,
        repository_identity=_repository_identity(root, commit),
    )

    assert binding["receipt"]["path"] == str(receipt)
    assert binding["receipt"]["sha256"] == helper.sha256_file(receipt)
    assert binding["runtime"]["root"] == str(runtime)
    assert binding["runtime"]["venv"] == str(runtime / "venv")
    assert binding["python_identity"] == document["python"]["identity"]
    assert binding["python_executable"]["sha256"] == helper.sha256_file(python)


@pytest.mark.parametrize(
    ("mutation", "error"),
    [
        (lambda document: document.update(status="failed"), "gate2_receipt_not_passed"),
        (
            lambda document: document["repository_after"].update(tree="c" * 40),
            "gate2_repository_identity_mismatch",
        ),
        (
            lambda document: document["fresh_environment"].update(
                path="/tmp/substitute/venv"
            ),
            "gate2_runtime_path_mismatch",
        ),
    ],
)
def test_gate2_receipt_rejects_substitution(
    tmp_path: Path,
    mutation,
    error: str,
) -> None:
    helper = _helper()
    root = tmp_path / "release"
    root.mkdir()
    evidence = tmp_path / "gate2"
    evidence.mkdir(mode=0o700)
    commit = "a" * 40
    document = _gate2_receipt(root, evidence, commit)
    mutation(document)
    receipt = evidence / "backend-non-postgres-receipt.json"
    receipt.write_bytes(helper.canonical_json(document))
    receipt.chmod(0o600)

    with pytest.raises(helper.GateError, match=error):
        helper.validate_gate2_receipt(
            path=receipt,
            root=root,
            expected_commit=commit,
            repository_identity=_repository_identity(root, commit),
        )


def test_gate2_receipt_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    helper = _helper()
    receipt = tmp_path / "backend-non-postgres-receipt.json"
    receipt.write_text('{"status":"passed","status":"failed"}', encoding="utf-8")
    receipt.chmod(0o600)

    with pytest.raises(helper.GateError, match="duplicate_json_key"):
        helper.load_canonical_json(receipt)


def test_gate2_receipt_rejects_symlinked_runtime_parent(tmp_path: Path) -> None:
    helper = _helper()
    root = tmp_path / "release"
    root.mkdir()
    evidence = tmp_path / "gate2"
    evidence.mkdir(mode=0o700)
    commit = "a" * 40
    document = _gate2_receipt(root, evidence, commit)
    receipt = evidence / "backend-non-postgres-receipt.json"
    receipt.write_bytes(helper.canonical_json(document))
    receipt.chmod(0o600)
    external = tmp_path / "substituted-runtime"
    external.mkdir()
    (root / ".tmp").symlink_to(external, target_is_directory=True)
    runtime = helper.gate2_runtime_path(root=root, evidence=evidence, commit=commit)
    for name in ("home", "tmp", "pycache", "venv"):
        (runtime / name).mkdir(parents=True, exist_ok=True)

    with pytest.raises(helper.GateError, match="gate2_runtime_parent_unsafe"):
        helper.validate_gate2_receipt(
            path=receipt,
            root=root,
            expected_commit=commit,
            repository_identity=_repository_identity(root, commit),
        )


def test_public_runner_rejects_helper_only_arguments() -> None:
    completed = subprocess.run(
        [
            "bash",
            str(RUNNER),
            "--describe",
            "--repository-root",
            "/tmp/substitute",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        env={**os.environ, "DATABASE_URL": "must-not-pass"},
    )

    assert completed.returncode == 78
    assert "python_static_error=public_argument_forbidden" in completed.stderr
    assert completed.stdout == ""


def test_canonical_json_is_utf8_sorted_compact_and_newline_free() -> None:
    helper = _helper()

    content = helper.canonical_json({"z": "中文", "a": [1, 2]})

    assert content == '{"a":[1,2],"z":"中文"}'.encode()
    assert not content.endswith(b"\n")
    assert json.loads(content) == {"a": [1, 2], "z": "中文"}
