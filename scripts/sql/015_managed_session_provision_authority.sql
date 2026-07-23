-- Agent v0.2: least-privilege authority for durable managed-Session provisioning.
--
-- The connector must advance only the provisioning state machine.  It must
-- never be able to rewrite Session identity, lineage, payload policy, owner,
-- writer, or timestamps directly.  Migration 010 intentionally revoked the
-- table-level UPDATE grant; migration 013 later added the provisioning state
-- machine but did not restore the bounded column authority required by its
-- worker.  This corrective migration grants exactly the ten CAS state columns.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:015_managed_session_provision_authority', 0)
);

DO $$
DECLARE
    registry_version INTEGER;
    security_version INTEGER;
BEGIN
    SELECT schema_version
    INTO registry_version
    FROM quant_system.hermes_session_registry_meta
    WHERE singleton IS TRUE;

    SELECT schema_version
    INTO security_version
    FROM quant_system.hermes_security_meta
    WHERE singleton IS TRUE;

    IF registry_version IS DISTINCT FROM 3 THEN
        RAISE EXCEPTION
            'Hermes session registry schema version % cannot grant provisioning authority',
            registry_version;
    END IF;
    IF security_version IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION
            'Hermes runtime security schema version % cannot grant provisioning authority',
            security_version;
    END IF;
END $$;

-- Correct both accidental table-wide grants and any stale column grants before
-- applying the exact allowlist.  The readonly role remains unable to mutate.
REVOKE UPDATE ON quant_system.hermes_workspace_sessions
    FROM quant_runtime, quant_readonly, PUBLIC;
REVOKE UPDATE (
    platform_session_id,
    hermes_session_id,
    workspace_id,
    owner_user_id,
    kind,
    source_channel,
    parent_platform_session_id,
    fork_point,
    provider_policy_digest,
    payload_ttl_days,
    creation_client_action_id,
    creation_action_digest,
    writer,
    provision_state,
    provision_version,
    provision_attempt_count,
    provision_lease_owner,
    provision_lease_token,
    provision_lease_until,
    provision_next_attempt_at,
    provision_last_error_code,
    provisioning_receipt_digest,
    provisioned_at,
    created_at,
    updated_at
) ON quant_system.hermes_workspace_sessions
    FROM quant_runtime, quant_readonly, PUBLIC;

GRANT UPDATE (
    provision_state,
    provision_version,
    provision_attempt_count,
    provision_lease_owner,
    provision_lease_token,
    provision_lease_until,
    provision_next_attempt_at,
    provision_last_error_code,
    provisioning_receipt_digest,
    provisioned_at
) ON quant_system.hermes_workspace_sessions
    TO quant_runtime;

-- Keep creation time immutable under the same ALWAYS trigger.  The restricted
-- runtime already lacks this column privilege; the trigger also protects
-- against accidental writes through the migrator/admin maintenance path.
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
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
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

COMMIT;
