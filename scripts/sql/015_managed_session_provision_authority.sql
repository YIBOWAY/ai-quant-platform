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

COMMIT;
