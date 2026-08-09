"""PostgreSQL integration coverage for candidate evidence v3.

The fixtures exercise the public authorities against a constrained runtime
login.  Hermes, HQA, promotion, and Futu are represented by bounded local
fakes; every fact consumed by CandidateEvidenceV3Authority is persisted in
the real PostgreSQL authority tables and remains subject to their triggers
and RLS policies.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.config.settings import (
    CandidateAdmissionSettings,
    DatabaseSettings,
    FutuSettings,
    PaperAccountSettings,
    SafetySettings,
    Settings,
)
from quant_system.hermes.agent_workspace_actions import (
    ConfirmFormulaSource,
    PreparePromotionReview,
    ReviewCandidateCAS,
    WorkspaceRef,
    canonical_action_digest,
    canonical_auth_envelope_digest,
)
from quant_system.hermes.candidate_admission_authority import (
    CandidateAdmissionAuthority,
    OpenCandidateAdmissionRequest,
    canonical_candidate_action_digest,
)
from quant_system.hermes.candidate_evidence_v3 import (
    CandidateEvidenceReferences,
    CandidateEvidenceV3Authority,
    CandidateEvidenceV3Error,
    candidate_evidence_runtime_security_is_ready,
)
from quant_system.hermes.command_ledger import (
    ROOT_USER_ID,
    HermesCommandLedger,
)
from quant_system.hermes.dark_identity_profile import (
    PROVIDER_POLICY_DIGEST,
    STORE_TTL_DAYS,
)
from quant_system.hermes.managed_session_provisioner import (
    ManagedSessionProvisioner,
    ManagedSessionProvisionReceipt,
)
from quant_system.hermes.paper_gate_authority import (
    PaperGateAuthority,
    RegisterPaperGateChallenge,
    RegisterPaperGateCompletion,
)
from quant_system.hermes.session_registry import (
    RegisterWorkspaceSession,
    register_workspace_session,
)
from quant_system.hermes.vertical_a_durable_authority import (
    PostgresVerticalAAuthority,
    VerticalAAdmissionBinding,
)
from quant_system.hermes.vertical_ro_provider import VerticalRoQuote
from quant_system.hermes.zero_order_observation import (
    capture_canonical_zero_order_snapshot,
)
from quant_system.storage import database as db

pytestmark = pytest.mark.pg

MIGRATIONS = (
    "003_app_users_brief_ai_reports.sql",
    # Candidate evidence compares the four canonical paper authorities.
    "004_paper_account_tables.sql",
    "005_hermes_command_ledger.sql",
    "006_hermes_workflow_binding.sql",
    "007_hermes_session_registry.sql",
    "008_l2a_conversation_turn_claim.sql",
    "010_agent_v0_2_runtime_security.sql",
    "011_hermes_session_action_idempotency.sql",
    "012_agent_v0_2_release_authority.sql",
    "013_managed_hermes_session_provisioning.sql",
    "014_agent_v02_connector_liveness.sql",
    "015_managed_session_provision_authority.sql",
    "016_agent_v02_candidate_admission.sql",
    "017_agent_v02_vertical_a_authority.sql",
    "018_agent_v02_paper_gate_bridge.sql",
    "019_agent_v02_candidate_evidence_v3.sql",
)
REQUIRED_FLOW_NAMES = (
    "web_chat_multi_turn",
    "hermes_restart_recovery",
    "exact_message_fork",
    "options_vertical_live_futu_ro",
    "paper_factor_gate_1_2_3_via_hermes",
)


@dataclass(frozen=True)
class _DatabaseEnvironment:
    admin_url: str
    runtime_url: str
    admin: db.Database
    runtime: db.Database
    settings: Settings
    runtime_login: str


@dataclass
class _FakeGateway:
    messages: dict[str, dict[str, object]]
    details: dict[str, dict[str, object]]
    instance_id: str
    started_at: datetime
    capability_sequence: list[tuple[str, datetime]] | None = None

    def capabilities(self) -> dict[str, object]:
        if self.capability_sequence:
            instance_id, started_at = self.capability_sequence.pop(0)
        else:
            instance_id, started_at = self.instance_id, self.started_at
        return {
            "runtime": {
                "instance_id": instance_id,
                "started_at": started_at.isoformat().replace("+00:00", "Z"),
            }
        }

    def session_detail(self, session_id: str) -> dict[str, object]:
        return dict(self.details[session_id])

    def session_messages(self, session_id: str) -> dict[str, object]:
        document = self.messages[session_id]
        return {
            **document,
            "data": [dict(message) for message in document["data"]],  # type: ignore[index]
        }

    def set_runtime(self, instance_id: str, started_at: datetime) -> None:
        self.instance_id = instance_id
        self.started_at = started_at


@dataclass(frozen=True)
class _Scenario:
    refs: CandidateEvidenceReferences
    authority: CandidateEvidenceV3Authority
    gateway: _FakeGateway
    admission_id: str
    admission_digest: str
    web_platform_session_id: str
    web_hermes_session_id: str
    web_command_ids: tuple[str, str]
    gate1_id: str
    gate1_hqa_ref: str
    gate3_id: str
    gate3_hqa_ref: str
    task_ref: str
    source_digest: str
    candidate_id: str
    candidate_digest: str
    final_backtest_receipt_id: str
    promotion_id: str
    base_commit: str
    reviewed_commit: str
    paper_gate3_command_id: str
    hqa_run_ref: str
    provider_evidence_ref: str
    workflow_audit: dict[str, object]


class _ProvisionPort:
    def ensure_session(
        self,
        *,
        session_id: str,
        action_digest: str,
    ) -> ManagedSessionProvisionReceipt:
        return ManagedSessionProvisionReceipt(
            session_id=session_id,
            action_digest=action_digest,
            created=True,
            recovered=False,
        )

    def fork_session(
        self,
        *,
        source_session_id: str,
        session_id: str,
        fork_point: str,
        action_digest: str,
    ) -> ManagedSessionProvisionReceipt:
        return ManagedSessionProvisionReceipt(
            session_id=session_id,
            action_digest=action_digest,
            created=True,
            recovered=False,
            source_session_id=source_session_id,
            resolved_source_session_id=source_session_id,
            fork_point=fork_point,
            preserve_source=True,
        )


class _PaperGatePort:
    def __init__(self, *, promotion_id: str) -> None:
        self.promotion_id = promotion_id

    def execute(
        self,
        operation: str,
        request: dict[str, object],
    ) -> dict[str, object]:
        response: dict[str, object] = {
            "ok": True,
            "operation_id": request["operation_id"],
            "hqa_receipt_ref": (f"hqa-paper-gate:{request['operation_id']}"),
            "managed_session_ref": request["managed_session_ref"],
            "task_ref": request["task_ref"],
            "attempt_ref": (request.get("attempt_ref") or "attempt:integration-plan"),
            "task_version": int(request["expected_task_version"]) + 1,
            "gate_ref": request["gate_ref"],
        }
        if operation == "confirm-formula":
            response.update(
                {
                    "attempt_ref": "attempt:integration-plan",
                    "reviewed_source_digest": (request["reviewed_source_digest"]),
                    "gate1_confirmation_id": ("gate1-" + "5" * 32),
                }
            )
        elif operation == "approve":
            response.update(
                {
                    "attempt_ref": "attempt:integration-plan",
                    "gate1_confirmation_id": (request["gate1_confirmation_id"]),
                    "reviewed_source_digest": (request["reviewed_source_digest"]),
                    "candidate_id": request["candidate_id"],
                    "candidate_digest": request["expected_digest"],
                    "decision": "approve",
                    "registration": "manual_required",
                    "review_note_digest": hashlib.sha256(
                        str(request["note"]).encode("utf-8")
                    ).hexdigest(),
                }
            )
        elif operation == "promote":
            response.update(
                {
                    "task_version": int(request["expected_task_version"]) + 2,
                    "attempt_ref": request["attempt_ref"],
                    "workflow_gate_resolution_event_id": ("event:" + "8" * 64),
                    "workflow_gate3_event_id": "event:" + "9" * 64,
                    "run_ref": request["run_ref"],
                    "candidate_id": request["candidate_id"],
                    "candidate_digest": request["expected_digest"],
                    "final_backtest_receipt_id": (request["final_backtest_receipt_id"]),
                    "base_commit": request["base_commit"],
                    "promotion_id": self.promotion_id,
                    "promotion_status": "awaiting_human_commit",
                    "worktree": "/tmp/candidate-evidence-review",
                    "patch": "/tmp/candidate-evidence-review.patch",
                    "manifest": "/tmp/candidate-evidence-review.json",
                    "human_git_commit_required": True,
                    "auto_commit": False,
                }
            )
        else:  # pragma: no cover - the authority owns this closed enum
            raise AssertionError(f"unexpected paper operation: {operation}")
        evidence = {
            key: value
            for key, value in response.items()
            if key not in {"ok", "hqa_receipt_ref", "hqa_receipt_digest"}
        }
        response["hqa_receipt_digest"] = hashlib.sha256(
            json.dumps(
                evidence,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()
        return response


def _test_database_url() -> str:
    url = os.environ.get("QS_TEST_DATABASE_URL")
    if not url:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    database_name = conninfo_to_dict(url).get("dbname")
    if not database_name or not (database_name.endswith("_tmp") or "test" in database_name):
        pytest.fail("QS_TEST_DATABASE_URL must point at a throwaway test database")
    return url


def _runtime_url(admin_url: str, *, user: str, password: str) -> str:
    parameters = conninfo_to_dict(admin_url)
    parameters["user"] = user
    parameters["password"] = password
    return make_conninfo(**parameters)


@pytest.fixture(scope="module")
def database_environment() -> _DatabaseEnvironment:
    admin_url = _test_database_url()
    parameters = conninfo_to_dict(admin_url)
    database_name = str(parameters["dbname"])
    maintenance = dict(parameters)
    maintenance["dbname"] = "postgres"
    with psycopg.connect(make_conninfo(**maintenance), autocommit=True) as conn:
        conn.execute(
            sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(database_name))
        )
        conn.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name)))

    admin = db.Database(admin_url, connect_timeout=2)
    db.run_migrations(admin, only=MIGRATIONS)

    suffix = uuid4().hex[:10]
    runtime_login = f"aqp_candidate_evidence_{suffix}"
    runtime_password = f"candidate-evidence-{suffix}"
    with admin.connect() as conn:
        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS "
                "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
            ).format(
                sql.Identifier(runtime_login),
                sql.Literal(runtime_password),
            )
        )
        conn.execute(sql.SQL("GRANT quant_runtime TO {}").format(sql.Identifier(runtime_login)))
        now = datetime.now(UTC)
        conn.execute(
            """
            INSERT INTO quant_system.paper_accounts (
                account_id,
                owner_user_id,
                base_currency,
                initial_cash,
                cash,
                realized_pnl,
                kill_switch,
                version,
                raw,
                created_at,
                updated_at
            )
            VALUES (
                'candidate-evidence-paper',
                %s,
                'USD',
                100000,
                100000,
                0,
                TRUE,
                1,
                '{"kill_switch":true,"version":1}'::jsonb,
                %s,
                %s
            )
            """,
            (ROOT_USER_ID, now, now),
        )

    runtime_url = _runtime_url(
        admin_url,
        user=runtime_login,
        password=runtime_password,
    )
    settings = Settings(
        database=DatabaseSettings(
            enabled=True,
            url=runtime_url,
            auto_migrate=False,
            connect_timeout_seconds=2,
        ),
        candidate_admission=CandidateAdmissionSettings(
            enabled=True,
            ttl_seconds=1800,
        ),
        paper_account=PaperAccountSettings(
            db_mode="canonical",
            auto_process_pending_orders_enabled=False,
        ),
        safety=SafetySettings(
            dry_run=True,
            paper_trading=True,
            live_trading_enabled=False,
            kill_switch=True,
        ),
        futu=FutuSettings(enabled=True, options_enabled=True),
    )
    runtime = db.Database(runtime_url, connect_timeout=2)
    environment = _DatabaseEnvironment(
        admin_url=admin_url,
        runtime_url=runtime_url,
        admin=admin,
        runtime=runtime,
        settings=settings,
        runtime_login=runtime_login,
    )
    db.reset_database_cache()
    try:
        yield environment
    finally:
        db.reset_database_cache()
        with admin.connect() as conn:
            conn.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(runtime_login)))
            conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(runtime_login)))
        db.reset_database_cache()


def _digest(label: str) -> str:
    return hashlib.sha256(label.encode("utf-8")).hexdigest()


def _transcript(
    session_id: str,
    *,
    prefix: str,
    fork_point: str | None = None,
) -> dict[str, object]:
    roles = ("user", "assistant", "user", "assistant")
    messages: list[dict[str, object]] = []
    for index, role in enumerate(roles, start=1):
        messages.append(
            {
                "id": f"{prefix}-message-{index}",
                "role": role,
                "content": f"{prefix} {role} turn {index}",
                "timestamp": f"2026-07-24T01:0{index}:00Z",
                "fork_point": (fork_point if fork_point is not None and index == 2 else None),
            }
        )
    return {
        "session_id": session_id,
        "omitted_message_count": 0,
        "data": messages,
    }


def _register_managed_session(
    environment: _DatabaseEnvironment,
    *,
    workspace_id: str,
    platform_session_id: str,
    label: str,
    parent_platform_session_id: str | None = None,
    fork_point: str | None = None,
) -> str:
    creation_digest = _digest(f"session:{label}")
    hermes_session_id = f"web_{creation_digest[:40]}"
    register_workspace_session(
        environment.settings,
        RegisterWorkspaceSession(
            platform_session_id=platform_session_id,
            hermes_session_id=hermes_session_id,
            workspace_id=workspace_id,
            kind="web_managed_session",
            source_channel=(None if parent_platform_session_id is None else "discord"),
            parent_platform_session_id=parent_platform_session_id,
            fork_point=fork_point,
            provider_policy_digest=PROVIDER_POLICY_DIGEST,
            payload_ttl_days=STORE_TTL_DAYS,
            creation_client_action_id=f"create-{label}",
            creation_action_digest=creation_digest,
        ),
    )
    provisioned = ManagedSessionProvisioner(
        settings=environment.settings,
        port=_ProvisionPort(),
        lease_seconds=30,
    ).provision_next(
        worker_id=f"provision-{label}",
        now=datetime.now(UTC),
    )
    assert provisioned.outcome == "ready"
    assert provisioned.platform_session_id == platform_session_id
    return hermes_session_id


def _complete_command(
    environment: _DatabaseEnvironment,
    *,
    admission_id: str,
    platform_session_id: str,
    hermes_session_id: str,
    run_id: str,
    label: str,
) -> str:
    ledger = HermesCommandLedger(
        environment.settings,
        claim_candidate_admission_id=admission_id,
    )
    created = ledger.create_command(
        platform_session_id=platform_session_id,
        client_request_id=f"request-{label}",
        kind="conversation_turn",
        canonical_request_digest=_digest(f"request-digest:{label}"),
        payload_ref=f"platform-payload://sha256/{_digest(f'payload:{label}')}",
        provider_policy_digest=PROVIDER_POLICY_DIGEST,
    ).command
    now = datetime.now(UTC)
    claimed = ledger.claim_next_command(
        worker_id=f"worker-{label}",
        now=now,
        lease_duration=timedelta(seconds=30),
    )
    assert claimed is not None
    assert claimed.command_id == created.command_id
    assert claimed.lease_token is not None
    dispatched = ledger.mark_dispatch_started(
        command_id=claimed.command_id,
        expected_version=claimed.version,
        lease_token=claimed.lease_token,
        now=now + timedelta(milliseconds=10),
    )
    delivered = ledger.mark_delivered(
        command_id=dispatched.command_id,
        expected_version=dispatched.version,
        lease_token=claimed.lease_token,
        now=now + timedelta(milliseconds=20),
        hermes_session_id=hermes_session_id,
        hermes_run_id=run_id,
    )
    succeeded = ledger.mark_succeeded(
        command_id=delivered.command_id,
        expected_version=delivered.version,
        now=now + timedelta(milliseconds=30),
        hermes_session_id=hermes_session_id,
        hermes_run_id=run_id,
        evidence_digest=_digest(f"terminal:{label}"),
    )
    return str(succeeded.command_id)


def _open_candidate(
    environment: _DatabaseEnvironment,
    *,
    workspace_id: str,
    suffix: str,
) -> tuple[str, str, datetime, datetime]:
    with environment.runtime.connect() as conn:
        baseline = capture_canonical_zero_order_snapshot(
            conn,
            owner_user_id=ROOT_USER_ID,
        )
    schema_fingerprint = db.schema_fingerprint(environment.admin)
    payload = {
        "baseline_order_snapshot_digest": baseline.snapshot_digest,
        "database_schema_fingerprint": schema_fingerprint,
        "hermes_runtime_digest": _digest(f"hermes-runtime:{suffix}"),
        "hqa_runtime_digest": _digest(f"hqa-runtime:{suffix}"),
        "note": "verify exact live candidate evidence",
        "platform_runtime_digest": _digest(f"platform-runtime:{suffix}"),
        "preflight_evidence_digest": _digest(f"preflight:{suffix}"),
        "route": "/hermes",
        "ttl_seconds": 1800,
        "workspace_id": workspace_id,
    }
    request = OpenCandidateAdmissionRequest(
        workspace_id=workspace_id,
        route="/hermes",
        platform_runtime_digest=str(payload["platform_runtime_digest"]),
        hqa_runtime_digest=str(payload["hqa_runtime_digest"]),
        hermes_runtime_digest=str(payload["hermes_runtime_digest"]),
        database_schema_fingerprint=schema_fingerprint,
        preflight_evidence_digest=str(payload["preflight_evidence_digest"]),
        baseline_order_snapshot_digest=baseline.snapshot_digest,
        ttl_seconds=1800,
        note=str(payload["note"]),
        client_action_id=f"candidate-open-{suffix}",
        action_digest=canonical_candidate_action_digest(
            "candidate.open",
            payload,
        ),
    )
    opened = CandidateAdmissionAuthority(
        environment.settings,
        database=environment.runtime,
        schema_fingerprint_reader=lambda _database: schema_fingerprint,
    )
    receipt = opened.open(
        request,
        admission_id=f"candidate-{suffix}",
    )
    record = opened.active(workspace_id)
    assert record is not None
    return (
        receipt.admission_id,
        receipt.admission_digest,
        record.opened_at,
        record.expires_at,
    )


def _seed_scenario(
    environment: _DatabaseEnvironment,
) -> _Scenario:
    suffix = uuid4().hex[:12]
    workspace_id = f"candidate-evidence-{suffix}"
    (
        admission_id,
        admission_digest,
        opened_at,
        expires_at,
    ) = _open_candidate(
        environment,
        workspace_id=workspace_id,
        suffix=suffix,
    )

    web_platform_session_id = f"web-platform-{suffix}"
    web_hermes_session_id = _register_managed_session(
        environment,
        workspace_id=workspace_id,
        platform_session_id=web_platform_session_id,
        label=f"web-{suffix}",
    )
    source_platform_session_id = f"discord-platform-{suffix}"
    source_hermes_session_id = f"discord-session-{suffix}"
    register_workspace_session(
        environment.settings,
        RegisterWorkspaceSession(
            platform_session_id=source_platform_session_id,
            hermes_session_id=source_hermes_session_id,
            workspace_id=workspace_id,
            kind="observed_external_session",
            source_channel="discord",
        ),
    )
    fork_platform_session_id = f"fork-platform-{suffix}"
    fork_hermes_session_id = _register_managed_session(
        environment,
        workspace_id=workspace_id,
        platform_session_id=fork_platform_session_id,
        label=f"fork-{suffix}",
        parent_platform_session_id=source_platform_session_id,
        fork_point="message:2",
    )

    first_web_run = f"web-run-{suffix}-1"
    second_web_run = f"web-run-{suffix}-2"
    web_command_ids = (
        _complete_command(
            environment,
            admission_id=admission_id,
            platform_session_id=web_platform_session_id,
            hermes_session_id=web_hermes_session_id,
            run_id=first_web_run,
            label=f"web-{suffix}-1",
        ),
        _complete_command(
            environment,
            admission_id=admission_id,
            platform_session_id=web_platform_session_id,
            hermes_session_id=web_hermes_session_id,
            run_id=second_web_run,
            label=f"web-{suffix}-2",
        ),
    )
    options_run_id = f"options-run-{suffix}"
    _complete_command(
        environment,
        admission_id=admission_id,
        platform_session_id=web_platform_session_id,
        hermes_session_id=web_hermes_session_id,
        run_id=options_run_id,
        label=f"options-{suffix}",
    )
    paper_gate1_run_id = f"paper-gate1-run-{suffix}"
    paper_gate2_run_id = f"paper-gate2-run-{suffix}"
    paper_gate3_run_id = f"paper-gate3-run-{suffix}"
    paper_gate1_command_id = _complete_command(
        environment,
        admission_id=admission_id,
        platform_session_id=web_platform_session_id,
        hermes_session_id=web_hermes_session_id,
        run_id=paper_gate1_run_id,
        label=f"paper-gate1-{suffix}",
    )
    paper_gate2_command_id = _complete_command(
        environment,
        admission_id=admission_id,
        platform_session_id=web_platform_session_id,
        hermes_session_id=web_hermes_session_id,
        run_id=paper_gate2_run_id,
        label=f"paper-gate2-{suffix}",
    )
    paper_gate3_command_id = _complete_command(
        environment,
        admission_id=admission_id,
        platform_session_id=web_platform_session_id,
        hermes_session_id=web_hermes_session_id,
        run_id=paper_gate3_run_id,
        label=f"paper-gate3-{suffix}",
    )

    admission = VerticalAAdmissionBinding(
        admission_id=admission_id,
        admission_digest=admission_digest,
        workspace_id=workspace_id,
        opened_at=opened_at,
        expires_at=expires_at,
    )
    vertical = PostgresVerticalAAuthority(
        environment.settings,
        database=environment.runtime,
        admission_resolver=lambda _workspace_id: admission,
    )
    now = datetime.now(UTC)
    authorization: dict[str, Any] = {
        "tickers": ["AAPL"],
        "fields": [
            "bid",
            "ask",
            "delta",
            "iv",
            "expiry",
            "strike",
        ],
        "max_calls": 100,
        "grant_id": f"client-envelope-{suffix}",
        "window_start": (now - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
        "window_end": (now + timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }
    authorization["grant_digest"] = canonical_auth_envelope_digest(authorization)
    vertical_action_digest = _digest(f"vertical-action:{suffix}")
    vertical_seed = vertical.seed_options_vertical_a(
        workspace_id=workspace_id,
        client_action_id=f"vertical-action-{suffix}",
        action_digest=vertical_action_digest,
        ticker="AAPL",
        goal_note="live read-only AAPL options evidence",
        expiry="2026-12-18",
        strike=200.0,
        include_provider_evidence=True,
        provider_mode="live_futu_ro",
        auth_envelope=authorization,
    )
    vertical_claim = vertical.claim_request(
        request_id=vertical_seed.domain_request_id,
        expected_action_digest=vertical_action_digest,
        expected_admission_id=admission_id,
        expected_admission_digest=admission_digest,
        session_ref=f"session:{web_platform_session_id}",
        run_ref=f"run:{options_run_id}",
        worker_id=f"vertical-worker-{suffix}",
    )
    vertical.finalize_verified_futu_quote(
        claim_id=vertical_claim.claim_id,
        expected_claim_digest=vertical_claim.claim_digest,
        quote=VerticalRoQuote(
            provider_name="futu",
            request_id=f"futu-ro-{suffix}",
            as_of=datetime.now(UTC),
            ticker="AAPL",
            expiry="2026-12-18",
            strike=200.0,
            bid=5.1,
            ask=5.3,
            delta=-0.23,
            iv=0.31,
            apr=0.14,
            evidence=(
                "provider:futu",
                f"request_id:futu-ro-{suffix}",
            ),
        ),
    )

    paper = PaperGateAuthority(
        environment.settings,
        database=environment.runtime,
    )
    task_ref = f"task:paper-{suffix}"
    plan_attempt_ref = "attempt:integration-plan"
    research_attempt_ref = "attempt:integration-research"
    source_digest = _digest(f"paper-source:{suffix}")
    candidate_id = f"factor-{suffix}"
    candidate_digest = _digest(f"paper-candidate:{suffix}")
    gate1_id = f"paper-g1-{suffix}"
    gate2_id = f"paper-g2-{suffix}"
    gate3_id = f"paper-g3-{suffix}"
    gate1_hqa_ref = f"gate:hqa-paper-g1-{suffix}"
    gate3_hqa_ref = f"gate:hqa-paper-g3-{suffix}"
    final_backtest_receipt_id = f"backtest-{uuid4().hex}"
    base_commit = "b" * 40
    reviewed_commit = "c" * 40
    promotion_id = f"promo-{uuid4().hex}"
    paper_port = _PaperGatePort(promotion_id=promotion_id)
    paper.register_challenge(
        RegisterPaperGateChallenge(
            gate_id=gate1_id,
            gate_kind="gate1",
            workspace_id=workspace_id,
            task_ref=task_ref,
            expected_task_version=1,
            attempt_ref=plan_attempt_ref,
            hqa_gate_ref=gate1_hqa_ref,
            platform_session_id=web_platform_session_id,
            hermes_session_id=web_hermes_session_id,
            command_id=paper_gate1_command_id,
            hermes_run_id=paper_gate1_run_id,
            parent_gate_id=None,
            source_file_ref=f"/tmp/{candidate_id}.py",
            universe="Global equities",
            reviewed_source_sha256=source_digest,
        )
    )
    gate1_action = ConfirmFormulaSource(
        client_action_id=f"confirm-formula-{suffix}",
        workspace=WorkspaceRef(workspace_id),
        task_ref=task_ref,
        reviewed_source_sha256=source_digest,
        confirmation_note="I reviewed the exact paper factor source.",
    )
    gate1 = paper.execute_action(
        gate1_action,
        action_digest=canonical_action_digest(gate1_action),
        port=paper_port,
    )
    assert gate1.gate1_confirmation_id is not None
    paper.register_challenge(
        RegisterPaperGateChallenge(
            gate_id=gate2_id,
            gate_kind="gate2",
            workspace_id=workspace_id,
            task_ref=task_ref,
            expected_task_version=2,
            attempt_ref=plan_attempt_ref,
            hqa_gate_ref=gate1_hqa_ref,
            platform_session_id=web_platform_session_id,
            hermes_session_id=web_hermes_session_id,
            command_id=paper_gate2_command_id,
            hermes_run_id=paper_gate2_run_id,
            parent_gate_id=gate1_id,
            reviewed_source_sha256=source_digest,
            gate1_confirmation_id=gate1.gate1_confirmation_id,
            candidate_id=candidate_id,
            expected_digest=candidate_digest,
            expected_status="pending",
        )
    )
    gate2_action = ReviewCandidateCAS(
        client_action_id=f"review-candidate-{suffix}",
        workspace=WorkspaceRef(workspace_id),
        candidate_ref=f"candidate:{candidate_id}",
        expected_digest=candidate_digest,
        expected_status="pending",
        note="Reviewed the exact candidate and manifest.",
    )
    paper.execute_action(
        gate2_action,
        action_digest=canonical_action_digest(gate2_action),
        port=paper_port,
    )
    paper.register_challenge(
        RegisterPaperGateChallenge(
            gate_id=gate3_id,
            gate_kind="gate3",
            workspace_id=workspace_id,
            task_ref=task_ref,
            expected_task_version=3,
            attempt_ref=research_attempt_ref,
            hqa_gate_ref=gate3_hqa_ref,
            platform_session_id=web_platform_session_id,
            hermes_session_id=web_hermes_session_id,
            command_id=paper_gate3_command_id,
            hermes_run_id=paper_gate3_run_id,
            hqa_run_ref=f"run:paper-{suffix}",
            parent_gate_id=gate2_id,
            reviewed_source_sha256=source_digest,
            gate1_confirmation_id=gate1.gate1_confirmation_id,
            candidate_id=candidate_id,
            expected_digest=candidate_digest,
            final_backtest_receipt_id=final_backtest_receipt_id,
            base_commit=base_commit,
        )
    )
    gate3_action = PreparePromotionReview(
        client_action_id=f"prepare-promotion-{suffix}",
        workspace=WorkspaceRef(workspace_id),
        candidate_ref=f"candidate:{candidate_id}",
        expected_digest=candidate_digest,
        final_backtest_receipt_ref=(f"receipt:{final_backtest_receipt_id}"),
        base_commit=base_commit,
    )
    gate3 = paper.execute_action(
        gate3_action,
        action_digest=canonical_action_digest(gate3_action),
        port=paper_port,
    )
    assert gate3.promotion_id == promotion_id
    hqa_run_ref = f"run:paper-{suffix}"
    provider_evidence_ref = f"provider-evidence:futu-{suffix}"
    workflow_audit = {
        "schema_version": 1,
        "status": "consistent",
        "owner_user_id": str(ROOT_USER_ID),
        "event_count": 7,
        "task_count": 1,
        "operation_count": 7,
        "binding_counts": {
            "tasks": 1,
            "attempts": 2,
            "domain_gates": 1,
        },
        "last_record_sha256": _digest(f"workflow-last:{suffix}"),
        "projection_sha256": _digest(f"workflow-projection:{suffix}"),
    }
    workflow_audit_digest = hashlib.sha256(
        json.dumps(
            workflow_audit,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    completion_evidence = {
        "schema_version": "agent-v0.2-paper-completion/v1",
        "task_ref": task_ref,
        "task_version": 7,
        "task_status": "completed",
        "task_terminal_outcome": "completed",
        "attempt_ref": research_attempt_ref,
        "attempt_status": "completed",
        "attempt_terminal_outcome": "completed",
        "domain_gate_ref": gate3_hqa_ref,
        "domain_gate_outcome": "passed",
        "hqa_run_ref": hqa_run_ref,
        "provider_evidence_ref": provider_evidence_ref,
        "promotion_id": promotion_id,
        "reviewed_commit": reviewed_commit,
        "candidate_id": candidate_id,
        "candidate_digest": candidate_digest,
        "final_backtest_receipt_id": final_backtest_receipt_id,
        "base_commit": base_commit,
        "attempt_completion_operation_id": (f"paper-research-complete-{suffix}"),
        "attempt_completion_event_id": "event:" + "a" * 64,
        "task_completion_operation_id": f"paper-task-complete-{suffix}",
        "task_completion_event_id": "event:" + "b" * 64,
        "workflow_audit_status": "consistent",
        "workflow_audit_ref": f"workflow-audit:{workflow_audit_digest}",
        "workflow_audit_digest": workflow_audit_digest,
    }
    completion_digest = hashlib.sha256(
        json.dumps(
            completion_evidence,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()
    paper.register_completion(
        RegisterPaperGateCompletion(
            gate_id=gate3_id,
            workspace_id=workspace_id,
            hqa_completion_receipt_ref=(f"hqa-paper-completion:{completion_digest[:32]}"),
            hqa_completion_receipt_digest=completion_digest,
            completion_evidence=completion_evidence,
        )
    )

    gateway = _FakeGateway(
        messages={
            web_hermes_session_id: _transcript(
                web_hermes_session_id,
                prefix=f"web-{suffix}",
            ),
            source_hermes_session_id: _transcript(
                source_hermes_session_id,
                prefix=f"discord-{suffix}",
                fork_point="message:2",
            ),
        },
        details={
            fork_hermes_session_id: {
                "id": fork_hermes_session_id,
                "parent_session_id": source_hermes_session_id,
            }
        },
        instance_id="1" * 32,
        started_at=datetime(2026, 7, 24, 1, 0, tzinfo=UTC),
    )

    def hqa_probe(
        operation: str,
        arguments: tuple[str, ...] | list[str],
    ) -> dict[str, object]:
        if operation == "audit":
            assert not arguments
            return dict(workflow_audit)
        assert operation == "show"
        assert tuple(arguments) == ("--task-ref", task_ref)
        return {
            "task_ref": task_ref,
            "version": 7,
            "state": "terminal",
            "terminal_outcome": "completed",
            "managed_session_ref": f"session:{web_platform_session_id}",
            "gate1_ref": gate1_hqa_ref,
            "gate1_source_digest": source_digest,
            "gate1_candidate_ref": f"candidate:{candidate_id}",
            "gate1_manifest_digest": candidate_digest,
            "gate3_refs": [gate3_hqa_ref],
            "result_refs": [f"result:{final_backtest_receipt_id}"],
            "attempts": [
                {
                    "attempt_ref": plan_attempt_ref,
                    "gate3_refs": [],
                    "run_ref": "run:paper-plan",
                    "submission_command_ref": (f"command:{paper_gate1_command_id}"),
                },
                {
                    "attempt_ref": research_attempt_ref,
                    "gate3_refs": [gate3_hqa_ref],
                    "run_ref": f"run:paper-{suffix}",
                    "submission_command_ref": (f"command:{paper_gate3_command_id}"),
                    "terminal_outcome": "completed",
                    "domain_gate_outcome": "passed",
                    "provider_evidence_refs": [provider_evidence_ref],
                },
            ],
        }

    def promotion_probe(requested_id: str) -> dict[str, object]:
        assert requested_id == promotion_id
        return {
            "promotion_id": promotion_id,
            "status": "reviewed",
            "reviewed_commit": reviewed_commit,
            "candidate_id": candidate_id,
            "candidate_digest": candidate_digest,
            "final_backtest_receipt_id": final_backtest_receipt_id,
            "base_commit": base_commit,
        }

    refs = CandidateEvidenceReferences(
        admission_id=admission_id,
        admission_digest=admission_digest,
        web_platform_session_id=web_platform_session_id,
        web_command_ids=web_command_ids,
        fork_source_platform_session_id=source_platform_session_id,
        fork_child_platform_session_id=fork_platform_session_id,
        options_request_id=vertical_seed.domain_request_id,
        paper_gate3_id=gate3_id,
        reviewed_commit=reviewed_commit,
    )
    authority = CandidateEvidenceV3Authority(
        environment.settings,
        database=environment.runtime,
        gateway=gateway,
        hqa_probe=hqa_probe,
        promotion_probe=promotion_probe,
    )
    return _Scenario(
        refs=refs,
        authority=authority,
        gateway=gateway,
        admission_id=admission_id,
        admission_digest=admission_digest,
        web_platform_session_id=web_platform_session_id,
        web_hermes_session_id=web_hermes_session_id,
        web_command_ids=web_command_ids,
        gate1_id=gate1_id,
        gate1_hqa_ref=gate1_hqa_ref,
        gate3_id=gate3_id,
        gate3_hqa_ref=gate3_hqa_ref,
        task_ref=task_ref,
        source_digest=source_digest,
        candidate_id=candidate_id,
        candidate_digest=candidate_digest,
        final_backtest_receipt_id=final_backtest_receipt_id,
        promotion_id=promotion_id,
        base_commit=base_commit,
        reviewed_commit=reviewed_commit,
        paper_gate3_command_id=paper_gate3_command_id,
        hqa_run_ref=hqa_run_ref,
        provider_evidence_ref=provider_evidence_ref,
        workflow_audit=workflow_audit,
    )


def _capture_valid_restart(scenario: _Scenario) -> None:
    scenario.gateway.set_runtime(
        "1" * 32,
        datetime(2026, 7, 24, 1, 0, tzinfo=UTC),
    )
    before = scenario.authority.capture_restart(
        admission_id=scenario.admission_id,
        admission_digest=scenario.admission_digest,
        phase="before",
        platform_session_id=scenario.web_platform_session_id,
    )
    scenario.gateway.set_runtime(
        "2" * 32,
        datetime(2026, 7, 24, 1, 1, tzinfo=UTC),
    )
    after = scenario.authority.capture_restart(
        admission_id=scenario.admission_id,
        admission_digest=scenario.admission_digest,
        phase="after",
        platform_session_id=scenario.web_platform_session_id,
    )
    assert before.transcript_digest == after.transcript_digest
    assert before.runtime_instance_id != after.runtime_instance_id


def _correct_hqa_probe(
    scenario: _Scenario,
    operation: str,
    arguments: tuple[str, ...] | list[str],
) -> dict[str, object]:
    if operation == "audit":
        assert not arguments
        return dict(scenario.workflow_audit)
    assert operation == "show"
    assert tuple(arguments) == ("--task-ref", scenario.task_ref)
    return {
        "task_ref": scenario.task_ref,
        "version": 7,
        "state": "terminal",
        "terminal_outcome": "completed",
        "managed_session_ref": (f"session:{scenario.web_platform_session_id}"),
        "gate1_ref": scenario.gate1_hqa_ref,
        "gate1_source_digest": scenario.source_digest,
        "gate1_candidate_ref": f"candidate:{scenario.candidate_id}",
        "gate1_manifest_digest": scenario.candidate_digest,
        "gate3_refs": [scenario.gate3_hqa_ref],
        "result_refs": [f"result:{scenario.final_backtest_receipt_id}"],
        "attempts": [
            {
                "attempt_ref": "attempt:integration-plan",
                "gate3_refs": [],
                "run_ref": "run:paper-plan",
                "submission_command_ref": "command:plan-placeholder",
            },
            {
                "attempt_ref": "attempt:integration-research",
                "gate3_refs": [scenario.gate3_hqa_ref],
                "run_ref": scenario.hqa_run_ref,
                "submission_command_ref": (f"command:{scenario.paper_gate3_command_id}"),
                "terminal_outcome": "completed",
                "domain_gate_outcome": "passed",
                "provider_evidence_refs": [scenario.provider_evidence_ref],
            },
        ],
    }


def _correct_promotion_probe(
    scenario: _Scenario,
    promotion_id: str,
) -> dict[str, object]:
    assert promotion_id == scenario.promotion_id
    return {
        "promotion_id": scenario.promotion_id,
        "status": "reviewed",
        "reviewed_commit": scenario.reviewed_commit,
        "candidate_id": scenario.candidate_id,
        "candidate_digest": scenario.candidate_digest,
        "final_backtest_receipt_id": (scenario.final_backtest_receipt_id),
        "base_commit": scenario.base_commit,
    }


def _attempt_minimal_evidence_insert(
    environment: _DatabaseEnvironment,
    scenario: _Scenario,
) -> None:
    with environment.runtime.connect() as conn:
        candidate = conn.execute(
            """
            SELECT
                workspace_id,
                platform_runtime_digest,
                hqa_runtime_digest,
                hermes_runtime_digest,
                database_schema_fingerprint,
                baseline_order_snapshot_digest
            FROM quant_system.agent_v02_candidate_admissions
            WHERE admission_id = %s
            """,
            (scenario.admission_id,),
        ).fetchone()
        assert candidate is not None
        facts = {"contract": "agent-v0.2-candidate-evidence-facts/v1"}
        conn.execute(
            """
            INSERT INTO quant_system.agent_v02_candidate_evidence_sets (
                evidence_set_id,
                owner_user_id,
                workspace_id,
                admission_id,
                admission_digest,
                platform_runtime_digest,
                hqa_runtime_digest,
                hermes_runtime_digest,
                database_schema_fingerprint,
                baseline_order_snapshot_digest,
                final_order_snapshot_digest,
                facts,
                facts_digest
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s::jsonb, %s
            )
            """,
            (
                f"evidence-direct-{uuid4().hex}",
                ROOT_USER_ID,
                candidate[0],
                scenario.admission_id,
                scenario.admission_digest,
                candidate[1],
                candidate[2],
                candidate[3],
                candidate[4],
                candidate[5],
                candidate[5],
                json.dumps(facts),
                _digest(f"direct-evidence:{uuid4().hex}"),
            ),
        )


def _direct_evidence_facts(
    environment: _DatabaseEnvironment,
    scenario: _Scenario,
    *,
    flow_names: tuple[str, ...],
) -> tuple[dict[str, object], tuple[object, ...]]:
    with environment.runtime.connect() as conn:
        candidate = conn.execute(
            """
            SELECT
                workspace_id,
                platform_runtime_digest,
                hqa_runtime_digest,
                hermes_runtime_digest,
                database_schema_fingerprint,
                baseline_order_snapshot_digest
            FROM quant_system.agent_v02_candidate_admissions
            WHERE admission_id = %s
            """,
            (scenario.admission_id,),
        ).fetchone()
    assert candidate is not None
    facts: dict[str, object] = {
        "admission_digest": scenario.admission_digest,
        "admission_id": scenario.admission_id,
        "contract": "agent-v0.2-candidate-evidence-facts/v1",
        "database_schema_fingerprint": str(candidate[4]).strip(),
        "final_order_snapshot_digest": str(candidate[5]).strip(),
        "flows": {name: {"claim": "self-attested-not-canonical"} for name in flow_names},
        "runtime": {
            "hermes": str(candidate[3]).strip(),
            "hqa": str(candidate[2]).strip(),
            "platform": str(candidate[1]).strip(),
        },
        "workspace_id": str(candidate[0]),
    }
    return facts, candidate


def _insert_direct_evidence_set(
    environment: _DatabaseEnvironment,
    scenario: _Scenario,
    *,
    facts: dict[str, object],
    candidate: tuple[object, ...],
    facts_digest: str,
) -> str:
    evidence_set_id = f"evidence_{facts_digest[:32]}"
    with environment.runtime.connect() as conn:
        conn.execute(
            """
            INSERT INTO quant_system.agent_v02_candidate_evidence_sets (
                evidence_set_id,
                owner_user_id,
                workspace_id,
                admission_id,
                admission_digest,
                platform_runtime_digest,
                hqa_runtime_digest,
                hermes_runtime_digest,
                database_schema_fingerprint,
                baseline_order_snapshot_digest,
                final_order_snapshot_digest,
                facts,
                facts_digest
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s::jsonb, %s
            )
            """,
            (
                evidence_set_id,
                ROOT_USER_ID,
                candidate[0],
                scenario.admission_id,
                scenario.admission_digest,
                candidate[1],
                candidate[2],
                candidate[3],
                candidate[4],
                candidate[5],
                candidate[5],
                json.dumps(facts),
                facts_digest,
            ),
        )
    return evidence_set_id


def _insert_forged_command_with_mismatched_run(
    environment: _DatabaseEnvironment,
    scenario: _Scenario,
) -> str:
    command_id = uuid4()
    now = datetime.now(UTC)
    request_digest = _digest(f"forged-command:{command_id}")
    with environment.runtime.connect() as conn:
        conn.execute(
            """
            INSERT INTO quant_system.hermes_commands (
                command_id,
                owner_user_id,
                platform_session_id,
                client_request_id,
                kind,
                canonical_request_digest,
                payload_ref,
                provider_policy_digest,
                state,
                version,
                attempt_count,
                dispatch_started_at,
                hermes_session_id,
                hermes_run_id,
                created_at,
                updated_at
            )
            VALUES (
                %s, %s, %s, %s, 'conversation_turn',
                %s, %s, %s, 'succeeded', 5, 1,
                %s, %s, %s, %s, %s
            )
            """,
            (
                command_id,
                ROOT_USER_ID,
                scenario.web_platform_session_id,
                f"forged-{command_id.hex}",
                request_digest,
                f"platform-payload://sha256/{_digest(str(command_id))}",
                PROVIDER_POLICY_DIGEST,
                now,
                scenario.web_hermes_session_id,
                f"forged-run-{command_id.hex[:12]}",
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO quant_system.hermes_command_events (
                command_id,
                command_version,
                event_type,
                actor,
                from_state,
                to_state,
                canonical_request_digest,
                attempt_count,
                dispatch_started_at,
                hermes_session_id,
                hermes_run_id,
                event_data,
                occurred_at
            )
            VALUES (
                %s, 5, 'command_succeeded', 'worker',
                'delivered', 'succeeded', %s, 1,
                %s, %s, %s, '{}'::jsonb, %s
            )
            """,
            (
                command_id,
                request_digest,
                now,
                scenario.web_hermes_session_id,
                f"substituted-run-{command_id.hex[:12]}",
                now,
            ),
        )
    return str(command_id)


def test_candidate_evidence_runtime_is_restricted_and_schema_is_live(
    database_environment: _DatabaseEnvironment,
) -> None:
    assert candidate_evidence_runtime_security_is_ready(database_environment.settings)
    with database_environment.runtime.connect() as conn:
        assert conn.execute(
            """
            SELECT schema_version
            FROM quant_system.agent_v02_candidate_evidence_meta
            WHERE singleton IS TRUE
            """
        ).fetchone() == (1,)


@pytest.mark.parametrize(
    ("migration", "meta_table", "version_constraint"),
    [
        (
            "018_agent_v02_paper_gate_bridge.sql",
            "agent_v02_paper_gate_meta",
            "agent_v02_paper_gate_meta_schema_version_check",
        ),
        (
            "019_agent_v02_candidate_evidence_v3.sql",
            "agent_v02_candidate_evidence_meta",
            "agent_v02_candidate_evidence_meta_schema_version_check",
        ),
    ],
)
def test_migration_replay_refuses_to_clobber_newer_schema_version(
    database_environment: _DatabaseEnvironment,
    migration: str,
    meta_table: str,
    version_constraint: str,
) -> None:
    table = sql.Identifier("quant_system", meta_table)
    constraint = sql.Identifier(version_constraint)
    with database_environment.admin.connect() as conn:
        conn.execute(
            sql.SQL("ALTER TABLE {} DROP CONSTRAINT {}").format(
                table,
                constraint,
            )
        )
        conn.execute(sql.SQL("UPDATE {} SET schema_version = 2").format(table))
    try:
        with pytest.raises(
            psycopg.errors.RaiseException,
            match="incompatible with this binary",
        ):
            db.run_migrations(
                database_environment.admin,
                only=(migration,),
            )
        with database_environment.admin.connect() as conn:
            assert conn.execute(
                sql.SQL("SELECT schema_version FROM {} WHERE singleton IS TRUE").format(table)
            ).fetchone() == (2,)
    finally:
        with database_environment.admin.connect() as conn:
            conn.execute(sql.SQL("UPDATE {} SET schema_version = 1").format(table))
            conn.execute(
                sql.SQL("ALTER TABLE {} ADD CONSTRAINT {} CHECK (schema_version = 1)").format(
                    table, constraint
                )
            )


def test_complete_canonical_fact_set_is_verified_and_idempotent(
    database_environment: _DatabaseEnvironment,
) -> None:
    scenario = _seed_scenario(database_environment)
    _capture_valid_restart(scenario)

    verified = scenario.authority.verify_and_store(scenario.refs)
    replay = scenario.authority.verify_and_store(scenario.refs)

    assert verified.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert replay.evidence_set_id == verified.evidence_set_id
    assert replay.facts_digest == verified.facts_digest
    assert set(verified.facts["flows"]) == {
        "web_chat_multi_turn",
        "hermes_restart_recovery",
        "exact_message_fork",
        "options_vertical_live_futu_ro",
        "paper_factor_gate_1_2_3_via_hermes",
    }
    with database_environment.runtime.connect() as conn:
        stored = conn.execute(
            """
            SELECT
                admission_id,
                facts_digest,
                baseline_order_snapshot_digest =
                    final_order_snapshot_digest,
                facts->>'contract'
            FROM quant_system.agent_v02_candidate_evidence_sets
            WHERE evidence_set_id = %s
            """,
            (verified.evidence_set_id,),
        ).fetchone()
    assert stored == (
        scenario.admission_id,
        verified.facts_digest,
        True,
        "agent-v0.2-candidate-evidence-facts/v1",
    )


def test_capture_restart_rejects_identity_change_during_observation(
    database_environment: _DatabaseEnvironment,
) -> None:
    scenario = _seed_scenario(database_environment)
    scenario.gateway.capability_sequence = [
        (
            "1" * 32,
            datetime(2026, 7, 24, 1, 0, tzinfo=UTC),
        ),
        (
            "2" * 32,
            datetime(2026, 7, 24, 1, 1, tzinfo=UTC),
        ),
    ]

    with pytest.raises(CandidateEvidenceV3Error) as captured:
        scenario.authority.capture_restart(
            admission_id=scenario.admission_id,
            admission_digest=scenario.admission_digest,
            phase="before",
            platform_session_id=scenario.web_platform_session_id,
        )
    assert captured.value.code == ("candidate_evidence_runtime_changed_during_capture")
    with database_environment.runtime.connect() as conn:
        assert conn.execute(
            """
            SELECT count(*)
            FROM quant_system.agent_v02_candidate_restart_observations
            WHERE admission_id = %s
            """,
            (scenario.admission_id,),
        ).fetchone() == (0,)


@pytest.mark.parametrize("failure_mode", ["same_instance", "transcript_drift"])
def test_restart_proof_is_rejected_by_authority_and_database(
    database_environment: _DatabaseEnvironment,
    failure_mode: str,
) -> None:
    scenario = _seed_scenario(database_environment)
    scenario.gateway.set_runtime(
        "1" * 32,
        datetime(2026, 7, 24, 1, 0, tzinfo=UTC),
    )
    scenario.authority.capture_restart(
        admission_id=scenario.admission_id,
        admission_digest=scenario.admission_digest,
        phase="before",
        platform_session_id=scenario.web_platform_session_id,
    )
    if failure_mode == "same_instance":
        scenario.gateway.set_runtime(
            "1" * 32,
            datetime(2026, 7, 24, 1, 0, tzinfo=UTC),
        )
    else:
        messages = scenario.gateway.messages[scenario.web_hermes_session_id]["data"]
        assert isinstance(messages, list)
        messages[0] = {
            **messages[0],
            "content": "transcript was substituted after restart",
        }
        scenario.gateway.set_runtime(
            "2" * 32,
            datetime(2026, 7, 24, 1, 1, tzinfo=UTC),
        )
    scenario.authority.capture_restart(
        admission_id=scenario.admission_id,
        admission_digest=scenario.admission_digest,
        phase="after",
        platform_session_id=scenario.web_platform_session_id,
    )

    with pytest.raises(CandidateEvidenceV3Error) as rejected:
        scenario.authority.verify_and_store(scenario.refs)
    assert rejected.value.code == "candidate_evidence_restart_mismatch"
    with pytest.raises(psycopg.errors.RaiseException):
        _attempt_minimal_evidence_insert(
            database_environment,
            scenario,
        )


@pytest.mark.parametrize(
    ("flow_names", "digest_is_correct"),
    [
        pytest.param(
            REQUIRED_FLOW_NAMES,
            False,
            id="wrong-facts-digest",
        ),
        pytest.param(
            REQUIRED_FLOW_NAMES[:-1],
            True,
            id="self-consistent-digest-missing-exact-flow",
        ),
    ],
)
def test_database_trigger_rejects_self_attested_evidence_facts(
    database_environment: _DatabaseEnvironment,
    flow_names: tuple[str, ...],
    digest_is_correct: bool,
) -> None:
    scenario = _seed_scenario(database_environment)
    _capture_valid_restart(scenario)
    facts, candidate = _direct_evidence_facts(
        database_environment,
        scenario,
        flow_names=flow_names,
    )
    with database_environment.runtime.connect() as conn:
        digest_row = conn.execute(
            """
            SELECT encode(
                sha256(convert_to(%s::jsonb::text, 'UTF8')),
                'hex'
            )
            """,
            (json.dumps(facts),),
        ).fetchone()
    assert digest_row is not None
    canonical_digest = str(digest_row[0])
    supplied_digest = canonical_digest if digest_is_correct else "0" * 64
    assert (supplied_digest == canonical_digest) is digest_is_correct

    with pytest.raises(psycopg.errors.RaiseException):
        _insert_direct_evidence_set(
            database_environment,
            scenario,
            facts=facts,
            candidate=candidate,
            facts_digest=supplied_digest,
        )
    with database_environment.runtime.connect() as conn:
        assert conn.execute(
            """
            SELECT count(*)
            FROM quant_system.agent_v02_candidate_evidence_sets
            WHERE admission_id = %s
            """,
            (scenario.admission_id,),
        ).fetchone() == (0,)


def test_fake_command_run_gate_promotion_and_hqa_facts_are_rejected(
    database_environment: _DatabaseEnvironment,
) -> None:
    scenario = _seed_scenario(database_environment)
    _capture_valid_restart(scenario)

    forged_command_id = _insert_forged_command_with_mismatched_run(
        database_environment,
        scenario,
    )
    with pytest.raises(CandidateEvidenceV3Error) as fake_command:
        scenario.authority.verify_and_store(
            replace(
                scenario.refs,
                web_command_ids=(
                    scenario.web_command_ids[0],
                    forged_command_id,
                ),
            )
        )
    assert fake_command.value.code == "candidate_evidence_multiturn_missing"

    with pytest.raises(CandidateEvidenceV3Error) as fake_gate:
        scenario.authority.verify_and_store(
            replace(
                scenario.refs,
                paper_gate3_id=f"paper-g3-fake-{uuid4().hex[:10]}",
            )
        )
    assert fake_gate.value.code == "candidate_evidence_paper_gate_missing"

    wrong_promotion = CandidateEvidenceV3Authority(
        database_environment.settings,
        database=database_environment.runtime,
        gateway=scenario.gateway,
        hqa_probe=lambda operation, arguments: _correct_hqa_probe(
            scenario,
            operation,
            arguments,
        ),
        promotion_probe=lambda promotion_id: {
            **_correct_promotion_probe(scenario, promotion_id),
            "reviewed_commit": "d" * 40,
        },
    )
    with pytest.raises(CandidateEvidenceV3Error) as promotion:
        wrong_promotion.verify_and_store(scenario.refs)
    assert promotion.value.code == "candidate_evidence_promotion_unreviewed"

    def mismatched_hqa(
        operation: str,
        arguments: tuple[str, ...] | list[str],
    ) -> dict[str, object]:
        result = _correct_hqa_probe(scenario, operation, arguments)
        if operation == "show":
            result["gate1_manifest_digest"] = "e" * 64
        return result

    wrong_hqa = CandidateEvidenceV3Authority(
        database_environment.settings,
        database=database_environment.runtime,
        gateway=scenario.gateway,
        hqa_probe=mismatched_hqa,
        promotion_probe=lambda promotion_id: _correct_promotion_probe(
            scenario,
            promotion_id,
        ),
    )
    with pytest.raises(CandidateEvidenceV3Error) as hqa:
        wrong_hqa.verify_and_store(scenario.refs)
    assert hqa.value.code == "candidate_evidence_hqa_audit_mismatch"


@pytest.mark.parametrize(
    ("task_state", "task_outcome", "attempt_outcome"),
    [
        ("running", None, None),
        ("terminal", "completed", None),
    ],
)
def test_candidate_rejects_running_or_nonterminal_hqa_workflow(
    database_environment: _DatabaseEnvironment,
    task_state: str,
    task_outcome: str | None,
    attempt_outcome: str | None,
) -> None:
    scenario = _seed_scenario(database_environment)
    _capture_valid_restart(scenario)

    def nonterminal_hqa(
        operation: str,
        arguments: tuple[str, ...] | list[str],
    ) -> dict[str, object]:
        result = _correct_hqa_probe(scenario, operation, arguments)
        if operation == "show":
            result["state"] = task_state
            result["terminal_outcome"] = task_outcome
            attempts = result["attempts"]
            assert isinstance(attempts, list)
            attempts[1]["terminal_outcome"] = attempt_outcome
        return result

    authority = CandidateEvidenceV3Authority(
        database_environment.settings,
        database=database_environment.runtime,
        gateway=scenario.gateway,
        hqa_probe=nonterminal_hqa,
        promotion_probe=lambda promotion_id: _correct_promotion_probe(
            scenario,
            promotion_id,
        ),
    )
    with pytest.raises(CandidateEvidenceV3Error) as rejected:
        authority.verify_and_store(scenario.refs)
    assert rejected.value.code == "candidate_evidence_hqa_audit_mismatch"


def test_verified_evidence_is_append_only_for_constrained_runtime(
    database_environment: _DatabaseEnvironment,
) -> None:
    scenario = _seed_scenario(database_environment)
    _capture_valid_restart(scenario)
    verified = scenario.authority.verify_and_store(scenario.refs)

    with database_environment.runtime.connect() as conn:
        assert conn.execute(
            """
            SELECT owner_user_id
            FROM quant_system.agent_v02_candidate_evidence_sets
            WHERE evidence_set_id = %s
            """,
            (verified.evidence_set_id,),
        ).fetchone() == (ROOT_USER_ID,)
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        database_environment.runtime.connect() as conn,
    ):
        conn.execute(
            """
            UPDATE quant_system.agent_v02_candidate_evidence_sets
            SET facts = facts
            WHERE evidence_set_id = %s
            """,
            (verified.evidence_set_id,),
        )
    with (
        pytest.raises(psycopg.errors.InsufficientPrivilege),
        database_environment.runtime.connect() as conn,
    ):
        conn.execute(
            """
            DELETE FROM quant_system.agent_v02_candidate_evidence_sets
            WHERE evidence_set_id = %s
            """,
            (verified.evidence_set_id,),
        )


def test_zero_order_baseline_and_final_drift_is_rejected(
    database_environment: _DatabaseEnvironment,
) -> None:
    scenario = _seed_scenario(database_environment)
    _capture_valid_restart(scenario)
    with database_environment.admin.connect() as conn:
        conn.execute(
            """
            UPDATE quant_system.paper_accounts
            SET version = version + 1,
                raw = jsonb_set(
                    raw,
                    '{version}',
                    to_jsonb(version + 1)
                ),
                updated_at = clock_timestamp()
            WHERE account_id = 'candidate-evidence-paper'
            """
        )

    with pytest.raises(CandidateEvidenceV3Error) as drift:
        scenario.authority.verify_and_store(scenario.refs)
    assert drift.value.code == "candidate_evidence_orders_changed"
    with database_environment.runtime.connect() as conn:
        assert conn.execute(
            """
            SELECT count(*)
            FROM quant_system.agent_v02_candidate_evidence_sets
            WHERE admission_id = %s
            """,
            (scenario.admission_id,),
        ).fetchone() == (0,)
