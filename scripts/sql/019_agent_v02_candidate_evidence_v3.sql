-- Agent v0.2 candidate evidence v3.
--
-- The old release-evidence JSON remains a sealed attachment, but it is not an
-- authority for real-flow truth.  This migration adds:
--   * append-only, live-Hermes restart observations; and
--   * one append-only verified fact set for each candidate admission.
--
-- Candidate acceptance and the final release stamp must bind the exact
-- verified fact set.  No table stores prompts, message bodies, provider
-- credentials, or trading payloads.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:019_agent_v02_candidate_evidence_v3', 0)
);

CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_candidate_evidence_meta (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO quant_system.agent_v02_candidate_evidence_meta (
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
    FROM quant_system.agent_v02_candidate_evidence_meta
    WHERE singleton IS TRUE;

    IF installed_version <> 1 THEN
        RAISE EXCEPTION
            'Candidate evidence schema version % is incompatible with this binary (expected 1)',
            installed_version;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS
quant_system.agent_v02_candidate_restart_observations (
    observation_id TEXT PRIMARY KEY,
    owner_user_id UUID NOT NULL
        REFERENCES quant_system.app_users(id),
    workspace_id TEXT NOT NULL,
    admission_id TEXT NOT NULL
        REFERENCES quant_system.agent_v02_candidate_admissions(admission_id),
    admission_digest CHAR(64) NOT NULL,
    phase TEXT NOT NULL CHECK (phase IN ('before', 'after')),
    platform_session_id TEXT NOT NULL
        REFERENCES quant_system.hermes_workspace_sessions(platform_session_id),
    hermes_session_id TEXT NOT NULL,
    runtime_instance_id CHAR(32) NOT NULL,
    runtime_started_at TIMESTAMPTZ NOT NULL,
    transcript_digest CHAR(64) NOT NULL,
    message_count INTEGER NOT NULL CHECK (message_count >= 4),
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (admission_id, phase),
    CONSTRAINT ck_agent_v02_candidate_restart_observation_id
        CHECK (
            char_length(observation_id) BETWEEN 1 AND 200
            AND observation_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_candidate_restart_workspace
        CHECK (
            char_length(workspace_id) BETWEEN 1 AND 200
            AND workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_candidate_restart_admission_digest
        CHECK (admission_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_candidate_restart_hermes_session
        CHECK (
            char_length(hermes_session_id) BETWEEN 1 AND 255
            AND hermes_session_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_candidate_restart_instance
        CHECK (runtime_instance_id ~ '^[0-9a-f]{32}$'),
    CONSTRAINT ck_agent_v02_candidate_restart_transcript
        CHECK (transcript_digest ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_candidate_evidence_sets (
    evidence_set_id TEXT PRIMARY KEY,
    owner_user_id UUID NOT NULL
        REFERENCES quant_system.app_users(id),
    workspace_id TEXT NOT NULL,
    admission_id TEXT NOT NULL UNIQUE
        REFERENCES quant_system.agent_v02_candidate_admissions(admission_id),
    admission_digest CHAR(64) NOT NULL,
    platform_runtime_digest CHAR(64) NOT NULL,
    hqa_runtime_digest CHAR(64) NOT NULL,
    hermes_runtime_digest CHAR(64) NOT NULL,
    database_schema_fingerprint CHAR(64) NOT NULL,
    baseline_order_snapshot_digest CHAR(64) NOT NULL,
    final_order_snapshot_digest CHAR(64) NOT NULL,
    facts JSONB NOT NULL,
    facts_digest CHAR(64) NOT NULL UNIQUE,
    verified_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_agent_v02_candidate_evidence_set_id
        CHECK (
            char_length(evidence_set_id) BETWEEN 1 AND 200
            AND evidence_set_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_candidate_evidence_workspace
        CHECK (
            char_length(workspace_id) BETWEEN 1 AND 200
            AND workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_candidate_evidence_digests
        CHECK (
            admission_digest ~ '^[0-9a-f]{64}$'
            AND platform_runtime_digest ~ '^[0-9a-f]{64}$'
            AND hqa_runtime_digest ~ '^[0-9a-f]{64}$'
            AND hermes_runtime_digest ~ '^[0-9a-f]{64}$'
            AND database_schema_fingerprint ~ '^[0-9a-f]{64}$'
            AND baseline_order_snapshot_digest ~ '^[0-9a-f]{64}$'
            AND final_order_snapshot_digest ~ '^[0-9a-f]{64}$'
            AND facts_digest ~ '^[0-9a-f]{64}$'
        ),
    CONSTRAINT ck_agent_v02_candidate_evidence_zero_order
        CHECK (
            final_order_snapshot_digest =
            baseline_order_snapshot_digest
        ),
    CONSTRAINT ck_agent_v02_candidate_evidence_facts
        CHECK (
            jsonb_typeof(facts) = 'object'
            AND facts->>'contract' =
                'agent-v0.2-candidate-evidence-facts/v1'
        )
);

ALTER TABLE quant_system.agent_v02_candidate_admissions
    ADD COLUMN IF NOT EXISTS evidence_set_id TEXT;
ALTER TABLE quant_system.agent_v02_candidate_admissions
    ADD COLUMN IF NOT EXISTS evidence_set_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_candidate_admissions
    ADD COLUMN IF NOT EXISTS final_order_snapshot_digest CHAR(64);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_agent_v02_candidate_verified_evidence_set'
          AND conrelid =
              'quant_system.agent_v02_candidate_admissions'::regclass
    ) THEN
        ALTER TABLE quant_system.agent_v02_candidate_admissions
            ADD CONSTRAINT fk_agent_v02_candidate_verified_evidence_set
            FOREIGN KEY (evidence_set_id)
            REFERENCES quant_system.agent_v02_candidate_evidence_sets(
                evidence_set_id
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_agent_v02_candidate_evidence_binding'
          AND conrelid =
              'quant_system.agent_v02_candidate_admissions'::regclass
    ) THEN
        ALTER TABLE quant_system.agent_v02_candidate_admissions
            ADD CONSTRAINT ck_agent_v02_candidate_evidence_binding
            CHECK (
                (
                    status = 'accepted'
                    AND evidence_set_id IS NOT NULL
                    AND evidence_set_digest
                        ~ '^[0-9a-f]{64}$'
                    AND final_order_snapshot_digest
                        ~ '^[0-9a-f]{64}$'
                )
                OR
                (
                    status <> 'accepted'
                    AND evidence_set_id IS NULL
                    AND evidence_set_digest IS NULL
                    AND final_order_snapshot_digest IS NULL
                )
            );
    END IF;
END $$;

CREATE OR REPLACE FUNCTION
quant_system.reject_agent_v02_candidate_evidence_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    RAISE EXCEPTION 'Agent v0.2 candidate evidence is append-only';
END;
$$;

CREATE OR REPLACE FUNCTION
quant_system.guard_agent_v02_candidate_restart_observation()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    candidate_row RECORD;
    session_row RECORD;
BEGIN
    SELECT
        owner_user_id,
        workspace_id,
        admission_digest,
        status,
        expires_at
    INTO candidate_row
    FROM quant_system.agent_v02_candidate_admissions
    WHERE admission_id = NEW.admission_id;

    IF candidate_row IS NULL
       OR candidate_row.owner_user_id IS DISTINCT FROM NEW.owner_user_id
       OR candidate_row.workspace_id IS DISTINCT FROM NEW.workspace_id
       OR candidate_row.admission_digest
            IS DISTINCT FROM NEW.admission_digest
       OR candidate_row.status <> 'open'
       OR candidate_row.expires_at <= clock_timestamp()
    THEN
        RAISE EXCEPTION
            'restart observation requires its exact active candidate';
    END IF;

    SELECT
        owner_user_id,
        workspace_id,
        hermes_session_id,
        candidate_admission_id,
        kind,
        provision_state
    INTO session_row
    FROM quant_system.hermes_workspace_sessions
    WHERE platform_session_id = NEW.platform_session_id;

    IF session_row IS NULL
       OR session_row.owner_user_id IS DISTINCT FROM NEW.owner_user_id
       OR session_row.workspace_id IS DISTINCT FROM NEW.workspace_id
       OR session_row.hermes_session_id
            IS DISTINCT FROM NEW.hermes_session_id
       OR session_row.candidate_admission_id
            IS DISTINCT FROM NEW.admission_id
       OR session_row.kind <> 'web_managed_session'
       OR session_row.provision_state <> 'ready'
    THEN
        RAISE EXCEPTION
            'restart observation requires its exact ready candidate session';
    END IF;

    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION
quant_system.guard_agent_v02_candidate_evidence_set()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    candidate_row RECORD;
    before_row RECORD;
    after_row RECORD;
    flows JSONB;
    web_flow JSONB;
    restart_flow JSONB;
    fork_flow JSONB;
    options_flow JSONB;
    paper_flow JSONB;
    matched_count INTEGER;
    expected_facts_digest TEXT;
BEGIN
    SELECT *
    INTO candidate_row
    FROM quant_system.agent_v02_candidate_admissions
    WHERE admission_id = NEW.admission_id
    FOR UPDATE;

    IF candidate_row IS NULL
       OR candidate_row.owner_user_id IS DISTINCT FROM NEW.owner_user_id
       OR candidate_row.workspace_id IS DISTINCT FROM NEW.workspace_id
       OR candidate_row.admission_digest
            IS DISTINCT FROM NEW.admission_digest
       OR candidate_row.status <> 'open'
       OR candidate_row.expires_at <= clock_timestamp()
       OR candidate_row.platform_runtime_digest
            IS DISTINCT FROM NEW.platform_runtime_digest
       OR candidate_row.hqa_runtime_digest
            IS DISTINCT FROM NEW.hqa_runtime_digest
       OR candidate_row.hermes_runtime_digest
            IS DISTINCT FROM NEW.hermes_runtime_digest
       OR candidate_row.database_schema_fingerprint
            IS DISTINCT FROM NEW.database_schema_fingerprint
       OR candidate_row.baseline_order_snapshot_digest
            IS DISTINCT FROM NEW.baseline_order_snapshot_digest
       OR NEW.final_order_snapshot_digest
            IS DISTINCT FROM candidate_row.baseline_order_snapshot_digest
    THEN
        RAISE EXCEPTION
            'verified evidence requires its exact active candidate and zero-order snapshot';
    END IF;

    SELECT *
    INTO before_row
    FROM quant_system.agent_v02_candidate_restart_observations
    WHERE admission_id = NEW.admission_id
      AND phase = 'before';
    SELECT *
    INTO after_row
    FROM quant_system.agent_v02_candidate_restart_observations
    WHERE admission_id = NEW.admission_id
      AND phase = 'after';

    IF before_row IS NULL
       OR after_row IS NULL
       OR before_row.platform_session_id
            IS DISTINCT FROM after_row.platform_session_id
       OR before_row.hermes_session_id
            IS DISTINCT FROM after_row.hermes_session_id
       OR before_row.transcript_digest
            IS DISTINCT FROM after_row.transcript_digest
       OR before_row.runtime_instance_id =
            after_row.runtime_instance_id
       OR before_row.runtime_started_at >=
            after_row.runtime_started_at
       OR before_row.observed_at >= after_row.observed_at
    THEN
        RAISE EXCEPTION
            'verified evidence requires a real stable-transcript Hermes restart';
    END IF;

    expected_facts_digest := encode(
        sha256(convert_to(NEW.facts::text, 'UTF8')),
        'hex'
    );
    flows := NEW.facts->'flows';
    IF NEW.facts_digest IS DISTINCT FROM expected_facts_digest
       OR NEW.evidence_set_id IS DISTINCT FROM
            'evidence_' || substring(expected_facts_digest FROM 1 FOR 32)
       OR jsonb_typeof(NEW.facts) <> 'object'
       OR (
            SELECT count(*)
            FROM jsonb_object_keys(NEW.facts)
       ) <> 8
       OR NEW.facts->>'contract' <>
            'agent-v0.2-candidate-evidence-facts/v1'
       OR NEW.facts->>'admission_id' IS DISTINCT FROM NEW.admission_id
       OR NEW.facts->>'admission_digest'
            IS DISTINCT FROM NEW.admission_digest
       OR NEW.facts->>'workspace_id' IS DISTINCT FROM NEW.workspace_id
       OR NEW.facts->>'database_schema_fingerprint'
            IS DISTINCT FROM NEW.database_schema_fingerprint
       OR NEW.facts->>'final_order_snapshot_digest'
            IS DISTINCT FROM NEW.final_order_snapshot_digest
       OR jsonb_typeof(NEW.facts->'runtime') <> 'object'
       OR (
            SELECT count(*)
            FROM jsonb_object_keys(NEW.facts->'runtime')
       ) <> 3
       OR NEW.facts->'runtime'->>'platform'
            IS DISTINCT FROM NEW.platform_runtime_digest
       OR NEW.facts->'runtime'->>'hqa'
            IS DISTINCT FROM NEW.hqa_runtime_digest
       OR NEW.facts->'runtime'->>'hermes'
            IS DISTINCT FROM NEW.hermes_runtime_digest
       OR jsonb_typeof(flows) <> 'object'
       OR (
            SELECT count(*)
            FROM jsonb_object_keys(flows)
       ) <> 5
       OR NOT (
            flows ?&
            ARRAY[
                'web_chat_multi_turn',
                'hermes_restart_recovery',
                'exact_message_fork',
                'options_vertical_live_futu_ro',
                'paper_factor_gate_1_2_3_via_hermes'
            ]::TEXT[]
       )
       OR EXISTS (
            SELECT 1
            FROM jsonb_each(flows) AS flow_item
            WHERE jsonb_typeof(flow_item.value) <> 'object'
       )
    THEN
        RAISE EXCEPTION
            'verified evidence requires an exact content-addressed five-flow fact set';
    END IF;

    web_flow := flows->'web_chat_multi_turn';
    restart_flow := flows->'hermes_restart_recovery';
    fork_flow := flows->'exact_message_fork';
    options_flow := flows->'options_vertical_live_futu_ro';
    paper_flow := flows->'paper_factor_gate_1_2_3_via_hermes';

    IF web_flow->>'route' <> '/hermes'
       OR web_flow->>'platform_session_id'
            IS DISTINCT FROM before_row.platform_session_id
       OR web_flow->>'hermes_session_id'
            IS DISTINCT FROM before_row.hermes_session_id
       OR web_flow->>'transcript_digest'
            IS DISTINCT FROM before_row.transcript_digest
       OR COALESCE(web_flow->>'message_count', '') !~ '^[0-9]+$'
       OR COALESCE(web_flow->>'user_message_count', '') !~ '^[0-9]+$'
       OR COALESCE(web_flow->>'assistant_message_count', '') !~ '^[0-9]+$'
       OR jsonb_typeof(web_flow->'command_ids') <> 'array'
       OR jsonb_typeof(web_flow->'run_ids') <> 'array'
       OR jsonb_typeof(web_flow->'terminal_event_ids') <> 'array'
    THEN
        RAISE EXCEPTION
            'verified evidence web flow does not bind the restart transcript';
    END IF;
    IF (web_flow->>'message_count')::INTEGER < 4
       OR (web_flow->>'user_message_count')::INTEGER < 2
       OR (web_flow->>'assistant_message_count')::INTEGER < 2
       OR jsonb_array_length(web_flow->'command_ids') < 2
       OR jsonb_array_length(web_flow->'command_ids') <>
            jsonb_array_length(web_flow->'run_ids')
       OR jsonb_array_length(web_flow->'command_ids') <>
            jsonb_array_length(web_flow->'terminal_event_ids')
    THEN
        RAISE EXCEPTION
            'verified evidence web flow requires two complete durable turns';
    END IF;

    SELECT count(DISTINCT command.command_id::text)
    INTO matched_count
    FROM quant_system.hermes_commands AS command
    JOIN quant_system.hermes_command_events AS event
      ON event.command_id = command.command_id
     AND event.to_state = 'succeeded'
     AND event.hermes_session_id = command.hermes_session_id
     AND event.hermes_run_id = command.hermes_run_id
    WHERE command.owner_user_id = NEW.owner_user_id
      AND command.platform_session_id = before_row.platform_session_id
      AND command.hermes_session_id = before_row.hermes_session_id
      AND command.candidate_admission_id = NEW.admission_id
      AND command.kind = 'conversation_turn'
      AND command.state = 'succeeded'
      AND command.command_id::text IN (
          SELECT jsonb_array_elements_text(web_flow->'command_ids')
      )
      AND command.hermes_run_id IN (
          SELECT jsonb_array_elements_text(web_flow->'run_ids')
      )
      AND event.event_id::text IN (
          SELECT jsonb_array_elements_text(
              web_flow->'terminal_event_ids'
          )
      );
    IF matched_count <> jsonb_array_length(web_flow->'command_ids') THEN
        RAISE EXCEPTION
            'verified evidence web flow does not match canonical command events';
    END IF;

    IF restart_flow->>'route' <> '/hermes'
       OR restart_flow->>'platform_session_id'
            IS DISTINCT FROM before_row.platform_session_id
       OR restart_flow->>'hermes_session_id'
            IS DISTINCT FROM before_row.hermes_session_id
       OR restart_flow->>'before_observation_id'
            IS DISTINCT FROM before_row.observation_id
       OR restart_flow->>'after_observation_id'
            IS DISTINCT FROM after_row.observation_id
       OR restart_flow->>'pre_restart_instance_id'
            IS DISTINCT FROM before_row.runtime_instance_id
       OR restart_flow->>'post_restart_instance_id'
            IS DISTINCT FROM after_row.runtime_instance_id
       OR restart_flow->>'transcript_digest'
            IS DISTINCT FROM before_row.transcript_digest
       OR restart_flow->>'message_count'
            IS DISTINCT FROM before_row.message_count::TEXT
    THEN
        RAISE EXCEPTION
            'verified evidence restart flow does not match durable observations';
    END IF;

    IF fork_flow->>'route' <> '/hermes'
       OR fork_flow->>'source_channel' <> 'discord'
       OR NOT EXISTS (
            SELECT 1
            FROM quant_system.hermes_workspace_sessions AS source
            JOIN quant_system.hermes_workspace_sessions AS child
              ON child.parent_platform_session_id =
                    source.platform_session_id
             AND child.owner_user_id = source.owner_user_id
             AND child.workspace_id = source.workspace_id
            WHERE source.owner_user_id = NEW.owner_user_id
              AND source.workspace_id = NEW.workspace_id
              AND source.platform_session_id =
                    fork_flow->>'source_platform_session_id'
              AND source.hermes_session_id =
                    fork_flow->>'source_hermes_session_id'
              AND source.kind = 'observed_external_session'
              AND source.source_channel = 'discord'
              AND child.platform_session_id =
                    fork_flow->>'child_platform_session_id'
              AND child.hermes_session_id =
                    fork_flow->>'child_hermes_session_id'
              AND child.candidate_admission_id = NEW.admission_id
              AND child.kind = 'web_managed_session'
              AND child.provision_state = 'ready'
              AND child.fork_point = fork_flow->>'fork_point'
              AND child.provisioning_receipt_digest =
                    fork_flow->>'provisioning_receipt_digest'
       )
    THEN
        RAISE EXCEPTION
            'verified evidence fork flow does not match canonical lineage';
    END IF;

    IF options_flow->>'route' <> '/hermes'
       OR options_flow->>'provider' <> 'futu'
       OR options_flow->>'sample_or_real' <> 'real'
       OR options_flow->>'orders_created' <> '0'
       OR options_flow->>'admission_digest'
            IS DISTINCT FROM NEW.admission_digest
       OR NOT EXISTS (
            SELECT 1
            FROM quant_system.agent_v02_vertical_a_requests AS request
            JOIN quant_system.agent_v02_vertical_a_claims AS claim
              ON claim.request_id = request.request_id
             AND claim.admission_id = request.admission_id
            JOIN
                quant_system.agent_v02_vertical_a_zero_order_observations
                AS zero
              ON zero.claim_id = claim.claim_id
            JOIN
                quant_system.agent_v02_vertical_a_provider_receipts
                AS provider
              ON provider.claim_id = claim.claim_id
             AND provider.capture_digest = zero.capture_digest
            JOIN quant_system.agent_v02_vertical_a_results AS result
              ON result.request_id = request.request_id
             AND result.claim_id = claim.claim_id
             AND result.provider_receipt_id =
                    provider.provider_receipt_id
            JOIN quant_system.agent_v02_vertical_a_outcomes AS outcome
              ON outcome.request_id = request.request_id
             AND outcome.claim_id = claim.claim_id
             AND outcome.result_id = result.result_id
            WHERE request.owner_user_id = NEW.owner_user_id
              AND request.workspace_id = NEW.workspace_id
              AND request.admission_id = NEW.admission_id
              AND request.request_id = options_flow->>'request_id'
              AND claim.claim_id = options_flow->>'claim_id'
              AND claim.command_id::text = options_flow->>'command_id'
              AND claim.platform_session_id =
                    options_flow->>'platform_session_id'
              AND claim.hermes_session_id =
                    options_flow->>'hermes_session_id'
              AND claim.hermes_run_id =
                    options_flow->>'hermes_run_id'
              AND zero.capture_digest =
                    options_flow->>'capture_digest'
              AND zero.orders_created = 0
              AND zero.delta_zero IS TRUE
              AND zero.begin_snapshot_digest =
                    zero.end_snapshot_digest
              AND provider.provider = 'futu'
              AND provider.provider_receipt_id =
                    options_flow->>'provider_receipt_id'
              AND provider.provider_request_id =
                    options_flow->>'provider_request_id'
              AND provider.receipt_digest =
                    options_flow->>'provider_receipt_digest'
              AND result.result_id = options_flow->>'result_id'
              AND result.public_payload_digest =
                    options_flow->>'result_payload_digest'
              AND result.status = 'completed'
              AND result.sample_or_real = 'real'
              AND outcome.status = 'completed'
       )
    THEN
        RAISE EXCEPTION
            'verified evidence options flow does not match canonical authorities';
    END IF;

    IF paper_flow->>'route' <> '/hermes'
       OR paper_flow->>'provider' <> 'futu'
       OR paper_flow->>'orders_created' <> '0'
       OR paper_flow->>'workflow_audit_status' <> 'consistent'
       OR paper_flow->>'task_status' <> 'completed'
       OR paper_flow->>'task_terminal_outcome' <> 'completed'
       OR paper_flow->>'attempt_status' <> 'completed'
       OR paper_flow->>'attempt_terminal_outcome' <> 'completed'
       OR paper_flow->>'domain_gate_outcome' <> 'passed'
       OR NOT EXISTS (
            SELECT 1
            FROM
                quant_system.agent_v02_paper_gate_challenges AS gate3
            JOIN
                quant_system.agent_v02_paper_gate_challenges AS gate2
              ON gate2.gate_id = gate3.parent_gate_id
             AND gate2.gate_kind = 'gate2'
             AND gate2.status = 'reviewed'
            JOIN
                quant_system.agent_v02_paper_gate_challenges AS gate1
              ON gate1.gate_id = gate2.parent_gate_id
             AND gate1.gate_kind = 'gate1'
             AND gate1.status = 'confirmed'
            JOIN quant_system.hermes_workspace_sessions AS session
              ON session.platform_session_id =
                    gate3.platform_session_id
             AND session.candidate_admission_id = NEW.admission_id
             AND session.kind = 'web_managed_session'
             AND session.provision_state = 'ready'
            JOIN quant_system.hermes_commands AS command1
              ON command1.command_id = gate1.command_id
             AND command1.command_id::text =
                    paper_flow->>'gate1_command_id'
             AND command1.platform_session_id =
                    gate3.platform_session_id
             AND command1.hermes_session_id =
                    session.hermes_session_id
             AND command1.hermes_run_id = gate1.hermes_run_id
             AND command1.candidate_admission_id = NEW.admission_id
             AND command1.state = 'succeeded'
            JOIN quant_system.hermes_commands AS command2
              ON command2.command_id = gate2.command_id
             AND command2.command_id::text =
                    paper_flow->>'gate2_command_id'
             AND command2.platform_session_id =
                    gate3.platform_session_id
             AND command2.hermes_session_id =
                    session.hermes_session_id
             AND command2.hermes_run_id = gate2.hermes_run_id
             AND command2.candidate_admission_id = NEW.admission_id
             AND command2.state = 'succeeded'
            JOIN quant_system.hermes_commands AS command3
              ON command3.command_id = gate3.command_id
             AND command3.command_id::text =
                    paper_flow->>'gate3_command_id'
             AND command3.command_id::text =
                    paper_flow->>'command_id'
             AND command3.platform_session_id =
                    gate3.platform_session_id
             AND command3.hermes_session_id =
                    session.hermes_session_id
             AND command3.hermes_run_id = gate3.hermes_run_id
             AND command3.candidate_admission_id = NEW.admission_id
             AND command3.state = 'succeeded'
            JOIN quant_system.agent_v02_paper_gate_completions AS completion
              ON completion.gate_id = gate3.gate_id
             AND completion.owner_user_id = gate3.owner_user_id
             AND completion.workspace_id = gate3.workspace_id
             AND completion.task_ref = gate3.task_ref
             AND completion.attempt_ref = gate3.attempt_ref
             AND completion.domain_gate_ref = gate3.hqa_gate_ref
             AND completion.hqa_run_ref = gate3.hqa_run_ref
             AND completion.promotion_id = gate3.promotion_id
             AND completion.candidate_id = gate3.candidate_id
             AND completion.candidate_digest = gate3.expected_digest
             AND completion.final_backtest_receipt_id =
                    gate3.final_backtest_receipt_id
             AND completion.base_commit = gate3.base_commit
            WHERE gate3.owner_user_id = NEW.owner_user_id
              AND gate3.workspace_id = NEW.workspace_id
              AND gate3.gate_id = paper_flow->>'gate3_id'
              AND gate3.hqa_gate_ref =
                    paper_flow->>'gate3_hqa_ref'
              AND gate3.status = 'prepared'
              AND gate2.gate_id = paper_flow->>'gate2_id'
              AND gate2.hqa_gate_ref =
                    paper_flow->>'gate2_hqa_ref'
              AND gate1.gate_id = paper_flow->>'gate1_id'
              AND gate1.hqa_gate_ref =
                    paper_flow->>'gate1_hqa_ref'
              AND gate1.gate1_confirmation_id =
                    paper_flow->>'gate1_confirmation_id'
              AND gate1.reviewed_source_sha256 =
                    paper_flow->>'gate1_source_digest'
              AND gate2.candidate_id =
                    paper_flow->>'candidate_id'
              AND gate2.expected_digest =
                    paper_flow->>'candidate_digest'
              AND gate3.final_backtest_receipt_id =
                    paper_flow->>'final_backtest_receipt_id'
              AND gate3.promotion_id =
                    paper_flow->>'promotion_id'
              AND gate3.task_ref = paper_flow->>'task_ref'
              AND gate1.attempt_ref =
                    paper_flow->>'gate1_attempt_ref'
              AND gate2.attempt_ref =
                    paper_flow->>'gate2_attempt_ref'
              AND gate3.attempt_ref =
                    paper_flow->>'gate3_attempt_ref'
              AND gate3.attempt_ref = paper_flow->>'attempt_ref'
              AND gate1.attempt_ref = gate2.attempt_ref
              AND gate3.attempt_ref <> gate2.attempt_ref
              AND gate1.hqa_gate_ref = gate2.hqa_gate_ref
              AND gate1.hermes_session_id =
                    session.hermes_session_id
              AND gate2.hermes_session_id =
                    session.hermes_session_id
              AND gate3.hermes_session_id =
                    session.hermes_session_id
              AND gate1.hermes_run_id =
                    paper_flow->>'gate1_hermes_run_id'
              AND gate2.hermes_run_id =
                    paper_flow->>'gate2_hermes_run_id'
              AND gate3.hermes_run_id =
                    paper_flow->>'gate3_hermes_run_id'
              AND gate3.hermes_run_id =
                    paper_flow->>'hermes_run_id'
              AND gate3.hermes_run_id <> gate2.hermes_run_id
              AND gate3.hqa_run_ref =
                    paper_flow->>'hqa_run_ref'
              AND completion.reviewed_commit =
                    paper_flow->>'reviewed_commit'
              AND completion.hqa_completion_receipt_ref =
                    paper_flow->>'completion_receipt_ref'
              AND completion.hqa_completion_receipt_digest =
                    paper_flow->>'completion_receipt_digest'
              AND completion.task_version =
                    (paper_flow->>'task_version')::bigint
              AND completion.task_status =
                    paper_flow->>'task_status'
              AND completion.task_terminal_outcome =
                    paper_flow->>'task_terminal_outcome'
              AND completion.attempt_status =
                    paper_flow->>'attempt_status'
              AND completion.attempt_terminal_outcome =
                    paper_flow->>'attempt_terminal_outcome'
              AND completion.domain_gate_outcome =
                    paper_flow->>'domain_gate_outcome'
              AND completion.provider_evidence_ref =
                    paper_flow->>'provider_evidence_ref'
              AND completion.workflow_audit_status =
                    paper_flow->>'workflow_audit_status'
              AND completion.workflow_audit_ref =
                    paper_flow->>'workflow_audit_ref'
              AND completion.workflow_audit_digest =
                    paper_flow->>'workflow_audit_digest'
              AND completion.attempt_completion_event_id =
                    paper_flow->>'attempt_completion_event_id'
              AND completion.task_completion_event_id =
                    paper_flow->>'task_completion_event_id'
              AND gate2.expected_task_version >
                    gate1.expected_task_version
              AND gate3.expected_task_version >
                    gate2.expected_task_version
       )
    THEN
        RAISE EXCEPTION
            'verified evidence paper flow does not match canonical gates';
    END IF;

    RETURN NEW;
END;
$$;

-- Replace the V16 transition guard so every newly accepted candidate binds a
-- verified v3 fact set.  Historical accepted rows remain visible but cannot
-- satisfy the final release join below.
CREATE OR REPLACE FUNCTION quant_system.guard_agent_v02_candidate_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Agent v0.2 candidate admission is not deletable';
    END IF;
    IF OLD.status <> 'open'
       OR NEW.status NOT IN ('accepted', 'revoked', 'expired')
       OR NEW.closed_at IS NULL
       OR NEW.close_reason IS NULL
       OR NEW.admission_id IS DISTINCT FROM OLD.admission_id
       OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.route IS DISTINCT FROM OLD.route
       OR NEW.platform_runtime_digest
            IS DISTINCT FROM OLD.platform_runtime_digest
       OR NEW.hqa_runtime_digest IS DISTINCT FROM OLD.hqa_runtime_digest
       OR NEW.hermes_runtime_digest
            IS DISTINCT FROM OLD.hermes_runtime_digest
       OR NEW.database_schema_fingerprint
            IS DISTINCT FROM OLD.database_schema_fingerprint
       OR NEW.preflight_evidence_digest
            IS DISTINCT FROM OLD.preflight_evidence_digest
       OR NEW.baseline_order_snapshot_digest
            IS DISTINCT FROM OLD.baseline_order_snapshot_digest
       OR NEW.admission_digest IS DISTINCT FROM OLD.admission_digest
       OR NEW.opened_at IS DISTINCT FROM OLD.opened_at
       OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
       OR (
            NEW.status = 'accepted'
            AND (
                NEW.evidence_set_id IS NULL
                OR NEW.evidence_set_digest IS NULL
                OR NEW.final_order_snapshot_digest
                    IS DISTINCT FROM
                    OLD.baseline_order_snapshot_digest
                OR NOT EXISTS (
                    SELECT 1
                    FROM quant_system.agent_v02_candidate_evidence_sets
                    AS evidence_set
                    WHERE evidence_set.evidence_set_id =
                        NEW.evidence_set_id
                      AND evidence_set.admission_id =
                        NEW.admission_id
                      AND evidence_set.facts_digest =
                        NEW.evidence_set_digest
                      AND evidence_set.final_order_snapshot_digest =
                        NEW.final_order_snapshot_digest
                )
            )
       )
       OR (
            NEW.status <> 'accepted'
            AND (
                NEW.evidence_set_id IS NOT NULL
                OR NEW.evidence_set_digest IS NOT NULL
                OR NEW.final_order_snapshot_digest IS NOT NULL
            )
       )
    THEN
        RAISE EXCEPTION
            'Agent v0.2 candidate permits only an evidence-bound open-to-terminal transition';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_agent_v02_candidate_restart_guard
    ON quant_system.agent_v02_candidate_restart_observations;
CREATE TRIGGER trg_agent_v02_candidate_restart_guard
BEFORE INSERT ON quant_system.agent_v02_candidate_restart_observations
FOR EACH ROW
EXECUTE FUNCTION
    quant_system.guard_agent_v02_candidate_restart_observation();
ALTER TABLE quant_system.agent_v02_candidate_restart_observations
    ENABLE ALWAYS TRIGGER trg_agent_v02_candidate_restart_guard;

DROP TRIGGER IF EXISTS trg_agent_v02_candidate_restart_append_only
    ON quant_system.agent_v02_candidate_restart_observations;
CREATE TRIGGER trg_agent_v02_candidate_restart_append_only
BEFORE UPDATE OR DELETE
ON quant_system.agent_v02_candidate_restart_observations
FOR EACH ROW
EXECUTE FUNCTION
    quant_system.reject_agent_v02_candidate_evidence_mutation();
ALTER TABLE quant_system.agent_v02_candidate_restart_observations
    ENABLE ALWAYS TRIGGER trg_agent_v02_candidate_restart_append_only;

DROP TRIGGER IF EXISTS trg_agent_v02_candidate_evidence_set_guard
    ON quant_system.agent_v02_candidate_evidence_sets;
CREATE TRIGGER trg_agent_v02_candidate_evidence_set_guard
BEFORE INSERT ON quant_system.agent_v02_candidate_evidence_sets
FOR EACH ROW
EXECUTE FUNCTION quant_system.guard_agent_v02_candidate_evidence_set();
ALTER TABLE quant_system.agent_v02_candidate_evidence_sets
    ENABLE ALWAYS TRIGGER trg_agent_v02_candidate_evidence_set_guard;

DROP TRIGGER IF EXISTS trg_agent_v02_candidate_evidence_set_append_only
    ON quant_system.agent_v02_candidate_evidence_sets;
CREATE TRIGGER trg_agent_v02_candidate_evidence_set_append_only
BEFORE UPDATE OR DELETE ON quant_system.agent_v02_candidate_evidence_sets
FOR EACH ROW
EXECUTE FUNCTION
    quant_system.reject_agent_v02_candidate_evidence_mutation();
ALTER TABLE quant_system.agent_v02_candidate_evidence_sets
    ENABLE ALWAYS TRIGGER trg_agent_v02_candidate_evidence_set_append_only;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_readonly')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator')
    THEN
        ALTER TABLE quant_system.agent_v02_candidate_evidence_meta
            OWNER TO quant_migrator;
        ALTER TABLE
            quant_system.agent_v02_candidate_restart_observations
            OWNER TO quant_migrator;
        ALTER TABLE quant_system.agent_v02_candidate_evidence_sets
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.reject_agent_v02_candidate_evidence_mutation()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.guard_agent_v02_candidate_restart_observation()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.guard_agent_v02_candidate_evidence_set()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.guard_agent_v02_candidate_transition()
            OWNER TO quant_migrator;

        FOREACH table_name IN ARRAY ARRAY[
            'agent_v02_candidate_restart_observations',
            'agent_v02_candidate_evidence_sets'
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
                || 'FOR ALL TO quant_runtime, quant_readonly '
                || 'USING (owner_user_id = '
                || quote_literal(
                    '00000000-0000-0000-0000-000000000001'
                )
                || '::uuid) WITH CHECK (owner_user_id = '
                || quote_literal(
                    '00000000-0000-0000-0000-000000000001'
                )
                || '::uuid)',
                table_name
            );
            EXECUTE format(
                'DROP POLICY IF EXISTS v4r_migrator_all ON quant_system.%I',
                table_name
            );
            EXECUTE format(
                'CREATE POLICY v4r_migrator_all ON quant_system.%I '
                || 'FOR ALL TO quant_migrator '
                || 'USING (true) WITH CHECK (true)',
                table_name
            );
        END LOOP;

        GRANT USAGE ON SCHEMA quant_system
            TO quant_runtime, quant_readonly, quant_migrator;
        REVOKE CREATE ON SCHEMA quant_system
            FROM quant_runtime, quant_readonly;

        GRANT SELECT
            ON quant_system.agent_v02_candidate_evidence_meta
            TO quant_runtime;
        GRANT SELECT, INSERT
            ON quant_system.agent_v02_candidate_restart_observations,
               quant_system.agent_v02_candidate_evidence_sets
            TO quant_runtime;
        REVOKE UPDATE, DELETE, TRUNCATE
            ON quant_system.agent_v02_candidate_restart_observations,
               quant_system.agent_v02_candidate_evidence_sets
            FROM quant_runtime;

        GRANT SELECT
            ON quant_system.agent_v02_candidate_evidence_meta,
               quant_system.agent_v02_candidate_restart_observations,
               quant_system.agent_v02_candidate_evidence_sets
            TO quant_readonly;
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE
            ON quant_system.agent_v02_candidate_restart_observations,
               quant_system.agent_v02_candidate_evidence_sets
            FROM quant_readonly;

        GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE
            ON quant_system.agent_v02_candidate_evidence_meta,
               quant_system.agent_v02_candidate_restart_observations,
               quant_system.agent_v02_candidate_evidence_sets
            TO quant_migrator;
    END IF;
END $$;

COMMIT;
