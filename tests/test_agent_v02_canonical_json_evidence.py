from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_system.ops.common import (
    ReleaseOperationError,
    canonical_json_bytes,
    canonicalize_json_bytes,
)
from quant_system.ops.zero_effect import _fresh_release_status_observation
from tests.agent_v02_zero_effect_test_support import materialize_platform_repository


def test_evidence_json_is_sorted_compact_utf8_without_trailing_bytes() -> None:
    assert canonical_json_bytes({"中": 2, "a": 1}) == '{"a":1,"中":2}'.encode()


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b'{"a":1,"a":2}', "duplicate JSON key"),
        (b'{"value":NaN}', "non-finite JSON constant"),
        (b'{"value":Infinity}', "non-finite JSON constant"),
        (b'{"value":-Infinity}', "non-finite JSON constant"),
        (b'{"value":"\xff"}', "valid UTF-8"),
    ],
)
def test_raw_json_canonicalization_rejects_ambiguous_input(
    payload: bytes,
    message: str,
) -> None:
    with pytest.raises(ReleaseOperationError, match=message):
        canonicalize_json_bytes(payload, label="raw response")


def test_raw_json_canonicalization_reencodes_before_persistence() -> None:
    assert (
        canonicalize_json_bytes(
            '{\n  "z": 1,\n  "a": "中"\n}\n'.encode(),
            label="raw response",
        )
        == '{"a":"中","z":1}'.encode()
    )


def test_release_status_raw_response_is_canonicalized_before_write(
    tmp_path: Path,
) -> None:
    repository = materialize_platform_repository(tmp_path / "platform")
    observation = _fresh_release_status_observation(
        platform_root=repository,
        state_dir=tmp_path / "state",
    )

    artifact = Path(observation["artifact"]["path"])
    payload = artifact.read_bytes()
    assert payload == canonical_json_bytes(json.loads(payload))
    assert not payload.endswith(b"\n")
    assert observation["command"]["stdout_bytes"] == len(payload) + 1
