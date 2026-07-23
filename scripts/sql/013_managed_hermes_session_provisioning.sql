-- Durable provisioning authority for Agent v0.2 managed Hermes Sessions.
--
-- Registration reserves an exact content-addressed Session identity but does
-- not claim that Hermes has created it.  A separately leased worker must
-- obtain and CAS-bind an exact HQA/Hermes receipt before the row becomes
-- writable.  External sessions remain observed/read-only.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:013_managed_hermes_session_provisioning', 0)
);

DO $$
DECLARE
    installed_version INTEGER;
BEGIN
    SELECT schema_version
    INTO installed_version
    FROM quant_system.hermes_session_registry_meta
    WHERE singleton IS TRUE;

    IF installed_version IS NULL OR installed_version NOT IN (2, 3) THEN
        RAISE EXCEPTION
            'Hermes session registry schema version % cannot migrate to 3',
            installed_version;
    END IF;
END $$;

ALTER TABLE quant_system.hermes_workspace_sessions
    ADD COLUMN IF NOT EXISTS provision_state TEXT,
    ADD COLUMN IF NOT EXISTS provision_version BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS provision_attempt_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS provision_lease_owner TEXT,
    ADD COLUMN IF NOT EXISTS provision_lease_token UUID,
    ADD COLUMN IF NOT EXISTS provision_lease_until TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS provision_next_attempt_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS provision_last_error_code TEXT,
    ADD COLUMN IF NOT EXISTS provisioning_receipt_digest CHAR(64),
    ADD COLUMN IF NOT EXISTS provisioned_at TIMESTAMPTZ;

UPDATE quant_system.hermes_workspace_sessions
SET provision_state = CASE
        WHEN kind = 'observed_external_session' THEN 'observed'
        WHEN creation_action_digest IS NULL THEN 'failed'
        ELSE 'pending'
    END,
    provision_last_error_code = CASE
        WHEN kind = 'web_managed_session' AND creation_action_digest IS NULL
            THEN 'legacy_action_identity_missing'
        ELSE NULL
    END
WHERE provision_state IS NULL;

ALTER TABLE quant_system.hermes_workspace_sessions
    ALTER COLUMN provision_state SET NOT NULL;

ALTER TABLE quant_system.hermes_workspace_sessions
    DROP CONSTRAINT IF EXISTS ck_hermes_workspace_session_provision_state;
ALTER TABLE quant_system.hermes_workspace_sessions
    ADD CONSTRAINT ck_hermes_workspace_session_provision_state
    CHECK (
        provision_state IN (
            'observed',
            'pending',
            'leased',
            'retryable',
            'ready',
            'failed'
        )
    );

ALTER TABLE quant_system.hermes_workspace_sessions
    DROP CONSTRAINT IF EXISTS ck_hermes_workspace_session_provision_counters;
ALTER TABLE quant_system.hermes_workspace_sessions
    ADD CONSTRAINT ck_hermes_workspace_session_provision_counters
    CHECK (
        provision_version >= 0
        AND provision_attempt_count >= 0
    );

ALTER TABLE quant_system.hermes_workspace_sessions
    DROP CONSTRAINT IF EXISTS ck_hermes_workspace_session_provision_error;
ALTER TABLE quant_system.hermes_workspace_sessions
    ADD CONSTRAINT ck_hermes_workspace_session_provision_error
    CHECK (
        provision_last_error_code IS NULL
        OR (
            char_length(provision_last_error_code) BETWEEN 1 AND 200
            AND provision_last_error_code
                ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        )
    );

ALTER TABLE quant_system.hermes_workspace_sessions
    DROP CONSTRAINT IF EXISTS ck_hermes_workspace_session_provision_receipt;
ALTER TABLE quant_system.hermes_workspace_sessions
    ADD CONSTRAINT ck_hermes_workspace_session_provision_receipt
    CHECK (
        provisioning_receipt_digest IS NULL
        OR provisioning_receipt_digest ~ '^[0-9a-f]{64}$'
    );

ALTER TABLE quant_system.hermes_workspace_sessions
    DROP CONSTRAINT IF EXISTS ck_hermes_workspace_session_provision_shape;
ALTER TABLE quant_system.hermes_workspace_sessions
    ADD CONSTRAINT ck_hermes_workspace_session_provision_shape
    CHECK (
        (
            kind = 'observed_external_session'
            AND provision_state = 'observed'
            AND provision_version = 0
            AND provision_attempt_count = 0
            AND provision_lease_owner IS NULL
            AND provision_lease_token IS NULL
            AND provision_lease_until IS NULL
            AND provision_next_attempt_at IS NULL
            AND provision_last_error_code IS NULL
            AND provisioning_receipt_digest IS NULL
            AND provisioned_at IS NULL
        )
        OR
        (
            kind = 'web_managed_session'
            AND provision_state <> 'observed'
            AND (
                (
                    provision_state = 'pending'
                    AND provision_lease_owner IS NULL
                    AND provision_lease_token IS NULL
                    AND provision_lease_until IS NULL
                    AND provision_next_attempt_at IS NULL
                    AND provision_last_error_code IS NULL
                    AND provisioning_receipt_digest IS NULL
                    AND provisioned_at IS NULL
                )
                OR
                (
                    provision_state = 'leased'
                    AND provision_lease_owner IS NOT NULL
                    AND char_length(provision_lease_owner) BETWEEN 1 AND 200
                    AND provision_lease_owner
                        ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
                    AND provision_lease_token IS NOT NULL
                    AND provision_lease_until IS NOT NULL
                    AND provision_next_attempt_at IS NULL
                    AND provision_last_error_code IS NULL
                    AND provisioning_receipt_digest IS NULL
                    AND provisioned_at IS NULL
                )
                OR
                (
                    provision_state = 'retryable'
                    AND provision_lease_owner IS NULL
                    AND provision_lease_token IS NULL
                    AND provision_lease_until IS NULL
                    AND provision_next_attempt_at IS NOT NULL
                    AND provision_last_error_code IS NOT NULL
                    AND provisioning_receipt_digest IS NULL
                    AND provisioned_at IS NULL
                )
                OR
                (
                    provision_state = 'ready'
                    AND provision_lease_owner IS NULL
                    AND provision_lease_token IS NULL
                    AND provision_lease_until IS NULL
                    AND provision_next_attempt_at IS NULL
                    AND provision_last_error_code IS NULL
                    AND provisioning_receipt_digest IS NOT NULL
                    AND provisioned_at IS NOT NULL
                )
                OR
                (
                    provision_state = 'failed'
                    AND provision_lease_owner IS NULL
                    AND provision_lease_token IS NULL
                    AND provision_lease_until IS NULL
                    AND provision_next_attempt_at IS NULL
                    AND provision_last_error_code IS NOT NULL
                    AND provisioning_receipt_digest IS NULL
                    AND provisioned_at IS NULL
                )
            )
        )
    );

ALTER TABLE quant_system.hermes_workspace_sessions
    DROP CONSTRAINT IF EXISTS ck_hermes_workspace_session_managed_exact_identity;
ALTER TABLE quant_system.hermes_workspace_sessions
    ADD CONSTRAINT ck_hermes_workspace_session_managed_exact_identity
    CHECK (
        kind <> 'web_managed_session'
        OR (
            creation_action_digest IS NULL
            AND provision_state = 'failed'
            AND provision_last_error_code = 'legacy_action_identity_missing'
        )
        OR (
            creation_action_digest IS NOT NULL
            AND hermes_session_id =
                'web_' || left(creation_action_digest::text, 40)
        )
    );

ALTER TABLE quant_system.hermes_workspace_sessions
    DROP CONSTRAINT IF EXISTS ck_hermes_workspace_session_exact_fork_point;
ALTER TABLE quant_system.hermes_workspace_sessions
    ADD CONSTRAINT ck_hermes_workspace_session_exact_fork_point
    CHECK (
        parent_platform_session_id IS NULL
        OR fork_point ~ '^message:[1-9][0-9]*$'
    );

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

    IF NEW.provision_state = 'leased'
       AND OLD.provision_state IN ('pending', 'retryable', 'leased')
       AND NEW.provision_version = OLD.provision_version + 1
       AND NEW.provision_attempt_count = OLD.provision_attempt_count + 1
       AND NEW.provision_lease_owner IS NOT NULL
       AND NEW.provision_lease_token IS NOT NULL
       AND NEW.provision_lease_until IS NOT NULL
       AND (
            OLD.provision_state <> 'leased'
            OR NEW.provision_lease_token IS DISTINCT FROM OLD.provision_lease_token
       )
       AND NEW.provision_next_attempt_at IS NULL
       AND NEW.provision_last_error_code IS NULL
       AND NEW.provisioning_receipt_digest IS NULL
       AND NEW.provisioned_at IS NULL
    THEN
        NULL;
    ELSIF OLD.provision_state = 'leased'
       AND NEW.provision_state IN ('retryable', 'ready', 'failed')
       AND NEW.provision_version = OLD.provision_version + 1
       AND NEW.provision_attempt_count = OLD.provision_attempt_count
       AND NEW.provision_lease_owner IS NULL
       AND NEW.provision_lease_token IS NULL
       AND NEW.provision_lease_until IS NULL
       AND (
            (
                NEW.provision_state = 'retryable'
                AND NEW.provision_next_attempt_at IS NOT NULL
                AND NEW.provision_last_error_code IS NOT NULL
                AND NEW.provisioning_receipt_digest IS NULL
                AND NEW.provisioned_at IS NULL
            )
            OR
            (
                NEW.provision_state = 'ready'
                AND NEW.provision_next_attempt_at IS NULL
                AND NEW.provision_last_error_code IS NULL
                AND NEW.provisioning_receipt_digest IS NOT NULL
                AND NEW.provisioned_at IS NOT NULL
            )
            OR
            (
                NEW.provision_state = 'failed'
                AND NEW.provision_next_attempt_at IS NULL
                AND NEW.provision_last_error_code IS NOT NULL
                AND NEW.provisioning_receipt_digest IS NULL
                AND NEW.provisioned_at IS NULL
            )
       )
    THEN
        NULL;
    ELSE
        RAISE EXCEPTION
            'Hermes workspace session provisioning requires an exact lease/CAS transition';
    END IF;

    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

ALTER TABLE quant_system.hermes_workspace_sessions
    ENABLE ALWAYS TRIGGER trg_hermes_workspace_session_immutability;

CREATE INDEX IF NOT EXISTS idx_hermes_workspace_sessions_provision_claim
    ON quant_system.hermes_workspace_sessions (
        provision_state,
        provision_next_attempt_at,
        provision_lease_until,
        created_at,
        platform_session_id
    )
    WHERE kind = 'web_managed_session'
      AND provision_state IN ('pending', 'retryable', 'leased');

UPDATE quant_system.hermes_session_registry_meta
SET schema_version = 3,
    updated_at = now()
WHERE singleton IS TRUE;

COMMIT;
