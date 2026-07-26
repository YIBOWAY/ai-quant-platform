from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from quant_system.config.settings import DatabaseSettings, Settings
from quant_system.hermes.agent_workspace_actions import (
    ConfirmFormulaSource,
    PreparePromotionReview,
    ReviewCandidateCAS,
    WorkspaceRef,
    canonical_action_digest,
)
from quant_system.hermes.command_ledger import ROOT_USER_ID
from quant_system.hermes.paper_gate_authority import (
    PaperGateAuthority,
    PaperGateAuthorityConflict,
    PaperGateAuthorityUnavailable,
    PaperGateAuthorityValidationError,
    RegisterPaperGateChallenge,
    RegisterPaperGateCompletion,
    paper_gate_runtime_security_is_ready_on_connection,
    paper_gate_schema_is_ready_on_connection,
)
from quant_system.hermes.paper_gate_port import PaperGatePortError
from quant_system.storage.database import Database

pytestmark = pytest.mark.pg

SOURCE = "1" * 64
CANDIDATE = "2" * 64
BASE = "3" * 40
_RUNTIME_TEST_URL: str | None = None


def _completion_request(
    *,
    gate_id: str,
    workspace_id: str,
    task_version: int,
    task_status: str = "completed",
    promotion_id: str = "promo-" + "8" * 32,
    subject_command_id: str = "10000000-0000-4000-8000-000000000099",
    subject_run_id: str = "paper-research",
) -> RegisterPaperGateCompletion:
    identity_digest = hashlib.sha256(f"{workspace_id}:{gate_id}".encode()).hexdigest()
    subject_attestation_digest = "5" * 64
    evidence = {
        "schema_version": "agent-v0.2-paper-completion/v1",
        "task_ref": "task:paper-1",
        "task_version": task_version,
        "task_status": task_status,
        "task_terminal_outcome": "completed",
        "plan_version": 1,
        "plan_digest": "6" * 64,
        "plan_confirmation_note_digest": "7" * 64,
        "attempt_ref": "attempt:paper-3",
        "attempt_status": "completed",
        "attempt_terminal_outcome": "completed",
        "domain_gate_ref": "gate:paper-domain-g3",
        "domain_gate_outcome": "passed",
        "hqa_run_ref": f"run:{subject_run_id}",
        "provider_evidence_ref": (f"provider-evidence:paper-run-{subject_attestation_digest}"),
        "subject_command_id": subject_command_id,
        "subject_hermes_run_id": subject_run_id,
        "subject_run_attestation_ref": (f"paper-run-attestation:{subject_attestation_digest}"),
        "subject_run_attestation_digest": subject_attestation_digest,
        "final_backtest_provider": "futu",
        "final_backtest_receipt_digest": "8" * 64,
        "final_backtest_config_ref": "/evidence/config.json",
        "final_backtest_config_digest": "9" * 64,
        "final_backtest_summary_ref": "/evidence/summary.json",
        "final_backtest_summary_digest": "a" * 64,
        "final_backtest_report_ref": "/evidence/report.json",
        "final_backtest_report_digest": "b" * 64,
        "promotion_id": promotion_id,
        "reviewed_commit": "4" * 40,
        "candidate_id": "factor-paper-1",
        "candidate_digest": CANDIDATE,
        "final_backtest_receipt_id": "backtest-" + "9" * 32,
        "base_commit": BASE,
        "attempt_completion_operation_id": (f"paper-research-complete-{identity_digest[:16]}"),
        "attempt_completion_event_id": "event:" + "a" * 64,
        "task_completion_operation_id": (f"paper-task-complete-{identity_digest[:16]}"),
        "task_completion_event_id": "event:" + "b" * 64,
        "workflow_audit_status": "consistent",
        "workflow_audit_ref": f"workflow-audit:{identity_digest}",
        "workflow_audit_digest": identity_digest,
    }
    digest = hashlib.sha256(
        json.dumps(
            evidence,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return RegisterPaperGateCompletion(
        gate_id=gate_id,
        workspace_id=workspace_id,
        hqa_completion_receipt_ref=(f"hqa-paper-completion:{digest[:32]}"),
        hqa_completion_receipt_digest=digest,
        completion_evidence=evidence,
    )


def _test_url() -> str:
    return _admin_test_url()


def _admin_test_url() -> str:
    url = os.environ.get("QS_TEST_DATABASE_ADMIN_URL") or os.environ.get(
        "QS_TEST_DATABASE_URL"
    )
    if not url:
        pytest.skip("set a PostgreSQL test admin URL for paper Gate tests")
    dbname = psycopg.conninfo.conninfo_to_dict(url).get("dbname")
    if not dbname or not (dbname.endswith("_tmp") or "test" in dbname):
        pytest.fail("QS_TEST_DATABASE_ADMIN_URL must point at a throwaway database")
    return url


@pytest.fixture(scope="module", autouse=True)
def _constrained_paper_gate_runtime_login() -> Iterator[None]:
    global _RUNTIME_TEST_URL

    admin_url = _admin_test_url()
    test_url = admin_url
    admin_params = conninfo_to_dict(admin_url)
    test_params = conninfo_to_dict(test_url)
    if admin_params.get("dbname") != test_params.get("dbname"):
        pytest.fail("paper gate runtime and admin URLs must target the same database")
    suffix = uuid4().hex[:12]
    login = f"aqp_paper_gate_{suffix}"
    password = f"paper-gate-{suffix}"
    with psycopg.connect(admin_url) as conn:
        conn.execute(
            sql.SQL(
                "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS "
                "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
            ).format(sql.Identifier(login), sql.Literal(password))
        )
        conn.execute(sql.SQL("GRANT quant_runtime TO {}").format(sql.Identifier(login)))
    runtime_params = dict(test_params)
    runtime_params["user"] = login
    runtime_params["password"] = password
    _RUNTIME_TEST_URL = make_conninfo(**runtime_params)
    try:
        yield
    finally:
        _RUNTIME_TEST_URL = None
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(
                """
                SELECT pg_terminate_backend(pid)
                FROM pg_stat_activity
                WHERE usename = %s
                  AND pid <> pg_backend_pid()
                """,
                (login,),
            )
            conn.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(login)))


def _runtime_test_url() -> str:
    if _RUNTIME_TEST_URL is None:
        pytest.fail("constrained paper gate runtime login is unavailable")
    return _RUNTIME_TEST_URL


def test_completion_contract_accepts_canonical_revision_promotion_id() -> None:
    request = _completion_request(
        gate_id="paper-g3-revision",
        workspace_id="paper-revision",
        task_version=13,
        promotion_id="promo-" + "8" * 32 + "-r2",
    )
    validated = PaperGateAuthority._validated_completion(request)
    assert validated[4]["promotion_id"] == "promo-" + "8" * 32 + "-r2"


def _settings() -> Settings:
    return Settings(
        database=DatabaseSettings(
            enabled=True,
            url=_runtime_test_url(),
            auto_migrate=False,
            connect_timeout_seconds=1,
        )
    )


def _managed_session(
    workspace_id: str,
    *,
    state: str = "ready",
) -> tuple[str, str]:
    suffix = os.urandom(8).hex()
    platform_session_id = f"paper-session-{suffix}"
    creation_digest = hashlib.sha256(f"{workspace_id}:{platform_session_id}".encode()).hexdigest()
    hermes_session_id = f"web_{creation_digest[:40]}"
    values: dict[str, object] = {
        "platform_session_id": platform_session_id,
        "hermes_session_id": hermes_session_id,
        "workspace_id": workspace_id,
        "owner_user_id": ROOT_USER_ID,
        "kind": "web_managed_session",
        "provider_policy_digest": "a" * 64,
        "writer": "web_control_plane",
        "payload_ttl_days": 7,
        "creation_client_action_id": f"paper-create-{suffix}",
        "creation_action_digest": creation_digest,
        "provision_state": state,
        "provisioning_receipt_digest": "b" * 64 if state == "ready" else None,
        "provisioned_at": "2026-07-24T00:00:00Z" if state == "ready" else None,
    }
    with Database(_test_url(), connect_timeout=1).connect() as conn:
        conn.execute(
            """
            INSERT INTO quant_system.hermes_workspace_sessions (
                platform_session_id,
                hermes_session_id,
                workspace_id,
                owner_user_id,
                kind,
                provider_policy_digest,
                writer,
                payload_ttl_days,
                creation_client_action_id,
                creation_action_digest,
                provision_state,
                provisioning_receipt_digest,
                provisioned_at
            )
            VALUES (
                %(platform_session_id)s,
                %(hermes_session_id)s,
                %(workspace_id)s,
                %(owner_user_id)s,
                %(kind)s,
                %(provider_policy_digest)s,
                %(writer)s,
                %(payload_ttl_days)s,
                %(creation_client_action_id)s,
                %(creation_action_digest)s,
                %(provision_state)s,
                %(provisioning_receipt_digest)s,
                %(provisioned_at)s
            )
            """,
            values,
        )
    return platform_session_id, hermes_session_id


def _succeeded_command(
    platform_session_id: str,
    hermes_run_id: str,
) -> str:
    command_id = uuid4()
    request_digest = hashlib.sha256(str(command_id).encode()).hexdigest()
    with Database(_test_url(), connect_timeout=1).connect() as conn:
        session = conn.execute(
            """
            SELECT hermes_session_id
            FROM quant_system.hermes_workspace_sessions
            WHERE platform_session_id = %s
            """,
            (platform_session_id,),
        ).fetchone()
        assert session is not None
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
                resolved_hermes_session_id,
                hermes_run_id
            )
            VALUES (
                %s, %s, %s, %s, 'conversation_turn', %s, %s, %s,
                'succeeded', 1, 1, clock_timestamp(), %s, %s, %s
            )
            """,
            (
                command_id,
                ROOT_USER_ID,
                platform_session_id,
                f"paper-test-{command_id}",
                request_digest,
                f"platform-payload://sha256/{request_digest}",
                "a" * 64,
                str(session[0]),
                str(session[0]),
                hermes_run_id,
            ),
        )
    return str(command_id)


def _hermes_session_id(platform_session_id: str) -> str:
    with Database(_test_url(), connect_timeout=1).connect() as conn:
        row = conn.execute(
            """
            SELECT hermes_session_id
            FROM quant_system.hermes_workspace_sessions
            WHERE platform_session_id = %s
            """,
            (platform_session_id,),
        ).fetchone()
    assert row is not None
    return str(row[0])


@dataclass
class _FakePort:
    calls: list[tuple[str, dict[str, object]]]

    def execute(self, operation: str, request: dict[str, object]):
        self.calls.append((operation, dict(request)))
        common = {
            "ok": True,
            "managed_session_ref": request["managed_session_ref"],
            "operation_id": request["operation_id"],
            "hqa_receipt_ref": f"hqa-paper-gate:{request['operation_id']}",
        }
        if operation == "confirm-formula":
            document = {
                **common,
                "task_ref": request["task_ref"],
                "gate_ref": request["gate_ref"],
                "reviewed_source_digest": request["reviewed_source_digest"],
                "gate1_confirmation_id": "gate1-" + "5" * 32,
                "event_id": "event:" + "6" * 64,
                "attempt_ref": "attempt:paper-2",
                "task_version": int(request["expected_task_version"]) + 1,
            }
        elif operation == "approve":
            document = {
                **common,
                "task_ref": request["task_ref"],
                "gate_ref": request["gate_ref"],
                "gate1_confirmation_id": request["gate1_confirmation_id"],
                "reviewed_source_digest": request["reviewed_source_digest"],
                "candidate_id": request["candidate_id"],
                "candidate_digest": request["expected_digest"],
                "decision": "approve",
                "registration": "manual_required",
                "review_note_digest": hashlib.sha256(
                    str(request["note"]).encode("utf-8")
                ).hexdigest(),
                "workflow_binding_event_id": "event:" + "7" * 64,
                "attempt_ref": "attempt:paper-2",
                "task_version": int(request["expected_task_version"]) + 1,
            }
        else:
            document = {
                **common,
                "task_ref": request["task_ref"],
                "attempt_ref": request["attempt_ref"],
                "task_version": int(request["expected_task_version"]) + 2,
                "workflow_gate_resolution_event_id": "event:" + "9" * 64,
                "workflow_gate3_event_id": "event:" + "8" * 64,
                "run_ref": request["run_ref"],
                "gate_ref": request["gate_ref"],
                "candidate_id": request["candidate_id"],
                "candidate_digest": request["expected_digest"],
                "final_backtest_receipt_id": request["final_backtest_receipt_id"],
                "base_commit": request["base_commit"],
                "promotion_id": "promo-" + "8" * 32,
                "promotion_status": "awaiting_human_commit",
                "worktree": "/tmp/paper-review",
                "patch": "/tmp/paper-review.patch",
                "manifest": "/tmp/paper-review.json",
                "human_git_commit_required": True,
                "auto_commit": False,
            }
        evidence = {
            key: value for key, value in document.items() if key not in {"ok", "hqa_receipt_ref"}
        }
        document["hqa_receipt_digest"] = hashlib.sha256(
            json.dumps(
                evidence,
                ensure_ascii=False,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        return document


def _authority() -> PaperGateAuthority:
    settings = _settings()
    database = Database(_runtime_test_url(), connect_timeout=1)
    with database.connect() as conn:
        assert paper_gate_schema_is_ready_on_connection(conn)
        assert paper_gate_runtime_security_is_ready_on_connection(conn)
    return PaperGateAuthority(settings, database=database)


def test_runtime_security_rejects_admin_or_migrator_connection() -> None:
    runtime_database = Database(_runtime_test_url(), connect_timeout=1)
    with runtime_database.connect() as conn:
        assert paper_gate_runtime_security_is_ready_on_connection(conn)

    admin_settings = Settings(
        database=DatabaseSettings(
            enabled=True,
            url=_admin_test_url(),
            auto_migrate=False,
            connect_timeout_seconds=1,
        )
    )
    admin_database = Database(_admin_test_url(), connect_timeout=1)
    with admin_database.connect() as conn:
        assert paper_gate_schema_is_ready_on_connection(conn)
        assert not paper_gate_runtime_security_is_ready_on_connection(conn)
    with pytest.raises(
        PaperGateAuthorityUnavailable,
        match="runtime security is not ready",
    ):
        PaperGateAuthority(
            admin_settings,
            database=admin_database,
        ).list_observed("workspace-root")


@pytest.mark.parametrize(
    "drift_sql",
    [
        (
            "ALTER TABLE quant_system.agent_v02_paper_gate_actions "
            "DROP CONSTRAINT agent_v02_paper_gate_actions_pkey"
        ),
        (
            "ALTER TABLE quant_system.agent_v02_paper_gate_actions "
            "DROP CONSTRAINT "
            "agent_v02_paper_gate_actions_action_state_check"
        ),
        ("DROP INDEX quant_system.ux_agent_v02_paper_gate_single_action"),
        (
            "ALTER POLICY v4r_root_scope ON "
            "quant_system.agent_v02_paper_gate_actions "
            "USING (true) WITH CHECK (true)"
        ),
        (
            "ALTER TABLE quant_system.agent_v02_paper_gate_challenges "
            "ALTER COLUMN platform_session_id DROP NOT NULL"
        ),
        (
            "DROP TRIGGER trg_agent_v02_paper_gate_ready_session ON "
            "quant_system.agent_v02_paper_gate_challenges"
        ),
        (
            "CREATE OR REPLACE FUNCTION "
            "quant_system.require_agent_v02_paper_gate_ready_session() "
            "RETURNS trigger LANGUAGE plpgsql STABLE SECURITY INVOKER "
            "AS 'BEGIN RETURN NEW; END;'"
        ),
    ],
)
def test_schema_readiness_fails_closed_on_security_drift(
    drift_sql: str,
) -> None:
    class _RollbackProbe(RuntimeError):
        pass

    database = Database(_admin_test_url(), connect_timeout=1)
    with database.connect() as conn:
        assert paper_gate_schema_is_ready_on_connection(conn)
        try:
            with conn.transaction():
                conn.execute(drift_sql)
                assert not paper_gate_schema_is_ready_on_connection(conn)
                raise _RollbackProbe
        except _RollbackProbe:
            pass
        assert paper_gate_schema_is_ready_on_connection(conn)


def test_registration_requires_exact_ready_platform_managed_session() -> None:
    authority = _authority()
    workspace = "paper-session-contract-" + os.urandom(5).hex()
    pending_session_id, hermes_session_id = _managed_session(
        workspace,
        state="pending",
    )
    pending_run_id = "paper-session-contract-run"
    pending_command_id = _succeeded_command(
        pending_session_id,
        pending_run_id,
    )

    def registration(
        *,
        gate_id: str,
        platform_session_id: object,
    ) -> RegisterPaperGateChallenge:
        return RegisterPaperGateChallenge(
            gate_id=gate_id,
            gate_kind="gate1",
            workspace_id=workspace,
            task_ref="task:paper-session-contract",
            expected_task_version=1,
            platform_session_id=platform_session_id,  # type: ignore[arg-type]
            hermes_session_id=hermes_session_id,
            command_id=pending_command_id,
            hermes_run_id=pending_run_id,
            attempt_ref="attempt:paper-session-contract-1",
            hqa_gate_ref="gate:paper-session-contract",
            source_file_ref="/tmp/paper-session-contract.py",
            universe="US",
            reviewed_source_sha256=SOURCE,
        )

    with pytest.raises(
        PaperGateAuthorityConflict,
        match="managed session binding is not ready",
    ):
        authority.register_challenge(
            registration(
                gate_id="paper-session-pending",
                platform_session_id=pending_session_id,
            )
        )
    with pytest.raises(
        PaperGateAuthorityConflict,
        match="managed session binding is not ready",
    ):
        authority.register_challenge(
            registration(
                gate_id="paper-session-hermes-id",
                platform_session_id=hermes_session_id,
            )
        )
    with pytest.raises(
        PaperGateAuthorityValidationError,
        match="platform_session_id",
    ):
        authority.register_challenge(
            registration(
                gate_id="paper-session-null",
                platform_session_id=None,
            )
        )

    with (
        Database(_admin_test_url(), connect_timeout=1).connect() as conn,
        pytest.raises(
            psycopg.errors.RaiseException,
            match="exact delivered or succeeded Command",
        ),
    ):
        conn.execute(
            """
            INSERT INTO quant_system.agent_v02_paper_gate_challenges (
                gate_id,
                owner_user_id,
                workspace_id,
                gate_kind,
                task_ref,
                expected_task_version,
                attempt_ref,
                hqa_gate_ref,
                platform_session_id,
                hermes_session_id,
                command_id,
                hermes_run_id,
                source_file_ref,
                universe,
                reviewed_source_sha256
            )
            VALUES (
                'paper-session-direct-bypass',
                %s,
                %s,
                'gate1',
                'task:paper-session-contract',
                1,
                'attempt:paper-session-contract-1',
                'gate:paper-session-contract',
                %s,
                %s,
                %s,
                %s,
                '/tmp/paper-session-contract.py',
                'US',
                %s
            )
            """,
            (
                ROOT_USER_ID,
                workspace,
                pending_session_id,
                hermes_session_id,
                pending_command_id,
                pending_run_id,
                SOURCE,
            ),
        )


def test_gate1_source_evidence_is_exact_workspace_bound_and_rehashed(
    tmp_path: Path,
) -> None:
    authority = _authority()
    workspace = "paper-source-review-" + os.urandom(5).hex()
    platform_session_id, hermes_session_id = _managed_session(workspace)
    run_id = "paper-source-review-run"
    command_id = _succeeded_command(platform_session_id, run_id)
    source = tmp_path / "paper_reversal_factor.py"
    source.write_text(
        "def paper_reversal(short_return: float) -> float:\n    return -short_return\n",
        encoding="utf-8",
    )
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    gate_id = "paper-source-review-" + os.urandom(4).hex()
    authority.register_challenge(
        RegisterPaperGateChallenge(
            gate_id=gate_id,
            gate_kind="gate1",
            workspace_id=workspace,
            task_ref="task:paper-source-review",
            expected_task_version=1,
            platform_session_id=platform_session_id,
            hermes_session_id=hermes_session_id,
            command_id=command_id,
            hermes_run_id=run_id,
            attempt_ref="attempt:paper-source-review-1",
            hqa_gate_ref="gate:paper-source-review",
            source_file_ref=str(source),
            universe="Global equities",
            reviewed_source_sha256=digest,
        )
    )

    evidence = authority.get_gate1_source_evidence(
        workspace_id=workspace,
        gate_id=gate_id,
    )
    assert evidence["source_utf8"] == source.read_text(encoding="utf-8")
    assert evidence["reviewed_source_sha256"] == digest
    assert evidence["observed_source_sha256"] == digest
    assert evidence["workspace_id"] == workspace

    source.write_text("def changed():\n    return True\n", encoding="utf-8")
    with pytest.raises(
        RuntimeError,
        match="no longer match",
    ):
        authority.get_gate1_source_evidence(
            workspace_id=workspace,
            gate_id=gate_id,
        )

    with pytest.raises(
        RuntimeError,
        match="missing",
    ):
        authority.get_gate1_source_evidence(
            workspace_id=workspace + "-other",
            gate_id=gate_id,
        )


def test_durable_gate_chain_calls_exact_hqa_ports_and_replays_after_restart(
    tmp_path: Path,
) -> None:
    authority = _authority()
    workspace = "paper-chain-" + os.urandom(5).hex()
    platform_session_id, _ = _managed_session(workspace)
    source_file = tmp_path / "reversal.py"
    source_file.write_text("class ReversalFactor:\n    pass\n", encoding="utf-8")
    port = _FakePort([])
    gate1_run_id = "run-paper-1"
    gate2_run_id = "run-paper-2"
    gate3_run_id = "run-paper-3"
    gate1_command_id = _succeeded_command(
        platform_session_id,
        gate1_run_id,
    )
    gate2_command_id = _succeeded_command(
        platform_session_id,
        gate2_run_id,
    )
    gate3_command_id = _succeeded_command(
        platform_session_id,
        gate3_run_id,
    )
    subject_run_id = "paper-research"
    subject_command_id = _succeeded_command(
        platform_session_id,
        subject_run_id,
    )
    subject_attestation_digest = "5" * 64
    gate3_evidence = {
        "provider_evidence_ref": (f"provider-evidence:paper-run-{subject_attestation_digest}"),
        "subject_command_id": subject_command_id,
        "subject_hermes_run_id": subject_run_id,
        "subject_run_attestation_ref": (f"paper-run-attestation:{subject_attestation_digest}"),
        "subject_run_attestation_digest": subject_attestation_digest,
        "final_backtest_provider": "futu",
        "final_backtest_receipt_digest": "8" * 64,
        "final_backtest_config_ref": "/evidence/config.json",
        "final_backtest_config_digest": "9" * 64,
        "final_backtest_summary_ref": "/evidence/summary.json",
        "final_backtest_summary_digest": "a" * 64,
        "final_backtest_report_ref": "/evidence/report.json",
        "final_backtest_report_digest": "b" * 64,
    }

    authority.register_challenge(
        RegisterPaperGateChallenge(
            gate_id="paper-g1-" + os.urandom(4).hex(),
            gate_kind="gate1",
            workspace_id=workspace,
            task_ref="task:paper-1",
            expected_task_version=7,
            attempt_ref="attempt:paper-2",
            hqa_gate_ref="gate:paper-domain-g1",
            platform_session_id=platform_session_id,
            hermes_session_id=_hermes_session_id(platform_session_id),
            command_id=gate1_command_id,
            hermes_run_id=gate1_run_id,
            parent_gate_id=None,
            source_file_ref=str(source_file),
            universe="US ETFs",
            reviewed_source_sha256=SOURCE,
        )
    )
    gate1_action = ConfirmFormulaSource(
        client_action_id="paper-g1-action",
        workspace=WorkspaceRef(workspace),
        task_ref="task:paper-1",
        reviewed_source_sha256=SOURCE,
        confirmation_note="I reviewed the exact source bytes.",
    )
    gate1 = authority.execute_action(
        gate1_action,
        action_digest=canonical_action_digest(gate1_action),
        port=port,
    )
    assert gate1.status == "confirmed"
    assert gate1.hqa_receipt_ref.startswith("hqa-paper-gate:")
    assert port.calls[0] == (
        "confirm-formula",
        {
            "confirmation_note": "I reviewed the exact source bytes.",
            "expected_task_version": 7,
            "gate_ref": "gate:paper-domain-g1",
            "managed_session_ref": f"session:{platform_session_id}",
            "operation_id": gate1.hqa_operation_id,
            "reviewed_source_digest": SOURCE,
            "source_file": str(source_file),
            "task_ref": "task:paper-1",
            "universe": "US ETFs",
        },
    )

    # A fresh authority instance returns the durable receipt without a second
    # HQA mutation.
    replay = _authority().execute_action(
        gate1_action,
        action_digest=canonical_action_digest(gate1_action),
        port=port,
    )
    assert replay.idempotent_replay is True
    assert replay.managed_session_ref == f"session:{platform_session_id}"
    assert len(port.calls) == 1

    gate2_id = "paper-g2-" + os.urandom(4).hex()
    with pytest.raises(
        PaperGateAuthorityConflict,
        match="parent Gate exact binding",
    ):
        authority.register_challenge(
            RegisterPaperGateChallenge(
                gate_id="paper-g2-wrong-attempt-" + os.urandom(3).hex(),
                gate_kind="gate2",
                workspace_id=workspace,
                task_ref="task:paper-1",
                expected_task_version=8,
                attempt_ref="attempt:substituted-plan",
                hqa_gate_ref="gate:paper-domain-g1",
                platform_session_id=platform_session_id,
                hermes_session_id=_hermes_session_id(platform_session_id),
                command_id=gate2_command_id,
                hermes_run_id=gate2_run_id,
                parent_gate_id=gate1.gate_id,
                reviewed_source_sha256=SOURCE,
                gate1_confirmation_id=gate1.gate1_confirmation_id,
                candidate_id="factor-paper-1",
                expected_digest=CANDIDATE,
                expected_status="pending",
            )
        )
    authority.register_challenge(
        RegisterPaperGateChallenge(
            gate_id=gate2_id,
            gate_kind="gate2",
            workspace_id=workspace,
            task_ref="task:paper-1",
            expected_task_version=8,
            attempt_ref="attempt:paper-2",
            hqa_gate_ref="gate:paper-domain-g1",
            platform_session_id=platform_session_id,
            hermes_session_id=_hermes_session_id(platform_session_id),
            command_id=gate2_command_id,
            hermes_run_id=gate2_run_id,
            parent_gate_id=gate1.gate_id,
            reviewed_source_sha256=SOURCE,
            gate1_confirmation_id=gate1.gate1_confirmation_id,
            candidate_id="factor-paper-1",
            expected_digest=CANDIDATE,
            expected_status="pending",
        )
    )
    gate2_action = ReviewCandidateCAS(
        client_action_id="paper-g2-action",
        workspace=WorkspaceRef(workspace),
        candidate_ref="candidate:factor-paper-1",
        expected_digest=CANDIDATE,
        expected_status="pending",
        note="Reviewed exact candidate and manifest.",
    )
    gate2 = authority.execute_action(
        gate2_action,
        action_digest=canonical_action_digest(gate2_action),
        port=port,
    )
    assert gate2.status == "reviewed"
    assert port.calls[1][0] == "approve"
    assert port.calls[1][1]["gate1_confirmation_id"] == gate1.gate1_confirmation_id
    assert port.calls[1][1]["expected_status"] == "pending"

    with pytest.raises(
        PaperGateAuthorityConflict,
        match="parent Gate exact binding",
    ):
        authority.register_challenge(
            RegisterPaperGateChallenge(
                gate_id="paper-g3-reused-attempt-" + os.urandom(3).hex(),
                gate_kind="gate3",
                workspace_id=workspace,
                task_ref="task:paper-1",
                expected_task_version=9,
                attempt_ref="attempt:paper-2",
                hqa_gate_ref="gate:paper-domain-g3",
                platform_session_id=platform_session_id,
                hermes_session_id=_hermes_session_id(platform_session_id),
                command_id=gate3_command_id,
                hermes_run_id=gate3_run_id,
                hqa_run_ref="run:paper-research",
                **gate3_evidence,
                parent_gate_id=gate2_id,
                reviewed_source_sha256=SOURCE,
                gate1_confirmation_id=gate1.gate1_confirmation_id,
                candidate_id="factor-paper-1",
                expected_digest=CANDIDATE,
                final_backtest_receipt_id="backtest-" + "9" * 32,
                base_commit=BASE,
            )
        )
    gate3_id = "paper-g3-" + os.urandom(4).hex()
    authority.register_challenge(
        RegisterPaperGateChallenge(
            gate_id=gate3_id,
            gate_kind="gate3",
            workspace_id=workspace,
            task_ref="task:paper-1",
            expected_task_version=9,
            attempt_ref="attempt:paper-3",
            hqa_gate_ref="gate:paper-domain-g3",
            platform_session_id=platform_session_id,
            hermes_session_id=_hermes_session_id(platform_session_id),
            command_id=gate3_command_id,
            hermes_run_id=gate3_run_id,
            hqa_run_ref="run:paper-research",
            **gate3_evidence,
            parent_gate_id=gate2_id,
            reviewed_source_sha256=SOURCE,
            gate1_confirmation_id=gate1.gate1_confirmation_id,
            candidate_id="factor-paper-1",
            expected_digest=CANDIDATE,
            final_backtest_receipt_id="backtest-" + "9" * 32,
            base_commit=BASE,
        )
    )
    gate3_action = PreparePromotionReview(
        client_action_id="paper-g3-action",
        workspace=WorkspaceRef(workspace),
        candidate_ref="candidate:factor-paper-1",
        expected_digest=CANDIDATE,
        final_backtest_receipt_ref="receipt:backtest-" + "9" * 32,
        base_commit=BASE,
    )
    gate3 = authority.execute_action(
        gate3_action,
        action_digest=canonical_action_digest(gate3_action),
        port=port,
    )
    assert gate3.status == "prepared"
    assert gate3.human_git_commit_required is True
    assert gate3.auto_commit is False
    assert port.calls[2][0] == "promote"
    assert port.calls[2][1]["final_backtest_receipt_id"] == ("backtest-" + "9" * 32)

    with pytest.raises(
        PaperGateAuthorityValidationError,
        match="not terminal",
    ):
        authority.register_completion(
            _completion_request(
                gate_id=gate3_id,
                workspace_id=workspace,
                task_version=13,
                task_status="running",
                subject_command_id=subject_command_id,
                subject_run_id=subject_run_id,
            )
        )
    completion_request = _completion_request(
        gate_id=gate3_id,
        workspace_id=workspace,
        task_version=13,
        subject_command_id=subject_command_id,
        subject_run_id=subject_run_id,
    )
    completion = authority.register_completion(completion_request)
    replayed_completion = _authority().register_completion(completion_request)
    assert completion.gate_id == gate3_id
    assert completion.task_terminal_outcome == "completed"
    assert replayed_completion.hqa_completion_receipt_digest == (
        completion.hqa_completion_receipt_digest
    )
    recovered = _authority().get_operator_record(gate3_id)
    assert recovered["status"] == "completed"
    assert recovered["completion"]["hqa_completion_receipt_ref"] == (
        completion.hqa_completion_receipt_ref
    )

    observed = authority.list_observed(workspace)
    assert [row["status"] for row in observed] == [
        "confirmed",
        "reviewed",
        "completed",
    ]
    assert observed[2]["reviewed_commit"] == "4" * 40
    assert observed[2]["workflow_audit_status"] == "consistent"
    assert observed[2]["human_git_commit_required"] is False

    with Database(_test_url(), connect_timeout=1).connect() as conn:
        stored = conn.execute(
            """
            SELECT receipt::text
            FROM quant_system.agent_v02_paper_gate_actions
            WHERE workspace_id = %s
            ORDER BY created_at
            """,
            (workspace,),
        ).fetchall()
    storage_text = "\n".join(str(row[0]) for row in stored)
    assert "I reviewed the exact source bytes." not in storage_text
    assert "Reviewed exact candidate and manifest." not in storage_text
    assert "class ReversalFactor" not in storage_text


def test_action_digest_conflict_and_expired_lease_recover_as_unknown(
    tmp_path: Path,
) -> None:
    authority = _authority()
    workspace = "paper-unknown-" + os.urandom(5).hex()
    platform_session_id, _ = _managed_session(workspace)
    run_id = "run-paper-unknown"
    command_id = _succeeded_command(platform_session_id, run_id)
    source_file = tmp_path / "factor.py"
    source_file.write_text("VALUE = 1\n", encoding="utf-8")
    authority.register_challenge(
        RegisterPaperGateChallenge(
            gate_id="paper-unknown-g1-" + os.urandom(4).hex(),
            gate_kind="gate1",
            workspace_id=workspace,
            task_ref="task:paper-unknown",
            expected_task_version=1,
            attempt_ref="attempt:paper-unknown-1",
            hqa_gate_ref="gate:paper-unknown",
            platform_session_id=platform_session_id,
            hermes_session_id=_hermes_session_id(platform_session_id),
            command_id=command_id,
            hermes_run_id=run_id,
            parent_gate_id=None,
            source_file_ref=str(source_file),
            universe="US",
            reviewed_source_sha256=SOURCE,
        )
    )
    action = ConfirmFormulaSource(
        client_action_id="paper-unknown-action",
        workspace=WorkspaceRef(workspace),
        task_ref="task:paper-unknown",
        reviewed_source_sha256=SOURCE,
        confirmation_note="Reviewed.",
    )

    class _CrashPort:
        def execute(self, operation, request):
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        authority.execute_action(
            action,
            action_digest=canonical_action_digest(action),
            port=_CrashPort(),
        )
    with Database(_test_url(), connect_timeout=1).connect() as conn:
        lease = conn.execute(
            """
            SELECT EXTRACT(EPOCH FROM (lease_until - clock_timestamp()))
            FROM quant_system.agent_v02_paper_gate_actions
            WHERE workspace_id = %s
              AND client_action_id = %s
            """,
            (workspace, action.client_action_id),
        ).fetchone()
        assert lease is not None and float(lease[0]) > 300
        conn.execute(
            """
            UPDATE quant_system.agent_v02_paper_gate_actions
            SET lease_until = clock_timestamp() - interval '1 second'
            WHERE workspace_id = %s
              AND client_action_id = %s
            """,
            (workspace, action.client_action_id),
        )
    recovered = authority.execute_action(
        action,
        action_digest=canonical_action_digest(action),
        port=_FakePort([]),
    )
    assert recovered.status == "outcome_unknown"
    assert recovered.reason_code == "paper_gate_interrupted_outcome_unknown"
    replacement = authority.register_challenge(
        RegisterPaperGateChallenge(
            gate_id="paper-unknown-g1-replacement-" + os.urandom(3).hex(),
            gate_kind="gate1",
            workspace_id=workspace,
            task_ref="task:paper-unknown",
            expected_task_version=1,
            attempt_ref="attempt:paper-unknown-1",
            hqa_gate_ref="gate:paper-unknown",
            platform_session_id=platform_session_id,
            hermes_session_id=_hermes_session_id(platform_session_id),
            command_id=command_id,
            hermes_run_id=run_id,
            parent_gate_id=None,
            source_file_ref=str(source_file),
            universe="US",
            reviewed_source_sha256=SOURCE,
        )
    )
    assert replacement.status == "pending"

    conflicting_action = ConfirmFormulaSource(
        client_action_id=action.client_action_id,
        workspace=action.workspace,
        task_ref=action.task_ref,
        reviewed_source_sha256=action.reviewed_source_sha256,
        confirmation_note="Different reviewed note.",
    )
    with pytest.raises(PaperGateAuthorityConflict):
        authority.execute_action(
            conflicting_action,
            action_digest=canonical_action_digest(conflicting_action),
            port=_FakePort([]),
        )


def test_hqa_receipt_cannot_substitute_hermes_session_id() -> None:
    authority = _authority()
    workspace = "paper-session-receipt-" + os.urandom(5).hex()
    platform_session_id, hermes_session_id = _managed_session(workspace)
    run_id = "run-paper-session-receipt"
    command_id = _succeeded_command(platform_session_id, run_id)
    authority.register_challenge(
        RegisterPaperGateChallenge(
            gate_id="paper-session-receipt-g1-" + os.urandom(4).hex(),
            gate_kind="gate1",
            workspace_id=workspace,
            task_ref="task:paper-session-receipt",
            expected_task_version=1,
            platform_session_id=platform_session_id,
            hermes_session_id=hermes_session_id,
            command_id=command_id,
            hermes_run_id=run_id,
            attempt_ref="attempt:paper-session-receipt-1",
            hqa_gate_ref="gate:paper-session-receipt",
            source_file_ref="/tmp/paper-session-receipt.py",
            universe="US",
            reviewed_source_sha256=SOURCE,
        )
    )
    action = ConfirmFormulaSource(
        client_action_id="paper-session-receipt-action",
        workspace=WorkspaceRef(workspace),
        task_ref="task:paper-session-receipt",
        reviewed_source_sha256=SOURCE,
        confirmation_note="Reviewed.",
    )

    class _SubstitutingPort:
        def execute(self, operation, request):
            document = _FakePort([]).execute(operation, dict(request))
            document["managed_session_ref"] = hermes_session_id
            evidence = {
                key: value
                for key, value in document.items()
                if key not in {"ok", "hqa_receipt_ref", "hqa_receipt_digest"}
            }
            document["hqa_receipt_digest"] = hashlib.sha256(
                json.dumps(
                    evidence,
                    ensure_ascii=False,
                    allow_nan=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            return document

    receipt = authority.execute_action(
        action,
        action_digest=canonical_action_digest(action),
        port=_SubstitutingPort(),
    )
    assert receipt.status == "outcome_unknown"
    assert receipt.reason_code == "paper_gate_invalid_hqa_receipt"
    assert receipt.managed_session_ref == f"session:{platform_session_id}"


def test_post_hqa_success_finalize_failure_is_durable_unknown_on_restart() -> None:
    workspace = "paper-finalize-unknown-" + os.urandom(5).hex()
    platform_session_id, _ = _managed_session(workspace)
    run_id = "run-paper-finalize-unknown"
    command_id = _succeeded_command(platform_session_id, run_id)
    authority = _authority()
    authority.register_challenge(
        RegisterPaperGateChallenge(
            gate_id="paper-finalize-unknown-g1-" + os.urandom(4).hex(),
            gate_kind="gate1",
            workspace_id=workspace,
            task_ref="task:paper-finalize-unknown",
            expected_task_version=1,
            platform_session_id=platform_session_id,
            hermes_session_id=_hermes_session_id(platform_session_id),
            command_id=command_id,
            hermes_run_id=run_id,
            attempt_ref="attempt:paper-2",
            hqa_gate_ref="gate:paper-finalize-unknown",
            source_file_ref="/tmp/paper-finalize-unknown.py",
            universe="US",
            reviewed_source_sha256=SOURCE,
        )
    )
    action = ConfirmFormulaSource(
        client_action_id="paper-finalize-unknown-action",
        workspace=WorkspaceRef(workspace),
        task_ref="task:paper-finalize-unknown",
        reviewed_source_sha256=SOURCE,
        confirmation_note="Reviewed.",
    )
    port = _FakePort([])
    admin = Database(_admin_test_url(), connect_timeout=1)
    with admin.connect() as conn:
        conn.execute(
            """
            CREATE OR REPLACE FUNCTION
                quant_system.test_reject_paper_gate_success()
            RETURNS trigger
            LANGUAGE plpgsql
            VOLATILE
            SECURITY INVOKER
            AS $$
            BEGIN
                IF NEW.status IN ('confirmed', 'reviewed', 'prepared') THEN
                    RAISE EXCEPTION 'injected post-HQA finalization failure';
                END IF;
                RETURN NEW;
            END;
            $$
            """
        )
        conn.execute(
            """
            DROP TRIGGER IF EXISTS test_reject_paper_gate_success
            ON quant_system.agent_v02_paper_gate_challenges
            """
        )
        conn.execute(
            """
            CREATE TRIGGER test_reject_paper_gate_success
            BEFORE UPDATE
            ON quant_system.agent_v02_paper_gate_challenges
            FOR EACH ROW
            EXECUTE FUNCTION
                quant_system.test_reject_paper_gate_success()
            """
        )
    try:
        first = authority.execute_action(
            action,
            action_digest=canonical_action_digest(action),
            port=port,
        )
    finally:
        with admin.connect() as conn:
            conn.execute(
                """
                DROP TRIGGER IF EXISTS test_reject_paper_gate_success
                ON quant_system.agent_v02_paper_gate_challenges
                """
            )
            conn.execute(
                """
                DROP FUNCTION IF EXISTS
                    quant_system.test_reject_paper_gate_success()
                """
            )
    assert first.status == "outcome_unknown"
    assert first.reason_code == "paper_gate_finalization_outcome_unknown"
    assert len(port.calls) == 1

    replay = _authority().execute_action(
        action,
        action_digest=canonical_action_digest(action),
        port=port,
    )
    assert replay.status == "outcome_unknown"
    assert replay.reason_code == "paper_gate_finalization_outcome_unknown"
    assert replay.idempotent_replay is True
    assert len(port.calls) == 1


def test_definitive_port_outcome_unknown_is_durable() -> None:
    authority = _authority()
    workspace = "paper-port-unknown-" + os.urandom(5).hex()
    platform_session_id, _ = _managed_session(workspace)
    run_id = "run-paper-port"
    command_id = _succeeded_command(platform_session_id, run_id)
    authority.register_challenge(
        RegisterPaperGateChallenge(
            gate_id="paper-port-g1-" + os.urandom(4).hex(),
            gate_kind="gate1",
            workspace_id=workspace,
            task_ref="task:paper-port",
            expected_task_version=1,
            attempt_ref="attempt:paper-port-1",
            hqa_gate_ref="gate:paper-port",
            platform_session_id=platform_session_id,
            hermes_session_id=_hermes_session_id(platform_session_id),
            command_id=command_id,
            hermes_run_id=run_id,
            parent_gate_id=None,
            source_file_ref="/tmp/no-source-bytes-in-db.py",
            universe="US",
            reviewed_source_sha256=SOURCE,
        )
    )
    action = ConfirmFormulaSource(
        client_action_id="paper-port-action",
        workspace=WorkspaceRef(workspace),
        task_ref="task:paper-port",
        reviewed_source_sha256=SOURCE,
        confirmation_note="Reviewed.",
    )

    class _UnknownPort:
        def execute(self, operation, request):
            raise PaperGatePortError(
                "paper_gate_outcome_unknown",
                "unknown",
                retryable=False,
            )

    first = authority.execute_action(
        action,
        action_digest=canonical_action_digest(action),
        port=_UnknownPort(),
    )
    assert first.status == "outcome_unknown"
    replay = _authority().execute_action(
        action,
        action_digest=canonical_action_digest(action),
        port=_FakePort([]),
    )
    assert replay.idempotent_replay is True


def test_malformed_post_mutation_receipt_is_unknown_and_never_retried() -> None:
    authority = _authority()
    workspace = "paper-malformed-" + os.urandom(5).hex()
    platform_session_id, _ = _managed_session(workspace)
    run_id = "run-paper-malformed"
    command_id = _succeeded_command(platform_session_id, run_id)
    authority.register_challenge(
        RegisterPaperGateChallenge(
            gate_id="paper-malformed-g1-" + os.urandom(4).hex(),
            gate_kind="gate1",
            workspace_id=workspace,
            task_ref="task:paper-malformed",
            expected_task_version=1,
            attempt_ref="attempt:paper-2",
            hqa_gate_ref="gate:paper-malformed",
            platform_session_id=platform_session_id,
            hermes_session_id=_hermes_session_id(platform_session_id),
            command_id=command_id,
            hermes_run_id=run_id,
            parent_gate_id=None,
            source_file_ref="/tmp/paper-malformed.py",
            universe="US",
            reviewed_source_sha256=SOURCE,
        )
    )
    action = ConfirmFormulaSource(
        client_action_id="paper-malformed-action",
        workspace=WorkspaceRef(workspace),
        task_ref="task:paper-malformed",
        reviewed_source_sha256=SOURCE,
        confirmation_note="Reviewed.",
    )

    class _BadReceiptPort:
        def __init__(self) -> None:
            self.calls = 0

        def execute(self, operation, request):
            self.calls += 1
            document = _FakePort([]).execute(operation, dict(request))
            document["hqa_receipt_digest"] = "f" * 64
            return document

    port = _BadReceiptPort()
    first = authority.execute_action(
        action,
        action_digest=canonical_action_digest(action),
        port=port,
    )
    assert first.status == "outcome_unknown"
    replay = _authority().execute_action(
        action,
        action_digest=canonical_action_digest(action),
        port=port,
    )
    assert replay.status == "outcome_unknown"
    assert replay.idempotent_replay is True
    assert port.calls == 1

    replacement_gate = authority.register_challenge(
        RegisterPaperGateChallenge(
            gate_id="paper-malformed-g1-recovery-" + os.urandom(4).hex(),
            gate_kind="gate1",
            workspace_id=workspace,
            task_ref="task:paper-malformed",
            expected_task_version=1,
            attempt_ref="attempt:paper-2",
            hqa_gate_ref="gate:paper-malformed",
            platform_session_id=platform_session_id,
            hermes_session_id=_hermes_session_id(platform_session_id),
            command_id=command_id,
            hermes_run_id=run_id,
            parent_gate_id=None,
            source_file_ref="/tmp/paper-malformed.py",
            universe="US",
            reviewed_source_sha256=SOURCE,
        )
    )
    recovery_action = ConfirmFormulaSource(
        client_action_id="paper-malformed-recovery-action",
        workspace=WorkspaceRef(workspace),
        task_ref="task:paper-malformed",
        reviewed_source_sha256=SOURCE,
        confirmation_note="Reviewed.",
    )
    recovery_port = _FakePort([])
    recovered = _authority().execute_action(
        recovery_action,
        action_digest=canonical_action_digest(recovery_action),
        port=recovery_port,
    )
    assert recovered.status == "confirmed"
    assert recovered.gate_id == replacement_gate.gate_id
    assert recovery_port.calls[0][1]["gate_ref"] == "gate:paper-malformed"
