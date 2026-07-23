from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from quant_system.hermes.managed_session_provisioner import (
    ManagedSessionProvisionError,
    SubprocessManagedSessionProvisionPort,
)
from quant_system.hermes.run_lifecycle_port import HermesRunCliSettings

ACTION_DIGEST = "d" * 64
SESSION_ID = f"web_{ACTION_DIGEST[:40]}"


def _port(tmp_path: Path, runner) -> SubprocessManagedSessionProvisionPort:
    python = tmp_path / "python"
    python.touch(mode=0o700)
    hqa_root = tmp_path / "hqa"
    hqa_root.mkdir()
    return SubprocessManagedSessionProvisionPort(
        cli_settings=HermesRunCliSettings(
            python_executable=python,
            hqa_root=hqa_root,
            base_url="http://127.0.0.1:8642",
            api_key="owner-secret",
            timeout_seconds=5,
        ),
        runner=runner,
    )


def test_ensure_uses_bounded_stdin_and_requires_exact_action_receipt(
    tmp_path: Path,
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(argv, **kwargs):
        request = json.loads(kwargs["input"])
        calls.append((list(argv), request))
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "session_id": SESSION_ID,
                    "action_digest": ACTION_DIGEST,
                    "created": True,
                    "recovered": False,
                    "session": {"id": SESSION_ID},
                }
            ).encode(),
            stderr=b"",
        )

    receipt = _port(tmp_path, runner).ensure_session(
        session_id=SESSION_ID,
        action_digest=ACTION_DIGEST,
    )

    assert receipt.session_id == SESSION_ID
    assert receipt.action_digest == ACTION_DIGEST
    assert receipt.created is True
    argv, request = calls[0]
    assert argv[-2:] == ["hqa.hermes_run_cli", "session-ensure"]
    assert "owner-secret" not in " ".join(argv)
    assert request == {
        "endpoint": {
            "api_key": "owner-secret",
            "base_url": "http://127.0.0.1:8642",
            "timeout_seconds": 5.0,
        },
        "action_digest": ACTION_DIGEST,
        "session_id": SESSION_ID,
    }


def test_fork_requires_exact_source_resolution_and_preserve_source(
    tmp_path: Path,
) -> None:
    source_id = "discord-source-real"

    def runner(argv, **kwargs):
        request = json.loads(kwargs["input"])
        assert request["source_session_id"] == source_id
        assert request["fork_point"] == "message:19"
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(
                {
                    "ok": True,
                    "session_id": SESSION_ID,
                    "action_digest": ACTION_DIGEST,
                    "source_session_id": source_id,
                    "resolved_source_session_id": source_id,
                    "fork_point": "message:19",
                    "preserve_source": True,
                    "created": False,
                    "recovered": True,
                    "session": {"id": SESSION_ID},
                }
            ).encode(),
            stderr=b"",
        )

    receipt = _port(tmp_path, runner).fork_session(
        source_session_id=source_id,
        session_id=SESSION_ID,
        fork_point="message:19",
        action_digest=ACTION_DIGEST,
    )

    assert receipt.source_session_id == source_id
    assert receipt.resolved_source_session_id == source_id
    assert receipt.preserve_source is True
    assert receipt.recovered is True


@pytest.mark.parametrize(
    "mutate",
    [
        lambda receipt: {**receipt, "action_digest": "e" * 64},
        lambda receipt: {**receipt, "session_id": "web_" + ("e" * 40)},
        lambda receipt: {**receipt, "unexpected": True},
    ],
)
def test_receipt_substitution_or_contract_drift_fails_closed(
    tmp_path: Path,
    mutate,
) -> None:
    valid = {
        "ok": True,
        "session_id": SESSION_ID,
        "action_digest": ACTION_DIGEST,
        "created": False,
        "recovered": False,
        "session": {"id": SESSION_ID},
    }

    def runner(argv, **_kwargs):
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout=json.dumps(mutate(valid)).encode(),
            stderr=b"",
        )

    with pytest.raises(ManagedSessionProvisionError):
        _port(tmp_path, runner).ensure_session(
            session_id=SESSION_ID,
            action_digest=ACTION_DIGEST,
        )
