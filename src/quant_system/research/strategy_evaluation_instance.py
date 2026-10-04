"""Read-only recovery evidence for frozen, repeatable research computations."""

from __future__ import annotations

import fcntl
import json
import os
import subprocess
from pathlib import Path

from quant_system.research.intake_evaluation import file_hash, validate_snapshot
from quant_system.research.strategy_definition import validate_definition
from quant_system.research.study_runtime import resolve_docker_executable
from quant_system.research.validation_receipts import verify_validation_receipt


def find_evaluation(settings, directory, evaluation):
    validate_snapshot(settings, evaluation)
    definition_path = directory / "definition.json"
    definition = validate_definition(json.loads(definition_path.read_text()))
    paths = (directory / "validations").glob("*/evaluation-entry.json")
    for path in sorted(paths, key=lambda p: p.stat().st_mtime_ns, reverse=True):
        entry = json.loads(path.read_text())
        if entry.get("evaluation") != evaluation:
            continue
        validation = entry.get("validation")
        if not validation:
            # A recorded computation error is retryable, never a completed result.
            continue
        receipt = path.parent / "validation.json"
        if (
            file_hash(receipt) != entry.get("validation_sha256")
            or json.loads(receipt.read_text()) != validation
            or validation.get("evaluation") != evaluation
        ):
            raise ValueError("intake_archived_evaluation_changed")
        if (
            entry.get("strategy_id") != directory.name
            or entry.get("definition_digest") != definition.content_digest
            or entry.get("definition") != definition.model_dump(mode="json")
            or entry.get("source_sha256") != file_hash(definition_path)
        ):
            raise ValueError("intake_strategy_identity_mismatch")
        verified = verify_validation_receipt(
            receipt,
            expected_sha=entry["validation_sha256"],
            definition_digest=definition.content_digest,
            require_admission=False,
        )
        if verified["receipts"]["files"]["prices.parquet"] != evaluation["prices_sha256"]:
            raise ValueError("intake_archived_evaluation_changed")
        return entry
    return None


def computation_idle(settings, directory, evaluation):
    """Fail closed on alive PID, held lock, active mounted container or unknown Docker."""
    validate_snapshot(settings, evaluation)
    with (directory / "validation.lock").open("a+") as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return False
        runs = []
        for path in (directory / "validations").glob("*/evaluation-owner.json"):
            owner = json.loads(path.read_text())
            if owner.get("evaluation_id") != evaluation["evaluation_id"]:
                continue
            runs.append(path.parent.resolve())
            try:
                os.kill(owner["pid"], 0)
            except ProcessLookupError:
                pass
            except (PermissionError, TypeError, KeyError):
                return False
            else:
                # Completed current-process calls need no recovery. A still
                # running or potentially PID-reused owner is not known dead.
                return False
        if not runs:
            return False
        try:
            if not _docker_cli_idle(runs):
                return False
            docker = resolve_docker_executable()
            containers = subprocess.run(
                [docker, "ps", "-q"],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.split()
            if not containers:
                return True
            info = subprocess.run(
                [docker, "inspect", *containers],
                check=True,
                capture_output=True,
                text=True,
                timeout=10,
            )
            return not any(
                Path(mount.get("Source", "/")).resolve() in runs
                for item in json.loads(info.stdout)
                for mount in item.get("Mounts", [])
            )
        except (
            OSError,
            ValueError,
            TypeError,
            AttributeError,
            subprocess.SubprocessError,
            RuntimeError,
        ):
            return False


def _docker_cli_idle(runs):
    """An orphan CLI may still create its container after the Python owner died.

    Inspect command lines only for Docker executables, retain nothing and never
    emit process arguments (which may contain credentials).
    """
    processes = subprocess.run(
        ["/bin/ps", "-ww", "-axo", "pid=,comm="],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    for line in processes.stdout.splitlines():
        pid, executable = line.strip().split(maxsplit=1)
        if Path(executable).name not in {"docker", "com.docker.cli"}:
            continue
        if not pid.isdecimal():
            return False
        arguments = subprocess.run(
            ["/bin/ps", "-ww", "-p", pid, "-o", "args="],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
        if not arguments.strip() or any(str(run) in arguments for run in runs):
            return False
    return True
