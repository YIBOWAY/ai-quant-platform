-- Durable Agent v0.2 paper-research Gate 1/2/3 bridge.
--
-- PostgreSQL owns browser action CAS, restart recovery, and exact linkage to
-- the HQA Task/Attempt plus managed Hermes Session/Run.  It never stores source
-- bytes, research prompts, provider credentials, or order/trading payloads.
-- HQA remains the formula/Gate1 and Gate3-entry authority; the Platform
-- candidate repository remains the Gate2 CAS authority.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:018_agent_v02_paper_gate_bridge', 0)
);

CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_paper_gate_meta (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO quant_system.agent_v02_paper_gate_meta (
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
    FROM quant_system.agent_v02_paper_gate_meta
    WHERE singleton IS TRUE;

    IF installed_version <> 1 THEN
        RAISE EXCEPTION
            'Paper Gate schema version % is incompatible with this binary (expected 1)',
            installed_version;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_paper_gate_challenges (
    gate_id TEXT PRIMARY KEY,
    owner_user_id UUID NOT NULL
        REFERENCES quant_system.app_users(id),
    workspace_id TEXT NOT NULL,
    gate_kind TEXT NOT NULL
        CHECK (gate_kind IN ('gate1', 'gate2', 'gate3')),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (
            status IN (
                'pending',
                'confirmed',
                'reviewed',
                'prepared',
                'rejected',
                'outcome_unknown'
            )
        ),
    task_ref TEXT NOT NULL,
    expected_task_version BIGINT NOT NULL
        CHECK (expected_task_version BETWEEN 1 AND 9223372036854775807),
    attempt_ref TEXT NOT NULL,
    hqa_gate_ref TEXT NOT NULL,
    platform_session_id TEXT NOT NULL
        REFERENCES quant_system.hermes_workspace_sessions(platform_session_id),
    hermes_session_id TEXT NOT NULL,
    command_id UUID NOT NULL
        REFERENCES quant_system.hermes_commands(command_id),
    hermes_run_id TEXT NOT NULL,
    hqa_run_ref TEXT,
    parent_gate_id TEXT
        REFERENCES quant_system.agent_v02_paper_gate_challenges(gate_id),
    source_file_ref TEXT,
    universe TEXT,
    reviewed_source_sha256 CHAR(64),
    gate1_confirmation_id TEXT,
    candidate_id TEXT,
    expected_digest CHAR(64),
    expected_status TEXT,
    final_backtest_receipt_id TEXT,
    base_commit CHAR(40),
    hqa_receipt_ref TEXT,
    hqa_receipt_digest CHAR(64),
    promotion_id TEXT,
    worktree_ref TEXT,
    patch_ref TEXT,
    manifest_ref TEXT,
    decided_action_kind TEXT,
    decided_client_action_id TEXT,
    decided_action_digest CHAR(64),
    decided_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_agent_v02_paper_gate_id
        CHECK (
            char_length(gate_id) BETWEEN 1 AND 128
            AND gate_id ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
        ),
    CONSTRAINT ck_agent_v02_paper_gate_workspace
        CHECK (
            char_length(workspace_id) BETWEEN 1 AND 200
            AND workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_paper_gate_task
        CHECK (
            char_length(task_ref) BETWEEN 6 AND 133
            AND task_ref ~ '^task:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
        ),
    CONSTRAINT ck_agent_v02_paper_gate_attempt
        CHECK (
            char_length(attempt_ref) BETWEEN 9 AND 136
            AND attempt_ref
                ~ '^attempt:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
        ),
    CONSTRAINT ck_agent_v02_paper_gate_hqa_gate
        CHECK (
            char_length(hqa_gate_ref) BETWEEN 6 AND 133
            AND hqa_gate_ref
                ~ '^gate:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
        ),
    CONSTRAINT ck_agent_v02_paper_gate_run
        CHECK (
            char_length(hermes_session_id) BETWEEN 1 AND 255
            AND hermes_session_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
            AND
            char_length(hermes_run_id) BETWEEN 1 AND 255
            AND hermes_run_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_paper_gate_hqa_run
        CHECK (
            hqa_run_ref IS NULL
            OR (
                char_length(hqa_run_ref) BETWEEN 5 AND 132
                AND hqa_run_ref
                    ~ '^run:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
            )
        ),
    CONSTRAINT ck_agent_v02_paper_gate_digest_fields
        CHECK (
            (reviewed_source_sha256 IS NULL
                OR reviewed_source_sha256 ~ '^[0-9a-f]{64}$')
            AND
            (expected_digest IS NULL
                OR expected_digest ~ '^[0-9a-f]{64}$')
            AND
            (hqa_receipt_digest IS NULL
                OR hqa_receipt_digest ~ '^[0-9a-f]{64}$')
            AND
            (decided_action_digest IS NULL
                OR decided_action_digest ~ '^[0-9a-f]{64}$')
            AND
            (base_commit IS NULL
                OR base_commit ~ '^[0-9a-f]{40}$')
        ),
    CONSTRAINT ck_agent_v02_paper_gate_source_ref
        CHECK (
            source_file_ref IS NULL
            OR (
                char_length(source_file_ref) BETWEEN 2 AND 4096
                AND left(source_file_ref, 1) = '/'
            )
        ),
    CONSTRAINT ck_agent_v02_paper_gate_universe
        CHECK (
            universe IS NULL
            OR char_length(universe) BETWEEN 1 AND 2000
        ),
    CONSTRAINT ck_agent_v02_paper_gate_expected_status
        CHECK (expected_status IS NULL OR expected_status = 'pending'),
    CONSTRAINT ck_agent_v02_paper_gate_exact_refs
        CHECK (
            (
                gate1_confirmation_id IS NULL
                OR gate1_confirmation_id ~ '^gate1-[0-9a-f]{32}$'
            )
            AND
            (
                candidate_id IS NULL
                OR candidate_id
                    ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
            )
            AND
            (
                final_backtest_receipt_id IS NULL
                OR final_backtest_receipt_id
                    ~ '^backtest-[0-9a-f]{32}$'
            )
            AND
            (
                hqa_receipt_ref IS NULL
                OR hqa_receipt_ref
                    ~ '^hqa-paper-gate:pgate-[0-9a-f]{32}$'
            )
            AND
            (
                promotion_id IS NULL
                OR promotion_id
                    ~ '^promo-[0-9a-f]{32}(-r([2-9]|[1-9][0-9]+))?$'
            )
        ),
    CONSTRAINT ck_agent_v02_paper_gate_artifact_refs
        CHECK (
            (worktree_ref IS NULL OR left(worktree_ref, 1) = '/')
            AND (patch_ref IS NULL OR left(patch_ref, 1) = '/')
            AND (manifest_ref IS NULL OR left(manifest_ref, 1) = '/')
        ),
    CONSTRAINT ck_agent_v02_paper_gate_hqa_receipt_pair
        CHECK (
            (hqa_receipt_ref IS NULL) = (hqa_receipt_digest IS NULL)
        ),
    CONSTRAINT ck_agent_v02_paper_gate_decision_identity
        CHECK (
            (
                status = 'pending'
                AND decided_action_kind IS NULL
                AND decided_client_action_id IS NULL
                AND decided_action_digest IS NULL
                AND decided_at IS NULL
                AND hqa_receipt_ref IS NULL
            )
            OR
            (
                status IN ('confirmed', 'reviewed', 'prepared')
                AND decided_action_kind IS NOT NULL
                AND decided_client_action_id IS NOT NULL
                AND decided_action_digest IS NOT NULL
                AND decided_at IS NOT NULL
                AND hqa_receipt_ref IS NOT NULL
            )
            OR
            (
                status IN ('rejected', 'outcome_unknown')
                AND decided_action_kind IS NOT NULL
                AND decided_client_action_id IS NOT NULL
                AND decided_action_digest IS NOT NULL
                AND decided_at IS NOT NULL
                AND hqa_receipt_ref IS NULL
            )
        ),
    CONSTRAINT ck_agent_v02_paper_gate_kind_shape
        CHECK (
            (
                gate_kind = 'gate1'
                AND status IN (
                    'pending',
                    'confirmed',
                    'rejected',
                    'outcome_unknown'
                )
                AND hqa_run_ref IS NULL
                AND source_file_ref IS NOT NULL
                AND universe IS NOT NULL
                AND reviewed_source_sha256 IS NOT NULL
                AND candidate_id IS NULL
                AND expected_digest IS NULL
                AND expected_status IS NULL
                AND final_backtest_receipt_id IS NULL
                AND base_commit IS NULL
                AND promotion_id IS NULL
                AND worktree_ref IS NULL
                AND patch_ref IS NULL
                AND manifest_ref IS NULL
                AND (
                    (
                        status IN ('pending', 'rejected', 'outcome_unknown')
                        AND gate1_confirmation_id IS NULL
                    )
                    OR
                    (status = 'confirmed' AND gate1_confirmation_id IS NOT NULL)
                )
            )
            OR
            (
                gate_kind = 'gate2'
                AND status IN (
                    'pending',
                    'reviewed',
                    'rejected',
                    'outcome_unknown'
                )
                AND hqa_run_ref IS NULL
                AND parent_gate_id IS NOT NULL
                AND source_file_ref IS NULL
                AND universe IS NULL
                AND reviewed_source_sha256 IS NOT NULL
                AND gate1_confirmation_id IS NOT NULL
                AND candidate_id IS NOT NULL
                AND expected_digest IS NOT NULL
                AND expected_status = 'pending'
                AND final_backtest_receipt_id IS NULL
                AND base_commit IS NULL
                AND promotion_id IS NULL
                AND worktree_ref IS NULL
                AND patch_ref IS NULL
                AND manifest_ref IS NULL
            )
            OR
            (
                gate_kind = 'gate3'
                AND status IN (
                    'pending',
                    'prepared',
                    'rejected',
                    'outcome_unknown'
                )
                AND hqa_run_ref IS NOT NULL
                AND parent_gate_id IS NOT NULL
                AND source_file_ref IS NULL
                AND universe IS NULL
                AND reviewed_source_sha256 IS NOT NULL
                AND gate1_confirmation_id IS NOT NULL
                AND candidate_id IS NOT NULL
                AND expected_digest IS NOT NULL
                AND expected_status IS NULL
                AND final_backtest_receipt_id IS NOT NULL
                AND base_commit IS NOT NULL
                AND (
                    (
                        status IN ('pending', 'rejected', 'outcome_unknown')
                        AND promotion_id IS NULL
                        AND worktree_ref IS NULL
                        AND patch_ref IS NULL
                        AND manifest_ref IS NULL
                    )
                    OR
                    (
                        status = 'prepared'
                        AND promotion_id IS NOT NULL
                        AND worktree_ref IS NOT NULL
                        AND patch_ref IS NOT NULL
                        AND manifest_ref IS NOT NULL
                    )
                )
            )
        )
);

ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ALTER COLUMN platform_session_id SET NOT NULL;
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ALTER COLUMN hermes_session_id SET NOT NULL;
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ALTER COLUMN command_id SET NOT NULL;
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ALTER COLUMN hermes_run_id SET NOT NULL;

CREATE INDEX IF NOT EXISTS ix_agent_v02_paper_gate_workspace
    ON quant_system.agent_v02_paper_gate_challenges (
        owner_user_id,
        workspace_id,
        status,
        gate_kind,
        created_at,
        gate_id
    );

CREATE INDEX IF NOT EXISTS ix_agent_v02_paper_gate_task_attempt
    ON quant_system.agent_v02_paper_gate_challenges (
        owner_user_id,
        workspace_id,
        task_ref,
        attempt_ref,
        created_at
    );

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_agent_v02_paper_gate_pending_gate1_target
    ON quant_system.agent_v02_paper_gate_challenges (
        owner_user_id,
        workspace_id,
        task_ref,
        reviewed_source_sha256
    )
    WHERE gate_kind = 'gate1' AND status = 'pending';

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_agent_v02_paper_gate_pending_gate2_target
    ON quant_system.agent_v02_paper_gate_challenges (
        owner_user_id,
        workspace_id,
        candidate_id,
        expected_digest
    )
    WHERE gate_kind = 'gate2' AND status = 'pending';

CREATE UNIQUE INDEX IF NOT EXISTS
    ux_agent_v02_paper_gate_pending_gate3_target
    ON quant_system.agent_v02_paper_gate_challenges (
        owner_user_id,
        workspace_id,
        candidate_id,
        expected_digest,
        final_backtest_receipt_id,
        base_commit
    )
    WHERE gate_kind = 'gate3' AND status = 'pending';

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_paper_gate_actions (
    owner_user_id UUID NOT NULL
        REFERENCES quant_system.app_users(id),
    workspace_id TEXT NOT NULL,
    action_kind TEXT NOT NULL
        CHECK (
            action_kind IN (
                'gate1_formula_source_confirm',
                'gate2_candidate_review',
                'gate3_promotion_review_prepare'
            )
        ),
    client_action_id TEXT NOT NULL,
    action_digest CHAR(64) NOT NULL
        CHECK (action_digest ~ '^[0-9a-f]{64}$'),
    gate_id TEXT NOT NULL
        REFERENCES quant_system.agent_v02_paper_gate_challenges(gate_id),
    action_state TEXT NOT NULL
        CHECK (
            action_state IN (
                'executing',
                'retryable',
                'succeeded',
                'outcome_unknown',
                'failed'
            )
        ),
    attempt_count INTEGER NOT NULL DEFAULT 1
        CHECK (attempt_count BETWEEN 1 AND 1000),
    lease_token UUID,
    lease_until TIMESTAMPTZ,
    hqa_operation_id TEXT NOT NULL,
    hqa_receipt_ref TEXT,
    hqa_receipt_digest CHAR(64),
    receipt JSONB,
    last_error_code TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (
        owner_user_id,
        workspace_id,
        action_kind,
        client_action_id
    ),
    CONSTRAINT ck_agent_v02_paper_gate_action_workspace
        CHECK (
            char_length(workspace_id) BETWEEN 1 AND 200
            AND workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_paper_gate_action_id
        CHECK (
            char_length(client_action_id) BETWEEN 1 AND 200
            AND client_action_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_paper_gate_hqa_operation
        CHECK (
            hqa_operation_id ~ '^pgate-[0-9a-f]{32}$'
        ),
    CONSTRAINT ck_agent_v02_paper_gate_action_receipt_pair
        CHECK (
            (hqa_receipt_ref IS NULL) = (hqa_receipt_digest IS NULL)
            AND
            (hqa_receipt_digest IS NULL
                OR hqa_receipt_digest ~ '^[0-9a-f]{64}$')
        ),
    CONSTRAINT ck_agent_v02_paper_gate_action_error
        CHECK (
            last_error_code IS NULL
            OR (
                char_length(last_error_code) BETWEEN 1 AND 200
                AND last_error_code ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
            )
        ),
    CONSTRAINT ck_agent_v02_paper_gate_action_shape
        CHECK (
            (
                action_state = 'executing'
                AND lease_token IS NOT NULL
                AND lease_until IS NOT NULL
                AND receipt IS NULL
                AND hqa_receipt_ref IS NULL
                AND last_error_code IS NULL
            )
            OR
            (
                action_state = 'retryable'
                AND lease_token IS NULL
                AND lease_until IS NULL
                AND receipt IS NULL
                AND hqa_receipt_ref IS NULL
                AND last_error_code IS NOT NULL
            )
            OR
            (
                action_state = 'succeeded'
                AND lease_token IS NULL
                AND lease_until IS NULL
                AND receipt IS NOT NULL
                AND hqa_receipt_ref IS NOT NULL
                AND last_error_code IS NULL
            )
            OR
            (
                action_state IN ('outcome_unknown', 'failed')
                AND lease_token IS NULL
                AND lease_until IS NULL
                AND receipt IS NOT NULL
                AND last_error_code IS NOT NULL
            )
        )
);

CREATE INDEX IF NOT EXISTS ix_agent_v02_paper_gate_action_gate
    ON quant_system.agent_v02_paper_gate_actions (
        gate_id,
        created_at
    );

CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_v02_paper_gate_single_action
    ON quant_system.agent_v02_paper_gate_actions (gate_id);

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_paper_gate_completions (
    gate_id TEXT PRIMARY KEY
        REFERENCES quant_system.agent_v02_paper_gate_challenges(gate_id),
    owner_user_id UUID NOT NULL
        REFERENCES quant_system.app_users(id),
    workspace_id TEXT NOT NULL,
    task_ref TEXT NOT NULL,
    task_version BIGINT NOT NULL
        CHECK (task_version BETWEEN 1 AND 9223372036854775807),
    task_status TEXT NOT NULL CHECK (task_status = 'completed'),
    task_terminal_outcome TEXT NOT NULL
        CHECK (task_terminal_outcome = 'completed'),
    attempt_ref TEXT NOT NULL,
    attempt_status TEXT NOT NULL CHECK (attempt_status = 'completed'),
    attempt_terminal_outcome TEXT NOT NULL
        CHECK (attempt_terminal_outcome = 'completed'),
    domain_gate_ref TEXT NOT NULL,
    domain_gate_outcome TEXT NOT NULL
        CHECK (domain_gate_outcome = 'passed'),
    hqa_run_ref TEXT NOT NULL,
    provider_evidence_ref TEXT NOT NULL,
    promotion_id TEXT NOT NULL,
    reviewed_commit CHAR(40) NOT NULL,
    candidate_id TEXT NOT NULL,
    candidate_digest CHAR(64) NOT NULL,
    final_backtest_receipt_id TEXT NOT NULL,
    base_commit CHAR(40) NOT NULL,
    attempt_completion_operation_id TEXT NOT NULL,
    attempt_completion_event_id TEXT NOT NULL,
    task_completion_operation_id TEXT NOT NULL,
    task_completion_event_id TEXT NOT NULL,
    workflow_audit_status TEXT NOT NULL
        CHECK (workflow_audit_status = 'consistent'),
    workflow_audit_ref TEXT NOT NULL,
    workflow_audit_digest CHAR(64) NOT NULL,
    hqa_completion_receipt_ref TEXT NOT NULL UNIQUE,
    hqa_completion_receipt_digest CHAR(64) NOT NULL UNIQUE,
    completion_evidence JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_agent_v02_paper_completion_workspace
        CHECK (
            char_length(workspace_id) BETWEEN 1 AND 200
            AND workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_paper_completion_refs
        CHECK (
            task_ref ~ '^task:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
            AND attempt_ref
                ~ '^attempt:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
            AND domain_gate_ref
                ~ '^gate:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
            AND hqa_run_ref
                ~ '^run:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
            AND provider_evidence_ref
                ~ '^provider-evidence:[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$'
            AND promotion_id
                ~ '^promo-[0-9a-f]{32}(-r([2-9]|[1-9][0-9]+))?$'
            AND candidate_id
                ~ '^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
            AND final_backtest_receipt_id
                ~ '^backtest-[0-9a-f]{32}$'
            AND hqa_completion_receipt_ref
                ~ '^hqa-paper-completion:[0-9a-f]{32}$'
            AND workflow_audit_ref
                ~ '^workflow-audit:[0-9a-f]{64}$'
        ),
    CONSTRAINT ck_agent_v02_paper_completion_digests
        CHECK (
            reviewed_commit ~ '^[0-9a-f]{40}$'
            AND candidate_digest ~ '^[0-9a-f]{64}$'
            AND base_commit ~ '^[0-9a-f]{40}$'
            AND workflow_audit_digest ~ '^[0-9a-f]{64}$'
            AND workflow_audit_ref =
                'workflow-audit:' || workflow_audit_digest
            AND hqa_completion_receipt_digest ~ '^[0-9a-f]{64}$'
            AND hqa_completion_receipt_ref =
                'hqa-paper-completion:'
                || left(hqa_completion_receipt_digest, 32)
        ),
    CONSTRAINT ck_agent_v02_paper_completion_events
        CHECK (
            attempt_completion_operation_id
                ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$'
            AND task_completion_operation_id
                ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$'
            AND attempt_completion_event_id ~ '^event:[0-9a-f]{64}$'
            AND task_completion_event_id ~ '^event:[0-9a-f]{64}$'
            AND attempt_completion_operation_id
                <> task_completion_operation_id
            AND attempt_completion_event_id <> task_completion_event_id
        )
);

CREATE INDEX IF NOT EXISTS ix_agent_v02_paper_completion_workspace
    ON quant_system.agent_v02_paper_gate_completions (
        owner_user_id,
        workspace_id,
        task_ref,
        created_at
    );

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
     AND (
            (
                command.state = 'leased'
                AND command.dispatch_started_at IS NOT NULL
                AND command.hermes_session_id IS NULL
                AND command.hermes_run_id IS NULL
            )
            OR (
                command.state IN ('delivered', 'succeeded')
                AND command.hermes_session_id =
                        managed_session.hermes_session_id
                AND command.hermes_run_id = NEW.hermes_run_id
            )
         )
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
            'paper gate requires an exact active or succeeded Command on a ready web-managed Session';
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

    IF challenge.task_ref <> NEW.task_ref
       OR challenge.attempt_ref <> NEW.attempt_ref
       OR challenge.hqa_gate_ref <> NEW.domain_gate_ref
       OR challenge.hqa_run_ref <> NEW.hqa_run_ref
       OR challenge.promotion_id <> NEW.promotion_id
       OR challenge.candidate_id <> NEW.candidate_id
       OR challenge.expected_digest <> NEW.candidate_digest
       OR challenge.final_backtest_receipt_id
            <> NEW.final_backtest_receipt_id
       OR challenge.base_commit <> NEW.base_commit
       OR NEW.task_version <> challenge.expected_task_version + 4
       OR NEW.completion_evidence IS DISTINCT FROM jsonb_build_object(
            'schema_version', 'agent-v0.2-paper-completion/v1',
            'task_ref', NEW.task_ref,
            'task_version', NEW.task_version,
            'task_status', NEW.task_status,
            'task_terminal_outcome', NEW.task_terminal_outcome,
            'attempt_ref', NEW.attempt_ref,
            'attempt_status', NEW.attempt_status,
            'attempt_terminal_outcome', NEW.attempt_terminal_outcome,
            'domain_gate_ref', NEW.domain_gate_ref,
            'domain_gate_outcome', NEW.domain_gate_outcome,
            'hqa_run_ref', NEW.hqa_run_ref,
            'provider_evidence_ref', NEW.provider_evidence_ref,
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

CREATE OR REPLACE FUNCTION quant_system.guard_agent_v02_paper_gate_challenge()
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
       OR NEW.parent_gate_id IS DISTINCT FROM OLD.parent_gate_id
       OR NEW.source_file_ref IS DISTINCT FROM OLD.source_file_ref
       OR NEW.universe IS DISTINCT FROM OLD.universe
       OR NEW.reviewed_source_sha256 IS DISTINCT FROM OLD.reviewed_source_sha256
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

CREATE OR REPLACE FUNCTION quant_system.guard_agent_v02_paper_gate_action()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    IF NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.action_kind IS DISTINCT FROM OLD.action_kind
       OR NEW.client_action_id IS DISTINCT FROM OLD.client_action_id
       OR NEW.action_digest IS DISTINCT FROM OLD.action_digest
       OR NEW.gate_id IS DISTINCT FROM OLD.gate_id
       OR NEW.hqa_operation_id IS DISTINCT FROM OLD.hqa_operation_id
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
    THEN
        RAISE EXCEPTION 'paper gate action identity is immutable';
    END IF;
    IF OLD.receipt IS NOT NULL
       AND NEW.receipt IS DISTINCT FROM OLD.receipt
    THEN
        RAISE EXCEPTION 'paper gate action receipt is immutable';
    END IF;
    IF NEW.attempt_count < OLD.attempt_count
       OR NEW.attempt_count > OLD.attempt_count + 1
    THEN
        RAISE EXCEPTION 'paper gate action attempt counter is invalid';
    END IF;
    IF OLD.action_state IN ('succeeded', 'outcome_unknown', 'failed') THEN
        RAISE EXCEPTION 'terminal paper gate action is immutable';
    END IF;
    IF OLD.action_state = 'executing'
       AND OLD.lease_until > now()
       AND NEW.action_state = 'executing'
       AND NEW.lease_token IS DISTINCT FROM OLD.lease_token
    THEN
        RAISE EXCEPTION 'active paper gate action lease cannot be stolen';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION quant_system.reject_agent_v02_paper_gate_delete()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    RAISE EXCEPTION 'paper gate authority facts are append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_agent_v02_paper_gate_challenge_update
    ON quant_system.agent_v02_paper_gate_challenges;
DROP TRIGGER IF EXISTS trg_agent_v02_paper_gate_ready_session
    ON quant_system.agent_v02_paper_gate_challenges;
DROP TRIGGER IF EXISTS trg_agent_v02_paper_gate_challenge_delete
    ON quant_system.agent_v02_paper_gate_challenges;
DROP TRIGGER IF EXISTS trg_agent_v02_paper_gate_challenge_truncate
    ON quant_system.agent_v02_paper_gate_challenges;
CREATE TRIGGER trg_agent_v02_paper_gate_challenge_update
BEFORE UPDATE ON quant_system.agent_v02_paper_gate_challenges
FOR EACH ROW
EXECUTE FUNCTION quant_system.guard_agent_v02_paper_gate_challenge();
CREATE TRIGGER trg_agent_v02_paper_gate_ready_session
BEFORE INSERT OR UPDATE ON quant_system.agent_v02_paper_gate_challenges
FOR EACH ROW
EXECUTE FUNCTION quant_system.require_agent_v02_paper_gate_ready_session();
CREATE TRIGGER trg_agent_v02_paper_gate_challenge_delete
BEFORE DELETE ON quant_system.agent_v02_paper_gate_challenges
FOR EACH ROW
EXECUTE FUNCTION quant_system.reject_agent_v02_paper_gate_delete();
CREATE TRIGGER trg_agent_v02_paper_gate_challenge_truncate
BEFORE TRUNCATE ON quant_system.agent_v02_paper_gate_challenges
FOR EACH STATEMENT
EXECUTE FUNCTION quant_system.reject_agent_v02_paper_gate_delete();

DROP TRIGGER IF EXISTS trg_agent_v02_paper_gate_action_update
    ON quant_system.agent_v02_paper_gate_actions;
DROP TRIGGER IF EXISTS trg_agent_v02_paper_gate_action_delete
    ON quant_system.agent_v02_paper_gate_actions;
DROP TRIGGER IF EXISTS trg_agent_v02_paper_gate_action_truncate
    ON quant_system.agent_v02_paper_gate_actions;
CREATE TRIGGER trg_agent_v02_paper_gate_action_update
BEFORE UPDATE ON quant_system.agent_v02_paper_gate_actions
FOR EACH ROW
EXECUTE FUNCTION quant_system.guard_agent_v02_paper_gate_action();
CREATE TRIGGER trg_agent_v02_paper_gate_action_delete
BEFORE DELETE ON quant_system.agent_v02_paper_gate_actions
FOR EACH ROW
EXECUTE FUNCTION quant_system.reject_agent_v02_paper_gate_delete();
CREATE TRIGGER trg_agent_v02_paper_gate_action_truncate
BEFORE TRUNCATE ON quant_system.agent_v02_paper_gate_actions
FOR EACH STATEMENT
EXECUTE FUNCTION quant_system.reject_agent_v02_paper_gate_delete();

DROP TRIGGER IF EXISTS trg_agent_v02_paper_completion_binding
    ON quant_system.agent_v02_paper_gate_completions;
DROP TRIGGER IF EXISTS trg_agent_v02_paper_completion_update
    ON quant_system.agent_v02_paper_gate_completions;
DROP TRIGGER IF EXISTS trg_agent_v02_paper_completion_delete
    ON quant_system.agent_v02_paper_gate_completions;
DROP TRIGGER IF EXISTS trg_agent_v02_paper_completion_truncate
    ON quant_system.agent_v02_paper_gate_completions;
CREATE TRIGGER trg_agent_v02_paper_completion_binding
BEFORE INSERT ON quant_system.agent_v02_paper_gate_completions
FOR EACH ROW
EXECUTE FUNCTION quant_system.require_agent_v02_paper_completion_binding();
CREATE TRIGGER trg_agent_v02_paper_completion_update
BEFORE UPDATE ON quant_system.agent_v02_paper_gate_completions
FOR EACH ROW
EXECUTE FUNCTION quant_system.reject_agent_v02_paper_gate_delete();
CREATE TRIGGER trg_agent_v02_paper_completion_delete
BEFORE DELETE ON quant_system.agent_v02_paper_gate_completions
FOR EACH ROW
EXECUTE FUNCTION quant_system.reject_agent_v02_paper_gate_delete();
CREATE TRIGGER trg_agent_v02_paper_completion_truncate
BEFORE TRUNCATE ON quant_system.agent_v02_paper_gate_completions
FOR EACH STATEMENT
EXECUTE FUNCTION quant_system.reject_agent_v02_paper_gate_delete();

ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ENABLE ALWAYS TRIGGER trg_agent_v02_paper_gate_challenge_update;
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ENABLE ALWAYS TRIGGER trg_agent_v02_paper_gate_ready_session;
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ENABLE ALWAYS TRIGGER trg_agent_v02_paper_gate_challenge_delete;
ALTER TABLE quant_system.agent_v02_paper_gate_challenges
    ENABLE ALWAYS TRIGGER trg_agent_v02_paper_gate_challenge_truncate;
ALTER TABLE quant_system.agent_v02_paper_gate_actions
    ENABLE ALWAYS TRIGGER trg_agent_v02_paper_gate_action_update;
ALTER TABLE quant_system.agent_v02_paper_gate_actions
    ENABLE ALWAYS TRIGGER trg_agent_v02_paper_gate_action_delete;
ALTER TABLE quant_system.agent_v02_paper_gate_actions
    ENABLE ALWAYS TRIGGER trg_agent_v02_paper_gate_action_truncate;
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ENABLE ALWAYS TRIGGER trg_agent_v02_paper_completion_binding;
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ENABLE ALWAYS TRIGGER trg_agent_v02_paper_completion_update;
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ENABLE ALWAYS TRIGGER trg_agent_v02_paper_completion_delete;
ALTER TABLE quant_system.agent_v02_paper_gate_completions
    ENABLE ALWAYS TRIGGER trg_agent_v02_paper_completion_truncate;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_readonly')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator')
    THEN
        GRANT USAGE ON SCHEMA quant_system
            TO quant_runtime, quant_readonly, quant_migrator;
        REVOKE CREATE ON SCHEMA quant_system
            FROM quant_runtime, quant_readonly;
        FOREACH table_name IN ARRAY ARRAY[
            'agent_v02_paper_gate_challenges',
            'agent_v02_paper_gate_actions',
            'agent_v02_paper_gate_completions'
        ]
        LOOP
            EXECUTE format(
                'ALTER TABLE quant_system.%I ENABLE ROW LEVEL SECURITY',
                table_name
            );
            EXECUTE format(
                'ALTER TABLE quant_system.%I FORCE ROW LEVEL SECURITY',
                table_name
            );
            EXECUTE format(
                'DROP POLICY IF EXISTS v4r_root_scope ON quant_system.%I',
                table_name
            );
            EXECUTE format(
                'CREATE POLICY v4r_root_scope ON quant_system.%I '
                'FOR ALL TO quant_runtime, quant_readonly '
                'USING (owner_user_id = '
                '''00000000-0000-0000-0000-000000000001''::uuid) '
                'WITH CHECK (owner_user_id = '
                '''00000000-0000-0000-0000-000000000001''::uuid)',
                table_name
            );
            EXECUTE format(
                'DROP POLICY IF EXISTS v4r_migrator_all ON quant_system.%I',
                table_name
            );
            EXECUTE format(
                'CREATE POLICY v4r_migrator_all ON quant_system.%I '
                'FOR ALL TO quant_migrator USING (true) WITH CHECK (true)',
                table_name
            );
        END LOOP;

        GRANT SELECT, INSERT, UPDATE
            ON quant_system.agent_v02_paper_gate_challenges,
               quant_system.agent_v02_paper_gate_actions
            TO quant_runtime;
        GRANT SELECT, INSERT
            ON quant_system.agent_v02_paper_gate_completions
            TO quant_runtime;
        GRANT SELECT
            ON quant_system.agent_v02_paper_gate_challenges,
               quant_system.agent_v02_paper_gate_actions,
               quant_system.agent_v02_paper_gate_completions,
               quant_system.agent_v02_paper_gate_meta
            TO quant_readonly;
        GRANT SELECT
            ON quant_system.agent_v02_paper_gate_meta
            TO quant_runtime;
        REVOKE DELETE, TRUNCATE
            ON quant_system.agent_v02_paper_gate_challenges,
               quant_system.agent_v02_paper_gate_actions,
               quant_system.agent_v02_paper_gate_completions
            FROM quant_runtime;
        REVOKE UPDATE
            ON quant_system.agent_v02_paper_gate_completions
            FROM quant_runtime;
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE
            ON quant_system.agent_v02_paper_gate_meta
            FROM quant_runtime;
        REVOKE ALL
            ON quant_system.agent_v02_paper_gate_challenges,
               quant_system.agent_v02_paper_gate_actions,
               quant_system.agent_v02_paper_gate_completions,
               quant_system.agent_v02_paper_gate_meta
            FROM PUBLIC;
        GRANT ALL
            ON quant_system.agent_v02_paper_gate_challenges,
               quant_system.agent_v02_paper_gate_actions,
               quant_system.agent_v02_paper_gate_completions,
               quant_system.agent_v02_paper_gate_meta
            TO quant_migrator;

        ALTER TABLE quant_system.agent_v02_paper_gate_challenges
            OWNER TO quant_migrator;
        ALTER TABLE quant_system.agent_v02_paper_gate_actions
            OWNER TO quant_migrator;
        ALTER TABLE quant_system.agent_v02_paper_gate_completions
            OWNER TO quant_migrator;
        ALTER TABLE quant_system.agent_v02_paper_gate_meta
            OWNER TO quant_migrator;
        ALTER FUNCTION quant_system.guard_agent_v02_paper_gate_challenge()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.require_agent_v02_paper_gate_ready_session()
            OWNER TO quant_migrator;
        ALTER FUNCTION quant_system.guard_agent_v02_paper_gate_action()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.require_agent_v02_paper_completion_binding()
            OWNER TO quant_migrator;
        ALTER FUNCTION quant_system.reject_agent_v02_paper_gate_delete()
            OWNER TO quant_migrator;
    END IF;
END $$;

COMMIT;
