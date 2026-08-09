from __future__ import annotations

import pytest

from quant_system.hermes.candidate_evidence_v3 import (
    CandidateEvidenceV3Error,
    canonical_transcript_observation,
)


def _messages() -> dict[str, object]:
    return {
        "session_id": "web_session",
        "omitted_message_count": 0,
        "data": [
            {
                "id": "1",
                "role": "user",
                "content": "first",
                "timestamp": "2026-07-24T01:00:00Z",
                "fork_point": "message:1",
            },
            {
                "id": "2",
                "role": "assistant",
                "content": "answer one",
                "timestamp": "2026-07-24T01:00:01Z",
                "fork_point": "message:2",
            },
            {
                "id": "3",
                "role": "user",
                "content": "second",
                "timestamp": "2026-07-24T01:00:02Z",
                "fork_point": "message:3",
            },
            {
                "id": "4",
                "role": "assistant",
                "content": "answer two",
                "timestamp": "2026-07-24T01:00:03Z",
                "fork_point": "message:4",
            },
        ],
    }


def test_transcript_digest_binds_exact_canonical_messages() -> None:
    first, count, roles = canonical_transcript_observation(
        _messages(),
        expected_session_id="web_session",
    )
    repeated, _, _ = canonical_transcript_observation(
        _messages(),
        expected_session_id="web_session",
    )
    changed = _messages()
    changed["data"][3]["content"] = "different answer"  # type: ignore[index]
    changed_digest, _, _ = canonical_transcript_observation(
        changed,
        expected_session_id="web_session",
    )

    assert first == repeated
    assert first != changed_digest
    assert count == 4
    assert roles == {"assistant": 2, "user": 2}


@pytest.mark.parametrize(
    "mutation",
    (
        lambda value: value.update({"session_id": "substituted"}),
        lambda value: value.update({"omitted_message_count": 1}),
        lambda value: value["data"].append(value["data"][0]),  # type: ignore[index,union-attr]
        lambda value: value["data"][0].update({"role": "tool"}),  # type: ignore[index]
        lambda value: value["data"][0].update({"content": "   "}),  # type: ignore[index]
    ),
)
def test_transcript_digest_rejects_substitution_truncation_and_bad_rows(
    mutation,
) -> None:
    document = _messages()
    mutation(document)

    with pytest.raises(CandidateEvidenceV3Error):
        canonical_transcript_observation(
            document,
            expected_session_id="web_session",
        )
