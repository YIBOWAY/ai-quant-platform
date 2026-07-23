from __future__ import annotations

from types import SimpleNamespace

import pytest

from quant_system.hermes import external_session_fork as fork_module
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.dark_identity_profile import (
    PLATFORM_WORKSPACE_ID,
    PROVIDER_POLICY_DIGEST,
    STORE_TTL_DAYS,
)
from quant_system.hermes.external_session_fork import (
    ExternalSessionForkError,
    external_session_fork_context,
    submit_external_session_fork,
)
from quant_system.hermes.submission_saga import ActionReceipt


class _Gateway:
    def __init__(
        self,
        *,
        source: str = "discord",
        messages: list[dict[str, object]] | None = None,
    ) -> None:
        self.source = source
        self.messages = (
            messages
            if messages is not None
            else [
                {
                    "id": "41",
                    "role": "user",
                    "content": "question",
                    "timestamp": None,
                    "fork_point": "message:41",
                }
            ]
        )
        self.calls: list[tuple[str, str]] = []

    def capabilities(self) -> dict[str, object]:
        return {"features": {"session_resources": True}}

    def session_detail(self, session_id: str) -> dict[str, object]:
        self.calls.append(("detail", session_id))
        return {"id": session_id, "source": self.source}

    def session_messages(self, session_id: str) -> dict[str, object]:
        self.calls.append(("messages", session_id))
        return {
            "session_id": session_id,
            "data": list(self.messages),
            "omitted_message_count": 0,
        }


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("discord", (True, "discord", None)),
        ("desktop", (True, "historical", None)),
        ("api_server", (False, None, "source_session_not_external")),
        ("unknown", (False, None, "source_session_not_external")),
        (None, (False, None, "source_session_not_external")),
    ],
)
def test_external_session_fork_context_is_read_only_and_fail_closed(
    source: object,
    expected: tuple[bool, str | None, str | None],
) -> None:
    context = external_session_fork_context({"id": "s1", "source": source})

    assert (
        context["eligible"],
        context["source_channel"],
        context["reason_code"],
    ) == expected


def test_external_fork_registers_authoritative_source_and_delegates_exact_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    registered: list[object] = []
    delegated: list[object] = []

    def register(_settings: object, request: object):
        registered.append(request)
        return SimpleNamespace(platform_session_id=request.platform_session_id), True

    def submit(_settings: object, action: object, **kwargs: object) -> ActionReceipt:
        delegated.append((action, kwargs))
        return ActionReceipt(
            status="accepted",
            client_action_id=action.client_action_id,
            action_digest="a" * 64,
            workspace_id=action.workspace.workspace_id,
            mutation_enabled=True,
            platform_session_id="wm_child",
            hermes_session_id="web_" + ("b" * 40),
        )

    monkeypatch.setattr(fork_module, "register_workspace_session", register)
    monkeypatch.setattr(
        fork_module,
        "submit_fork_into_managed_session",
        submit,
    )

    receipt = submit_external_session_fork(
        SimpleNamespace(),
        _Gateway(),
        hermes_session_id="discord-session-1",
        fork_point="message:41",
        client_action_id="fork-browser-1",
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    )

    assert receipt.status == "accepted"
    assert len(registered) == 1
    observed = registered[0]
    assert observed.hermes_session_id == "discord-session-1"
    assert observed.workspace_id == PLATFORM_WORKSPACE_ID
    assert observed.kind == "observed_external_session"
    assert observed.source_channel == "discord"
    assert observed.owner_user_id == ROOT_USER_ID

    action, kwargs = delegated[0]
    assert action.source_session_ref == f"session:{observed.platform_session_id}"
    assert action.source_channel == "discord"
    assert action.fork_point == "message:41"
    assert action.new_provider_policy_digest == PROVIDER_POLICY_DIGEST
    assert action.payload_ttl_days == STORE_TTL_DAYS
    assert kwargs == {
        "mutation_enabled": True,
        "actor_owner_user_id": ROOT_USER_ID,
    }


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("discord", "discord"),
        ("desktop", "historical"),
        ("telegram", "historical"),
        ("tui", "historical"),
        ("cli", "historical"),
    ],
)
def test_external_fork_maps_persisted_non_api_sources(
    source: str,
    expected: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_channels: list[str] = []

    def register(_settings: object, request: object):
        observed_channels.append(request.source_channel)
        return SimpleNamespace(platform_session_id=request.platform_session_id), False

    monkeypatch.setattr(fork_module, "register_workspace_session", register)
    monkeypatch.setattr(
        fork_module,
        "submit_fork_into_managed_session",
        lambda *_args, **_kwargs: SimpleNamespace(status="accepted"),
    )

    submit_external_session_fork(
        SimpleNamespace(),
        _Gateway(source=source),
        hermes_session_id="historical-session-1",
        fork_point="message:41",
        client_action_id="fork-browser-2",
        mutation_enabled=True,
        actor_owner_user_id=ROOT_USER_ID,
    )

    assert observed_channels == [expected]


@pytest.mark.parametrize("source", ["api_server", "", "unknown"])
def test_external_fork_rejects_non_external_or_unclassified_source(
    source: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fork_module,
        "register_workspace_session",
        lambda *_args, **_kwargs: pytest.fail("must not register source"),
    )

    with pytest.raises(
        ExternalSessionForkError,
        match="external",
    ) as caught:
        submit_external_session_fork(
            SimpleNamespace(),
            _Gateway(source=source),
            hermes_session_id="not-external",
            fork_point="message:41",
            client_action_id="fork-browser-3",
            mutation_enabled=True,
            actor_owner_user_id=ROOT_USER_ID,
        )

    assert caught.value.code == "source_session_not_external"


@pytest.mark.parametrize(
    "messages",
    [
        [{"id": "41", "role": "user", "content": "fallback", "fork_point": None}],
        [{"id": "41", "role": "user", "content": "fallback"}],
        [],
    ],
)
def test_external_fork_rejects_cursor_without_authoritative_message(
    messages: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        fork_module,
        "register_workspace_session",
        lambda *_args, **_kwargs: pytest.fail("must not mutate registry"),
    )

    with pytest.raises(ExternalSessionForkError) as caught:
        submit_external_session_fork(
            SimpleNamespace(),
            _Gateway(messages=messages),
            hermes_session_id="discord-session-1",
            fork_point="message:41",
            client_action_id="fork-browser-4",
            mutation_enabled=True,
            actor_owner_user_id=ROOT_USER_ID,
        )

    assert caught.value.code == "fork_point_not_authoritative"


def test_external_fork_requires_advertised_session_resources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _Gateway()
    gateway.capabilities = lambda: {"features": {"session_resources": False}}
    monkeypatch.setattr(
        fork_module,
        "register_workspace_session",
        lambda *_args, **_kwargs: pytest.fail("must not mutate registry"),
    )

    with pytest.raises(ExternalSessionForkError) as caught:
        submit_external_session_fork(
            SimpleNamespace(),
            gateway,
            hermes_session_id="discord-session-1",
            fork_point="message:41",
            client_action_id="fork-browser-5",
            mutation_enabled=True,
            actor_owner_user_id=ROOT_USER_ID,
        )

    assert caught.value.code == "session_resources_unavailable"
