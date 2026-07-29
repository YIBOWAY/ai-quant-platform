from __future__ import annotations

import importlib.util
import inspect
import stat
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "scripts" / "backend_non_postgres_gate.py"


def _gate_helper():
    spec = importlib.util.spec_from_file_location(
        "backend_non_postgres_gate_installed_tree",
        HELPER,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = _gate_helper()


def test_installed_tree_identity_is_content_mode_and_path_bound(
    tmp_path: Path,
) -> None:
    package = tmp_path / "site-packages" / "quant_system"
    nested = package / "nested"
    nested.mkdir(parents=True)
    (package / "__init__.py").write_text("VERSION = 1\n", encoding="utf-8")
    (nested / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    for path in (package, nested):
        path.chmod(0o700)
    for path in (package / "__init__.py", nested / "module.py"):
        path.chmod(0o600)

    first = gate.installed_quant_system_tree_identity(
        package / "__init__.py"
    )
    second = gate.installed_quant_system_tree_identity(
        package / "__init__.py"
    )
    assert first == second
    assert first["file_count"] == 2
    assert first["root"] == str(package.resolve())
    assert len(first["tree_sha256"]) == 64

    (nested / "module.py").write_text("VALUE = 3\n", encoding="utf-8")
    changed_bytes = gate.installed_quant_system_tree_identity(
        package / "__init__.py"
    )
    assert changed_bytes["tree_sha256"] != first["tree_sha256"]

    (nested / "module.py").write_text("VALUE = 2\n", encoding="utf-8")
    (nested / "module.py").chmod(0o700)
    changed_mode = gate.installed_quant_system_tree_identity(
        package / "__init__.py"
    )
    assert changed_mode["tree_sha256"] != first["tree_sha256"]


def test_installed_tree_identity_rejects_symlink_or_writable_entries(
    tmp_path: Path,
) -> None:
    package = tmp_path / "quant_system"
    package.mkdir(mode=0o700)
    module = package / "__init__.py"
    module.write_text("VALUE = 1\n", encoding="utf-8")
    module.chmod(0o600)
    (package / "escape.py").symlink_to(module)

    with pytest.raises(
        gate.GateError,
        match="installed_quant_system_tree_entry_unsafe",
    ):
        gate.installed_quant_system_tree_identity(module)

    (package / "escape.py").unlink()
    module.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IWGRP)
    with pytest.raises(
        gate.GateError,
        match="installed_quant_system_tree_entry_unsafe",
    ):
        gate.installed_quant_system_tree_identity(module)


def test_gate2_run_seals_and_compares_installed_tree_before_and_after() -> None:
    source = inspect.getsource(gate.run_gate)
    assert 'receipt["installed_quant_system_tree_before"]' in source
    assert 'receipt["installed_quant_system_tree_after"]' in source
    assert "installed_quant_system_tree_changed" in source
    assert 'receipt["installed_environment_tree_before"]' in source
    assert 'receipt["installed_environment_tree_after"]' in source
    assert "installed_environment_tree_changed" in source


def test_installed_environment_tree_binds_dependency_bytes_and_symlink_targets(
    tmp_path: Path,
) -> None:
    environment = tmp_path / "venv"
    dependency = environment / "lib" / "python3.11" / "site-packages" / "uvicorn"
    dependency.mkdir(parents=True)
    executable = environment / "interpreter"
    executable.write_bytes(b"python-runtime\n")
    executable.chmod(0o500)
    python = environment / "bin" / "python"
    python.parent.mkdir()
    python.symlink_to(executable)
    module = dependency / "__main__.py"
    module.write_text("print('trusted')\n", encoding="utf-8")
    for directory in (
        environment,
        environment / "bin",
        environment / "lib",
        environment / "lib" / "python3.11",
        environment / "lib" / "python3.11" / "site-packages",
        dependency,
    ):
        directory.chmod(0o700)
    module.chmod(0o600)

    first = gate.installed_environment_tree_identity(environment)
    assert first["root"] == str(environment.resolve())
    assert first["entry_count"] >= 7

    module.write_text("print('forged')\n", encoding="utf-8")
    dependency_tamper = gate.installed_environment_tree_identity(environment)
    assert dependency_tamper["tree_sha256"] != first["tree_sha256"]

    module.write_text("print('trusted')\n", encoding="utf-8")
    executable.chmod(0o700)
    executable.write_bytes(b"changed-runtime\n")
    executable.chmod(0o500)
    runtime_tamper = gate.installed_environment_tree_identity(environment)
    assert runtime_tamper["tree_sha256"] != first["tree_sha256"]


def test_installed_environment_tree_rejects_unsafe_or_broken_entries(
    tmp_path: Path,
) -> None:
    environment = tmp_path / "venv"
    environment.mkdir(mode=0o700)
    broken = environment / "broken"
    broken.symlink_to(environment / "missing")
    with pytest.raises(
        gate.GateError,
        match="installed_environment_tree_entry_unsafe",
    ):
        gate.installed_environment_tree_identity(environment)

    broken.unlink()
    dependency = environment / "dependency.py"
    dependency.write_text("VALUE = 1\n", encoding="utf-8")
    dependency.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IWGRP)
    with pytest.raises(
        gate.GateError,
        match="installed_environment_tree_entry_unsafe",
    ):
        gate.installed_environment_tree_identity(environment)


def test_uv_environment_lock_is_narrowly_normalized_before_tree_seal(
    tmp_path: Path,
) -> None:
    environment = tmp_path / "venv"
    environment.mkdir(mode=0o700)
    lock = environment / ".lock"
    lock.write_bytes(b"")
    lock.chmod(0o666)

    normalization = gate.normalize_installed_environment_lock(environment)

    assert normalization["path"] == ".lock"
    assert normalization["before_mode"] == "666"
    assert normalization["after_mode"] == "600"
    assert stat.S_IMODE(lock.stat().st_mode) == 0o600
    identity = gate.installed_environment_tree_identity(environment)
    assert identity["entry_count"] == 1

    lock.unlink()
    lock.symlink_to(environment / "missing")
    with pytest.raises(
        gate.GateError,
        match="installed_environment_lock_unsafe",
    ):
        gate.normalize_installed_environment_lock(environment)
