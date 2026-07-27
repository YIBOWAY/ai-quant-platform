"""Published-baseline to final non-editable wheel upgrade rehearsal."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tarfile
import zipfile
from dataclasses import asdict
from pathlib import Path, PurePosixPath

from quant_system.ops.common import (
    ReleaseOperationError,
    canonical_json_bytes,
    ensure_private_directory,
    git_identity,
    sha256_bytes,
    sha256_file,
    utc_now,
    write_immutable,
)

PUBLISHED_BASELINE = "e19087e1580a21ccc9160bc664167972e322021c"


def _run(
    argv: list[str],
    *,
    cwd: Path,
    log_path: Path,
    env: dict[str, str] | None = None,
) -> dict[str, object]:
    completed = subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        check=False,
        capture_output=True,
    )
    payload = completed.stdout + completed.stderr
    write_immutable(log_path, payload)
    if completed.returncode != 0:
        raise ReleaseOperationError(f"upgrade command failed: {log_path.name}")
    return {
        "argv": argv,
        "exit_code": completed.returncode,
        "stdout_stderr_sha256": sha256_bytes(payload),
        "stdout_stderr_bytes": len(payload),
        "log_path": str(log_path),
    }


def _archive_commit(
    *,
    repository_root: Path,
    commit: str,
    destination: Path,
    archive_path: Path,
) -> dict[str, object]:
    with archive_path.open("xb") as output:
        archive = subprocess.run(
            ["git", "-C", str(repository_root), "archive", "--format=tar", commit],
            check=False,
            stdout=output,
            stderr=subprocess.PIPE,
        )
    archive_path.chmod(0o600)
    if archive.returncode != 0:
        raise ReleaseOperationError(f"git archive failed for {commit}")
    destination.mkdir(mode=0o700)
    with tarfile.open(archive_path, mode="r:") as bundle:
        root = destination.resolve()
        for member in bundle.getmembers():
            target = (destination / member.name).resolve()
            if target != root and root not in target.parents:
                raise ReleaseOperationError("git archive contains an unsafe path")
            if member.issym() or member.islnk():
                raise ReleaseOperationError("git archive contains a link")
        bundle.extractall(destination, filter="data")
    return {
        "commit": commit,
        "archive_path": str(archive_path),
        "archive_sha256": sha256_file(archive_path),
        "archive_bytes": archive_path.stat().st_size,
    }


def _probe_script(expected_forbidden_roots: tuple[Path, ...]) -> str:
    forbidden = [str(path.resolve()) for path in expected_forbidden_roots]
    return "\n".join(
        (
            "import hashlib",
            "import importlib.metadata as metadata",
            "import json",
            "import pathlib",
            "import quant_system",
            "import sys",
            "distribution = metadata.distribution('quant-system')",
            "root = pathlib.Path(quant_system.__file__).resolve()",
            f"forbidden = {forbidden!r}",
            "direct = distribution.read_text('direct_url.json')",
            "site = root.parents[1]",
            "pth = [",
            "    {'path': str(path), 'text': path.read_text(errors='replace')}",
            "    for path in sorted(site.glob('*.pth'))",
            "]",
            "assert all(value not in str(root) for value in forbidden)",
            "direct_document = json.loads(direct) if direct else {}",
            "assert not direct_document.get('dir_info', {}).get('editable', False)",
            "assert all(all(value not in row['text'] for value in forbidden) for row in pth)",
            "installed = hashlib.sha256()",
            "installed_files = []",
            "for entry in sorted(distribution.files or (), key=str):",
            "    target = distribution.locate_file(entry)",
            "    if target.is_file():",
            "        installed_files.append(str(entry))",
            "        installed.update(str(entry).encode('utf-8'))",
            "        installed.update(b'\\0')",
            "        installed.update(target.read_bytes())",
            "        installed.update(b'\\0')",
            "print(json.dumps({",
            "    'distribution': distribution.metadata['Name'],",
            "    'version': distribution.version,",
            "    'module': str(root),",
            "    'sys_executable': sys.executable,",
            "    'direct_url': direct_document or None,",
            "    'pth': pth,",
            "    'installed_file_count': len(installed_files),",
            "    'installed_tree_sha256': installed.hexdigest(),",
            "}, sort_keys=True))",
        )
    )


def _json_probe(
    *,
    python: Path,
    cwd: Path,
    forbidden_roots: tuple[Path, ...],
    log_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    argv = [str(python), "-I", "-c", _probe_script(forbidden_roots)]
    completed = subprocess.run(argv, cwd=cwd, check=False, capture_output=True)
    payload = completed.stdout + completed.stderr
    write_immutable(log_path, payload)
    if completed.returncode != 0:
        raise ReleaseOperationError(f"non-editable import probe failed: {log_path.name}")
    try:
        document = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise ReleaseOperationError("non-editable import probe output is not JSON") from exc
    return document, {
        "argv": argv,
        "exit_code": completed.returncode,
        "stdout_stderr_sha256": sha256_bytes(payload),
        "stdout_stderr_bytes": len(payload),
        "log_path": str(log_path),
    }


def _single_wheel(directory: Path) -> Path:
    wheels = sorted(directory.glob("*.whl"))
    if len(wheels) != 1:
        raise ReleaseOperationError("wheel build did not produce exactly one wheel")
    wheel = wheels[0]
    wheel.chmod(0o600)
    return wheel


def _wheel_payload_facts(wheel: Path) -> dict[str, object]:
    """Hash sorted uncompressed wheel members, excluding ZIP container metadata."""

    digest = hashlib.sha256()
    names: set[str] = set()
    total_bytes = 0
    with zipfile.ZipFile(wheel) as bundle:
        members = sorted(
            (member for member in bundle.infolist() if not member.is_dir()),
            key=lambda member: member.filename,
        )
        for member in members:
            path = PurePosixPath(member.filename)
            if (
                member.filename in names
                or path.is_absolute()
                or ".." in path.parts
                or not path.parts
            ):
                raise ReleaseOperationError("wheel contains an unsafe or duplicate member")
            names.add(member.filename)
            payload = bundle.read(member)
            total_bytes += len(payload)
            digest.update(member.filename.encode("utf-8"))
            digest.update(b"\0")
            digest.update(payload)
            digest.update(b"\0")
    if not names:
        raise ReleaseOperationError("wheel has no payload members")
    return {
        "member_count": len(names),
        "uncompressed_bytes": total_bytes,
        "normalized_payload_sha256": digest.hexdigest(),
    }


def verify_noneditable_upgrade(
    *,
    repository_root: Path,
    output_dir: Path,
    uv_binary: str | None = None,
) -> dict[str, object]:
    repository_root = repository_root.resolve()
    identity = git_identity(repository_root, require_clean=True)
    final_commit = identity.commit
    ancestor = subprocess.run(
        [
            "git",
            "-C",
            str(repository_root),
            "merge-base",
            "--is-ancestor",
            PUBLISHED_BASELINE,
            final_commit,
        ],
        check=False,
    )
    if ancestor.returncode != 0:
        raise ReleaseOperationError("published baseline is not an ancestor of final commit")

    uv = uv_binary or shutil.which("uv")
    if not uv or not Path(uv).is_file() or not os.access(uv, os.X_OK):
        raise ReleaseOperationError("uv executable is unavailable")
    output_dir = ensure_private_directory(output_dir)
    receipt_path = output_dir / "noneditable-upgrade-receipt.json"
    if receipt_path.exists():
        raise ReleaseOperationError("upgrade receipt already exists")
    work = output_dir / "work"
    if work.exists():
        raise ReleaseOperationError("upgrade work directory already exists")
    work.mkdir(mode=0o700)
    baseline_root = work / "baseline"
    final_root = work / "final"
    baseline_archive = _archive_commit(
        repository_root=repository_root,
        commit=PUBLISHED_BASELINE,
        destination=baseline_root,
        archive_path=work / "baseline.tar",
    )
    final_archive = _archive_commit(
        repository_root=repository_root,
        commit=final_commit,
        destination=final_root,
        archive_path=work / "final.tar",
    )
    for root in (baseline_root, final_root):
        if not (root / "pyproject.toml").is_file() or not (root / "uv.lock").is_file():
            raise ReleaseOperationError("archive lacks pyproject.toml or uv.lock")

    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    env.pop("VIRTUAL_ENV", None)
    env.pop("UV_PROJECT_ENVIRONMENT", None)
    baseline_sync = _run(
        [
            str(Path(uv).resolve()),
            "sync",
            "--frozen",
            "--extra",
            "api",
            "--no-editable",
            "--no-install-project",
            "--python",
            "3.11",
            "--no-python-downloads",
        ],
        cwd=baseline_root,
        env=env,
        log_path=output_dir / "baseline-sync.log",
    )
    python = baseline_root / ".venv" / "bin" / "python"
    if not python.is_file():
        raise ReleaseOperationError("baseline dependency environment is incomplete")
    baseline_dist = ensure_private_directory(work / "baseline-dist")
    baseline_build = _run(
        [
            str(Path(uv).resolve()),
            "build",
            "--wheel",
            "--out-dir",
            str(baseline_dist),
            "--python",
            str(python),
            "--no-python-downloads",
        ],
        cwd=baseline_root,
        env=env,
        log_path=output_dir / "baseline-wheel-build.log",
    )
    baseline_wheel = _single_wheel(baseline_dist)
    baseline_wheel_payload = _wheel_payload_facts(baseline_wheel)
    baseline_install = _run(
        [
            str(Path(uv).resolve()),
            "pip",
            "install",
            "--python",
            str(python),
            "--reinstall",
            "--no-deps",
            str(baseline_wheel),
        ],
        cwd=baseline_root,
        env=env,
        log_path=output_dir / "baseline-wheel-install.log",
    )
    cli = baseline_root / ".venv" / "bin" / "quant-system"
    if not cli.is_file():
        raise ReleaseOperationError("baseline wheel did not install the CLI")
    neutral = work / "neutral"
    neutral.mkdir(mode=0o700)
    forbidden = (repository_root, baseline_root, final_root)
    baseline_probe, baseline_probe_command = _json_probe(
        python=python,
        cwd=neutral,
        forbidden_roots=forbidden,
        log_path=output_dir / "baseline-import.log",
    )
    baseline_cli = _run(
        [str(cli), "--help"],
        cwd=neutral,
        env=env,
        log_path=output_dir / "baseline-cli.log",
    )

    final_sync_env = dict(env)
    final_sync_env["VIRTUAL_ENV"] = str(baseline_root / ".venv")
    final_sync = _run(
        [
            str(Path(uv).resolve()),
            "sync",
            "--frozen",
            "--extra",
            "api",
            "--no-editable",
            "--no-install-project",
            "--active",
            "--python",
            str(python),
            "--no-python-downloads",
        ],
        cwd=final_root,
        env=final_sync_env,
        log_path=output_dir / "final-sync.log",
    )
    final_dist = ensure_private_directory(work / "final-dist")
    final_build = _run(
        [
            str(Path(uv).resolve()),
            "build",
            "--wheel",
            "--out-dir",
            str(final_dist),
            "--python",
            str(python),
            "--no-python-downloads",
        ],
        cwd=final_root,
        env=env,
        log_path=output_dir / "final-wheel-build.log",
    )
    final_wheel = _single_wheel(final_dist)
    final_wheel_payload = _wheel_payload_facts(final_wheel)
    if (
        final_wheel_payload["normalized_payload_sha256"]
        == baseline_wheel_payload["normalized_payload_sha256"]
    ):
        raise ReleaseOperationError("baseline and final wheel payloads are identical")
    upgrade = _run(
        [
            str(Path(uv).resolve()),
            "pip",
            "install",
            "--python",
            str(python),
            "--reinstall",
            "--no-deps",
            str(final_wheel),
        ],
        cwd=neutral,
        env=env,
        log_path=output_dir / "final-upgrade.log",
    )
    dependency_check = _run(
        [
            str(Path(uv).resolve()),
            "pip",
            "check",
            "--python",
            str(python),
            "--no-python-downloads",
        ],
        cwd=neutral,
        env=env,
        log_path=output_dir / "final-pip-check.log",
    )
    installed_inventory = _run(
        [
            str(Path(uv).resolve()),
            "pip",
            "freeze",
            "--strict",
            "--python",
            str(python),
            "--no-python-downloads",
        ],
        cwd=neutral,
        env=env,
        log_path=output_dir / "final-pip-freeze.log",
    )
    final_probe, final_probe_command = _json_probe(
        python=python,
        cwd=neutral,
        forbidden_roots=forbidden,
        log_path=output_dir / "final-import.log",
    )
    final_cli = _run(
        [str(cli), "--help"],
        cwd=neutral,
        env=env,
        log_path=output_dir / "final-cli.log",
    )
    if baseline_probe["distribution"] != "quant-system":
        raise ReleaseOperationError("baseline distribution identity mismatch")
    if final_probe["distribution"] != "quant-system":
        raise ReleaseOperationError("final distribution identity mismatch")
    if final_probe["module"] != baseline_probe["module"]:
        raise ReleaseOperationError("wheel upgrade changed the isolated site-packages location")
    if any(str(root) in str(final_probe["module"]) for root in forbidden):
        raise ReleaseOperationError("final import resolves to a checkout")

    receipt: dict[str, object] = {
        "schema_version": "agent-v0.2.2-noneditable-upgrade.v1",
        "status": "passed",
        "completed_at": utc_now(),
        "repository": asdict(identity),
        "published_baseline": PUBLISHED_BASELINE,
        "final_commit": final_commit,
        "baseline_is_ancestor": True,
        "baseline_archive": baseline_archive,
        "final_archive": final_archive,
        "baseline_lock_sha256": sha256_file(baseline_root / "uv.lock"),
        "final_lock_sha256": sha256_file(final_root / "uv.lock"),
        "environment_python": str(python),
        "baseline_sync": baseline_sync,
        "baseline_wheel_build": baseline_build,
        "baseline_wheel": {
            "filename": baseline_wheel.name,
            "sha256": sha256_file(baseline_wheel),
            "bytes": baseline_wheel.stat().st_size,
            "payload": baseline_wheel_payload,
        },
        "baseline_wheel_install": baseline_install,
        "baseline_import": baseline_probe,
        "baseline_import_command": baseline_probe_command,
        "baseline_cli_smoke": baseline_cli,
        "final_sync_from_final_lock": final_sync,
        "final_wheel_build": final_build,
        "final_wheel": {
            "filename": final_wheel.name,
            "sha256": sha256_file(final_wheel),
            "bytes": final_wheel.stat().st_size,
            "payload": final_wheel_payload,
        },
        "upgrade": upgrade,
        "dependency_check": dependency_check,
        "installed_inventory": installed_inventory,
        "final_import": final_probe,
        "final_import_command": final_probe_command,
        "final_cli_smoke": final_cli,
        "noneditable": True,
        "isolated_import": True,
        "final_lock_consumed_in_same_environment": True,
        "normalized_wheel_payload_changed": True,
    }
    write_immutable(receipt_path, canonical_json_bytes(receipt))
    return receipt
