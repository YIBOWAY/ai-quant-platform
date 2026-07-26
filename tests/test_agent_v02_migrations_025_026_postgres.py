from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from threading import Event
from uuid import UUID, uuid4

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict

from quant_system.config.settings import (
    CandidateAdmissionSettings,
    DatabaseSettings,
    Settings,
)
from quant_system.hermes.command_ledger import (
    HermesCommandLedger,
    HermesCommandLedgerUnavailable,
)
from quant_system.hermes.dark_identity_profile import (
    PROVIDER_POLICY_DIGEST,
    STORE_TTL_DAYS,
)
from quant_system.hermes.release_authority import ReleaseAuthority
from quant_system.hermes.session_registry import (
    RegisterWorkspaceSession,
    register_workspace_session,
)
from quant_system.storage import database as db
from tests import test_release_authority_hardening as release_test_support
from tests.postgres_reset import isolated_test_database_url

pytestmark = pytest.mark.pg

MIGRATION_025 = "025_agent_v02_release_session_binding.sql"
MIGRATION_026 = "026_agent_v02_paper_research_claim_lineage.sql"
THROUGH_018 = (
    "001_runs_index.sql",
    "002_ai_news_cache.sql",
    "003_app_users_brief_ai_reports.sql",
    "004_paper_account_tables.sql",
    "005_hermes_command_ledger.sql",
    "006_hermes_workflow_binding.sql",
    "007_hermes_session_registry.sql",
    "008_l2a_conversation_turn_claim.sql",
    "009_ai_news_provider_runs.sql",
    "010_agent_v0_2_runtime_security.sql",
    "011_hermes_session_action_idempotency.sql",
    "012_agent_v0_2_release_authority.sql",
    "013_managed_hermes_session_provisioning.sql",
    "014_agent_v02_connector_liveness.sql",
    "015_managed_session_provision_authority.sql",
    "016_agent_v02_candidate_admission.sql",
    "017_agent_v02_vertical_a_authority.sql",
    "018_agent_v02_paper_gate_bridge.sql",
)
THROUGH_020 = THROUGH_018 + (
    "019_agent_v02_candidate_evidence_v3.sql",
    "020_agent_v02_release_authority_hardening.sql",
)
THROUGH_021 = THROUGH_020 + ("021_agent_v02_paper_run_attestation.sql",)
THROUGH_026 = THROUGH_021 + (
    "022_agent_v02_resolved_fork_lineage.sql",
    "023_agent_v02_resolved_run_tip.sql",
    "024_agent_v02_run_control_outcome.sql",
    MIGRATION_025,
    MIGRATION_026,
)
ROOT_USER_ID = UUID("00000000-0000-0000-0000-000000000001")
CLAIM_DIGEST = "c" * 64
START_DIGEST = "d" * 64
CONTINUE_DIGEST = "e" * 64


def _base_url() -> str:
    value = os.environ.get("QS_TEST_DATABASE_ADMIN_URL") or os.environ.get("QS_TEST_DATABASE_URL")
    if not value:
        pytest.skip("set QS_TEST_DATABASE_URL to run PostgreSQL integration tests")
    database_name = conninfo_to_dict(value).get("dbname", "")
    if not (database_name.endswith("_tmp") or "test" in database_name):
        pytest.fail("PostgreSQL migration tests require a throwaway base database")
    return value


@contextmanager
def _database(
    *,
    purpose: str,
    migrations: tuple[str, ...],
) -> Iterator[db.Database]:
    with isolated_test_database_url(_base_url(), purpose=purpose) as isolated_url:
        database = db.Database(isolated_url, connect_timeout=2)
        db.run_migrations(database, only=migrations)
        yield database


@pytest.mark.parametrize(
    ("predecessors", "migration", "message", "purpose"),
    [
        (
            THROUGH_018,
            MIGRATION_025,
            "requires migration 020",
            "025pre18",
        ),
        (
            THROUGH_018,
            MIGRATION_026,
            "requires migration 021",
            "026pre18",
        ),
        (
            THROUGH_020,
            MIGRATION_026,
            "requires migration 021",
            "026pre20",
        ),
    ],
)
def test_migrations_reject_incomplete_predecessor_ladders(
    predecessors: tuple[str, ...],
    migration: str,
    message: str,
    purpose: str,
) -> None:
    with (
        _database(purpose=purpose, migrations=predecessors) as database,
        pytest.raises(psycopg.errors.RaiseException, match=message),
    ):
        db.run_migrations(database, only=(migration,))


def test_025_applies_after_020_and_replays_exactly() -> None:
    with _database(purpose="025replay", migrations=THROUGH_020) as database:
        db.run_migrations(database, only=(MIGRATION_025,))
        db.run_migrations(database, only=(MIGRATION_025,))
        with database.connect() as conn:
            rows = conn.execute(
                """
                SELECT
                    procedure.proname,
                    position(
                        'current_agent_v02_paper_authority_epoch'
                        IN procedure.prosrc
                    ) > 0
                FROM pg_proc AS procedure
                JOIN pg_namespace AS namespace
                  ON namespace.oid = procedure.pronamespace
                WHERE namespace.nspname = 'quant_system'
                  AND procedure.proname IN (
                      'bind_agent_v02_candidate_session',
                      'bind_agent_v02_candidate_command'
                  )
                ORDER BY procedure.proname
                """
            ).fetchall()
        assert rows == [
            ("bind_agent_v02_candidate_command", True),
            ("bind_agent_v02_candidate_session", True),
        ]


def test_026_applies_after_021_and_replays_exactly() -> None:
    with _database(purpose="026replay", migrations=THROUGH_021) as database:
        db.run_migrations(database, only=(MIGRATION_026,))
        db.run_migrations(database, only=(MIGRATION_026,))
        with database.connect() as conn:
            columns = conn.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'quant_system'
                  AND table_name = 'agent_v02_paper_gate_challenges'
                  AND column_name IN (
                      'research_claim_digest',
                      'research_start_payload_digest',
                      'research_continue_payload_digest'
                  )
                ORDER BY column_name
                """
            ).fetchall()
            constraint = conn.execute(
                """
                SELECT convalidated
                FROM pg_constraint
                WHERE conrelid =
                    'quant_system.agent_v02_paper_gate_challenges'::regclass
                  AND conname =
                    'ck_agent_v02_paper_gate_research_lineage'
                """
            ).fetchone()
            trigger = conn.execute(
                """
                SELECT tgenabled, tgtype
                FROM pg_trigger
                WHERE tgrelid =
                    'quant_system.agent_v02_paper_gate_challenges'::regclass
                  AND tgname = 'trg_agent_v02_paper_research_lineage'
                  AND NOT tgisinternal
                """
            ).fetchone()
        assert columns == [
            ("research_claim_digest",),
            ("research_continue_payload_digest",),
            ("research_start_payload_digest",),
        ]
        assert constraint == (True,)
        assert trigger == ("A", 23)


def _seed_managed_session_and_commands(
    database: db.Database,
    *,
    workspace_id: str,
) -> tuple[str, str, dict[str, UUID]]:
    token = uuid4().hex
    platform_session_id = f"paper-lineage-{token}"
    creation_digest = hashlib.sha256(platform_session_id.encode()).hexdigest()
    hermes_session_id = f"web_{creation_digest[:40]}"
    command_ids = {
        "gate1": uuid4(),
        "gate2": uuid4(),
        "gate3": uuid4(),
        "subject": uuid4(),
    }
    with database.connect() as conn, conn.transaction():
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
                %s, %s, %s, %s, 'web_managed_session', %s,
                'web_control_plane', 7, %s, %s, 'ready', %s,
                clock_timestamp()
            )
            """,
            (
                platform_session_id,
                hermes_session_id,
                workspace_id,
                ROOT_USER_ID,
                "a" * 64,
                f"create-{token}",
                creation_digest,
                "b" * 64,
            ),
        )
        for label, command_id in command_ids.items():
            request_digest = hashlib.sha256(str(command_id).encode()).hexdigest()
            run_id = f"paper-{label}-{token}"
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
                    f"paper-{label}-{token}",
                    request_digest,
                    f"platform-payload://sha256/{request_digest}",
                    "a" * 64,
                    hermes_session_id,
                    hermes_session_id,
                    run_id,
                ),
            )
    return platform_session_id, hermes_session_id, command_ids


def _insert_claimed_gate1(
    conn: psycopg.Connection,
    *,
    gate_id: str,
    workspace_id: str,
    platform_session_id: str,
    hermes_session_id: str,
    command_id: UUID,
    run_id: str,
) -> None:
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
            research_claim_digest,
            research_start_payload_digest,
            research_continue_payload_digest,
            source_file_ref,
            universe,
            reviewed_source_sha256
        )
        VALUES (
            %s, %s, %s, 'gate1', 'task:paper-lineage', 1,
            'attempt:paper-lineage-1', 'gate:paper-lineage-g1',
            %s, %s, %s, %s, %s, %s, NULL, %s, %s, %s
        )
        """,
        (
            gate_id,
            ROOT_USER_ID,
            workspace_id,
            platform_session_id,
            hermes_session_id,
            command_id,
            run_id,
            CLAIM_DIGEST,
            START_DIGEST,
            "/tmp/paper-lineage.py",
            f"research-claim:sha256:{CLAIM_DIGEST}",
            "1" * 64,
        ),
    )


def _confirm_gate(
    conn: psycopg.Connection,
    *,
    gate_id: str,
    status: str,
    action_kind: str,
    confirmation_id: str | None = None,
    promotion_id: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE quant_system.agent_v02_paper_gate_challenges
        SET status = %s,
            gate1_confirmation_id =
                COALESCE(%s::text, gate1_confirmation_id),
            promotion_id = COALESCE(%s::text, promotion_id),
            worktree_ref = CASE
                WHEN %s::text IS NULL THEN worktree_ref
                ELSE '/tmp/paper-lineage-review'
            END,
            patch_ref = CASE
                WHEN %s::text IS NULL THEN patch_ref
                ELSE '/tmp/paper-lineage-review.patch'
            END,
            manifest_ref = CASE
                WHEN %s::text IS NULL THEN manifest_ref
                ELSE '/tmp/paper-lineage-review.json'
            END,
            hqa_receipt_ref =
                'hqa-paper-gate:pgate-' || repeat('a', 32),
            hqa_receipt_digest = repeat('b', 64),
            decided_action_kind = %s,
            decided_client_action_id = %s,
            decided_action_digest = repeat('f', 64),
            decided_at = clock_timestamp()
        WHERE gate_id = %s
        """,
        (
            status,
            confirmation_id,
            promotion_id,
            promotion_id,
            promotion_id,
            promotion_id,
            action_kind,
            f"decide-{gate_id}",
            gate_id,
        ),
    )


def _seed_claimed_gate_chain(
    database: db.Database,
    *,
    workspace_id: str,
) -> tuple[str, dict[str, object]]:
    (
        platform_session_id,
        hermes_session_id,
        command_ids,
    ) = _seed_managed_session_and_commands(
        database,
        workspace_id=workspace_id,
    )
    token = uuid4().hex
    gate1_id = f"paper-g1-{token}"
    gate2_id = f"paper-g2-{token}"
    gate3_id = f"paper-g3-{token}"
    confirmation_id = "gate1-" + "5" * 32
    candidate_digest = "2" * 64
    candidate_id = "factor-paper-lineage"
    subject_attestation_digest = "5" * 64
    subject_run_id = f"paper-subject-{platform_session_id.rsplit('-', 1)[-1]}"
    gate3_run_id = f"paper-gate3-{platform_session_id.rsplit('-', 1)[-1]}"
    with database.connect() as conn, conn.transaction():
        _insert_claimed_gate1(
            conn,
            gate_id=gate1_id,
            workspace_id=workspace_id,
            platform_session_id=platform_session_id,
            hermes_session_id=hermes_session_id,
            command_id=command_ids["gate1"],
            run_id=f"paper-gate1-{platform_session_id.rsplit('-', 1)[-1]}",
        )
        _confirm_gate(
            conn,
            gate_id=gate1_id,
            status="confirmed",
            action_kind="gate1_formula_source_confirm",
            confirmation_id=confirmation_id,
        )
        conn.execute(
            """
            INSERT INTO quant_system.agent_v02_paper_gate_challenges (
                gate_id, owner_user_id, workspace_id, gate_kind, task_ref,
                expected_task_version, attempt_ref, hqa_gate_ref,
                platform_session_id, hermes_session_id, command_id,
                hermes_run_id, parent_gate_id, reviewed_source_sha256,
                gate1_confirmation_id, candidate_id, expected_digest,
                expected_status, research_claim_digest,
                research_start_payload_digest,
                research_continue_payload_digest
            )
            VALUES (
                %s, %s, %s, 'gate2', 'task:paper-lineage', 2,
                'attempt:paper-lineage-1', 'gate:paper-lineage-g1',
                %s, %s, %s, %s, %s, %s, %s, %s, %s, 'pending',
                %s, %s, NULL
            )
            """,
            (
                gate2_id,
                ROOT_USER_ID,
                workspace_id,
                platform_session_id,
                hermes_session_id,
                command_ids["gate2"],
                f"paper-gate2-{platform_session_id.rsplit('-', 1)[-1]}",
                gate1_id,
                "1" * 64,
                confirmation_id,
                candidate_id,
                candidate_digest,
                CLAIM_DIGEST,
                START_DIGEST,
            ),
        )
        _confirm_gate(
            conn,
            gate_id=gate2_id,
            status="reviewed",
            action_kind="gate2_candidate_review",
        )
        conn.execute(
            """
            INSERT INTO quant_system.agent_v02_paper_gate_challenges (
                gate_id, owner_user_id, workspace_id, gate_kind, task_ref,
                expected_task_version, attempt_ref, hqa_gate_ref,
                platform_session_id, hermes_session_id, command_id,
                hermes_run_id, hqa_run_ref, provider_evidence_ref,
                subject_command_id, subject_hermes_run_id,
                subject_run_attestation_ref,
                subject_run_attestation_digest,
                final_backtest_provider, final_backtest_receipt_digest,
                final_backtest_config_ref, final_backtest_config_digest,
                final_backtest_summary_ref, final_backtest_summary_digest,
                final_backtest_report_ref, final_backtest_report_digest,
                parent_gate_id, reviewed_source_sha256,
                gate1_confirmation_id, candidate_id, expected_digest,
                final_backtest_receipt_id, base_commit,
                research_claim_digest, research_start_payload_digest,
                research_continue_payload_digest
            )
            VALUES (
                %s, %s, %s, 'gate3', 'task:paper-lineage', 3,
                'attempt:paper-lineage-2', 'gate:paper-lineage-g3',
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                'futu', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                gate3_id,
                ROOT_USER_ID,
                workspace_id,
                platform_session_id,
                hermes_session_id,
                command_ids["gate3"],
                gate3_run_id,
                f"run:{subject_run_id}",
                f"provider-evidence:paper-run-{subject_attestation_digest}",
                command_ids["subject"],
                subject_run_id,
                f"paper-run-attestation:{subject_attestation_digest}",
                subject_attestation_digest,
                "8" * 64,
                "/tmp/paper-lineage-config.json",
                "9" * 64,
                "/tmp/paper-lineage-summary.json",
                "a" * 64,
                "/tmp/paper-lineage-report.json",
                "b" * 64,
                gate2_id,
                "1" * 64,
                confirmation_id,
                candidate_id,
                candidate_digest,
                "backtest-" + "9" * 32,
                "3" * 40,
                CLAIM_DIGEST,
                START_DIGEST,
                CONTINUE_DIGEST,
            ),
        )
        promotion_id = "promo-" + "8" * 32
        _confirm_gate(
            conn,
            gate_id=gate3_id,
            status="prepared",
            action_kind="gate3_promotion_review_prepare",
            promotion_id=promotion_id,
        )
        conn.execute(
            """
            INSERT INTO quant_system.agent_v02_paper_gate_actions (
                owner_user_id, workspace_id, action_kind,
                client_action_id, action_digest, gate_id, action_state,
                hqa_operation_id, hqa_receipt_ref, hqa_receipt_digest,
                receipt
            )
            VALUES (
                %s, %s, 'gate3_promotion_review_prepare',
                %s, %s, %s, 'succeeded', %s, %s, %s, '{}'::jsonb
            )
            """,
            (
                ROOT_USER_ID,
                workspace_id,
                f"prepare-{token}",
                "f" * 64,
                gate3_id,
                f"pgate-{token}",
                f"hqa-paper-gate:pgate-{token}",
                "b" * 64,
            ),
        )
    return gate3_id, {
        "base_commit": "3" * 40,
        "candidate_digest": candidate_digest,
        "candidate_id": candidate_id,
        "domain_gate_ref": "gate:paper-lineage-g3",
        "final_backtest_config_digest": "9" * 64,
        "final_backtest_config_ref": "/tmp/paper-lineage-config.json",
        "final_backtest_provider": "futu",
        "final_backtest_receipt_digest": "8" * 64,
        "final_backtest_receipt_id": "backtest-" + "9" * 32,
        "final_backtest_report_digest": "b" * 64,
        "final_backtest_report_ref": "/tmp/paper-lineage-report.json",
        "final_backtest_summary_digest": "a" * 64,
        "final_backtest_summary_ref": "/tmp/paper-lineage-summary.json",
        "hqa_run_ref": f"run:{subject_run_id}",
        "promotion_id": "promo-" + "8" * 32,
        "provider_evidence_ref": (f"provider-evidence:paper-run-{subject_attestation_digest}"),
        "subject_command_id": str(command_ids["subject"]),
        "subject_hermes_run_id": subject_run_id,
        "subject_run_attestation_digest": subject_attestation_digest,
        "subject_run_attestation_ref": (f"paper-run-attestation:{subject_attestation_digest}"),
        "workspace_id": workspace_id,
    }


def _completion_evidence(
    chain: dict[str, object],
    *,
    claim_digest: str = CLAIM_DIGEST,
) -> dict[str, object]:
    identity_digest = hashlib.sha256(str(chain["workspace_id"]).encode()).hexdigest()
    return {
        "schema_version": "agent-v0.2-paper-completion/v2",
        "task_ref": "task:paper-lineage",
        "task_version": 7,
        "task_status": "completed",
        "task_terminal_outcome": "completed",
        "plan_version": 1,
        "plan_digest": "6" * 64,
        "plan_confirmation_note_digest": "7" * 64,
        "attempt_ref": "attempt:paper-lineage-2",
        "attempt_status": "completed",
        "attempt_terminal_outcome": "completed",
        "domain_gate_ref": chain["domain_gate_ref"],
        "domain_gate_outcome": "passed",
        "hqa_run_ref": chain["hqa_run_ref"],
        "provider_evidence_ref": chain["provider_evidence_ref"],
        "subject_command_id": chain["subject_command_id"],
        "subject_hermes_run_id": chain["subject_hermes_run_id"],
        "subject_run_attestation_ref": chain["subject_run_attestation_ref"],
        "subject_run_attestation_digest": chain["subject_run_attestation_digest"],
        "final_backtest_provider": chain["final_backtest_provider"],
        "final_backtest_receipt_digest": chain["final_backtest_receipt_digest"],
        "final_backtest_config_ref": chain["final_backtest_config_ref"],
        "final_backtest_config_digest": chain["final_backtest_config_digest"],
        "final_backtest_summary_ref": chain["final_backtest_summary_ref"],
        "final_backtest_summary_digest": chain["final_backtest_summary_digest"],
        "final_backtest_report_ref": chain["final_backtest_report_ref"],
        "final_backtest_report_digest": chain["final_backtest_report_digest"],
        "promotion_id": chain["promotion_id"],
        "reviewed_commit": "4" * 40,
        "candidate_id": chain["candidate_id"],
        "candidate_digest": chain["candidate_digest"],
        "final_backtest_receipt_id": chain["final_backtest_receipt_id"],
        "base_commit": chain["base_commit"],
        "attempt_completion_operation_id": "complete-paper-attempt",
        "attempt_completion_event_id": "event:" + "a" * 64,
        "task_completion_operation_id": "complete-paper-task",
        "task_completion_event_id": "event:" + "b" * 64,
        "workflow_audit_status": "consistent",
        "workflow_audit_ref": f"workflow-audit:{identity_digest}",
        "workflow_audit_digest": identity_digest,
        "research_claim_digest": claim_digest,
        "research_start_payload_digest": START_DIGEST,
        "research_continue_payload_digest": CONTINUE_DIGEST,
    }


def _insert_completion(
    conn: psycopg.Connection,
    *,
    gate_id: str,
    chain: dict[str, object],
    evidence: dict[str, object],
) -> None:
    receipt_digest = hashlib.sha256(
        json.dumps(
            evidence,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
    ).hexdigest()
    conn.execute(
        """
        INSERT INTO quant_system.agent_v02_paper_gate_completions (
            gate_id, owner_user_id, workspace_id, task_ref, task_version,
            task_status, task_terminal_outcome, plan_version, plan_digest,
            plan_confirmation_note_digest, attempt_ref, attempt_status,
            attempt_terminal_outcome, domain_gate_ref, domain_gate_outcome,
            hqa_run_ref, provider_evidence_ref, subject_command_id,
            subject_hermes_run_id, subject_run_attestation_ref,
            subject_run_attestation_digest, final_backtest_provider,
            final_backtest_receipt_digest, final_backtest_config_ref,
            final_backtest_config_digest, final_backtest_summary_ref,
            final_backtest_summary_digest, final_backtest_report_ref,
            final_backtest_report_digest, promotion_id, reviewed_commit,
            candidate_id, candidate_digest, final_backtest_receipt_id,
            base_commit, attempt_completion_operation_id,
            attempt_completion_event_id, task_completion_operation_id,
            task_completion_event_id, workflow_audit_status,
            workflow_audit_ref, workflow_audit_digest,
            hqa_completion_receipt_ref, hqa_completion_receipt_digest,
            completion_evidence
        )
        VALUES (
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
            %s, %s, %s, %s, %s::jsonb
        )
        """,
        (
            gate_id,
            ROOT_USER_ID,
            chain["workspace_id"],
            evidence["task_ref"],
            evidence["task_version"],
            evidence["task_status"],
            evidence["task_terminal_outcome"],
            evidence["plan_version"],
            evidence["plan_digest"],
            evidence["plan_confirmation_note_digest"],
            evidence["attempt_ref"],
            evidence["attempt_status"],
            evidence["attempt_terminal_outcome"],
            evidence["domain_gate_ref"],
            evidence["domain_gate_outcome"],
            evidence["hqa_run_ref"],
            evidence["provider_evidence_ref"],
            evidence["subject_command_id"],
            evidence["subject_hermes_run_id"],
            evidence["subject_run_attestation_ref"],
            evidence["subject_run_attestation_digest"],
            evidence["final_backtest_provider"],
            evidence["final_backtest_receipt_digest"],
            evidence["final_backtest_config_ref"],
            evidence["final_backtest_config_digest"],
            evidence["final_backtest_summary_ref"],
            evidence["final_backtest_summary_digest"],
            evidence["final_backtest_report_ref"],
            evidence["final_backtest_report_digest"],
            evidence["promotion_id"],
            evidence["reviewed_commit"],
            evidence["candidate_id"],
            evidence["candidate_digest"],
            evidence["final_backtest_receipt_id"],
            evidence["base_commit"],
            evidence["attempt_completion_operation_id"],
            evidence["attempt_completion_event_id"],
            evidence["task_completion_operation_id"],
            evidence["task_completion_event_id"],
            evidence["workflow_audit_status"],
            evidence["workflow_audit_ref"],
            evidence["workflow_audit_digest"],
            f"hqa-paper-completion:{receipt_digest[:32]}",
            receipt_digest,
            json.dumps(evidence, separators=(",", ":"), sort_keys=True),
        ),
    )


def test_026_runtime_cannot_update_sealed_challenge_lineage() -> None:
    with _database(purpose="026immut", migrations=THROUGH_026) as database:
        workspace_id = f"paper-immut-{uuid4().hex}"
        (
            platform_session_id,
            hermes_session_id,
            command_ids,
        ) = _seed_managed_session_and_commands(
            database,
            workspace_id=workspace_id,
        )
        gate_id = f"paper-g1-{uuid4().hex}"
        with database.connect() as conn:
            _insert_claimed_gate1(
                conn,
                gate_id=gate_id,
                workspace_id=workspace_id,
                platform_session_id=platform_session_id,
                hermes_session_id=hermes_session_id,
                command_id=command_ids["gate1"],
                run_id=f"paper-gate1-{platform_session_id.rsplit('-', 1)[-1]}",
            )
            login = f"aqp_lineage_{uuid4().hex[:12]}"
            password = f"lineage-{uuid4().hex}"
            conn.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS "
                    "NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD {}"
                ).format(sql.Identifier(login), sql.Literal(password))
            )
            conn.execute(sql.SQL("GRANT quant_runtime TO {}").format(sql.Identifier(login)))
            runtime_url = psycopg.conninfo.make_conninfo(
                **{
                    **conninfo_to_dict(_base_url()),
                    **conninfo_to_dict(database._url),  # noqa: SLF001
                    "user": login,
                    "password": password,
                }
            )
        try:
            with (
                psycopg.connect(runtime_url, autocommit=True) as runtime_conn,
                pytest.raises(
                    psycopg.errors.RaiseException,
                    match=(
                        "research claim lineage is immutable"
                        "|paper gate challenge transition is invalid"
                    ),
                ),
            ):
                runtime_conn.execute(
                    """
                    UPDATE quant_system.agent_v02_paper_gate_challenges
                    SET research_claim_digest = %s
                    WHERE gate_id = %s
                    """,
                    ("f" * 64, gate_id),
                )
            with database.connect() as conn:
                assert conn.execute(
                    """
                    SELECT research_claim_digest
                    FROM quant_system.agent_v02_paper_gate_challenges
                    WHERE gate_id = %s
                    """,
                    (gate_id,),
                ).fetchone() == (CLAIM_DIGEST,)
        finally:
            with database.connect() as conn:
                conn.execute(sql.SQL("REVOKE quant_runtime FROM {}").format(sql.Identifier(login)))
                conn.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(login)))


def test_026_completion_rejects_substitution_and_accepts_sealed_lineage() -> None:
    with _database(purpose="026complete", migrations=THROUGH_026) as database:
        workspace_id = f"paper-complete-{uuid4().hex}"
        gate3_id, chain = _seed_claimed_gate_chain(
            database,
            workspace_id=workspace_id,
        )
        null_schema = _completion_evidence(chain)
        null_schema["schema_version"] = None
        with (
            database.connect() as conn,
            pytest.raises(
                psycopg.errors.RaiseException,
                match="paper completion schema is unsupported",
            ),
        ):
            _insert_completion(
                conn,
                gate_id=gate3_id,
                chain=chain,
                evidence=null_schema,
            )

        substituted = _completion_evidence(chain, claim_digest="f" * 64)
        with (
            database.connect() as conn,
            pytest.raises(
                psycopg.errors.RaiseException,
                match="does not match sealed Gate 3",
            ),
        ):
            _insert_completion(
                conn,
                gate_id=gate3_id,
                chain=chain,
                evidence=substituted,
            )

        trusted = _completion_evidence(chain)
        with database.connect() as conn:
            _insert_completion(
                conn,
                gate_id=gate3_id,
                chain=chain,
                evidence=trusted,
            )
            assert conn.execute(
                """
                SELECT completion_evidence ->> 'research_claim_digest'
                FROM quant_system.agent_v02_paper_gate_completions
                WHERE gate_id = %s
                """,
                (gate3_id,),
            ).fetchone() == (CLAIM_DIGEST,)


@contextmanager
def _released_database(
    *,
    purpose: str,
) -> Iterator[tuple[Settings, db.Database]]:
    with isolated_test_database_url(_base_url(), purpose=purpose) as isolated_url:
        database = db.Database(isolated_url, connect_timeout=2)
        db.run_migrations(database, only=THROUGH_026)
        settings = Settings(
            database=DatabaseSettings(
                enabled=True,
                url=isolated_url,
                auto_migrate=False,
                connect_timeout_seconds=2,
            ),
            candidate_admission=CandidateAdmissionSettings(
                enabled=True,
                ttl_seconds=120,
            ),
        )
        db.reset_database_cache()
        try:
            yield settings, database
        finally:
            db.reset_database_cache()


def _open_exact_release(
    settings: Settings,
    database: db.Database,
    *,
    workspace_id: str,
) -> str:
    candidate_authority, opened, accept_request = (
        release_test_support._seed_open_candidate_with_evidence(  # noqa: SLF001
            settings,
            database,
            workspace_id=workspace_id,
            generation=uuid4().hex,
        )
    )
    assert candidate_authority.accept(accept_request).status == "accepted"
    release_authority = ReleaseAuthority(
        settings,
        database=database,
        schema_fingerprint_reader=(lambda _database: release_test_support.SCHEMA_DIGEST),
    )
    stamp = release_authority.create_release_stamp(
        release_test_support._release_request(workspace_id),  # noqa: SLF001
        now=datetime.now(UTC) + timedelta(seconds=1),
        stamp_id=f"release-stamp-{uuid4().hex}",
    )
    release_authority.create_public_cutover(
        release_test_support._cutover_request(  # noqa: SLF001
            workspace_id,
            stamp_id=stamp.resource_id,
            release_digest=stamp.resource_digest,
        ),
        now=datetime.now(UTC) + timedelta(seconds=2),
        cutover_id=f"release-cutover-{uuid4().hex}",
    )
    return opened.admission_id


def _register_release_session(
    settings: Settings,
    *,
    workspace_id: str,
    label: str,
) -> tuple[str, str | None]:
    creation_digest = hashlib.sha256(f"{workspace_id}:{label}".encode()).hexdigest()
    session, created = register_workspace_session(
        settings,
        RegisterWorkspaceSession(
            platform_session_id=f"wm_{label}_{uuid4().hex}",
            hermes_session_id=f"web_{creation_digest[:40]}",
            workspace_id=workspace_id,
            kind="web_managed_session",
            provider_policy_digest=PROVIDER_POLICY_DIGEST,
            payload_ttl_days=STORE_TTL_DAYS,
            creation_client_action_id=f"create-{label}-{uuid4().hex}",
            creation_action_digest=creation_digest,
        ),
    )
    assert created is True
    return session.platform_session_id, session.candidate_admission_id


def _insert_paper_epoch_mutation(
    conn: psycopg.Connection,
    *,
    label: str,
) -> None:
    observed_at = datetime.now(UTC)
    conn.execute(
        """
        INSERT INTO quant_system.paper_accounts (
            account_id, owner_user_id, base_currency, initial_cash,
            cash, realized_pnl, kill_switch, version, raw,
            created_at, updated_at
        )
        VALUES (
            %s, %s, 'USD', 1000, 1000, 0, TRUE, 1,
            '{}'::jsonb, %s, %s
        )
        """,
        (
            f"paper-{label}-{uuid4().hex}",
            ROOT_USER_ID,
            observed_at,
            observed_at,
        ),
    )


def test_025_mutation_first_closes_release_for_new_session_and_command() -> None:
    with _released_database(purpose="025mutate") as (
        settings,
        database,
    ):
        workspace_id = f"epoch-mutation-{uuid4().hex}"
        admission_id = _open_exact_release(
            settings,
            database,
            workspace_id=workspace_id,
        )
        old_session_id, old_binding = _register_release_session(
            settings,
            workspace_id=workspace_id,
            label="before-mutation",
        )
        assert old_binding == admission_id
        with database.connect() as conn:
            _insert_paper_epoch_mutation(conn, label="before-new-writes")

        _new_session_id, new_binding = _register_release_session(
            settings,
            workspace_id=workspace_id,
            label="after-mutation",
        )
        assert new_binding is None
        with pytest.raises(HermesCommandLedgerUnavailable):
            HermesCommandLedger(settings).create_command(
                platform_session_id=old_session_id,
                client_request_id=f"turn-after-mutation-{uuid4().hex}",
                kind="conversation_turn",
                canonical_request_digest="9" * 64,
                payload_ref=f"platform-payload://sha256/{'a' * 64}",
                provider_policy_digest=PROVIDER_POLICY_DIGEST,
            )


def test_025_concurrent_epoch_bump_serializes_session_insert() -> None:
    with _released_database(purpose="025sessrace") as (
        settings,
        database,
    ):
        workspace_id = f"epoch-session-race-{uuid4().hex}"
        _open_exact_release(
            settings,
            database,
            workspace_id=workspace_id,
        )
        insert_started = Event()

        def insert_session() -> tuple[str, str | None]:
            insert_started.set()
            return _register_release_session(
                settings,
                workspace_id=workspace_id,
                label="concurrent-epoch-session",
            )

        with ThreadPoolExecutor(max_workers=1) as executor:
            with database.connect() as mutation_conn, mutation_conn.transaction():
                _insert_paper_epoch_mutation(
                    mutation_conn,
                    label="concurrent-session",
                )
                future = executor.submit(insert_session)
                assert insert_started.wait(timeout=2)
                with pytest.raises(FutureTimeoutError):
                    future.result(timeout=0.25)
            _session_id, binding = future.result(timeout=5)
        assert binding is None


def test_025_concurrent_epoch_bump_serializes_command_insert() -> None:
    with _released_database(purpose="025cmdrace") as (
        settings,
        database,
    ):
        workspace_id = f"epoch-command-race-{uuid4().hex}"
        admission_id = _open_exact_release(
            settings,
            database,
            workspace_id=workspace_id,
        )
        session_id, binding = _register_release_session(
            settings,
            workspace_id=workspace_id,
            label="before-concurrent-command",
        )
        assert binding == admission_id
        insert_started = Event()
        client_request_id = f"concurrent-command-{uuid4().hex}"

        def insert_command() -> str:
            insert_started.set()
            try:
                HermesCommandLedger(settings).create_command(
                    platform_session_id=session_id,
                    client_request_id=client_request_id,
                    kind="conversation_turn",
                    canonical_request_digest="b" * 64,
                    payload_ref=f"platform-payload://sha256/{'c' * 64}",
                    provider_policy_digest=PROVIDER_POLICY_DIGEST,
                )
            except HermesCommandLedgerUnavailable:
                return "rejected"
            return "accepted"

        with ThreadPoolExecutor(max_workers=1) as executor:
            with database.connect() as mutation_conn, mutation_conn.transaction():
                _insert_paper_epoch_mutation(
                    mutation_conn,
                    label="concurrent-command",
                )
                future = executor.submit(insert_command)
                assert insert_started.wait(timeout=2)
                with pytest.raises(FutureTimeoutError):
                    future.result(timeout=0.25)
            outcome = future.result(timeout=5)
        assert outcome == "rejected"
        with database.connect() as conn:
            assert conn.execute(
                """
                SELECT count(*)
                FROM quant_system.hermes_commands
                WHERE client_request_id = %s
                """,
                (client_request_id,),
            ).fetchone() == (0,)
