-- Seal the HQA paper research claim and encrypted prompt lineage into the
-- already-durable Gate 1/2/3 chain.
--
-- PostgreSQL stores only SHA-256 digests.  Gate 1 and Gate 2 carry the exact
-- claim/start pair; Gate 3 adds the continue digest.  Completion v2 must repeat
-- those already-sealed Gate 3 values exactly, so a completion INSERT cannot
-- self-attest a substituted claim or payload.  Historical claim-less rows
-- remain valid only with the v1 completion envelope.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended(
        'quant_system:026_agent_v02_paper_research_claim_lineage',
        0
    )
);

DO $$
DECLARE
    installed_version INTEGER;
    missing_column_count INTEGER;
    completion_trigger_count INTEGER;
BEGIN
    IF to_regclass(
        'quant_system.agent_v02_paper_run_attestation_meta'
    ) IS NULL
       OR to_regclass(
           'quant_system.agent_v02_paper_gate_challenges'
       ) IS NULL
       OR to_regclass(
           'quant_system.agent_v02_paper_gate_completions'
       ) IS NULL
       OR to_regprocedure(
           'quant_system.require_agent_v02_paper_completion_binding()'
       ) IS NULL
    THEN
        RAISE EXCEPTION
            'paper research claim lineage requires migration 021';
    END IF;

    SELECT schema_version
    INTO installed_version
    FROM quant_system.agent_v02_paper_run_attestation_meta
    WHERE singleton IS TRUE;
    IF installed_version IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION
            'paper research claim lineage requires paper Run attestation schema version 1';
    END IF;

    WITH required_columns(table_name, column_name) AS (
        VALUES
            ('agent_v02_paper_gate_challenges', 'provider_evidence_ref'),
            ('agent_v02_paper_gate_challenges', 'subject_command_id'),
            ('agent_v02_paper_gate_challenges', 'subject_hermes_run_id'),
            ('agent_v02_paper_gate_challenges', 'subject_run_attestation_ref'),
            ('agent_v02_paper_gate_challenges', 'subject_run_attestation_digest'),
            ('agent_v02_paper_gate_challenges', 'final_backtest_provider'),
            ('agent_v02_paper_gate_challenges', 'final_backtest_receipt_digest'),
            ('agent_v02_paper_gate_challenges', 'final_backtest_config_ref'),
            ('agent_v02_paper_gate_challenges', 'final_backtest_config_digest'),
            ('agent_v02_paper_gate_challenges', 'final_backtest_summary_ref'),
            ('agent_v02_paper_gate_challenges', 'final_backtest_summary_digest'),
            ('agent_v02_paper_gate_challenges', 'final_backtest_report_ref'),
            ('agent_v02_paper_gate_challenges', 'final_backtest_report_digest'),
            ('agent_v02_paper_gate_completions', 'plan_version'),
            ('agent_v02_paper_gate_completions', 'plan_digest'),
            ('agent_v02_paper_gate_completions', 'plan_confirmation_note_digest'),
            ('agent_v02_paper_gate_completions', 'subject_command_id'),
            ('agent_v02_paper_gate_completions', 'subject_hermes_run_id'),
            ('agent_v02_paper_gate_completions', 'subject_run_attestation_ref'),
            ('agent_v02_paper_gate_completions', 'subject_run_attestation_digest'),
            ('agent_v02_paper_gate_completions', 'final_backtest_provider'),
            ('agent_v02_paper_gate_completions', 'final_backtest_receipt_digest'),
            ('agent_v02_paper_gate_completions', 'final_backtest_config_ref'),
            ('agent_v02_paper_gate_completions', 'final_backtest_config_digest'),
            ('agent_v02_paper_gate_completions', 'final_backtest_summary_ref'),
            ('agent_v02_paper_gate_completions', 'final_backtest_summary_digest'),
            ('agent_v02_paper_gate_completions', 'final_backtest_report_ref'),
            ('agent_v02_paper_gate_completions', 'final_backtest_report_digest')
    )
    SELECT count(*)
    INTO missing_column_count
    FROM required_columns AS required
    LEFT JOIN information_schema.columns AS observed
      ON observed.table_schema = 'quant_system'
     AND observed.table_name = required.table_name
     AND observed.column_name = required.column_name
    WHERE observed.column_name IS NULL;
    IF missing_column_count <> 0 THEN
        RAISE EXCEPTION
            'paper research claim lineage prerequisite columns are unavailable';
    END IF;

    SELECT count(*)
    INTO completion_trigger_count
    FROM pg_trigger AS trigger_record
    JOIN pg_class AS relation
      ON relation.oid = trigger_record.tgrelid
    JOIN pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'quant_system'
      AND relation.relname = 'agent_v02_paper_gate_completions'
      AND trigger_record.tgname =
            'trg_agent_v02_paper_completion_binding'
      AND trigger_record.tgfoid = to_regprocedure(
            'quant_system.require_agent_v02_paper_completion_binding()'
      )
      AND trigger_record.tgenabled = 'A'
      AND trigger_record.tgtype = 7
      AND NOT trigger_record.tgisinternal;
    IF completion_trigger_count <> 1 THEN
        RAISE EXCEPTION
            'paper research claim lineage requires the migration 021 ALWAYS completion trigger';
    END IF;
END $$;

ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ADD COLUMN IF NOT EXISTS research_claim_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ADD COLUMN IF NOT EXISTS research_start_payload_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ADD COLUMN IF NOT EXISTS research_continue_payload_digest CHAR(64);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_agent_v02_paper_gate_research_lineage'
          AND conrelid =
              'quant_system.agent_v02_paper_gate_challenges'::regclass
    ) THEN
        ALTER TABLE quant_system.agent_v02_paper_gate_challenges
            ADD CONSTRAINT ck_agent_v02_paper_gate_research_lineage
            CHECK (
                (
                    research_claim_digest IS NULL
                    AND research_start_payload_digest IS NULL
                    AND research_continue_payload_digest IS NULL
                    AND (
                        gate_kind <> 'gate1'
                        OR universe !~ '^research-claim:'
                    )
                )
                OR
                (
                    research_claim_digest IS NOT NULL
                    AND research_claim_digest ~ '^[0-9a-f]{64}$'
                    AND research_start_payload_digest IS NOT NULL
                    AND research_start_payload_digest
                        ~ '^[0-9a-f]{64}$'
                    AND (
                        (
                            gate_kind = 'gate1'
                            AND research_continue_payload_digest IS NULL
                            AND universe =
                                'research-claim:sha256:'
                                || research_claim_digest
                        )
                        OR
                        (
                            gate_kind = 'gate2'
                            AND research_continue_payload_digest IS NULL
                        )
                        OR
                        (
                            gate_kind = 'gate3'
                            AND research_continue_payload_digest IS NOT NULL
                            AND research_continue_payload_digest
                                ~ '^[0-9a-f]{64}$'
                        )
                    )
                )
            );
    END IF;
END $$;

CREATE OR REPLACE FUNCTION
    quant_system.require_agent_v02_paper_research_lineage()
RETURNS TRIGGER
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
AS $$
DECLARE
    parent_row quant_system.agent_v02_paper_gate_challenges%ROWTYPE;
    gate1_row quant_system.agent_v02_paper_gate_challenges%ROWTYPE;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.research_claim_digest
                IS DISTINCT FROM OLD.research_claim_digest
           OR NEW.research_start_payload_digest
                IS DISTINCT FROM OLD.research_start_payload_digest
           OR NEW.research_continue_payload_digest
                IS DISTINCT FROM OLD.research_continue_payload_digest
        THEN
            RAISE EXCEPTION
                'paper research claim lineage is immutable';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.gate_kind = 'gate1' THEN
        RETURN NEW;
    END IF;

    SELECT *
    INTO parent_row
    FROM quant_system.agent_v02_paper_gate_challenges
    WHERE gate_id = NEW.parent_gate_id
      AND owner_user_id = NEW.owner_user_id
      AND workspace_id = NEW.workspace_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION
            'paper research lineage parent is missing';
    END IF;

    IF NEW.gate_kind = 'gate2' THEN
        IF parent_row.gate_kind <> 'gate1'
           OR parent_row.research_claim_digest
                IS DISTINCT FROM NEW.research_claim_digest
           OR parent_row.research_start_payload_digest
                IS DISTINCT FROM NEW.research_start_payload_digest
           OR parent_row.research_continue_payload_digest IS NOT NULL
           OR NEW.research_continue_payload_digest IS NOT NULL
        THEN
            RAISE EXCEPTION
                'paper Gate 2 research lineage does not match Gate 1';
        END IF;
        RETURN NEW;
    END IF;

    SELECT *
    INTO gate1_row
    FROM quant_system.agent_v02_paper_gate_challenges
    WHERE gate_id = parent_row.parent_gate_id
      AND owner_user_id = NEW.owner_user_id
      AND workspace_id = NEW.workspace_id
      AND gate_kind = 'gate1';

    IF NOT FOUND
       OR parent_row.gate_kind <> 'gate2'
       OR gate1_row.research_claim_digest
            IS DISTINCT FROM NEW.research_claim_digest
       OR parent_row.research_claim_digest
            IS DISTINCT FROM NEW.research_claim_digest
       OR gate1_row.research_start_payload_digest
            IS DISTINCT FROM NEW.research_start_payload_digest
       OR parent_row.research_start_payload_digest
            IS DISTINCT FROM NEW.research_start_payload_digest
       OR gate1_row.research_continue_payload_digest IS NOT NULL
       OR parent_row.research_continue_payload_digest IS NOT NULL
    THEN
        RAISE EXCEPTION
            'paper Gate 3 research lineage does not match Gate 1/2';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_agent_v02_paper_research_lineage
    ON quant_system.agent_v02_paper_gate_challenges;
CREATE TRIGGER trg_agent_v02_paper_research_lineage
BEFORE INSERT OR UPDATE
ON quant_system.agent_v02_paper_gate_challenges
FOR EACH ROW
EXECUTE FUNCTION quant_system.require_agent_v02_paper_research_lineage();
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ENABLE ALWAYS TRIGGER trg_agent_v02_paper_research_lineage;

CREATE OR REPLACE FUNCTION
    quant_system.require_agent_v02_paper_completion_binding()
RETURNS TRIGGER
LANGUAGE plpgsql
STABLE
SECURITY INVOKER
AS $$
DECLARE
    challenge RECORD;
    completion_schema TEXT;
    expected_completion JSONB;
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

    completion_schema := NEW.completion_evidence ->> 'schema_version';
    IF completion_schema IS NULL
       OR completion_schema NOT IN (
            'agent-v0.2-paper-completion/v1',
            'agent-v0.2-paper-completion/v2'
       )
    THEN
        RAISE EXCEPTION
            'paper completion schema is unsupported';
    END IF;

    expected_completion := jsonb_build_object(
        'schema_version', completion_schema,
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
    );

    IF completion_schema = 'agent-v0.2-paper-completion/v1' THEN
        IF challenge.research_claim_digest IS NOT NULL
           OR challenge.research_start_payload_digest IS NOT NULL
           OR challenge.research_continue_payload_digest IS NOT NULL
        THEN
            RAISE EXCEPTION
                'paper completion v1 cannot complete a claimed research lineage';
        END IF;
    ELSE
        IF challenge.research_claim_digest IS NULL
           OR challenge.research_start_payload_digest IS NULL
           OR challenge.research_continue_payload_digest IS NULL
           OR NEW.completion_evidence ->> 'research_claim_digest'
                IS DISTINCT FROM challenge.research_claim_digest
           OR NEW.completion_evidence
                ->> 'research_start_payload_digest'
                IS DISTINCT FROM challenge.research_start_payload_digest
           OR NEW.completion_evidence
                ->> 'research_continue_payload_digest'
                IS DISTINCT FROM challenge.research_continue_payload_digest
        THEN
            RAISE EXCEPTION
                'paper completion research lineage does not match sealed Gate 3';
        END IF;
        expected_completion := expected_completion || jsonb_build_object(
            'research_claim_digest',
                challenge.research_claim_digest,
            'research_start_payload_digest',
                challenge.research_start_payload_digest,
            'research_continue_payload_digest',
                challenge.research_continue_payload_digest
        );
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
       OR NEW.completion_evidence IS DISTINCT FROM expected_completion
    THEN
        RAISE EXCEPTION
            'paper completion exact terminal lineage does not match Gate 3';
    END IF;
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator') THEN
        ALTER FUNCTION
            quant_system.require_agent_v02_paper_research_lineage()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.require_agent_v02_paper_completion_binding()
            OWNER TO quant_migrator;
    END IF;
END $$;

COMMIT;
