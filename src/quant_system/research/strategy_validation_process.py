"""Run API validation in the same Python 3.11 environment as Hermes."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from quant_system.research import strategy_library as service

_ROOT = Path(__file__).resolve().parents[3]
_TIMEOUT_SECONDS = 600


class _ProcessFailure(RuntimeError):
    pass


def _current_is_python311():
    return sys.version_info[:2] == (3, 11)


def _record_failure(settings, strategy_id, digest, code):
    directory = service._directory(settings, strategy_id)
    entry = json.loads((directory / "entry.json").read_text())
    receipt = {
        "contract": "quant_system.strategy_validation_process/v1",
        "strategy_id": strategy_id,
        "definition_digest": digest,
        "status": "validation_failed",
        "error": code,
        "created_at": datetime.now(UTC).isoformat(),
    }
    path = directory / "failures" / f"process-{uuid4().hex}.json"
    service._write(path, receipt)
    if entry.get("definition_digest") == digest and entry.get("status") != "paper_running":
        entry.update(status="validation_failed", error=code, process_failure_receipt=path.name)
        service._write(directory / "entry.json", entry)


def validate_in_research_runtime(settings, strategy_id, digest):
    """One bounded attempt. Domain validation owns all candidate and validation files."""
    try:
        if _current_is_python311():
            return service.validate_strategy(settings, strategy_id, digest)
        python = Path(os.environ.get("QS_D34_WORKER_PYTHON") or _ROOT / ".venv/bin/python")
        if not python.is_absolute() or not os.access(python, os.X_OK):
            raise _ProcessFailure("strategy_validation_python_unavailable")
        probe = subprocess.run(
            [
                str(python),
                "-I",
                "-B",
                "-c",
                "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 11) else 1)",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=False,
        )
        if probe.returncode != 0:
            raise _ProcessFailure("strategy_validation_python_version_invalid")
        env = os.environ.copy()
        env.update(
            QS_DATA_DIR=str(settings.data.data_dir.resolve()),
            PYTHONPATH=str(_ROOT / "src"),
            QS_DATABASE_AUTO_MIGRATE="false",
            PYTHONNOUSERSITE="1",
            PYTHONDONTWRITEBYTECODE="1",
        )
        for key in ("PYTHONHOME", "PYTHONSTARTUP", "PYTHONINSPECT"):
            env.pop(key, None)
        result = subprocess.run(
            [
                str(python),
                "-B",
                "-m",
                "quant_system.research.strategy_library_cli",
                "validate",
                strategy_id,
                "--expected-digest",
                digest,
            ],
            cwd=_ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=_TIMEOUT_SECONDS,
            check=False,
        )
        entry = json.loads((service._directory(settings, strategy_id) / "entry.json").read_text())
        if entry.get("status") == "validation_failed":
            return entry  # Preserve the domain's actual gate failures and their receipts.
        if result.returncode != 0:
            raise _ProcessFailure("strategy_validation_process_failed")
        if entry.get("status") not in {"validated", "paper_running"}:
            raise _ProcessFailure("strategy_validation_process_incomplete")
        return entry
    except subprocess.TimeoutExpired:
        _record_failure(settings, strategy_id, digest, "strategy_validation_process_timeout")
    except Exception as exc:
        code = (
            str(exc) if isinstance(exc, _ProcessFailure) else "strategy_validation_process_failed"
        )
        _record_failure(settings, strategy_id, digest, code)
    return None
