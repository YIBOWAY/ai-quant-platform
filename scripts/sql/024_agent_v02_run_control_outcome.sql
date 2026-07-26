-- Durable production outcome authority for Web approval and Run-stop control.
--
-- These control actions use hermes_commands only for their pre-effect
-- idempotency identity. They are not dispatchable transport work. This
-- migration adds one narrowly-scoped finalizer that consumes the queued
-- outbox row, appends an immutable command event, and records an honest
-- succeeded / known-conflict / outcome-unknown projection.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:024_agent_v02_run_control_outcome', 0)
);

CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_run_control_meta (
    singleton       BOOLEAN PRIMARY KEY DEFAULT TRUE,
    schema_version  INTEGER NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_agent_v02_run_control_meta_singleton CHECK (singleton),
    CONSTRAINT ck_agent_v02_run_control_meta_version
        CHECK (schema_version = 1)
);

INSERT INTO quant_system.agent_v02_run_control_meta (
    singleton,
    schema_version
)
VALUES (TRUE, 1)
ON CONFLICT (singleton) DO UPDATE
SET schema_version = EXCLUDED.schema_version,
    updated_at = now();

CREATE OR REPLACE FUNCTION
    quant_system.finalize_agent_v02_run_control(
        p_owner_user_id UUID,
        p_command_id UUID,
        p_expected_action_digest CHAR(64),
        p_expected_action_kind TEXT,
        p_target_run_id TEXT,
        p_outcome_status TEXT,
        p_reason_code TEXT,
        p_external_status TEXT,
        p_external_idempotent_replay BOOLEAN,
        p_receipt JSONB
    )
RETURNS TABLE (
    command_state TEXT,
    command_version BIGINT,
    command_event_id BIGINT,
    idempotent_replay BOOLEAN
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quant_system
AS $$
DECLARE
    command_row quant_system.hermes_commands%ROWTYPE;
    target_state TEXT;
    inserted_event_id BIGINT;
    expected_receipt JSONB;
    existing_receipt JSONB;
BEGIN
    IF p_owner_user_id <>
        '00000000-0000-0000-0000-000000000001'::uuid
    THEN
        RAISE EXCEPTION 'run-control owner is invalid';
    END IF;
    IF p_expected_action_kind NOT IN (
        'hermes_command_approval_decide',
        'run_stop_request'
    ) THEN
        RAISE EXCEPTION 'run-control kind is invalid';
    END IF;
    IF p_expected_action_digest !~ '^[0-9a-f]{64}$'
       OR p_target_run_id !~
            '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
    THEN
        RAISE EXCEPTION 'run-control identity is invalid';
    END IF;
    IF p_outcome_status NOT IN (
        'succeeded',
        'conflict',
        'outcome_unknown'
    ) THEN
        RAISE EXCEPTION 'run-control outcome is invalid';
    END IF;
    IF (
        p_outcome_status = 'succeeded'
        AND p_reason_code IS NOT NULL
    ) OR (
        p_outcome_status <> 'succeeded'
        AND (
            p_reason_code IS NULL
            OR p_reason_code !~ '^[a-z][a-z0-9_.-]{0,63}$'
        )
    ) THEN
        RAISE EXCEPTION 'run-control reason is invalid';
    END IF;
    IF p_external_status IS NOT NULL
       AND p_external_status !~ '^[a-z][a-z0-9_.-]{0,63}$'
    THEN
        RAISE EXCEPTION 'run-control external status is invalid';
    END IF;

    expected_receipt := jsonb_build_object(
        'action_digest', trim(trailing FROM p_expected_action_digest),
        'action_kind', p_expected_action_kind,
        'contract', 'agent-v0.2-run-control-outcome/v1',
        'external_idempotent_replay',
            p_external_idempotent_replay,
        'external_status', p_external_status,
        'outcome_status', p_outcome_status,
        'reason_code', p_reason_code,
        'target_run_id', p_target_run_id
    );
    IF p_receipt IS NULL
       OR jsonb_typeof(p_receipt) <> 'object'
       OR p_receipt <> expected_receipt
    THEN
        RAISE EXCEPTION 'run-control receipt is invalid';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'agent-v02-run-control:' || p_command_id::text,
            0
        )
    );

    SELECT *
    INTO command_row
    FROM quant_system.hermes_commands
    WHERE command_id = p_command_id
      AND owner_user_id = p_owner_user_id
    FOR UPDATE;

    IF NOT FOUND
       OR command_row.platform_session_id !~ '^awctl_'
       OR command_row.kind <> p_expected_action_kind
       OR command_row.canonical_request_digest <>
            p_expected_action_digest
       OR command_row.provider_policy_digest IS NOT NULL
       OR command_row.hermes_session_id IS NOT NULL
       OR command_row.hermes_run_id IS NOT NULL
    THEN
        RAISE EXCEPTION 'run-control command identity mismatches';
    END IF;

    target_state := CASE p_outcome_status
        WHEN 'succeeded' THEN 'succeeded'
        WHEN 'conflict' THEN 'failed'
        ELSE 'outcome_unknown'
    END;

    IF command_row.state IN ('succeeded', 'failed') THEN
        SELECT event.event_data
        INTO existing_receipt
        FROM quant_system.hermes_command_events AS event
        WHERE event.command_id = p_command_id
          AND event.command_version = command_row.version
          AND event.actor = 'bff'
          AND event.event_type LIKE 'run_control.%'
        LIMIT 1;
        IF command_row.state <> target_state
           OR existing_receipt IS DISTINCT FROM p_receipt
        THEN
            RAISE EXCEPTION 'run-control terminal replay mismatches';
        END IF;
        RETURN QUERY SELECT
            command_row.state,
            command_row.version,
            (
                SELECT event.event_id
                FROM quant_system.hermes_command_events AS event
                WHERE event.command_id = p_command_id
                  AND event.command_version = command_row.version
            ),
            TRUE;
        RETURN;
    END IF;

    IF command_row.state NOT IN ('queued', 'outcome_unknown') THEN
        RAISE EXCEPTION 'run-control command state is not finalizable';
    END IF;

    UPDATE quant_system.hermes_commands
    SET state = target_state,
        version = version + 1,
        next_attempt_at = NULL,
        lease_owner = NULL,
        lease_token = NULL,
        lease_until = NULL,
        dispatch_started_at = NULL,
        last_error_code = p_reason_code,
        updated_at = clock_timestamp()
    WHERE command_id = p_command_id
      AND owner_user_id = p_owner_user_id
      AND version = command_row.version
      AND state = command_row.state
    RETURNING *
    INTO command_row;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'run-control command changed concurrently';
    END IF;

    INSERT INTO quant_system.hermes_command_events (
        command_id,
        command_version,
        event_type,
        actor,
        from_state,
        to_state,
        canonical_request_digest,
        attempt_count,
        next_attempt_at,
        lease_owner,
        lease_token,
        lease_until,
        dispatch_started_at,
        hermes_session_id,
        resolved_hermes_session_id,
        hermes_run_id,
        error_code,
        event_data,
        occurred_at
    )
    VALUES (
        command_row.command_id,
        command_row.version,
        'run_control.' || p_outcome_status,
        'bff',
        CASE
            WHEN command_row.version = 2 THEN 'queued'
            ELSE 'outcome_unknown'
        END,
        command_row.state,
        command_row.canonical_request_digest,
        command_row.attempt_count,
        command_row.next_attempt_at,
        command_row.lease_owner,
        command_row.lease_token,
        command_row.lease_until,
        command_row.dispatch_started_at,
        command_row.hermes_session_id,
        command_row.resolved_hermes_session_id,
        command_row.hermes_run_id,
        command_row.last_error_code,
        p_receipt,
        command_row.updated_at
    )
    RETURNING event_id INTO inserted_event_id;

    UPDATE quant_system.hermes_outbox
    SET consumed_by = COALESCE(consumed_by, 'run_control_bff'),
        consumed_at = COALESCE(consumed_at, clock_timestamp())
    WHERE command_id = p_command_id
      AND topic = 'hermes.command.queued'
      AND consumed_at IS NULL;

    RETURN QUERY SELECT
        command_row.state,
        command_row.version,
        inserted_event_id,
        FALSE;
END;
$$;

ALTER TABLE quant_system.agent_v02_run_control_meta
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_system.agent_v02_run_control_meta
    FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS agent_v02_run_control_meta_read
    ON quant_system.agent_v02_run_control_meta;
CREATE POLICY agent_v02_run_control_meta_read
    ON quant_system.agent_v02_run_control_meta
    FOR SELECT
    TO quant_runtime, quant_readonly
    USING (singleton IS TRUE);

DROP POLICY IF EXISTS agent_v02_run_control_meta_migrator
    ON quant_system.agent_v02_run_control_meta;
CREATE POLICY agent_v02_run_control_meta_migrator
    ON quant_system.agent_v02_run_control_meta
    FOR ALL
    TO quant_migrator
    USING (TRUE)
    WITH CHECK (TRUE);

REVOKE ALL ON TABLE
    quant_system.agent_v02_run_control_meta
FROM PUBLIC, quant_runtime, quant_readonly;
GRANT SELECT ON TABLE
    quant_system.agent_v02_run_control_meta
TO quant_runtime, quant_readonly;

REVOKE ALL ON FUNCTION
    quant_system.finalize_agent_v02_run_control(
        UUID, UUID, CHAR(64), TEXT, TEXT, TEXT,
        TEXT, TEXT, BOOLEAN, JSONB
    )
FROM PUBLIC, quant_readonly;
GRANT EXECUTE ON FUNCTION
    quant_system.finalize_agent_v02_run_control(
        UUID, UUID, CHAR(64), TEXT, TEXT, TEXT,
        TEXT, TEXT, BOOLEAN, JSONB
    )
TO quant_runtime, quant_migrator;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator'
    ) THEN
        ALTER TABLE quant_system.agent_v02_run_control_meta
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.finalize_agent_v02_run_control(
                UUID, UUID, CHAR(64), TEXT, TEXT, TEXT,
                TEXT, TEXT, BOOLEAN, JSONB
            )
            OWNER TO quant_migrator;
    END IF;
END $$;

ALTER TABLE quant_system.hermes_commands
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_commands
    FORCE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_command_events
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_command_events
    FORCE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_outbox
    ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_outbox
    FORCE ROW LEVEL SECURITY;

COMMIT;
