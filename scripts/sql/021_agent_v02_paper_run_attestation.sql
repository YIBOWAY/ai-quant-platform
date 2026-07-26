-- Agent v0.2 paper Run attestation and exact paper-completion binding.
--
-- This is a forward-only repair of the never-public 018 paper Gate schema.
-- It deliberately leaves 016-020 byte-for-byte unchanged.  The current
-- invocation Command must already have an exact delivered/succeeded Hermes
-- Session/Run binding; a dispatch lease is not evidence.  Gate 3 additionally
-- binds a distinct, succeeded subject Run plus the exact Futu final-backtest
-- artifact identities that flow into terminal completion evidence.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended(
        'quant_system:021_agent_v02_paper_run_attestation',
        0
    )
);

CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS
quant_system.agent_v02_paper_run_attestation_meta (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO quant_system.agent_v02_paper_run_attestation_meta (
    singleton,
    schema_version
)
VALUES (TRUE, 1)
ON CONFLICT (singleton) DO NOTHING;

DO $$
DECLARE
    installed_version INTEGER;
BEGIN
    SELECT schema_version
    INTO installed_version
    FROM quant_system.agent_v02_paper_run_attestation_meta
    WHERE singleton IS TRUE;

    IF installed_version > 1 THEN
        RAISE EXCEPTION
            'Paper Run attestation schema version % is newer than this binary supports (1)',
            installed_version;
    ELSIF installed_version <> 1 THEN
        RAISE EXCEPTION
            'Paper Run attestation schema version % is incompatible with this binary (expected 1)',
            installed_version;
    END IF;
END $$;

ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ADD COLUMN IF NOT EXISTS provider_evidence_ref TEXT;
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ADD COLUMN IF NOT EXISTS subject_command_id UUID;
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ADD COLUMN IF NOT EXISTS subject_hermes_run_id TEXT;
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ADD COLUMN IF NOT EXISTS subject_run_attestation_ref TEXT;
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ADD COLUMN IF NOT EXISTS subject_run_attestation_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ADD COLUMN IF NOT EXISTS final_backtest_provider TEXT;
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ADD COLUMN IF NOT EXISTS final_backtest_receipt_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ADD COLUMN IF NOT EXISTS final_backtest_config_ref TEXT;
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ADD COLUMN IF NOT EXISTS final_backtest_config_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ADD COLUMN IF NOT EXISTS final_backtest_summary_ref TEXT;
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ADD COLUMN IF NOT EXISTS final_backtest_summary_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ADD COLUMN IF NOT EXISTS final_backtest_report_ref TEXT;
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ADD COLUMN IF NOT EXISTS final_backtest_report_digest CHAR(64);

ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ADD COLUMN IF NOT EXISTS plan_version BIGINT;
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ADD COLUMN IF NOT EXISTS plan_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ADD COLUMN IF NOT EXISTS plan_confirmation_note_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ADD COLUMN IF NOT EXISTS subject_command_id UUID;
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ADD COLUMN IF NOT EXISTS subject_hermes_run_id TEXT;
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ADD COLUMN IF NOT EXISTS subject_run_attestation_ref TEXT;
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ADD COLUMN IF NOT EXISTS subject_run_attestation_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ADD COLUMN IF NOT EXISTS final_backtest_provider TEXT;
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ADD COLUMN IF NOT EXISTS final_backtest_receipt_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ADD COLUMN IF NOT EXISTS final_backtest_config_ref TEXT;
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ADD COLUMN IF NOT EXISTS final_backtest_config_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ADD COLUMN IF NOT EXISTS final_backtest_summary_ref TEXT;
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ADD COLUMN IF NOT EXISTS final_backtest_summary_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ADD COLUMN IF NOT EXISTS final_backtest_report_ref TEXT;
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ADD COLUMN IF NOT EXISTS final_backtest_report_digest CHAR(64);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_agent_v02_paper_gate_subject_command'
          AND conrelid =
              'quant_system.agent_v02_paper_gate_challenges'::regclass
    ) THEN
        ALTER TABLE quant_system.agent_v02_paper_gate_challenges
            ADD CONSTRAINT fk_agent_v02_paper_gate_subject_command
            FOREIGN KEY (subject_command_id)
            REFERENCES quant_system.hermes_commands(command_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_agent_v02_paper_completion_subject_command'
          AND conrelid =
              'quant_system.agent_v02_paper_gate_completions'::regclass
    ) THEN
        ALTER TABLE quant_system.agent_v02_paper_gate_completions
            ADD CONSTRAINT fk_agent_v02_paper_completion_subject_command
            FOREIGN KEY (subject_command_id)
            REFERENCES quant_system.hermes_commands(command_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_agent_v02_paper_gate_run_attestation'
          AND conrelid =
              'quant_system.agent_v02_paper_gate_challenges'::regclass
    ) THEN
        ALTER TABLE quant_system.agent_v02_paper_gate_challenges
            ADD CONSTRAINT ck_agent_v02_paper_gate_run_attestation
            CHECK (
                (
                    provider_evidence_ref IS NULL
                    AND subject_command_id IS NULL
                    AND subject_hermes_run_id IS NULL
                    AND subject_run_attestation_ref IS NULL
                    AND subject_run_attestation_digest IS NULL
                    AND final_backtest_provider IS NULL
                    AND final_backtest_receipt_digest IS NULL
                    AND final_backtest_config_ref IS NULL
                    AND final_backtest_config_digest IS NULL
                    AND final_backtest_summary_ref IS NULL
                    AND final_backtest_summary_digest IS NULL
                    AND final_backtest_report_ref IS NULL
                    AND final_backtest_report_digest IS NULL
                )
                OR
                (
                    gate_kind = 'gate3'
                    AND provider_evidence_ref IS NOT NULL
                    AND subject_command_id IS NOT NULL
                    AND subject_command_id <> command_id
                    AND subject_hermes_run_id IS NOT NULL
                    AND subject_hermes_run_id <> hermes_run_id
                    AND subject_hermes_run_id
                        ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
                    AND hqa_run_ref =
                        'run:' || subject_hermes_run_id
                    AND subject_run_attestation_ref IS NOT NULL
                    AND subject_run_attestation_digest IS NOT NULL
                    AND subject_run_attestation_digest
                        ~ '^[0-9a-f]{64}$'
                    AND subject_run_attestation_ref =
                        'paper-run-attestation:'
                        || subject_run_attestation_digest
                    AND provider_evidence_ref =
                        'provider-evidence:paper-run-'
                        || subject_run_attestation_digest
                    AND final_backtest_provider IS NOT NULL
                    AND final_backtest_provider = 'futu'
                    AND final_backtest_receipt_digest IS NOT NULL
                    AND final_backtest_receipt_digest
                        ~ '^[0-9a-f]{64}$'
                    AND final_backtest_config_ref IS NOT NULL
                    AND final_backtest_config_digest IS NOT NULL
                    AND final_backtest_config_digest
                        ~ '^[0-9a-f]{64}$'
                    AND final_backtest_summary_ref IS NOT NULL
                    AND final_backtest_summary_digest IS NOT NULL
                    AND final_backtest_summary_digest
                        ~ '^[0-9a-f]{64}$'
                    AND final_backtest_report_ref IS NOT NULL
                    AND final_backtest_report_digest IS NOT NULL
                    AND final_backtest_report_digest
                        ~ '^[0-9a-f]{64}$'
                    AND char_length(final_backtest_config_ref)
                        BETWEEN 1 AND 2048
                    AND char_length(final_backtest_summary_ref)
                        BETWEEN 1 AND 2048
                    AND char_length(final_backtest_report_ref)
                        BETWEEN 1 AND 2048
                    AND final_backtest_config_ref
                        !~ '[[:cntrl:]]'
                    AND final_backtest_summary_ref
                        !~ '[[:cntrl:]]'
                    AND final_backtest_report_ref
                        !~ '[[:cntrl:]]'
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_agent_v02_paper_completion_attestation'
          AND conrelid =
              'quant_system.agent_v02_paper_gate_completions'::regclass
    ) THEN
        ALTER TABLE quant_system.agent_v02_paper_gate_completions
            ADD CONSTRAINT ck_agent_v02_paper_completion_attestation
            CHECK (
                (
                    plan_version IS NULL
                    AND plan_digest IS NULL
                    AND plan_confirmation_note_digest IS NULL
                    AND subject_command_id IS NULL
                    AND subject_hermes_run_id IS NULL
                    AND subject_run_attestation_ref IS NULL
                    AND subject_run_attestation_digest IS NULL
                    AND final_backtest_provider IS NULL
                    AND final_backtest_receipt_digest IS NULL
                    AND final_backtest_config_ref IS NULL
                    AND final_backtest_config_digest IS NULL
                    AND final_backtest_summary_ref IS NULL
                    AND final_backtest_summary_digest IS NULL
                    AND final_backtest_report_ref IS NULL
                    AND final_backtest_report_digest IS NULL
                )
                OR
                (
                    plan_version IS NOT NULL
                    AND plan_version > 0
                    AND plan_digest IS NOT NULL
                    AND plan_digest ~ '^[0-9a-f]{64}$'
                    AND plan_confirmation_note_digest IS NOT NULL
                    AND plan_confirmation_note_digest
                        ~ '^[0-9a-f]{64}$'
                    AND subject_command_id IS NOT NULL
                    AND subject_hermes_run_id IS NOT NULL
                    AND subject_hermes_run_id
                        ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
                    AND hqa_run_ref =
                        'run:' || subject_hermes_run_id
                    AND subject_run_attestation_ref IS NOT NULL
                    AND subject_run_attestation_digest IS NOT NULL
                    AND subject_run_attestation_digest
                        ~ '^[0-9a-f]{64}$'
                    AND subject_run_attestation_ref =
                        'paper-run-attestation:'
                        || subject_run_attestation_digest
                    AND provider_evidence_ref =
                        'provider-evidence:paper-run-'
                        || subject_run_attestation_digest
                    AND final_backtest_provider IS NOT NULL
                    AND final_backtest_provider = 'futu'
                    AND final_backtest_receipt_digest IS NOT NULL
                    AND final_backtest_receipt_digest
                        ~ '^[0-9a-f]{64}$'
                    AND final_backtest_config_ref IS NOT NULL
                    AND final_backtest_config_digest IS NOT NULL
                    AND final_backtest_config_digest
                        ~ '^[0-9a-f]{64}$'
                    AND final_backtest_summary_ref IS NOT NULL
                    AND final_backtest_summary_digest IS NOT NULL
                    AND final_backtest_summary_digest
                        ~ '^[0-9a-f]{64}$'
                    AND final_backtest_report_ref IS NOT NULL
                    AND final_backtest_report_digest IS NOT NULL
                    AND final_backtest_report_digest
                        ~ '^[0-9a-f]{64}$'
                    AND char_length(final_backtest_config_ref)
                        BETWEEN 1 AND 2048
                    AND char_length(final_backtest_summary_ref)
                        BETWEEN 1 AND 2048
                    AND char_length(final_backtest_report_ref)
                        BETWEEN 1 AND 2048
                    AND final_backtest_config_ref
                        !~ '[[:cntrl:]]'
                    AND final_backtest_summary_ref
                        !~ '[[:cntrl:]]'
                    AND final_backtest_report_ref
                        !~ '[[:cntrl:]]'
                )
            );
    END IF;
END $$;

CREATE OR REPLACE FUNCTION
    quant_system.require_agent_v02_paper_gate_ready_session()
RETURNS TRIGGER
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
AS $$
DECLARE
    parent_row quant_system.agent_v02_paper_gate_challenges%ROWTYPE;
    gate1_row quant_system.agent_v02_paper_gate_challenges%ROWTYPE;
BEGIN
    PERFORM 1
    FROM quant_system.hermes_workspace_sessions AS managed_session
    JOIN quant_system.hermes_commands AS command
      ON command.command_id = NEW.command_id
     AND command.owner_user_id = managed_session.owner_user_id
     AND command.platform_session_id =
            managed_session.platform_session_id
     AND command.state IN ('delivered', 'succeeded')
     AND command.hermes_session_id =
            managed_session.hermes_session_id
     AND command.hermes_run_id = NEW.hermes_run_id
     AND command.candidate_admission_id
            IS NOT DISTINCT FROM managed_session.candidate_admission_id
    WHERE managed_session.platform_session_id = NEW.platform_session_id
      AND managed_session.hermes_session_id = NEW.hermes_session_id
      AND managed_session.owner_user_id = NEW.owner_user_id
      AND managed_session.workspace_id = NEW.workspace_id
      AND managed_session.kind = 'web_managed_session'
      AND managed_session.writer = 'web_control_plane'
      AND managed_session.provision_state = 'ready';

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'paper gate requires its exact delivered or succeeded Command on a ready web-managed Session';
    END IF;

    IF NEW.gate_kind IN ('gate1', 'gate2') THEN
        IF NEW.provider_evidence_ref IS NOT NULL
           OR NEW.subject_command_id IS NOT NULL
           OR NEW.subject_hermes_run_id IS NOT NULL
           OR NEW.subject_run_attestation_ref IS NOT NULL
           OR NEW.subject_run_attestation_digest IS NOT NULL
           OR NEW.final_backtest_provider IS NOT NULL
           OR NEW.final_backtest_receipt_digest IS NOT NULL
           OR NEW.final_backtest_config_ref IS NOT NULL
           OR NEW.final_backtest_config_digest IS NOT NULL
           OR NEW.final_backtest_summary_ref IS NOT NULL
           OR NEW.final_backtest_summary_digest IS NOT NULL
           OR NEW.final_backtest_report_ref IS NOT NULL
           OR NEW.final_backtest_report_digest IS NOT NULL
        THEN
            RAISE EXCEPTION
                'paper Gate 1/2 cannot claim terminal subject or Futu evidence';
        END IF;
    END IF;

    IF NEW.gate_kind = 'gate1' THEN
        IF NEW.parent_gate_id IS NOT NULL THEN
            RAISE EXCEPTION 'paper Gate 1 cannot have a parent';
        END IF;
        RETURN NEW;
    END IF;

    SELECT *
    INTO parent_row
    FROM quant_system.agent_v02_paper_gate_challenges
    WHERE gate_id = NEW.parent_gate_id
      AND owner_user_id = NEW.owner_user_id
      AND workspace_id = NEW.workspace_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'paper gate parent is missing';
    END IF;

    IF NEW.gate_kind = 'gate2' THEN
        IF parent_row.gate_kind <> 'gate1'
           OR parent_row.status <> 'confirmed'
           OR parent_row.task_ref IS DISTINCT FROM NEW.task_ref
           OR parent_row.attempt_ref IS DISTINCT FROM NEW.attempt_ref
           OR parent_row.hqa_gate_ref IS DISTINCT FROM NEW.hqa_gate_ref
           OR parent_row.platform_session_id
                IS DISTINCT FROM NEW.platform_session_id
           OR parent_row.hermes_session_id
                IS DISTINCT FROM NEW.hermes_session_id
           OR parent_row.reviewed_source_sha256
                IS DISTINCT FROM NEW.reviewed_source_sha256
           OR parent_row.gate1_confirmation_id
                IS DISTINCT FROM NEW.gate1_confirmation_id
           OR NEW.expected_task_version <= parent_row.expected_task_version
        THEN
            RAISE EXCEPTION
                'paper Gate 2 does not match the exact Gate 1 plan lineage';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.gate_kind <> 'gate3'
       OR parent_row.gate_kind <> 'gate2'
       OR parent_row.status <> 'reviewed'
    THEN
        RAISE EXCEPTION 'paper Gate 3 requires a reviewed Gate 2 parent';
    END IF;

    SELECT *
    INTO gate1_row
    FROM quant_system.agent_v02_paper_gate_challenges
    WHERE gate_id = parent_row.parent_gate_id
      AND owner_user_id = NEW.owner_user_id
      AND workspace_id = NEW.workspace_id
      AND gate_kind = 'gate1'
      AND status = 'confirmed';

    IF NOT FOUND
       OR parent_row.task_ref IS DISTINCT FROM NEW.task_ref
       OR gate1_row.task_ref IS DISTINCT FROM NEW.task_ref
       OR parent_row.platform_session_id
            IS DISTINCT FROM NEW.platform_session_id
       OR gate1_row.platform_session_id
            IS DISTINCT FROM NEW.platform_session_id
       OR parent_row.hermes_session_id
            IS DISTINCT FROM NEW.hermes_session_id
       OR gate1_row.hermes_session_id
            IS DISTINCT FROM NEW.hermes_session_id
       OR parent_row.reviewed_source_sha256
            IS DISTINCT FROM NEW.reviewed_source_sha256
       OR gate1_row.reviewed_source_sha256
            IS DISTINCT FROM NEW.reviewed_source_sha256
       OR parent_row.gate1_confirmation_id
            IS DISTINCT FROM NEW.gate1_confirmation_id
       OR gate1_row.gate1_confirmation_id
            IS DISTINCT FROM NEW.gate1_confirmation_id
       OR parent_row.candidate_id IS DISTINCT FROM NEW.candidate_id
       OR parent_row.expected_digest IS DISTINCT FROM NEW.expected_digest
       OR NEW.attempt_ref = parent_row.attempt_ref
       OR NEW.hqa_run_ref IS NULL
       OR NEW.hermes_run_id = parent_row.hermes_run_id
       OR NEW.expected_task_version <= parent_row.expected_task_version
    THEN
        RAISE EXCEPTION
            'paper Gate 3 does not match the continued research lineage';
    END IF;

    IF NEW.subject_command_id IS NULL
       OR NEW.subject_command_id = NEW.command_id
       OR NEW.subject_hermes_run_id IS NULL
       OR NEW.subject_hermes_run_id = NEW.hermes_run_id
       OR NEW.hqa_run_ref IS DISTINCT FROM
            'run:' || NEW.subject_hermes_run_id
       OR NEW.subject_run_attestation_digest IS NULL
       OR NEW.subject_run_attestation_digest
            !~ '^[0-9a-f]{64}$'
       OR NEW.subject_run_attestation_ref IS NULL
       OR NEW.subject_run_attestation_ref IS DISTINCT FROM
            'paper-run-attestation:'
            || NEW.subject_run_attestation_digest
       OR NEW.provider_evidence_ref IS NULL
       OR NEW.provider_evidence_ref IS DISTINCT FROM
            'provider-evidence:paper-run-'
            || NEW.subject_run_attestation_digest
       OR NEW.final_backtest_provider IS DISTINCT FROM 'futu'
       OR NEW.final_backtest_receipt_digest IS NULL
       OR NEW.final_backtest_receipt_digest
            !~ '^[0-9a-f]{64}$'
       OR NEW.final_backtest_config_ref IS NULL
       OR NEW.final_backtest_config_digest IS NULL
       OR NEW.final_backtest_config_digest
            !~ '^[0-9a-f]{64}$'
       OR NEW.final_backtest_summary_ref IS NULL
       OR NEW.final_backtest_summary_digest IS NULL
       OR NEW.final_backtest_summary_digest
            !~ '^[0-9a-f]{64}$'
       OR NEW.final_backtest_report_ref IS NULL
       OR NEW.final_backtest_report_digest IS NULL
       OR NEW.final_backtest_report_digest
            !~ '^[0-9a-f]{64}$'
    THEN
        RAISE EXCEPTION
            'paper Gate 3 terminal subject or Futu evidence is incomplete';
    END IF;

    PERFORM 1
    FROM quant_system.hermes_commands AS subject_command
    WHERE subject_command.command_id = NEW.subject_command_id
      AND subject_command.owner_user_id = NEW.owner_user_id
      AND subject_command.platform_session_id = NEW.platform_session_id
      AND subject_command.hermes_session_id = NEW.hermes_session_id
      AND subject_command.hermes_run_id = NEW.subject_hermes_run_id
      AND subject_command.state = 'succeeded'
      AND subject_command.candidate_admission_id IS NOT DISTINCT FROM (
            SELECT candidate_admission_id
            FROM quant_system.hermes_workspace_sessions
            WHERE platform_session_id = NEW.platform_session_id
      );
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'paper Gate 3 subject is not an exact succeeded Command';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION
    quant_system.guard_agent_v02_paper_gate_challenge()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    IF NEW.gate_id IS DISTINCT FROM OLD.gate_id
       OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.gate_kind IS DISTINCT FROM OLD.gate_kind
       OR NEW.task_ref IS DISTINCT FROM OLD.task_ref
       OR NEW.expected_task_version IS DISTINCT FROM OLD.expected_task_version
       OR NEW.attempt_ref IS DISTINCT FROM OLD.attempt_ref
       OR NEW.hqa_gate_ref IS DISTINCT FROM OLD.hqa_gate_ref
       OR NEW.platform_session_id IS DISTINCT FROM OLD.platform_session_id
       OR NEW.hermes_session_id IS DISTINCT FROM OLD.hermes_session_id
       OR NEW.command_id IS DISTINCT FROM OLD.command_id
       OR NEW.hermes_run_id IS DISTINCT FROM OLD.hermes_run_id
       OR NEW.hqa_run_ref IS DISTINCT FROM OLD.hqa_run_ref
       OR NEW.provider_evidence_ref IS DISTINCT FROM OLD.provider_evidence_ref
       OR NEW.subject_command_id IS DISTINCT FROM OLD.subject_command_id
       OR NEW.subject_hermes_run_id
            IS DISTINCT FROM OLD.subject_hermes_run_id
       OR NEW.subject_run_attestation_ref
            IS DISTINCT FROM OLD.subject_run_attestation_ref
       OR NEW.subject_run_attestation_digest
            IS DISTINCT FROM OLD.subject_run_attestation_digest
       OR NEW.final_backtest_provider
            IS DISTINCT FROM OLD.final_backtest_provider
       OR NEW.final_backtest_receipt_digest
            IS DISTINCT FROM OLD.final_backtest_receipt_digest
       OR NEW.final_backtest_config_ref
            IS DISTINCT FROM OLD.final_backtest_config_ref
       OR NEW.final_backtest_config_digest
            IS DISTINCT FROM OLD.final_backtest_config_digest
       OR NEW.final_backtest_summary_ref
            IS DISTINCT FROM OLD.final_backtest_summary_ref
       OR NEW.final_backtest_summary_digest
            IS DISTINCT FROM OLD.final_backtest_summary_digest
       OR NEW.final_backtest_report_ref
            IS DISTINCT FROM OLD.final_backtest_report_ref
       OR NEW.final_backtest_report_digest
            IS DISTINCT FROM OLD.final_backtest_report_digest
       OR NEW.parent_gate_id IS DISTINCT FROM OLD.parent_gate_id
       OR NEW.source_file_ref IS DISTINCT FROM OLD.source_file_ref
       OR NEW.universe IS DISTINCT FROM OLD.universe
       OR NEW.reviewed_source_sha256
            IS DISTINCT FROM OLD.reviewed_source_sha256
       OR NEW.candidate_id IS DISTINCT FROM OLD.candidate_id
       OR NEW.expected_digest IS DISTINCT FROM OLD.expected_digest
       OR NEW.expected_status IS DISTINCT FROM OLD.expected_status
       OR NEW.final_backtest_receipt_id
            IS DISTINCT FROM OLD.final_backtest_receipt_id
       OR NEW.base_commit IS DISTINCT FROM OLD.base_commit
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION
            'paper gate challenge identity and exact target are immutable';
    END IF;

    IF OLD.status <> 'pending' THEN
        RAISE EXCEPTION 'terminal paper gate challenge is immutable';
    END IF;
    IF (
        OLD.gate_kind = 'gate1'
        AND NEW.status NOT IN ('confirmed', 'rejected', 'outcome_unknown')
    )
       OR (
           OLD.gate_kind = 'gate2'
           AND NEW.status NOT IN ('reviewed', 'rejected', 'outcome_unknown')
       )
       OR (
           OLD.gate_kind = 'gate3'
           AND NEW.status NOT IN ('prepared', 'rejected', 'outcome_unknown')
       )
    THEN
        RAISE EXCEPTION 'paper gate challenge transition is invalid';
    END IF;
    IF NEW.decided_action_kind IS NULL
       OR NEW.decided_client_action_id IS NULL
       OR NEW.decided_action_digest IS NULL
       OR NEW.decided_at IS NULL
       OR (
           NEW.status IN ('confirmed', 'reviewed', 'prepared')
           AND (
               NEW.hqa_receipt_ref IS NULL
               OR NEW.hqa_receipt_digest IS NULL
           )
       )
       OR (
           NEW.status IN ('rejected', 'outcome_unknown')
           AND (
               NEW.hqa_receipt_ref IS NOT NULL
               OR NEW.hqa_receipt_digest IS NOT NULL
           )
       )
    THEN
        RAISE EXCEPTION 'paper gate challenge terminal evidence is incomplete';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION
    quant_system.require_agent_v02_paper_completion_binding()
RETURNS TRIGGER
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
AS $$
DECLARE
    challenge RECORD;
BEGIN
    SELECT gate3.*
    INTO challenge
    FROM quant_system.agent_v02_paper_gate_challenges AS gate3
    JOIN quant_system.agent_v02_paper_gate_actions AS action
      ON action.gate_id = gate3.gate_id
     AND action.owner_user_id = gate3.owner_user_id
     AND action.workspace_id = gate3.workspace_id
     AND action.action_kind = 'gate3_promotion_review_prepare'
     AND action.action_state = 'succeeded'
    WHERE gate3.gate_id = NEW.gate_id
      AND gate3.owner_user_id = NEW.owner_user_id
      AND gate3.workspace_id = NEW.workspace_id
      AND gate3.gate_kind = 'gate3'
      AND gate3.status = 'prepared';

    IF NOT FOUND THEN
        RAISE EXCEPTION
            'paper completion requires the exact prepared Gate 3 action';
    END IF;

    IF challenge.task_ref IS DISTINCT FROM NEW.task_ref
       OR challenge.attempt_ref IS DISTINCT FROM NEW.attempt_ref
       OR challenge.hqa_gate_ref IS DISTINCT FROM NEW.domain_gate_ref
       OR challenge.hqa_run_ref IS DISTINCT FROM NEW.hqa_run_ref
       OR challenge.provider_evidence_ref
            IS DISTINCT FROM NEW.provider_evidence_ref
       OR challenge.subject_command_id
            IS DISTINCT FROM NEW.subject_command_id
       OR challenge.subject_hermes_run_id
            IS DISTINCT FROM NEW.subject_hermes_run_id
       OR challenge.subject_run_attestation_ref
            IS DISTINCT FROM NEW.subject_run_attestation_ref
       OR challenge.subject_run_attestation_digest
            IS DISTINCT FROM NEW.subject_run_attestation_digest
       OR challenge.final_backtest_provider
            IS DISTINCT FROM NEW.final_backtest_provider
       OR challenge.final_backtest_receipt_digest
            IS DISTINCT FROM NEW.final_backtest_receipt_digest
       OR challenge.final_backtest_config_ref
            IS DISTINCT FROM NEW.final_backtest_config_ref
       OR challenge.final_backtest_config_digest
            IS DISTINCT FROM NEW.final_backtest_config_digest
       OR challenge.final_backtest_summary_ref
            IS DISTINCT FROM NEW.final_backtest_summary_ref
       OR challenge.final_backtest_summary_digest
            IS DISTINCT FROM NEW.final_backtest_summary_digest
       OR challenge.final_backtest_report_ref
            IS DISTINCT FROM NEW.final_backtest_report_ref
       OR challenge.final_backtest_report_digest
            IS DISTINCT FROM NEW.final_backtest_report_digest
       OR challenge.promotion_id IS DISTINCT FROM NEW.promotion_id
       OR challenge.candidate_id IS DISTINCT FROM NEW.candidate_id
       OR challenge.expected_digest IS DISTINCT FROM NEW.candidate_digest
       OR challenge.final_backtest_receipt_id
            IS DISTINCT FROM NEW.final_backtest_receipt_id
       OR challenge.base_commit IS DISTINCT FROM NEW.base_commit
       OR NEW.task_version
            IS DISTINCT FROM challenge.expected_task_version + 4
       OR NEW.plan_version IS NULL
       OR NEW.plan_version <= 0
       OR NEW.plan_digest IS NULL
       OR NEW.plan_digest !~ '^[0-9a-f]{64}$'
       OR NEW.plan_confirmation_note_digest IS NULL
       OR NEW.plan_confirmation_note_digest
            !~ '^[0-9a-f]{64}$'
       OR NEW.subject_command_id IS NULL
       OR NEW.subject_hermes_run_id IS NULL
       OR NEW.subject_run_attestation_ref IS NULL
       OR NEW.subject_run_attestation_digest IS NULL
       OR NEW.provider_evidence_ref IS NULL
       OR NEW.final_backtest_provider IS NULL
       OR NEW.final_backtest_receipt_digest IS NULL
       OR NEW.final_backtest_config_ref IS NULL
       OR NEW.final_backtest_config_digest IS NULL
       OR NEW.final_backtest_summary_ref IS NULL
       OR NEW.final_backtest_summary_digest IS NULL
       OR NEW.final_backtest_report_ref IS NULL
       OR NEW.final_backtest_report_digest IS NULL
       OR NEW.completion_evidence IS DISTINCT FROM jsonb_build_object(
            'schema_version', 'agent-v0.2-paper-completion/v1',
            'task_ref', NEW.task_ref,
            'task_version', NEW.task_version,
            'task_status', NEW.task_status,
            'task_terminal_outcome', NEW.task_terminal_outcome,
            'plan_version', NEW.plan_version,
            'plan_digest', NEW.plan_digest,
            'plan_confirmation_note_digest',
                NEW.plan_confirmation_note_digest,
            'attempt_ref', NEW.attempt_ref,
            'attempt_status', NEW.attempt_status,
            'attempt_terminal_outcome', NEW.attempt_terminal_outcome,
            'domain_gate_ref', NEW.domain_gate_ref,
            'domain_gate_outcome', NEW.domain_gate_outcome,
            'hqa_run_ref', NEW.hqa_run_ref,
            'provider_evidence_ref', NEW.provider_evidence_ref,
            'subject_command_id', NEW.subject_command_id::TEXT,
            'subject_hermes_run_id', NEW.subject_hermes_run_id,
            'subject_run_attestation_ref',
                NEW.subject_run_attestation_ref,
            'subject_run_attestation_digest',
                NEW.subject_run_attestation_digest,
            'final_backtest_provider', NEW.final_backtest_provider,
            'final_backtest_receipt_digest',
                NEW.final_backtest_receipt_digest,
            'final_backtest_config_ref', NEW.final_backtest_config_ref,
            'final_backtest_config_digest',
                NEW.final_backtest_config_digest,
            'final_backtest_summary_ref',
                NEW.final_backtest_summary_ref,
            'final_backtest_summary_digest',
                NEW.final_backtest_summary_digest,
            'final_backtest_report_ref', NEW.final_backtest_report_ref,
            'final_backtest_report_digest',
                NEW.final_backtest_report_digest,
            'promotion_id', NEW.promotion_id,
            'reviewed_commit', NEW.reviewed_commit,
            'candidate_id', NEW.candidate_id,
            'candidate_digest', NEW.candidate_digest,
            'final_backtest_receipt_id',
                NEW.final_backtest_receipt_id,
            'base_commit', NEW.base_commit,
            'attempt_completion_operation_id',
                NEW.attempt_completion_operation_id,
            'attempt_completion_event_id',
                NEW.attempt_completion_event_id,
            'task_completion_operation_id',
                NEW.task_completion_operation_id,
            'task_completion_event_id',
                NEW.task_completion_event_id,
            'workflow_audit_status', NEW.workflow_audit_status,
            'workflow_audit_ref', NEW.workflow_audit_ref,
            'workflow_audit_digest', NEW.workflow_audit_digest
       )
    THEN
        RAISE EXCEPTION
            'paper completion exact terminal lineage does not match Gate 3';
    END IF;
    RETURN NEW;
END;
$$;

ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ENABLE ALWAYS TRIGGER trg_agent_v02_paper_gate_challenge_update;
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ENABLE ALWAYS TRIGGER trg_agent_v02_paper_gate_ready_session;
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ENABLE ALWAYS TRIGGER trg_agent_v02_paper_completion_binding;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_readonly')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator')
    THEN
        GRANT USAGE ON SCHEMA quant_system
            TO quant_runtime, quant_readonly, quant_migrator;
        REVOKE CREATE ON SCHEMA quant_system
            FROM quant_runtime, quant_readonly;

        GRANT SELECT
            ON quant_system.agent_v02_paper_run_attestation_meta
            TO quant_runtime, quant_readonly;
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE
            ON quant_system.agent_v02_paper_run_attestation_meta
            FROM quant_runtime, quant_readonly;
        REVOKE ALL
            ON quant_system.agent_v02_paper_run_attestation_meta
            FROM PUBLIC;
        GRANT ALL
            ON quant_system.agent_v02_paper_run_attestation_meta
            TO quant_migrator;

        ALTER TABLE
            quant_system.agent_v02_paper_run_attestation_meta
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.require_agent_v02_paper_gate_ready_session()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.guard_agent_v02_paper_gate_challenge()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.require_agent_v02_paper_completion_binding()
            OWNER TO quant_migrator;
    END IF;
END $$;

COMMIT;
