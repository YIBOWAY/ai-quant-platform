from __future__ import annotations

import os
import subprocess
import sys
import venv
from pathlib import Path

from tests import agent_v02_zero_effect_test_support as support


def test_fixture_cli_rebinds_copied_venv_python_to_base_interpreter(
    monkeypatch,
    tmp_path: Path,
) -> None:
    base_executable = Path(sys._base_executable).resolve()
    copied_venv = tmp_path / "copied-venv"
    venv.EnvBuilder(with_pip=False, symlinks=False).create(copied_venv)
    copied_python = copied_venv / "bin" / "python3"
    assert copied_python.is_file()
    assert not copied_python.is_symlink()
    monkeypatch.setattr(support.sys, "executable", str(copied_python))

    repository = support.materialize_platform_repository(tmp_path / "platform")
    fixture_python = repository / ".venv" / "bin" / "python3"
    completed = subprocess.run(
        [str(fixture_python), "-I", "-B", "-c", "import encodings"],
        env={"PATH": os.defpath},
        check=False,
        capture_output=True,
        text=True,
    )

    assert fixture_python.resolve() == base_executable
    assert completed.returncode == 0, completed.stderr
