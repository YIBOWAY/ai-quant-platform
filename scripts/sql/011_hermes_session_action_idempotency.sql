-- Agent v0.2 V4-R follow-up: session create/fork idempotency belongs to the
-- session registry, not to the dispatchable Hermes command ledger.
--
-- Existing managed rows may keep NULL action identity. New application writes
-- require an exact client-action/digest pair. No Hermes/provider/trading call.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:011_hermes_session_action_idempotency', 0)
);

DO $$
DECLARE
    installed_version INTEGER;
BEGIN
    SELECT schema_version
    INTO installed_version
    FROM quant_system.hermes_session_registry_meta
    WHERE singleton IS TRUE;

    IF installed_version IS NULL OR installed_version NOT IN (1, 2, 3) THEN
        RAISE EXCEPTION
            'Hermes session registry schema version % cannot migrate to 2',
            installed_version;
    END IF;
END $$;

ALTER TABLE quant_system.hermes_workspace_sessions
    ADD COLUMN IF NOT EXISTS creation_client_action_id TEXT,
    ADD COLUMN IF NOT EXISTS creation_action_digest CHAR(64);

ALTER TABLE quant_system.hermes_workspace_sessions
    DROP CONSTRAINT IF EXISTS ck_hermes_workspace_session_creation_action;
ALTER TABLE quant_system.hermes_workspace_sessions
    ADD CONSTRAINT ck_hermes_workspace_session_creation_action
    CHECK (
        (
            creation_client_action_id IS NULL
            AND creation_action_digest IS NULL
        )
        OR
        (
            kind = 'web_managed_session'
            AND creation_client_action_id IS NOT NULL
            AND char_length(creation_client_action_id) BETWEEN 1 AND 200
            AND creation_client_action_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
            AND creation_action_digest IS NOT NULL
            AND creation_action_digest ~ '^[0-9a-f]{64}$'
        )
    );

CREATE UNIQUE INDEX IF NOT EXISTS uq_hermes_workspace_session_creation_action
    ON quant_system.hermes_workspace_sessions (
        owner_user_id,
        workspace_id,
        creation_client_action_id
    )
    WHERE creation_client_action_id IS NOT NULL;

CREATE OR REPLACE FUNCTION quant_system.reject_hermes_external_session_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'Hermes workspace session rows are immutable once registered';
    END IF;

    IF NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.hermes_session_id IS DISTINCT FROM OLD.hermes_session_id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
       OR NEW.writer IS DISTINCT FROM OLD.writer
       OR NEW.provider_policy_digest IS DISTINCT FROM OLD.provider_policy_digest
       OR NEW.payload_ttl_days IS DISTINCT FROM OLD.payload_ttl_days
       OR NEW.creation_client_action_id IS DISTINCT FROM OLD.creation_client_action_id
       OR NEW.creation_action_digest IS DISTINCT FROM OLD.creation_action_digest
       OR NEW.parent_platform_session_id IS DISTINCT FROM OLD.parent_platform_session_id
       OR NEW.fork_point IS DISTINCT FROM OLD.fork_point
       OR NEW.source_channel IS DISTINCT FROM OLD.source_channel
       OR NEW.platform_session_id IS DISTINCT FROM OLD.platform_session_id
    THEN
        RAISE EXCEPTION
            'Hermes workspace session identity, lineage, action and payload policy are immutable';
    END IF;

    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

ALTER TABLE quant_system.hermes_workspace_sessions
    ENABLE ALWAYS TRIGGER trg_hermes_workspace_session_immutability;

-- Before V2, create/fork were incorrectly represented as dispatchable Hermes
-- commands even though no worker could claim them. Retire only those legacy
-- queued control rows with an append-only terminal event; never touch real
-- conversation/research work or any row whose execution state is ambiguous.
WITH retired AS (
    UPDATE quant_system.hermes_commands
    SET state = 'cancelled',
        version = version + 1,
        next_attempt_at = NULL,
        lease_owner = NULL,
        lease_token = NULL,
        lease_until = NULL,
        dispatch_started_at = NULL,
        last_error_code = 'legacy_control_command_retired',
        updated_at = clock_timestamp()
    WHERE kind IN ('managed_session_create', 'managed_session_fork')
      AND state = 'queued'
      AND platform_session_id LIKE 'awctl\_%' ESCAPE '\'
    RETURNING *
)
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
    hermes_run_id,
    error_code,
    event_data
)
SELECT
    command_id,
    version,
    'legacy_control_retired',
    'system',
    'queued',
    state,
    canonical_request_digest,
    attempt_count,
    next_attempt_at,
    lease_owner,
    lease_token,
    lease_until,
    dispatch_started_at,
    hermes_session_id,
    hermes_run_id,
    last_error_code,
    '{"migration":"010","reason":"session_registry_owns_action"}'::jsonb
FROM retired;

UPDATE quant_system.hermes_outbox AS outbox
SET consumed_by = 'migration:010',
    consumed_at = clock_timestamp()
FROM quant_system.hermes_commands AS command
WHERE outbox.command_id = command.command_id
  AND outbox.consumed_at IS NULL
  AND command.kind IN ('managed_session_create', 'managed_session_fork')
  AND command.state = 'cancelled'
  AND command.last_error_code = 'legacy_control_command_retired';

UPDATE quant_system.hermes_session_registry_meta
SET schema_version = GREATEST(schema_version, 2),
    updated_at = now()
WHERE singleton IS TRUE;

COMMIT;
