from __future__ import annotations

import copy

import pytest

from quant_system.ops import restart_stack
from quant_system.ops.common import ReleaseOperationError


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
