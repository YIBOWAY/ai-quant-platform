from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import sysconfig
import time
from pathlib import Path

import pytest

from quant_system.ops.common import ReleaseOperationError
from quant_system.ops.noneditable_upgrade import (
    _forbidden_source_roots,
    _validate_import_probe,
)


def _init_release_repository(repository: Path) -> tuple[str, str]:
    from quant_system.ops import noneditable_upgrade as upgrade_ops

    repository.mkdir()
    commands = (
        ("/usr/bin/git", "init", "-q", "-b", "codex/agent-v0-2-release"),
        ("/usr/bin/git", "config", "user.email", "upgrade@example.invalid"),
        ("/usr/bin/git", "config", "user.name", "Upgrade Test"),
        (
            "/usr/bin/git",
            "remote",
            "add",
            "github",
            upgrade_ops.CANONICAL_GITHUB_REMOTE,
        ),
    )
    for command in commands:
        subprocess.run(command, cwd=repository, check=True)
    tracked = repository / "tracked.txt"
    tracked.write_text("first\n", encoding="utf-8")
    subprocess.run(("/usr/bin/git", "add", "tracked.txt"), cwd=repository, check=True)
    subprocess.run(("/usr/bin/git", "commit", "-qm", "first"), cwd=repository, check=True)
    first = subprocess.run(
        ("/usr/bin/git", "rev-parse", "HEAD"),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tracked.write_text("second\n", encoding="utf-8")
    subprocess.run(("/usr/bin/git", "commit", "-qam", "second"), cwd=repository, check=True)
    second = subprocess.run(
        ("/usr/bin/git", "rev-parse", "HEAD"),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return first, second


def _materialize_noneditable_wrapper_fixture(
    root: Path,
    *,
    pause_after_archive_identity_check: bool = False,
) -> Path:
    from quant_system.ops import noneditable_upgrade as upgrade_ops

    source_repository = Path(__file__).resolve().parents[1]
    repository = root / "repository"
    (repository / "src").mkdir(parents=True)
    shutil.copytree(
        source_repository / "src" / "quant_system",
        repository / "src" / "quant_system",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (repository / "scripts").mkdir()
    shutil.copy2(
        source_repository / "scripts" / "verify_agent_v02_noneditable_upgrade.sh",
        repository / "scripts" / "verify_agent_v02_noneditable_upgrade.sh",
    )
    if pause_after_archive_identity_check:
        wrapper = repository / "scripts" / "verify_agent_v02_noneditable_upgrade.sh"
        source = wrapper.read_text(encoding="utf-8")
        needle = "    if head_after_archive != commit:\n        fail()\n"
        barrier = (
            needle
            + '    barrier_value = os.environ.get("AGENT_V02_TEST_HEAD_MOVE_BARRIER")\n'
            + "    if barrier_value:\n"
            + "        barrier_path = Path(barrier_value)\n"
            + '        write_exclusive(barrier_path.with_suffix(".ready"), b"ready\\n")\n'
            + '        clock = __import__("time")\n'
            + "        deadline = clock.monotonic() + 10\n"
            + '        while not barrier_path.with_suffix(".release").is_file():\n'
            + "            if clock.monotonic() >= deadline:\n"
            + "                fail()\n"
            + "            clock.sleep(0.01)\n"
        )
        assert source.count(needle) == 1
        wrapper.write_text(source.replace(needle, barrier, 1), encoding="utf-8")
    (repository / ".gitignore").write_text(".venv/\n", encoding="utf-8")
    commands = (
        ("/usr/bin/git", "init", "-q", "-b", "codex/agent-v0-2-release"),
        ("/usr/bin/git", "config", "user.email", "upgrade@example.invalid"),
        ("/usr/bin/git", "config", "user.name", "Upgrade Test"),
        (
            "/usr/bin/git",
            "remote",
            "add",
            "github",
            upgrade_ops.CANONICAL_GITHUB_REMOTE,
        ),
        ("/usr/bin/git", "add", ".gitignore", "scripts", "src"),
        ("/usr/bin/git", "commit", "-qm", "fixture"),
    )
    for command in commands:
        subprocess.run(command, cwd=repository, check=True)

    fixture_python = repository / ".venv" / "bin" / "python"
    fixture_python.parent.mkdir(parents=True)
    fixture_python.symlink_to(Path(sys.executable).resolve())
    fixture_site = (
        repository
        / ".venv"
        / "lib"
        / f"python{sys.version_info.major}.{sys.version_info.minor}"
        / "site-packages"
    )
    fixture_site.mkdir(parents=True)
    active_site = Path(sysconfig.get_path("purelib")).resolve(strict=True)
    for entry in active_site.iterdir():
        (fixture_site / entry.name).symlink_to(
            entry,
            target_is_directory=entry.is_dir(),
        )
    return repository


def test_upgrade_forbids_source_trees_without_forbidding_its_venv(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    baseline_root = tmp_path / "work" / "baseline"
    final_root = tmp_path / "work" / "final"
    installed_module = (
        baseline_root
        / ".venv"
        / "lib"
        / "python3.11"
        / "site-packages"
        / "quant_system"
        / "__init__.py"
    )

    forbidden = _forbidden_source_roots(
        repository_root,
        baseline_root,
        final_root,
    )

    assert forbidden == (
        (repository_root / "src").resolve(),
        (baseline_root / "src").resolve(),
        (final_root / "src").resolve(),
    )
    assert all(not installed_module.resolve().is_relative_to(root) for root in forbidden)


def _probe_document(
    *,
    module: Path,
    site_packages: Path,
    direct_url: dict[str, object] | None = None,
    pth_text: str | None = None,
) -> dict[str, object]:
    pth = (
        [{"path": str(site_packages / "injected.pth"), "text": pth_text}]
        if pth_text is not None
        else []
    )
    return {
        "distribution": "quant-system",
        "version": "0.1.0",
        "module": str(module),
        "site_packages": str(site_packages),
        "sys_executable": str(site_packages.parents[2] / "bin" / "python"),
        "direct_url": direct_url,
        "pth": pth,
        "installed_file_count": 1,
        "installed_tree_sha256": "a" * 64,
    }


def test_import_probe_accepts_wheel_install_inside_baseline_environment(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    baseline_root = tmp_path / "work" / "baseline"
    final_root = tmp_path / "work" / "final"
    site_packages = baseline_root / ".venv/lib/python3.11/site-packages"
    document = _probe_document(
        module=site_packages / "quant_system/__init__.py",
        site_packages=site_packages,
        direct_url={"archive_info": {"hash": "sha256=abc"}, "url": "file:///wheel.whl"},
    )

    validation = _validate_import_probe(
        document,
        forbidden_roots=_forbidden_source_roots(
            repository_root,
            baseline_root,
            final_root,
        ),
    )

    assert validation["editable"] is False
    assert validation["source_root_import"] is False
    assert validation["source_root_pth"] is False


@pytest.mark.parametrize(
    ("mutation", "error"),
    (
        ("source-import", "source root"),
        ("editable", "editable direct_url"),
        ("source-pth", "PTH path"),
        ("source-pth-import", "PTH import"),
    ),
)
def test_import_probe_rejects_editable_and_source_injection(
    tmp_path: Path,
    mutation: str,
    error: str,
) -> None:
    repository_root = tmp_path / "repository"
    baseline_root = tmp_path / "work" / "baseline"
    final_root = tmp_path / "work" / "final"
    site_packages = baseline_root / ".venv/lib/python3.11/site-packages"
    module = site_packages / "quant_system/__init__.py"
    direct_url: dict[str, object] | None = None
    pth_text: str | None = None
    if mutation == "source-import":
        module = repository_root / "src/quant_system/__init__.py"
        site_packages = repository_root / "src"
    elif mutation == "editable":
        direct_url = {
            "dir_info": {"editable": True},
            "url": "file:///repository",
        }
    elif mutation == "source-pth":
        pth_text = str(final_root / "src")
    else:
        pth_text = f"import sys; sys.path.insert(0, {str(final_root / 'src')!r})"
    document = _probe_document(
        module=module,
        site_packages=site_packages,
        direct_url=direct_url,
        pth_text=pth_text,
    )

    with pytest.raises(ReleaseOperationError, match=error):
        _validate_import_probe(
            document,
            forbidden_roots=_forbidden_source_roots(
                repository_root,
                baseline_root,
                final_root,
            ),
        )


def test_noneditable_wrapper_has_no_masked_failure_or_health_probe() -> None:
    wrapper = (
        Path(__file__).resolve().parents[1] / "scripts" / "verify_agent_v02_noneditable_upgrade.sh"
    )
    source = wrapper.read_text(encoding="utf-8")
    assert "||" + " true" not in source
    assert "/api/" + "health" not in source


def test_noneditable_wrapper_executes_tracked_source_from_hostile_cwd(
    tmp_path: Path,
) -> None:
    repository_root = _materialize_noneditable_wrapper_fixture(tmp_path / "fixture")
    wrapper = repository_root / "scripts" / "verify_agent_v02_noneditable_upgrade.sh"
    hostile_cwd = tmp_path / "hostile-cwd"
    hostile_release_ops = hostile_cwd / "quant_system" / "ops"
    hostile_release_ops.mkdir(parents=True)
    (hostile_cwd / "quant_system" / "__init__.py").write_text("", encoding="utf-8")
    (hostile_release_ops / "__init__.py").write_text("", encoding="utf-8")
    cwd_marker = tmp_path / "hostile-cwd-imported"
    site_marker = tmp_path / "hostile-sitecustomize-imported"
    (hostile_release_ops / "release_ops.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(cwd_marker)!r}).write_text('loaded', encoding='utf-8')\n",
        encoding="utf-8",
    )
    (hostile_cwd / "sitecustomize.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(site_marker)!r}).write_text('loaded', encoding='utf-8')\n",
        encoding="utf-8",
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = str(hostile_cwd)

    completed = subprocess.run(
        (
            str(wrapper),
            "--output-dir",
            str(tmp_path / "help-output"),
            "--help",
        ),
        cwd=hostile_cwd,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
    assert not cwd_marker.exists(), "wrapper imported hostile cwd release_ops"
    assert not site_marker.exists(), "wrapper executed hostile sitecustomize"
    assert "--output-dir" in completed.stdout
    assert "--uv-binary" in completed.stdout
    assert (tmp_path / "help-output" / "bootstrap-source-authority.json").is_file()
    source = wrapper.read_text(encoding="utf-8")
    assert '"-I"' in source
    assert '"-S"' in source
    assert "PYTHONPATH" not in source


def test_noneditable_wrapper_rejects_real_head_move_after_archive(
    tmp_path: Path,
) -> None:
    repository = _materialize_noneditable_wrapper_fixture(
        tmp_path / "fixture",
        pause_after_archive_identity_check=True,
    )
    wrapper = repository / "scripts" / "verify_agent_v02_noneditable_upgrade.sh"
    first_commit = subprocess.run(
        ("/usr/bin/git", "rev-parse", "HEAD"),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    barrier = tmp_path / "head-move-barrier"
    output = tmp_path / "head-move-rejected"
    environment = dict(os.environ)
    environment["AGENT_V02_TEST_HEAD_MOVE_BARRIER"] = str(barrier)

    process = subprocess.Popen(
        (
            str(wrapper),
            "--output-dir",
            str(output),
            "--uv-binary",
            "/usr/bin/false",
        ),
        cwd=tmp_path,
        env=environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    ready = barrier.with_suffix(".ready")
    deadline = time.monotonic() + 10
    while not ready.is_file():
        if process.poll() is not None:
            stdout, stderr = process.communicate()
            pytest.fail(f"wrapper exited before HEAD-move barrier: {stdout=} {stderr=}")
        if time.monotonic() >= deadline:
            process.kill()
            process.wait()
            pytest.fail("wrapper did not reach the HEAD-move barrier")
        time.sleep(0.01)

    moved_source = repository / "src" / "quant_system" / "head_move_fixture.py"
    moved_source.write_text("MOVED_AFTER_BOOTSTRAP = True\n", encoding="utf-8")
    subprocess.run(
        ("/usr/bin/git", "add", moved_source.relative_to(repository).as_posix()),
        cwd=repository,
        check=True,
    )
    subprocess.run(
        ("/usr/bin/git", "commit", "-qm", "move HEAD after bootstrap archive"),
        cwd=repository,
        check=True,
    )
    second_commit = subprocess.run(
        ("/usr/bin/git", "rev-parse", "HEAD"),
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    assert second_commit != first_commit
    barrier.with_suffix(".release").write_text("resume\n", encoding="utf-8")

    stdout, stderr = process.communicate(timeout=20)
    assert process.returncode == 78, (stdout, stderr)
    assert "identity changed after bootstrap capture" in stderr
    authority = json.loads((output / "bootstrap-source-authority.json").read_text(encoding="utf-8"))
    assert authority["commit"] == first_commit
    assert not (
        output / "bootstrap-source" / "src" / "quant_system" / "head_move_fixture.py"
    ).exists()
    assert not (output / "noneditable-upgrade-receipt.json").exists()

    recovered_output = tmp_path / "head-move-recovered"
    recovered = subprocess.run(
        (
            str(wrapper),
            "--output-dir",
            str(recovered_output),
            "--help",
        ),
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    assert recovered.returncode == 0, recovered.stderr
    recovered_authority = json.loads(
        (recovered_output / "bootstrap-source-authority.json").read_text(encoding="utf-8")
    )
    assert recovered_authority["commit"] == second_commit
    assert (
        recovered_output / "bootstrap-source" / "src" / "quant_system" / "head_move_fixture.py"
    ).is_file()


def test_final_dependency_sync_must_preserve_the_installed_baseline() -> None:
    from quant_system.ops import noneditable_upgrade as upgrade_ops

    validator = getattr(upgrade_ops, "_validate_upgrade_continuity", None)
    assert callable(validator), "upgrade rehearsal lacks a baseline continuity gate"
    baseline = {
        "distribution": "quant-system",
        "version": "0.1.0",
        "module": "/evidence/work/upgrade/.venv/site-packages/quant_system/__init__.py",
        "site_packages": "/evidence/work/upgrade/.venv/site-packages",
        "sys_executable": "/evidence/work/upgrade/.venv/bin/python",
        "direct_url": {
            "archive_info": {"hash": "sha256=baseline"},
            "url": "file:///evidence/baseline.whl",
        },
        "pth": [],
        "installed_file_count": 100,
        "installed_tree_sha256": "a" * 64,
    }

    accepted = validator(baseline, dict(baseline))
    assert accepted["baseline_distribution_preserved"] is True
    removed = dict(baseline)
    removed["distribution"] = None
    with pytest.raises(ReleaseOperationError, match="baseline distribution"):
        validator(baseline, removed)


def test_import_probe_rejects_unlisted_clone_and_executable_pth() -> None:
    repository_root = Path("/evidence/release")
    baseline_root = Path("/evidence/work/baseline")
    final_root = Path("/evidence/work/final")
    environment = baseline_root / ".venv"
    external_source = Path("/evidence/unlisted-clone/src")
    external = _probe_document(
        module=external_source / "quant_system/__init__.py",
        site_packages=external_source,
        direct_url={
            "archive_info": {"hash": "sha256=external"},
            "url": "file:///evidence/external.whl",
        },
    )

    with pytest.raises(ReleaseOperationError, match="target environment"):
        _validate_import_probe(
            external,
            forbidden_roots=_forbidden_source_roots(
                repository_root,
                baseline_root,
                final_root,
            ),
        )

    site_packages = environment / "lib/python3.11/site-packages"
    executable_pth = _probe_document(
        module=site_packages / "quant_system/__init__.py",
        site_packages=site_packages,
        direct_url={
            "archive_info": {"hash": "sha256=wheel"},
            "url": "file:///evidence/wheel.whl",
        },
        pth_text=(f"import sys; sys.path.insert(0, {str(external_source)!r})"),
    )
    with pytest.raises(ReleaseOperationError, match="PTH import"):
        _validate_import_probe(
            executable_pth,
            forbidden_roots=_forbidden_source_roots(
                repository_root,
                baseline_root,
                final_root,
            ),
        )


def test_upgrade_process_environment_is_owner_local_and_offline(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quant_system.ops import noneditable_upgrade as upgrade_ops

    monkeypatch.setenv("PYTHONPATH", "/forbidden/clone/src")
    monkeypatch.setenv("UV_INDEX_URL", "https://token@example.invalid/simple")
    monkeypatch.setenv("QS_FUTU_HOST", "provider.example.invalid")
    builder = getattr(upgrade_ops, "_isolated_process_environment", None)
    assert callable(builder), "upgrade rehearsal lacks a contained environment"

    output_dir = tmp_path / "evidence"
    output_dir.mkdir(mode=0o700)
    environment, facts = builder(output_dir)
    required_paths = (
        "HOME",
        "TMPDIR",
        "TMP",
        "TEMP",
        "XDG_CACHE_HOME",
        "PYTHONPYCACHEPREFIX",
        "UV_CACHE_DIR",
    )
    for name in required_paths:
        value = Path(environment[name]).resolve()
        assert value.is_relative_to(output_dir.resolve())
        assert value.is_dir()
    assert environment["UV_OFFLINE"] == "1"
    assert environment["PIP_NO_INDEX"] == "1"
    assert environment["UV_NO_CONFIG"] == "1"
    assert "PYTHONPATH" not in environment
    assert "UV_INDEX_URL" not in environment
    assert "QS_FUTU_HOST" not in environment
    assert facts["network"] == "denied"


def test_upgraded_and_fresh_final_environments_are_independent_and_equivalent() -> None:
    from quant_system.ops import noneditable_upgrade as upgrade_ops

    validator = getattr(upgrade_ops, "_validate_final_environment_equivalence", None)
    assert callable(validator), "upgrade rehearsal lacks a fresh-final control"
    upgraded = {
        "distribution": "quant-system",
        "version": "0.1.0",
        "module": "/evidence/work/baseline/.venv/site-packages/quant_system/__init__.py",
        "site_packages": "/evidence/work/baseline/.venv/site-packages",
        "sys_executable": "/evidence/work/baseline/.venv/bin/python",
        "package_file_count": 250,
        "package_tree_sha256": "c" * 64,
    }
    fresh = {
        **upgraded,
        "module": "/evidence/work/final/.venv/site-packages/quant_system/__init__.py",
        "site_packages": "/evidence/work/final/.venv/site-packages",
        "sys_executable": "/evidence/work/final/.venv/bin/python",
    }

    accepted = validator(upgraded, fresh)
    assert accepted["independent_environments"] is True
    assert accepted["equivalent_final_installations"] is True
    with pytest.raises(ReleaseOperationError, match="not independent"):
        validator(upgraded, dict(upgraded))
    drifted = dict(fresh)
    drifted["package_tree_sha256"] = "d" * 64
    with pytest.raises(ReleaseOperationError, match="final installations differ"):
        validator(upgraded, drifted)


def test_upgrade_rechecks_exact_repository_identity_before_passing(
    tmp_path: Path,
) -> None:
    import subprocess

    from quant_system.ops import noneditable_upgrade as upgrade_ops

    repository = tmp_path / "repository"
    repository.mkdir()
    commands = (
        ("/usr/bin/git", "init", "-q", "-b", "codex/agent-v0-2-release"),
        ("/usr/bin/git", "config", "user.email", "upgrade@example.invalid"),
        ("/usr/bin/git", "config", "user.name", "Upgrade Test"),
        (
            "/usr/bin/git",
            "remote",
            "add",
            "github",
            upgrade_ops.CANONICAL_GITHUB_REMOTE,
        ),
    )
    for command in commands:
        subprocess.run(command, cwd=repository, check=True)
    tracked = repository / "tracked.txt"
    tracked.write_text("before\n", encoding="utf-8")
    subprocess.run(("/usr/bin/git", "add", "tracked.txt"), cwd=repository, check=True)
    subprocess.run(("/usr/bin/git", "commit", "-qm", "fixture"), cwd=repository, check=True)
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    environment, _facts = upgrade_ops._isolated_process_environment(evidence)
    before = upgrade_ops._git_identity_in_environment(
        repository,
        env=environment,
        require_clean=True,
    )

    validator = getattr(upgrade_ops, "_validate_repository_postcondition", None)
    assert callable(validator), "upgrade rehearsal lacks a post-run identity gate"
    assert validator(repository, before, env=environment) == before
    tracked.write_text("after\n", encoding="utf-8")
    with pytest.raises(ReleaseOperationError, match="dirty|changed"):
        validator(repository, before, env=environment)


def test_command_log_records_digests_without_raw_credentials() -> None:
    import json

    from quant_system.ops import noneditable_upgrade as upgrade_ops

    renderer = getattr(upgrade_ops, "_safe_command_log_payload", None)
    assert callable(renderer), "upgrade command logs do not have a safe renderer"
    stdout = b"downloaded package\n"
    stderr = b"https://operator:secret@example.invalid/simple failed\n"
    payload = renderer(
        argv=["/opt/homebrew/bin/uv", "sync", "--offline"],
        exit_code=1,
        stdout=stdout,
        stderr=stderr,
    )
    assert b"operator" not in payload
    assert b"secret" not in payload
    assert stdout not in payload
    document = json.loads(payload)
    assert document["stdout_bytes"] == len(stdout)
    assert document["stderr_bytes"] == len(stderr)
    assert len(document["stdout_sha256"]) == 64
    assert len(document["stderr_sha256"]) == 64


def test_strict_probe_binds_wheel_interpreter_and_search_path(
    tmp_path: Path,
) -> None:
    import hashlib
    import zipfile

    from quant_system.ops import noneditable_upgrade as upgrade_ops

    environment = tmp_path / "upgrade" / ".venv"
    site_packages = environment / "lib/python3.11/site-packages"
    python = environment / "bin/python"
    wheel = tmp_path / "quant_system.whl"
    package_payload = b"__version__ = '0.1.0'\n"
    with zipfile.ZipFile(wheel, mode="w") as bundle:
        bundle.writestr("quant_system/__init__.py", package_payload)
        bundle.writestr(
            "quant_system-0.1.0.dist-info/entry_points.txt",
            "[console_scripts]\nquant-system = quant_system.cli:app\n",
        )
    wheel_sha256 = hashlib.sha256(wheel.read_bytes()).hexdigest()
    package_tree = hashlib.sha256()
    package_tree.update(b"__init__.py\0")
    package_tree.update(package_payload)
    package_tree.update(b"\0")
    document = {
        "distribution": "quant-system",
        "version": "0.1.0",
        "console_entry_points": [
            {
                "group": "console_scripts",
                "name": "quant-system",
                "value": "quant_system.cli:app",
            }
        ],
        "module": str(site_packages / "quant_system/__init__.py"),
        "module_raw": str(site_packages / "quant_system/__init__.py"),
        "module_symlink_components": [],
        "site_packages": str(site_packages),
        "site_roots": [str(site_packages)],
        "sys_executable": str(python),
        "sys_executable_raw": str(python),
        "sys_executable_symlink_components": [],
        "sys_prefix": str(environment),
        "sys_base_prefix": str(tmp_path / "python-base"),
        "sys_path": [
            str(environment / "lib/python3.11/site-packages"),
            str(tmp_path / "python-base/lib/python3.11"),
        ],
        "direct_url": {
            "present": True,
            "scheme": "file",
            "credential_present": False,
            "netloc_present": False,
            "query_present": False,
            "fragment_present": False,
            "url_sha256": hashlib.sha256(wheel.resolve().as_uri().encode("utf-8")).hexdigest(),
            "archive_sha256": wheel_sha256,
            "directory_install": False,
            "editable": False,
        },
        "pth": [],
        "installed_file_count": 2,
        "installed_tree_sha256": "2" * 64,
        "installed_symlink_components": [],
        "package_file_count": 1,
        "package_tree_sha256": package_tree.hexdigest(),
        "package_symlink_components": [],
        "environment_inventory_count": 2,
        "environment_inventory_sha256": "4" * 64,
        "network_attempt_count": 0,
    }

    accepted = upgrade_ops._validate_import_probe(
        document,
        forbidden_roots=(tmp_path / "release/src",),
        expected_python=python,
        expected_wheel=wheel,
        expected_version="0.1.0",
    )
    assert accepted["target_environment_bound"] is True
    assert accepted["credential_safe_metadata"] is True

    escaped = dict(document)
    escaped["sys_path"] = ["/unlisted/clone/src"]
    with pytest.raises(ReleaseOperationError, match="sys.path escapes"):
        upgrade_ops._validate_import_probe(
            escaped,
            forbidden_roots=(tmp_path / "release/src",),
            expected_python=python,
            expected_wheel=wheel,
            expected_version="0.1.0",
        )

    credentialed = dict(document)
    credentialed["direct_url"] = {
        **document["direct_url"],
        "credential_present": True,
    }
    with pytest.raises(ReleaseOperationError, match="credential-bearing"):
        upgrade_ops._validate_import_probe(
            credentialed,
            forbidden_roots=(tmp_path / "release/src",),
            expected_python=python,
            expected_wheel=wheel,
            expected_version="0.1.0",
        )


def test_probe_script_emits_no_raw_pth_or_direct_url(tmp_path: Path) -> None:
    import json
    import os
    import subprocess
    import sys

    from quant_system.ops.noneditable_upgrade import _probe_script

    private_paths = {
        name: tmp_path / name for name in ("home", "tmp", "xdg-cache", "pycache", "uv-cache")
    }
    for path in private_paths.values():
        path.mkdir(mode=0o700)
    environment = {
        "PATH": os.environ.get("PATH", os.defpath),
        "HOME": str(private_paths["home"]),
        "TMPDIR": str(private_paths["tmp"]),
        "TMP": str(private_paths["tmp"]),
        "TEMP": str(private_paths["tmp"]),
        "XDG_CACHE_HOME": str(private_paths["xdg-cache"]),
        "PYTHONPYCACHEPREFIX": str(private_paths["pycache"]),
        "UV_CACHE_DIR": str(private_paths["uv-cache"]),
        "UV_OFFLINE": "1",
        "PIP_NO_INDEX": "1",
        "PYTHONNOUSERSITE": "1",
    }
    completed = subprocess.run(
        [sys.executable, "-I", "-B", "-c", _probe_script()],
        check=False,
        capture_output=True,
        env=environment,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8", "replace")
    document = json.loads(completed.stdout)
    assert all("text" not in row for row in document["pth"])
    if document["direct_url"] is not None:
        assert "url" not in document["direct_url"]
    assert document["network_attempt_count"] == 0


def test_every_repository_git_path_uses_the_pinned_network_guard() -> None:
    import inspect

    from quant_system.ops import noneditable_upgrade as upgrade_ops

    argv = upgrade_ops._git_argv(Path("/release/platform"), "status", "--porcelain=v2")
    assert argv[:4] == [
        "/usr/bin/sandbox-exec",
        "-p",
        upgrade_ops.NETWORK_SANDBOX_PROFILE,
        "/usr/bin/git",
    ]
    assert "core.fsmonitor=false" in argv
    assert "core.hooksPath=/dev/null" in argv
    assert "credential.helper=" in argv
    assert "--no-replace-objects" in argv
    for operation in (
        upgrade_ops._archive_commit,
        upgrade_ops._git_identity_in_environment,
        upgrade_ops.verify_noneditable_upgrade,
    ):
        source = inspect.getsource(operation)
        assert "subprocess.run(" not in source
        assert "_run_git(" in source


@pytest.mark.parametrize(
    "index_flag",
    ("--assume-unchanged", "--skip-worktree"),
)
def test_contained_git_identity_rejects_hidden_index_bits(
    tmp_path: Path,
    index_flag: str,
) -> None:
    from quant_system.ops import noneditable_upgrade as upgrade_ops

    repository = tmp_path / "repository"
    _init_release_repository(repository)
    subprocess.run(
        ("/usr/bin/git", "update-index", index_flag, "tracked.txt"),
        cwd=repository,
        check=True,
    )
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    environment, _facts = upgrade_ops._isolated_process_environment(evidence)

    with pytest.raises(ReleaseOperationError, match="hidden index"):
        upgrade_ops._git_identity_in_environment(
            repository,
            env=environment,
            require_clean=True,
        )


def test_noneditable_wrapper_rejects_hidden_verifier_bytes_before_import(
    tmp_path: Path,
) -> None:
    repository = _materialize_noneditable_wrapper_fixture(tmp_path / "fixture")
    wrapper = repository / "scripts" / "verify_agent_v02_noneditable_upgrade.sh"
    scenarios = (
        ("--assume-unchanged", "--no-assume-unchanged", "release_ops.py"),
        ("--skip-worktree", "--no-skip-worktree", "noneditable_upgrade.py"),
    )
    for ordinal, (index_flag, clear_flag, filename) in enumerate(scenarios, start=1):
        relative = Path("src") / "quant_system" / "ops" / filename
        target = repository / relative
        original = target.read_bytes()
        marker = tmp_path / f"hidden-verifier-imported-{ordinal}"
        subprocess.run(
            ("/usr/bin/git", "update-index", index_flag, relative.as_posix()),
            cwd=repository,
            check=True,
        )
        source = original.decode("utf-8")
        insertion = (
            "from pathlib import Path as _HiddenMarkerPath\n"
            f"_HiddenMarkerPath({str(marker)!r}).write_text('loaded', encoding='utf-8')\n"
        )
        source = source.replace(
            "from __future__ import annotations\n",
            "from __future__ import annotations\n\n" + insertion,
            1,
        )
        target.write_text(source, encoding="utf-8")

        rejected_output = tmp_path / f"hidden-rejected-{ordinal}"
        rejected = subprocess.run(
            (
                str(wrapper),
                "--output-dir",
                str(rejected_output),
                "--uv-binary",
                "/usr/bin/false",
            ),
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )
        assert rejected.returncode == 78
        assert "hidden index bits" in rejected.stderr
        assert not marker.exists(), "hidden working-tree verifier executed before its guard"
        assert not (rejected_output / "noneditable-upgrade-receipt.json").exists()
        authority = json.loads(
            (rejected_output / "bootstrap-source-authority.json").read_text(encoding="utf-8")
        )
        committed = subprocess.run(
            ("/usr/bin/git", "rev-parse", "HEAD"),
            cwd=repository,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert authority["commit"] == committed

        target.write_bytes(original)
        subprocess.run(
            ("/usr/bin/git", "update-index", clear_flag, relative.as_posix()),
            cwd=repository,
            check=True,
        )
        clean_help = subprocess.run(
            (
                str(wrapper),
                "--output-dir",
                str(tmp_path / f"clean-help-{ordinal}"),
                "--help",
            ),
            cwd=tmp_path,
            check=False,
            capture_output=True,
            text=True,
        )
        assert clean_help.returncode == 0, clean_help.stderr
        assert "--uv-binary" in clean_help.stdout
        assert not marker.exists()


def test_contained_git_identity_rejects_replace_refs(
    tmp_path: Path,
) -> None:
    from quant_system.ops import noneditable_upgrade as upgrade_ops

    repository = tmp_path / "repository"
    first, second = _init_release_repository(repository)
    subprocess.run(
        ("/usr/bin/git", "replace", first, second),
        cwd=repository,
        check=True,
    )
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    environment, _facts = upgrade_ops._isolated_process_environment(evidence)

    with pytest.raises(ReleaseOperationError, match="replace refs"):
        upgrade_ops._git_identity_in_environment(
            repository,
            env=environment,
            require_clean=True,
        )


def test_contained_git_identity_rejects_linked_worktree_grafts(
    tmp_path: Path,
) -> None:
    from quant_system.ops import noneditable_upgrade as upgrade_ops

    repository = tmp_path / "repository"
    first, second = _init_release_repository(repository)
    linked = tmp_path / "linked"
    subprocess.run(
        ("/usr/bin/git", "worktree", "add", "--detach", str(linked), second),
        cwd=repository,
        check=True,
        capture_output=True,
    )
    git_path = subprocess.run(
        ("/usr/bin/git", "rev-parse", "--git-path", "info/grafts"),
        cwd=linked,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    grafts = Path(git_path)
    if not grafts.is_absolute():
        grafts = linked / grafts
    grafts.parent.mkdir(parents=True, exist_ok=True)
    grafts.write_text(f"{second} {first}\n", encoding="ascii")
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    environment, _facts = upgrade_ops._isolated_process_environment(evidence)

    with pytest.raises(ReleaseOperationError, match="grafts"):
        upgrade_ops._git_identity_in_environment(
            linked,
            env=environment,
            require_clean=True,
        )


@pytest.mark.parametrize(
    "hostile_variable",
    ("GIT_REPLACE_REF_BASE", "GIT_CONFIG_GLOBAL"),
)
def test_contained_git_identity_rejects_hostile_git_environment(
    tmp_path: Path,
    hostile_variable: str,
) -> None:
    from quant_system.ops import noneditable_upgrade as upgrade_ops

    repository = tmp_path / "repository"
    _init_release_repository(repository)
    hostile_config = tmp_path / "hostile.gitconfig"
    hostile_config.write_text("[core]\n\tfsmonitor = true\n", encoding="utf-8")
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    environment, _facts = upgrade_ops._isolated_process_environment(evidence)
    environment[hostile_variable] = (
        "refs/hostile-replacements"
        if hostile_variable == "GIT_REPLACE_REF_BASE"
        else str(hostile_config)
    )

    with pytest.raises(ReleaseOperationError, match="Git environment overrides"):
        upgrade_ops._git_identity_in_environment(
            repository,
            env=environment,
            require_clean=True,
        )


def test_contained_git_identity_rejects_noncanonical_remote_without_leaking_it(
    tmp_path: Path,
) -> None:
    import subprocess

    from quant_system.ops import noneditable_upgrade as upgrade_ops

    repository = tmp_path / "repository"
    repository.mkdir()
    commands = (
        ("/usr/bin/git", "init", "-q", "-b", "codex/agent-v0-2-release"),
        ("/usr/bin/git", "config", "user.email", "upgrade@example.invalid"),
        ("/usr/bin/git", "config", "user.name", "Upgrade Test"),
        (
            "/usr/bin/git",
            "remote",
            "add",
            "github",
            "https://operator:do-not-leak@example.invalid/platform.git",
        ),
    )
    for command in commands:
        subprocess.run(command, cwd=repository, check=True)
    (repository / "tracked.txt").write_text("fixture\n", encoding="utf-8")
    subprocess.run(("/usr/bin/git", "add", "tracked.txt"), cwd=repository, check=True)
    subprocess.run(("/usr/bin/git", "commit", "-qm", "fixture"), cwd=repository, check=True)
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    environment, _facts = upgrade_ops._isolated_process_environment(evidence)

    with pytest.raises(ReleaseOperationError) as caught:
        upgrade_ops._git_identity_in_environment(
            repository,
            env=environment,
            require_clean=True,
        )

    rendered = str(caught.value)
    assert "canonical publication URL" in rendered
    assert "operator" not in rendered
    assert "do-not-leak" not in rendered


@pytest.mark.parametrize("push_override", ("pushurl", "pushInsteadOf"))
def test_contained_git_identity_rejects_noncanonical_effective_push_without_leak(
    tmp_path: Path,
    push_override: str,
) -> None:
    import subprocess

    from quant_system.ops import noneditable_upgrade as upgrade_ops

    repository = tmp_path / "repository"
    repository.mkdir()
    commands = (
        ("/usr/bin/git", "init", "-q", "-b", "codex/agent-v0-2-release"),
        ("/usr/bin/git", "config", "user.email", "upgrade@example.invalid"),
        ("/usr/bin/git", "config", "user.name", "Upgrade Test"),
        (
            "/usr/bin/git",
            "remote",
            "add",
            "github",
            upgrade_ops.CANONICAL_GITHUB_REMOTE,
        ),
    )
    for command in commands:
        subprocess.run(command, cwd=repository, check=True)
    if push_override == "pushurl":
        subprocess.run(
            (
                "/usr/bin/git",
                "config",
                "remote.github.pushurl",
                "https://operator:push-secret@example.invalid/platform.git",
            ),
            cwd=repository,
            check=True,
        )
    else:
        subprocess.run(
            (
                "/usr/bin/git",
                "config",
                "url.https://operator:push-secret@example.invalid/.pushInsteadOf",
                "https://github.com/YIBOWAY/",
            ),
            cwd=repository,
            check=True,
        )
    (repository / "tracked.txt").write_text("fixture\n", encoding="utf-8")
    subprocess.run(("/usr/bin/git", "add", "tracked.txt"), cwd=repository, check=True)
    subprocess.run(("/usr/bin/git", "commit", "-qm", "fixture"), cwd=repository, check=True)
    evidence = tmp_path / "evidence"
    evidence.mkdir(mode=0o700)
    environment, _facts = upgrade_ops._isolated_process_environment(evidence)

    with pytest.raises(ReleaseOperationError) as caught:
        upgrade_ops._git_identity_in_environment(
            repository,
            env=environment,
            require_clean=True,
        )

    rendered = str(caught.value)
    assert "canonical publication URL" in rendered
    assert "operator" not in rendered
    assert "push-secret" not in rendered


def test_cli_install_binds_exact_python_wheel_entry_point_and_normalized_script(
    tmp_path: Path,
) -> None:
    import zipfile

    from quant_system.ops import noneditable_upgrade as upgrade_ops

    environment = tmp_path / "environment"
    bin_dir = environment / "bin"
    bin_dir.mkdir(parents=True)
    python = bin_dir / "python"
    python.write_bytes(b"pinned interpreter fixture\n")
    python.chmod(0o700)
    cli = bin_dir / "quant-system"
    script_body = upgrade_ops.EXPECTED_CONSOLE_SCRIPT_BODY
    cli.write_text(f"#!{python}\n{script_body}", encoding="utf-8")
    cli.chmod(0o700)
    wheel = tmp_path / "quant_system-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(wheel, mode="w") as bundle:
        bundle.writestr("quant_system/__init__.py", b"")
        bundle.writestr(
            "quant_system-0.1.0.dist-info/entry_points.txt",
            "[console_scripts]\nquant-system = quant_system.cli:app\n",
        )
    probe = {
        "console_entry_points": [
            {
                "group": "console_scripts",
                "name": "quant-system",
                "value": "quant_system.cli:app",
            }
        ]
    }

    accepted = upgrade_ops._cli_install_facts(
        cli_path=cli,
        expected_python=python,
        expected_wheel=wheel,
        import_probe=probe,
    )
    assert accepted["target_environment_bound"] is True
    assert accepted["console_entry_point"] == "quant_system.cli:app"
    assert len(str(accepted["normalized_script_sha256"])) == 64

    foreign = bin_dir / "foreign-python"
    foreign.write_bytes(b"foreign interpreter fixture\n")
    foreign.chmod(0o700)
    cli.write_text(f"#!{foreign}\n{script_body}", encoding="utf-8")
    with pytest.raises(ReleaseOperationError, match="foreign interpreter"):
        upgrade_ops._cli_install_facts(
            cli_path=cli,
            expected_python=python,
            expected_wheel=wheel,
            import_probe=probe,
        )

    cli.write_text(
        f"#!{python}\n"
        + script_body.replace(
            "    sys.exit(app())\n",
            "    app = lambda: 0\n    sys.exit(app())\n",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ReleaseOperationError, match="canonical generated wrapper"):
        upgrade_ops._cli_install_facts(
            cli_path=cli,
            expected_python=python,
            expected_wheel=wheel,
            import_probe=probe,
        )
