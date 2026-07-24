"""Unit tests for L2a-Send Dark Identity Profile constants and mapping."""

from __future__ import annotations

import hashlib
import json

import pytest

from quant_system.hermes.dark_identity_profile import (
    CHAT_PROMPT_MAX_BYTES,
    PLATFORM_WORKSPACE_ID,
    PROVIDER_POLICY,
    PROVIDER_POLICY_DIGEST,
    STORE_OWNER_ID,
    STORE_WORKSPACE_ID,
    DarkIdentityProfileError,
    build_bind_resolve_request,
    build_put_request,
    normalize_payload_ref,
    require_l2a_workspace,
    store_session_id,
)


def test_provider_policy_digest_is_store_canonical() -> None:
    raw = json.dumps(
        PROVIDER_POLICY,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert not raw.endswith("\n")
    assert hashlib.sha256(raw.encode("utf-8")).hexdigest() == PROVIDER_POLICY_DIGEST
    assert PROVIDER_POLICY_DIGEST == (
        "be9265ec683224ba28643b01938dba87d2642944f3a0516ccb9ff0126f872e31"
    )


def test_require_l2a_workspace_fail_closed() -> None:
    assert require_l2a_workspace(PLATFORM_WORKSPACE_ID) == "ws-local-main"
    with pytest.raises(DarkIdentityProfileError) as exc:
        require_l2a_workspace("other-ws")
    assert exc.value.code == "workspace_not_admitted"


def test_store_session_id_normalizes_bare_and_prefixed() -> None:
    assert store_session_id("managed-abc") == "session:managed-abc"
    assert store_session_id("session:managed-abc") == "session:managed-abc"


def test_build_put_request_closed_schema() -> None:
    body = build_put_request(
        managed_session_ref="session:s1",
        client_intent_id="intent-1",
        prompt="Reply with exactly: L2a-pong",
    )
    assert body["owner_id"] == STORE_OWNER_ID
    assert body["workspace_id"] == STORE_WORKSPACE_ID
    assert body["session_id"] == "session:s1"
    assert body["kind"] == "conversation_turn"
    assert body["schema_version"] == "2.0"
    assert body["ttl_days"] == 7
    assert body["provider_policy"] == PROVIDER_POLICY
    assert body["client_intent_id"] == "intent-1"
    assert "prompt" in body


def test_build_put_rejects_empty_and_oversized_prompt() -> None:
    with pytest.raises(DarkIdentityProfileError) as empty:
        build_put_request(
            managed_session_ref="s1",
            client_intent_id="i1",
            prompt="   \n",
        )
    assert empty.value.code == "invalid_prompt"

    huge = "x" * (CHAT_PROMPT_MAX_BYTES + 1)
    with pytest.raises(DarkIdentityProfileError) as big:
        build_put_request(
            managed_session_ref="s1",
            client_intent_id="i1",
            prompt=huge,
        )
    assert big.value.code == "prompt_too_large"


def test_normalize_payload_ref_surfaces() -> None:
    digest = "a" * 64
    assert normalize_payload_ref("payload:sha256:" + digest) == "payload:sha256:" + digest
    assert (
        normalize_payload_ref("platform-payload://sha256/" + digest)
        == "payload:sha256:" + digest
    )
    assert normalize_payload_ref(digest) == "payload:sha256:" + digest
    with pytest.raises(DarkIdentityProfileError):
        normalize_payload_ref("payload:sha256:not-hex")


def test_build_bind_resolve_request() -> None:
    digest = "b" * 64
    body = build_bind_resolve_request(
        payload_ref="platform-payload://sha256/" + digest,
        managed_session_ref="s1",
        consumer_ref="command:cmd-1",
    )
    assert body == {
        "payload_ref": "payload:sha256:" + digest,
        "owner_id": STORE_OWNER_ID,
        "workspace_id": STORE_WORKSPACE_ID,
        "session_id": "session:s1",
        "consumer_ref": "command:cmd-1",
    }
