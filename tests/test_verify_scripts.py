import json
from pathlib import Path


def test_verify_scripts_run_core_checks_without_frontend_build_by_default() -> None:
    powershell = Path("scripts/verify.ps1").read_text(encoding="utf-8")
    shell = Path("scripts/verify.sh").read_text(encoding="utf-8")
    frontend_package = json.loads(
        Path("src/frontend/package.json").read_text(encoding="utf-8")
    )

    assert '@($PythonExe, "-m", "pytest", "-q")' in powershell
    assert '@($PythonExe, "-m", "ruff", "check", "src/quant_system", "tests")' in powershell
    assert '@("npm", "--prefix", "src/frontend", "run", "lint")' in powershell
    assert '@("npm", "--prefix", "src/frontend", "run", "type-check")' in powershell
    assert '@("npm", "--prefix", "src/frontend", "run", "test")' in powershell
    assert '@("npm", "--prefix", "src/frontend", "run", "build")' in powershell
    assert "[switch]$Build" in powershell
    assert "conda info --base" in powershell
    assert 'Join-Path $CondaBase "envs\\ai-quant\\python.exe"' in powershell
    assert '$env:PYTHONPATH = (Join-Path $Root "src")' in powershell
    assert powershell.index('"Pytest"') < powershell.index('"Frontend lint"')

    assert 'PYTHON_BIN="${PYTHON_BIN:-python}"' in shell
    assert '"$PYTHON_BIN" -m pytest -q' in shell
    assert 'export PYTHONPATH="$ROOT/src${PYTHONPATH:+:$PYTHONPATH}"' in shell
    assert '"$PYTHON_BIN" -m ruff check src/quant_system tests' in shell
    assert "npm --prefix src/frontend run lint" in shell
    assert "npm --prefix src/frontend run type-check" in shell
    assert "npm --prefix src/frontend run test" in shell
    assert "npm --prefix src/frontend run build" in shell
    assert "${RUN_BUILD:-0}" in shell
    assert frontend_package["scripts"]["type-check"] == "tsc --noEmit"


def test_conftest_reports_clear_python_version_guidance() -> None:
    conftest = Path("tests/conftest.py").read_text(encoding="utf-8")

    assert "Python 3.11+" in conftest
    assert "conda activate ai-quant" in conftest
