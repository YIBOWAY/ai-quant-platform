from __future__ import annotations

import copy

import pytest

from quant_system.ops import restart_stack
from quant_system.ops.common import ReleaseOperationError


def _real_never_exited_launchctl_document(*, top_level_state: str = "running") -> str:
    return (
        "gui/501/com.aiquant.agent-v02-connector = {\n"
        "\tactive count = 1\n"
        f"\tstate = {top_level_state}\n"
        "\tpid = 11367\n"
        "\truns = 1\n"
        "\tlast exit code = (never exited)\n"
        "\tcoalition = {\n"
        "\t\tstate = active\n"
        "\t}\n"
        "}\n"
    )


def test_never_exited_launchd_uses_running_top_level_state_not_nested_coalition() -> None:
    document = _real_never_exited_launchctl_document()

    assert restart_stack.parse_launchctl_state(document) == "running"
    assert (
        restart_stack.observed_launchctl_last_exit_code(
            document,
            label=restart_stack.CONNECTOR_LABEL,
        )
        is None
    )


def test_launchd_state_rejects_duplicate_top_level_state() -> None:
    document = _real_never_exited_launchctl_document().replace(
        "\tpid = 11367\n",
        "\tstate = waiting\n\tpid = 11367\n",
    )

    with pytest.raises(ReleaseOperationError, match="unambiguous current state"):
        restart_stack.parse_launchctl_state(document)


def test_launchd_state_rejects_nested_state_when_top_level_state_is_missing() -> None:
    document = _real_never_exited_launchctl_document().replace(
        "\tstate = running\n",
        "",
    )

    with pytest.raises(ReleaseOperationError, match="unambiguous current state"):
        restart_stack.parse_launchctl_state(document)


def test_never_exited_launchd_rejects_nonrunning_top_level_state() -> None:
    document = _real_never_exited_launchctl_document(top_level_state="active")

    with pytest.raises(ReleaseOperationError, match="state is not running"):
        restart_stack.observed_launchctl_last_exit_code(
            document,
            label=restart_stack.CONNECTOR_LABEL,
        )


def test_live_connector_authority_accepts_running_never_exited_reconcile_only() -> None:
    facts = {
        "label": restart_stack.CONNECTOR_LABEL,
        "pid": 11367,
        "process_started_at": "Wed Jul 29 08:10:00 2026",
        "process_command": "/release/run-agent connector-worker --mode reconcile_only",
        "actual_executable_image": "/release/.venv/bin/python",
        "actual_executable_image_sha256": "a" * 64,
        "launcher_sha256": "b" * 64,
        "launchd_runs": 1,
        "launchd_state": "running",
        "last_exit_code": None,
        "last_exit_status": "never_exited",
        "connector_mode": "reconcile_only",
    }

    authority = restart_stack._live_connector_generation_authority(facts)

    assert authority["launchd_state"] == "running"
    assert authority["last_exit_status"] == "never_exited"
    assert authority["last_exit_code"] is None
    assert authority["mode"] == "reconcile_only"


def _release_observation(*, stdout_sha256: str) -> dict[str, object]:
    return {
        "facts": {
            "release_authorized": False,
            "public_write_authorized": False,
            "chat_write_ready": False,
            "ready": False,
            "blockers": [
                "release_evidence_digest_unavailable",
                "active_release_stamp_missing",
            ],
            "release_stamp_id": None,
            "public_cutover_id": None,
            "event_cursor": 0,
        },
        "command": {
            "argv": ["/release/.venv/bin/quant-system", "hermes", "release", "status"],
            "exit_code": 0,
            "stdout_sha256": stdout_sha256,
            "stdout_bytes": 653,
            "stderr_sha256": "e" * 64,
            "stderr_bytes": 0,
        },
    }


def test_release_authority_ignores_only_volatile_command_artifact_bytes() -> None:
    expected = _release_observation(stdout_sha256="a" * 64)
    observed = _release_observation(stdout_sha256="b" * 64)

    assert (
        restart_stack.validate_release_authority_unchanged(expected, observed) == expected["facts"]
    )
    assert expected["command"] != observed["command"]


def test_release_authority_rejects_any_validated_fact_drift() -> None:
    expected = _release_observation(stdout_sha256="a" * 64)
    observed = copy.deepcopy(_release_observation(stdout_sha256="b" * 64))
    facts = observed["facts"]
    assert isinstance(facts, dict)
    facts["event_cursor"] = 1

    with pytest.raises(ReleaseOperationError, match="release authority facts changed"):
        restart_stack.validate_release_authority_unchanged(expected, observed)


@pytest.mark.parametrize("side", ("expected", "observed"))
def test_release_authority_requires_both_fact_projections(side: str) -> None:
    expected = _release_observation(stdout_sha256="a" * 64)
    observed = _release_observation(stdout_sha256="b" * 64)
    target = expected if side == "expected" else observed
    del target["facts"]

    with pytest.raises(ReleaseOperationError, match="release authority facts are absent"):
        restart_stack.validate_release_authority_unchanged(expected, observed)
