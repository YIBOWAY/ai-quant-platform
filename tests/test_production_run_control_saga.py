from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from quant_system.config.settings import (
    DatabaseSettings,
    HermesGatewaySettings,
    Settings,
)
from quant_system.hermes.approval_release_port import ApprovalReleaseResult
from quant_system.hermes.gateway_client import HermesRunControlError
from quant_system.hermes.run_stop_port import StopResult
from quant_system.hermes.submission_saga import (
    SubmissionSagaError,
    submit_action,
)

WORKSPACE_ID = "ws-production-control"
RUN_ID = "run-production-control"
CHALLENGE_ID = "challenge-production-control"
DIGEST = "a" * 64
EXPIRY = "2099-01-01T00:00:00.000000Z"


def _settings() -> Settings:
    return Settings(database=DatabaseSettings(enabled=False, auto_migrate=False))


def _approval_action(
    *,
    client_action_id: str = "action-approval-1",
    decision: str = "allow_once",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "hermes.command_approval.decide",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WORKSPACE_ID},
        "approval_ref": f"approval:{CHALLENGE_ID}",
        "run_ref": f"run:{RUN_ID}",
        "command_digest": DIGEST,
        "expected_status": "pending",
        "expected_expires_at": EXPIRY,
        "decision": decision,
    }


def _stop_action(*, client_action_id: str = "action-stop-1") -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "run.stop.request",
        "client_action_id": client_action_id,
        "workspace": {"workspace_id": WORKSPACE_ID},
        "run_ref": f"run:{RUN_ID}",
        "task_ref": None,
        "attempt_ref": None,
        "platform_job_ref": None,
    }


@dataclass
class _RunControl:
    calls: list[tuple[str, object]] = field(default_factory=list)
    approval_signal: str = "confirmed"
    stop_status: str = "stopped"
    next_error: HermesRunControlError | None = None

    def respond_approval_exact(
        self,
        run_id: str,
        *,
        choice: str,
        challenge_id: str,
        action_digest: str,
        expected_status: str,
        expected_expires_at: str,
    ) -> ApprovalReleaseResult:
        self.calls.append(
            (
                "approval",
                {
                    "run_id": run_id,
                    "choice": choice,
                    "challenge_id": challenge_id,
                    "action_digest": action_digest,
                    "expected_status": expected_status,
                    "expected_expires_at": expected_expires_at,
                },
            )
        )
        if self.next_error is not None:
            raise self.next_error
        return ApprovalReleaseResult(
            run_id=run_id,
            choice=choice,
            waiter_signal_status=self.approval_signal,  # type: ignore[arg-type]
            challenge_id=challenge_id,
            action_digest=action_digest,
        )

    def stop(self, run_id: str) -> StopResult:
        self.calls.append(("stop", run_id))
        if self.next_error is not None:
            raise self.next_error
        return StopResult(run_id=run_id, status=self.stop_status)


@dataclass
class _OutcomeAuthority:
    current: object | None = None
    finalizations: list[dict[str, object]] = field(default_factory=list)

    @staticmethod
    def ready() -> bool:
        return True

    def read(self, **_kwargs: object) -> object | None:
        return self.current

    def finalize(self, **kwargs: object) -> object:
        self.finalizations.append(dict(kwargs))
        self.current = SimpleNamespace(
            status=kwargs["status"],
            reason_code=kwargs["reason_code"],
            external_status=kwargs["external_status"],
        )
        return self.current


@pytest.fixture
def durable_preconditions(
    monkeypatch: pytest.MonkeyPatch,
) -> list[tuple[str, object]]:
    from quant_system.hermes import submission_saga

    events: list[tuple[str, object]] = []
    monkeypatch.setattr(submission_saga, "_ensure_ready", lambda _settings: True)
    monkeypatch.setattr(
        submission_saga,
        "_workspace_owns_run",
        lambda _settings, *, workspace_id, run_id: (
            events.append(("ownership", (workspace_id, run_id))) or True
        ),
    )

    def create(_settings: Settings, **kwargs: object) -> object:
        events.append(("ledger", dict(kwargs)))
        return SimpleNamespace(
            command=SimpleNamespace(command_id="control-command-1"),
            created=True,
        )

    monkeypatch.setattr(submission_saga, "_create_idempotent_command", create)
    return events


def test_production_approval_persists_identity_before_http(
    durable_preconditions: list[tuple[str, object]],
) -> None:
    control = _RunControl()

    receipt = submit_action(
        _settings(),
        _approval_action(),
        mutation_enabled=True,
        run_control_adapter=control,
        run_control_outcome_authority=_OutcomeAuthority(),
    )

    assert receipt.status == "accepted"
    assert receipt.command_id == "control-command-1"
    assert receipt.run_id == RUN_ID
    assert [name for name, _ in durable_preconditions] == ["ownership", "ledger"]
    assert control.calls[0][0] == "approval"
    ledger = durable_preconditions[1][1]
    assert ledger["kind"] == "hermes_command_approval_decide"
    assert ledger["client_request_id"] == "action-approval-1"


def test_durable_idempotency_conflict_prevents_external_mutation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quant_system.hermes import submission_saga

    monkeypatch.setattr(submission_saga, "_ensure_ready", lambda _settings: True)
    monkeypatch.setattr(
        submission_saga,
        "_workspace_owns_run",
        lambda *_args, **_kwargs: True,
    )

    def conflict(*_args: object, **_kwargs: object) -> object:
        raise SubmissionSagaError(
            "conflict",
            "client_request_id already belongs to a different command intent",
        )

    monkeypatch.setattr(submission_saga, "_create_idempotent_command", conflict)
    control = _RunControl()

    receipt = submit_action(
        _settings(),
        _approval_action(client_action_id="reused-action"),
        mutation_enabled=True,
        run_control_adapter=control,
        run_control_outcome_authority=_OutcomeAuthority(),
    )

    assert receipt.status == "conflict"
    assert receipt.reason_code == "idempotency_digest_conflict"
    assert control.calls == []


def test_unknown_approval_signal_stays_reconciling_after_committed_decision(
    durable_preconditions: list[tuple[str, object]],
) -> None:
    control = _RunControl(approval_signal="unknown")
    outcomes = _OutcomeAuthority()

    receipt = submit_action(
        _settings(),
        _approval_action(decision="deny"),
        mutation_enabled=True,
        run_control_adapter=control,
        run_control_outcome_authority=outcomes,
    )

    assert receipt.status == "reconciling"
    assert receipt.reason_code == "approval_signal_unknown"
    assert receipt.command_id == "control-command-1"
    assert outcomes.finalizations[0]["status"] == "outcome_unknown"


def test_stop_accepted_but_nonterminal_stays_requested_and_reconciling(
    durable_preconditions: list[tuple[str, object]],
) -> None:
    control = _RunControl(stop_status="running")
    outcomes = _OutcomeAuthority()

    receipt = submit_action(
        _settings(),
        _stop_action(),
        mutation_enabled=True,
        run_control_adapter=control,
        run_control_outcome_authority=outcomes,
    )

    assert receipt.status == "reconciling"
    assert receipt.reason_code == "stop_reconciliation_required"
    assert receipt.command_id == "control-command-1"
    assert receipt.stop_layers == {
        "hermes_run": "requested",
        "hqa_attempt": "not_applicable",
        "platform_job": "not_applicable",
        "overall": "requested",
        "run_id": RUN_ID,
        "run_status": "running",
        "idempotent_replay": False,
    }
    assert outcomes.finalizations[0]["status"] == "outcome_unknown"


def test_durable_succeeded_stop_replay_never_reposts_to_hermes(
    durable_preconditions: list[tuple[str, object]],
) -> None:
    control = _RunControl()
    outcomes = _OutcomeAuthority(
        current=SimpleNamespace(
            status="succeeded",
            reason_code=None,
            external_status="stopped",
        )
    )

    receipt = submit_action(
        _settings(),
        _stop_action(),
        mutation_enabled=True,
        run_control_adapter=control,
        run_control_outcome_authority=outcomes,
    )

    assert receipt.status == "accepted"
    assert receipt.command_id == "control-command-1"
    assert receipt.stop_layers == {
        "hermes_run": "already_terminal",
        "hqa_attempt": "not_applicable",
        "platform_job": "not_applicable",
        "overall": "already_terminal",
        "run_id": RUN_ID,
        "run_status": "stopped",
        "idempotent_replay": True,
    }
    assert control.calls == []
    assert outcomes.finalizations == []


def test_transport_unknown_keeps_durable_command_for_exact_retry(
    durable_preconditions: list[tuple[str, object]],
) -> None:
    control = _RunControl(
        next_error=HermesRunControlError(
            "transport_error",
            "outcome unknown",
        )
    )
    outcomes = _OutcomeAuthority()

    receipt = submit_action(
        _settings(),
        _stop_action(),
        mutation_enabled=True,
        run_control_adapter=control,
        run_control_outcome_authority=outcomes,
    )

    assert receipt.status == "reconciling"
    assert receipt.reason_code == "transport_error"
    assert receipt.command_id == "control-command-1"
    assert receipt.stop_layers is not None
    assert receipt.stop_layers["hermes_run"] == "unknown"
    assert outcomes.finalizations[0]["status"] == "outcome_unknown"


def test_run_must_belong_to_exact_workspace_before_ledger_or_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quant_system.hermes import submission_saga

    monkeypatch.setattr(submission_saga, "_ensure_ready", lambda _settings: True)
    monkeypatch.setattr(
        submission_saga,
        "_workspace_owns_run",
        lambda *_args, **_kwargs: False,
    )
    monkeypatch.setattr(
        submission_saga,
        "_create_idempotent_command",
        lambda *_args, **_kwargs: pytest.fail("ledger write must not happen"),
    )
    control = _RunControl()

    receipt = submit_action(
        _settings(),
        _stop_action(),
        mutation_enabled=True,
        run_control_adapter=control,
        run_control_outcome_authority=_OutcomeAuthority(),
    )

    assert receipt.status == "conflict"
    assert receipt.reason_code == "run_workspace_binding_mismatch"
    assert control.calls == []


def test_production_workspace_projects_only_official_run_approval_facts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quant_system.hermes import agent_workspace
    from quant_system.hermes.agent_workspace import PlatformAgentWorkspace
    from quant_system.hermes.command_ledger import ROOT_USER_ID

    approval = {
        "approval_id": CHALLENGE_ID,
        "run_id": RUN_ID,
        "command_id": "approval-core-1",
        "digest": DIGEST,
        "expires_at": EXPIRY,
        "expected_status": "pending",
        "status": "pending",
        "kind": "hermes.command_approval",
    }

    class _ProjectionControl:
        def pending_approvals(
            self,
            run_ids: tuple[str, ...],
        ) -> tuple[dict[str, object], ...]:
            assert run_ids == (RUN_ID,)
            return (approval,)

    monkeypatch.setattr(
        agent_workspace,
        "OfficialHermesRunControlClient",
        lambda _settings: _ProjectionControl(),
    )
    monkeypatch.setattr(
        agent_workspace,
        "authorities_ready",
        lambda _settings: {
            "ready": True,
            "mutation_enabled": True,
            "composer_write_ready": True,
            "chat_write_ready": True,
            "command_ledger_schema_ready": True,
            "session_registry_schema_ready": True,
            "workflow_binding_schema_ready": True,
            "research_binding_ready": True,
        },
    )
    monkeypatch.setattr(
        PlatformAgentWorkspace,
        "_collect_workspace_projection",
        lambda *_args, **_kwargs: (
            [],
            [],
            [{"hermes_run_id": RUN_ID}],
            1,
            True,
        ),
    )
    monkeypatch.setattr(
        PlatformAgentWorkspace,
        "_workspace_hermes_run_ids",
        lambda *_args, **_kwargs: (RUN_ID,),
    )
    settings = Settings(
        database=DatabaseSettings(enabled=False, auto_migrate=False),
        hermes_gateway=HermesGatewaySettings(enabled=True),
    )

    snapshot = PlatformAgentWorkspace(
        settings,
        mutation_enabled=True,
    ).snapshot(
        str(ROOT_USER_ID),
        {"workspace_id": WORKSPACE_ID},
    )

    assert snapshot.approvals == (approval,)
    assert snapshot.authority_health["command_approval"] == "ready"
    assert snapshot.authority_health["hermes_gateway"] == "ready"


def test_workspace_run_projection_selects_latest_active_64_not_old_history(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from contextlib import contextmanager

    from quant_system.hermes import agent_workspace
    from quant_system.hermes.agent_workspace import PlatformAgentWorkspace

    newest = "run-newest-pending"
    selected = tuple(sorted([newest, *(f"run-{index:03d}" for index in range(63))]))

    class _Cursor:
        @staticmethod
        def fetchall() -> list[tuple[str]]:
            return [(run_id,) for run_id in selected]

    class _Connection:
        statement = ""

        def execute(self, statement: str, _parameters: object) -> _Cursor:
            self.statement = statement
            return _Cursor()

    connection = _Connection()

    class _Database:
        @contextmanager
        def connect(self):
            yield connection

    monkeypatch.setattr(agent_workspace, "get_database", lambda _settings: _Database())
    workspace = PlatformAgentWorkspace(
        Settings(
            database=DatabaseSettings(enabled=False, auto_migrate=False),
            hermes_gateway=HermesGatewaySettings(enabled=False),
        )
    )

    run_ids = workspace._workspace_hermes_run_ids(WORKSPACE_ID)  # noqa: SLF001

    assert run_ids is not None
    assert newest in run_ids
    assert len(run_ids) == 64
    assert run_ids == tuple(sorted(run_ids))
    assert "command.state IN" in connection.statement
    assert "'delivered'" in connection.statement
    assert "'outcome_unknown'" in connection.statement
    assert "MAX(command.created_at)" in connection.statement
    assert "latest_created_at DESC" in connection.statement
    assert "LIMIT 64" in connection.statement


def test_database_outage_does_not_project_ready_empty_approvals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from quant_system.hermes import agent_workspace
    from quant_system.hermes.agent_workspace import PlatformAgentWorkspace

    calls = 0

    class _ProjectionControl:
        def pending_approvals(
            self,
            _run_ids: tuple[str, ...],
        ) -> tuple[dict[str, object], ...]:
            nonlocal calls
            calls += 1
            return ()

    monkeypatch.setattr(
        agent_workspace,
        "OfficialHermesRunControlClient",
        lambda _settings: _ProjectionControl(),
    )
    workspace = PlatformAgentWorkspace(
        Settings(
            database=DatabaseSettings(enabled=False, auto_migrate=False),
            hermes_gateway=HermesGatewaySettings(enabled=True),
        )
    )

    projection = workspace._authority_spine_projections(  # noqa: SLF001
        WORKSPACE_ID,
        hermes_run_ids=None,
    )

    assert projection["approvals"] == ()
    assert projection["authority_health"]["command_approval"] == "unavailable"
    assert projection["authority_health"]["hermes_gateway"] == "unavailable"
    assert calls == 0


def test_approval_projection_failure_logs_only_code_and_run_count(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from quant_system.hermes import agent_workspace
    from quant_system.hermes.agent_workspace import PlatformAgentWorkspace

    secret_message = f"Bearer must-not-log for {RUN_ID}"

    class _ProjectionControl:
        failing = True

        def pending_approvals(
            self,
            _run_ids: tuple[str, ...],
        ) -> tuple[dict[str, object], ...]:
            if self.failing:
                raise HermesRunControlError(
                    "run_event_replay_incomplete",
                    secret_message,
                )
            return ()

    control = _ProjectionControl()

    monkeypatch.setattr(
        agent_workspace,
        "OfficialHermesRunControlClient",
        lambda _settings: control,
    )
    monkeypatch.setattr(
        agent_workspace,
        "_APPROVAL_PROJECTION_LAST_ERROR_CODE",
        None,
    )
    workspace = PlatformAgentWorkspace(
        Settings(
            database=DatabaseSettings(enabled=False, auto_migrate=False),
            hermes_gateway=HermesGatewaySettings(enabled=True),
        )
    )
    caplog.set_level("WARNING", logger="quant_system.hermes.agent_workspace")

    projection = workspace._authority_spine_projections(  # noqa: SLF001
        WORKSPACE_ID,
        hermes_run_ids=(RUN_ID,),
    )
    repeated = workspace._authority_spine_projections(  # noqa: SLF001
        WORKSPACE_ID,
        hermes_run_ids=(RUN_ID,),
    )

    control.failing = False
    recovered = workspace._authority_spine_projections(  # noqa: SLF001
        WORKSPACE_ID,
        hermes_run_ids=(RUN_ID,),
    )
    control.failing = True
    failed_after_recovery = workspace._authority_spine_projections(  # noqa: SLF001
        WORKSPACE_ID,
        hermes_run_ids=(RUN_ID,),
    )

    assert projection["approvals"] == ()
    assert projection["authority_health"]["command_approval"] == "unavailable"
    assert projection["authority_health"]["hermes_gateway"] == "unavailable"
    assert repeated["authority_health"]["command_approval"] == "unavailable"
    assert recovered["authority_health"]["command_approval"] == "ready"
    assert failed_after_recovery["authority_health"]["command_approval"] == "unavailable"
    records = [
        record
        for record in caplog.records
        if record.name == "quant_system.hermes.agent_workspace"
    ]
    assert len(records) == 2
    assert all(
        record.getMessage() == "Hermes approval projection unavailable"
        for record in records
    )
    assert all(record.error_code == "run_event_replay_incomplete" for record in records)
    assert all(record.run_count == 1 for record in records)
    assert secret_message not in caplog.text
    assert RUN_ID not in caplog.text
