from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[1]
DRIVER = ROOT / "scripts" / "run_factor_automation_driver.sh"


def _driver_fixture(tmp_path: Path) -> tuple[dict[str, str], Path]:
    hqa_root = tmp_path / "stable-hqa"
    (hqa_root / "hqa").mkdir(parents=True)
    fake_python = hqa_root / "python"
    fake_python.write_text(
        "#!/bin/bash\n"
        "printf 'argv=%s\\n' \"$*\"\n"
        "printf 'hqa_mode=%s auto_land=%s\\n' "
        '"${HQA_FACTOR_AUTOMATION_MODE:-}" '
        '"${HQA_FACTOR_AUTOMATION_AUTO_LAND:-}"\n',
        encoding="utf-8",
    )
    fake_python.chmod(0o700)
    env_file = tmp_path / "owner.env"
    env_file.write_text(
        "\n".join(
            (
                f"QS_INTENT_PAYLOAD_HQA_ROOT={hqa_root}",
                f"QS_INTENT_PAYLOAD_PYTHON_EXECUTABLE={fake_python}",
                "HQA_FACTOR_AUTOMATION_MODE=true",
                "HQA_FACTOR_AUTOMATION_AUTO_LAND=true",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    env_file.chmod(0o600)
    return dict(os.environ, QS_AGENT_V02_BACKEND_ENV_FILE=str(env_file)), env_file


def test_factor_automation_driver_defaults_to_resident_run_once(tmp_path: Path) -> None:
    env, _env_file = _driver_fixture(tmp_path)

    result = subprocess.run(
        ["bash", str(DRIVER)],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "argv=-m hqa.factor_automation_cli run-once",
        "hqa_mode=true auto_land=true",
    ]


def test_factor_automation_driver_forwards_exact_enqueue_with_owner_flags(
    tmp_path: Path,
) -> None:
    env, _env_file = _driver_fixture(tmp_path)
    request = tmp_path / "request.json"

    result = subprocess.run(
        [
            "bash",
            str(DRIVER),
            "enqueue",
            "--request-file",
            str(request),
        ],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        f"argv=-m hqa.factor_automation_cli enqueue --request-file {request}",
        "hqa_mode=true auto_land=true",
    ]


def test_factor_automation_driver_rejects_unbounded_operation(tmp_path: Path) -> None:
    env, _env_file = _driver_fixture(tmp_path)

    result = subprocess.run(
        ["bash", str(DRIVER), "run-once"],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 78
    assert result.stderr.strip() == "factor_automation_driver_error=operation_invalid"
