from __future__ import annotations

import subprocess
from pathlib import Path

from quant_system.ops.zero_effect import _fresh_release_status_observation
from tests.agent_v02_zero_effect_test_support import (
    materialize_platform_repository,
    run_fixture_script,
)


def _git_status(repository: Path) -> str:
    completed = subprocess.run(
        ["git", "status", "--short"],
        cwd=repository,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout


def test_fixture_subprocess_import_cannot_dirty_platform_authority(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)
    repository = materialize_platform_repository(tmp_path / "platform")

    completed = run_fixture_script(
        repository,
        "import quant_system.ops.zero_effect",
    )

    assert completed.returncode == 0, completed.stderr
    assert _git_status(repository) == ""


def test_release_status_subprocess_cannot_dirty_platform_authority(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.delenv("PYTHONDONTWRITEBYTECODE", raising=False)
    monkeypatch.delenv("PYTHONPYCACHEPREFIX", raising=False)
    repository = materialize_platform_repository(tmp_path / "platform")

    observation = _fresh_release_status_observation(
        platform_root=repository,
        state_dir=tmp_path / "state",
    )

    assert _git_status(repository) == ""
    assert observation["command"]["module_binding"]["python_dont_write_bytecode"] is True
