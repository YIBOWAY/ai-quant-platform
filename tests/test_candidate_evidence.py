from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from quant_system.hermes.candidate_evidence import (
    CandidateEvidenceError,
    candidate_preflight_evidence_observation,
)
from quant_system.hermes.release_evidence_builder import (
    build_candidate_preflight,
    run_test_suite,
)

_TEST_NAMES = ("platform", "hqa", "hermes_focused", "frontend")


def _run(*argv: str, cwd: Path) -> str:
    return subprocess.run(
        argv,
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _runtime_roots(tmp_path: Path) -> dict[str, Path]:
    roots: dict[str, Path] = {}
    for name in ("platform", "hqa", "hermes"):
        root = tmp_path / f"{name}-repo"
        root.mkdir()
        _run("git", "init", "-q", cwd=root)
        _run("git", "config", "user.name", "Evidence Test", cwd=root)
        _run("git", "config", "user.email", "evidence@example.invalid", cwd=root)
        (root / "tracked.txt").write_text(name, encoding="utf-8")
        (root / ".gitignore").write_text(
            ".pytest_cache/\n__pycache__/\nsrc/frontend/node_modules/\n",
            encoding="utf-8",
        )
        tests_dir = root / "tests"
        tests_dir.mkdir()
        (tests_dir / "test_release_receipt.py").write_text(
            "import os\n\n"
            "def test_release_receipt():\n"
            "    assert 'PYTHONPATH' not in os.environ\n"
            "    assert 'PYTEST_ADDOPTS' not in os.environ\n"
            "    assert 'PYTEST_PLUGINS' not in os.environ\n"
            "    assert os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] == '1'\n",
            encoding="utf-8",
        )
        if name == "platform":
            frontend = root / "src" / "frontend"
            frontend.mkdir(parents=True)
            (frontend / "package.json").write_text(
                '{"scripts":{"test":"vitest run"},"type":"module"}\n',
                encoding="utf-8",
            )
            (frontend / "release-receipt.test.js").write_text(
                "import { expect, test } from 'vitest';\n"
                "test('release receipt', () => {\n"
                "  expect(process.env.PYTHONPATH).toBeUndefined();\n"
                "  expect(process.env.PYTEST_ADDOPTS).toBeUndefined();\n"
                "  expect(process.env.PYTEST_PLUGINS).toBeUndefined();\n"
                "  expect(process.env.PYTEST_DISABLE_PLUGIN_AUTOLOAD).toBe('1');\n"
                "});\n",
                encoding="utf-8",
            )
            frontend_modules = Path(__file__).resolve().parents[1] / "src/frontend/node_modules"
            assert frontend_modules.is_dir()
            (frontend / "node_modules").symlink_to(
                frontend_modules,
                target_is_directory=True,
            )
        _run("git", "add", ".", cwd=root)
        _run("git", "commit", "-q", "-m", "fixture", cwd=root)
        roots[name] = root
    return roots


def _receipt_paths(tmp_path: Path, roots: dict[str, Path]) -> tuple[Path, ...]:
    receipt_dir = tmp_path / "receipts"
    receipt_dir.mkdir(mode=0o700)
    paths: list[Path] = []
    for name in _TEST_NAMES:
        if name == "frontend":
            cwd = roots["platform"] / "src/frontend"
            argv = (
                str(cwd / "node_modules" / ".bin" / "vitest"),
                "run",
                "--reporter=junit",
                "--outputFile={junit}",
            )
        else:
            argv = (
                sys.executable,
                "-m",
                "pytest",
                "tests",
                "--junitxml={junit}",
            )
            cwd = roots[
                {
                    "platform": "platform",
                    "hqa": "hqa",
                    "hermes_focused": "hermes",
                }[name]
            ]
        result = run_test_suite(
            name=name,
            argv=argv,
            output_dir=receipt_dir,
            runtime_roots=roots,
            cwd=cwd,
        )
        paths.append(result.receipt_path)
    return tuple(paths)


def _preflight_manifest(
    tmp_path: Path,
) -> tuple[Path, dict[str, object], tuple[Path, ...]]:
    roots = _runtime_roots(tmp_path)
    receipts = _receipt_paths(tmp_path, roots)
    output_dir = tmp_path / "preflight"
    output_dir.mkdir(mode=0o700)
    result = build_candidate_preflight(
        output_dir=output_dir,
        runtime_roots=roots,
        test_receipts=receipts,
    )
    return (
        result.manifest_path,
        json.loads(result.manifest_path.read_text(encoding="utf-8")),
        receipts,
    )


def _write_json(path: Path, payload: object, *, mode: int = 0o600) -> bytes:
    content = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    path.write_bytes(content)
    path.chmod(mode)
    return content


def test_candidate_preflight_accepts_recomputable_mode_600_evidence(
    tmp_path: Path,
) -> None:
    path, manifest, _receipts = _preflight_manifest(tmp_path)

    observation = candidate_preflight_evidence_observation(path)

    assert observation.digest == hashlib.sha256(path.read_bytes()).hexdigest()
    runtime = manifest["runtime"]
    assert isinstance(runtime, dict)
    assert observation.platform_runtime_digest == runtime["platform"]["digest"]
    assert observation.test_passed_count == 4
    assert observation.test_failed_count == 0
    assert observation.test_skipped_count == 0


def test_candidate_preflight_rejects_any_real_flow_claim(tmp_path: Path) -> None:
    path, manifest, _receipts = _preflight_manifest(tmp_path)
    manifest["real_flows"] = {"passed": True, "flows": []}
    _write_json(path, manifest)

    with pytest.raises(CandidateEvidenceError, match="root"):
        candidate_preflight_evidence_observation(path)


def test_candidate_preflight_v2_rejects_legacy_v1_contract(
    tmp_path: Path,
) -> None:
    path, manifest, _receipts = _preflight_manifest(tmp_path)
    manifest["contract"] = "agent-v0.2-candidate-evidence/v1"
    _write_json(path, manifest)

    with pytest.raises(CandidateEvidenceError, match="version"):
        candidate_preflight_evidence_observation(path)


@pytest.mark.skipif(os.name == "nt", reason="POSIX mode contract")
def test_candidate_preflight_requires_exact_mode_600(tmp_path: Path) -> None:
    path, _manifest, _receipts = _preflight_manifest(tmp_path)
    path.chmod(0o644)

    with pytest.raises(CandidateEvidenceError, match="mode 0600"):
        candidate_preflight_evidence_observation(path)


def test_candidate_preflight_rejects_junit_count_drift_or_tamper(
    tmp_path: Path,
) -> None:
    path, manifest, _receipts = _preflight_manifest(tmp_path)
    tests = manifest["tests"]
    assert isinstance(tests, dict)
    suites = tests["suites"]
    assert isinstance(suites, list)
    first = suites[0]
    assert isinstance(first, dict)
    first["passed"] = 999
    _write_json(path, manifest)

    with pytest.raises(CandidateEvidenceError, match="counts"):
        candidate_preflight_evidence_observation(path)


def test_candidate_preflight_reopens_copied_raw_output_and_junit(
    tmp_path: Path,
) -> None:
    path, manifest, _receipts = _preflight_manifest(tmp_path)
    suite = manifest["tests"]["suites"][0]  # type: ignore[index]
    receipt_path = path.parent / suite["receipt"]["path"]  # type: ignore[index]
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    output_path = path.parent / receipt["output"]["path"]
    output_path.write_bytes(b"tampered")
    output_path.chmod(0o600)

    with pytest.raises(CandidateEvidenceError, match="digest or size"):
        candidate_preflight_evidence_observation(path)


def test_candidate_preflight_rejects_duplicate_json_keys(tmp_path: Path) -> None:
    path, _manifest, _receipts = _preflight_manifest(tmp_path)
    path.write_bytes(
        b'{"contract":"agent-v0.2-candidate-evidence/v2",'
        b'"contract":"agent-v0.2-candidate-evidence/v2"}'
    )

    with pytest.raises(CandidateEvidenceError, match="duplicate"):
        candidate_preflight_evidence_observation(path)
