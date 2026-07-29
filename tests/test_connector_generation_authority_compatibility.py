from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from quant_system.ops import restart_stack
from quant_system.ops.common import ReleaseOperationError


def _legacy_connector_process() -> dict[str, object]:
    return {
        "label": restart_stack.CONNECTOR_LABEL,
        "pid": 301,
        "process_started_at": "Mon Jul 27 16:50:06 2026",
        "process_command": (
            "/release/python -m quant_system.cli hermes connector-worker --mode reconcile_only"
        ),
        "actual_executable_image": "/release/python",
        "actual_executable_image_sha256": "a" * 64,
        "launcher_sha256": "b" * 64,
        "launchd_runs": 7,
        "last_exit_code": 0,
        "connector_mode": "reconcile_only",
    }


def test_legacy_projection_accepts_only_observed_zero_without_inventing_live_facts() -> None:
    authority = restart_stack._legacy_connector_generation_projection(_legacy_connector_process())

    assert authority["last_exit_code"] == 0
    assert "launchd_state" not in authority
    assert "last_exit_status" not in authority


@pytest.mark.parametrize(
    "updates,deleted_field",
    (
        ({"last_exit_code": 70}, None),
        ({"last_exit_code": False}, None),
        ({"last_exit_code": True}, None),
        ({"last_exit_code": None}, None),
        ({"launchd_state": "active"}, None),
        ({"last_exit_status": "recorded"}, None),
        ({}, "last_exit_code"),
    ),
)
def test_legacy_projection_rejects_every_nonexact_compatibility_shape(
    updates: dict[str, object],
    deleted_field: str | None,
) -> None:
    facts = {**_legacy_connector_process(), **updates}
    if deleted_field is not None:
        del facts[deleted_field]

    with pytest.raises(ReleaseOperationError):
        restart_stack._legacy_connector_generation_projection(facts)


def test_live_authority_requires_explicit_launchd_and_exit_status_facts() -> None:
    live = {
        **_legacy_connector_process(),
        "launchd_state": "active",
        "last_exit_status": "recorded",
    }

    authority = restart_stack._live_connector_generation_authority(live)

    assert authority["launchd_state"] == "active"
    assert authority["last_exit_status"] == "recorded"
    with pytest.raises(ReleaseOperationError, match="launchd_state"):
        restart_stack._live_connector_generation_authority(_legacy_connector_process())


@pytest.mark.parametrize("missing_field", ("launchd_state", "last_exit_status"))
def test_live_authority_rejects_each_member_of_a_partial_pair(
    missing_field: str,
) -> None:
    live = {
        **_legacy_connector_process(),
        "launchd_state": "active",
        "last_exit_status": "recorded",
    }
    del live[missing_field]

    with pytest.raises(ReleaseOperationError, match=missing_field):
        restart_stack._live_connector_generation_authority(live)


def _connector_process_observation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    launchd_state: object,
    last_exit_code: object,
) -> dict[str, object]:
    repository = tmp_path / "platform"
    script = repository / "scripts" / "run_agent_v02_connector.sh"
    script.parent.mkdir(parents=True)
    script.write_text("#!/bin/sh\n", encoding="utf-8")
    executable = tmp_path / "runtime" / "python"
    command = f"{executable} -m quant_system.cli hermes connector-worker --mode reconcile_only"
    launchd = "\n".join(
        (
            "state = active",
            "pid = 301",
            "runs = 7",
            "last exit code = 0",
            str(script),
        )
    )
    monkeypatch.setattr(
        restart_stack,
        "_launchctl_document",
        lambda _launchctl, _domain, _label: launchd,
    )
    monkeypatch.setattr(
        restart_stack,
        "parse_launchctl_state",
        lambda _document: launchd_state,
    )
    monkeypatch.setattr(
        restart_stack,
        "observed_launchctl_last_exit_code",
        lambda _document, *, label: last_exit_code,
    )
    monkeypatch.setattr(restart_stack, "sha256_file", lambda _path: "b" * 64)

    def run(argv: list[str], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        if argv[:2] == ["ps", "-ww"]:
            stdout = command + "\n"
        elif argv[:2] == ["ps", "-p"] and argv[-1] == "comm=":
            stdout = str(executable) + "\n"
        elif argv[:2] == ["ps", "-p"] and argv[-1] == "lstart=":
            stdout = "Mon Jul 27 16:50:06 2026\n"
        elif argv[:2] == ["lsof", "-nP"] and "txt" in argv:
            stdout = f"p301\nn{executable}\n"
        elif argv[:2] == ["lsof", "-nP"] and "cwd" in argv:
            stdout = f"p301\nn{repository}\n"
        else:
            raise AssertionError(f"unexpected process observation: {argv}")
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(restart_stack.subprocess, "run", run)
    return restart_stack._process_facts(
        launchctl="/usr/bin/launchctl",
        domain="gui/501",
        label=restart_stack.CONNECTOR_LABEL,
        repository_root=repository,
        preflight={
            "source_sha256": "b" * 64,
            "runtime": {"python": str(executable)},
        },
    )


@pytest.mark.parametrize(
    "launchd_state,last_exit_code,error",
    (
        ("", 0, "launchd_state"),
        ("active", 70, "nonzero"),
        ("active", False, "nonzero"),
        ("active", True, "nonzero"),
    ),
)
def test_live_process_observation_rejects_untrusted_generation_facts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    launchd_state: object,
    last_exit_code: object,
    error: str,
) -> None:
    with pytest.raises(ReleaseOperationError, match=error):
        _connector_process_observation(
            tmp_path,
            monkeypatch,
            launchd_state=launchd_state,
            last_exit_code=last_exit_code,
        )


def test_live_process_observation_returns_only_strictly_validated_connector(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    facts = _connector_process_observation(
        tmp_path,
        monkeypatch,
        launchd_state="active",
        last_exit_code=0,
    )

    assert facts["launchd_state"] == "active"
    assert facts["last_exit_status"] == "recorded"
    assert facts["last_exit_code"] == 0
