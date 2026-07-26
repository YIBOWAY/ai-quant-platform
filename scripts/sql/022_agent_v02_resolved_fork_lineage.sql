-- Agent v0.2 dual fork lineage.
--
-- parent_platform_session_id + fork_point preserve the immutable Session and
-- message selected by the user. resolved_source_session_id records the
-- canonical Hermes parent after provider-free compression-tip resolution.
-- Existing rows remain compatible with NULL; every new leased -> ready fork
-- must bind a non-NULL resolved parent through the provisioner CAS.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:022_agent_v02_resolved_fork_lineage', 0)
);

ALTER TABLE quant_system.hermes_workspace_sessions
    ADD COLUMN IF NOT EXISTS resolved_source_session_id TEXT;

ALTER TABLE quant_system.hermes_workspace_sessions
    DROP CONSTRAINT IF EXISTS
        ck_hermes_workspace_session_resolved_source;
ALTER TABLE quant_system.hermes_workspace_sessions
    ADD CONSTRAINT ck_hermes_workspace_session_resolved_source
    CHECK (
        resolved_source_session_id IS NULL
        OR (
            kind = 'web_managed_session'
            AND parent_platform_session_id IS NOT NULL
            AND provision_state = 'ready'
            AND char_length(resolved_source_session_id) BETWEEN 1 AND 255
            AND resolved_source_session_id
                ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        )
    );

COMMENT ON COLUMN
    quant_system.hermes_workspace_sessions.resolved_source_session_id
IS
    'Canonical Hermes parent resolved from the immutable user-selected source; NULL on roots, non-ready rows, and legacy rows';

CREATE OR REPLACE FUNCTION
quant_system.reject_hermes_external_session_mutation()
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
       AND NEW.resolved_source_session_id IS NULL
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
                AND NEW.resolved_source_session_id IS NULL
                AND NEW.provisioned_at IS NULL
            )
            OR
            (
                NEW.provision_state = 'ready'
                AND NEW.provision_next_attempt_at IS NULL
                AND NEW.provision_last_error_code IS NULL
                AND NEW.provisioning_receipt_digest IS NOT NULL
                AND (
                    (
                        NEW.parent_platform_session_id IS NULL
                        AND NEW.resolved_source_session_id IS NULL
                    )
                    OR
                    (
                        NEW.parent_platform_session_id IS NOT NULL
                        AND NEW.resolved_source_session_id IS NOT NULL
                    )
                )
                AND NEW.provisioned_at IS NOT NULL
            )
            OR
            (
                NEW.provision_state = 'failed'
                AND NEW.provision_next_attempt_at IS NULL
                AND NEW.provision_last_error_code IS NOT NULL
                AND NEW.provisioning_receipt_digest IS NULL
                AND NEW.resolved_source_session_id IS NULL
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

CREATE OR REPLACE FUNCTION
quant_system.guard_agent_v02_candidate_resolved_fork_lineage()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    fork_flow JSONB;
BEGIN
    fork_flow := NEW.facts->'flows'->'exact_message_fork';
    IF jsonb_typeof(fork_flow) <> 'object'
       OR COALESCE(fork_flow->>'resolved_source_session_id', '')
            !~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$'
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
              AND child.platform_session_id =
                    fork_flow->>'child_platform_session_id'
              AND child.hermes_session_id =
                    fork_flow->>'child_hermes_session_id'
              AND COALESCE(
                    child.resolved_source_session_id,
                    source.hermes_session_id
              ) = fork_flow->>'resolved_source_session_id'
              AND child.parent_platform_session_id =
                    fork_flow->>'source_platform_session_id'
              AND child.fork_point = fork_flow->>'fork_point'
              AND child.kind = 'web_managed_session'
              AND child.provision_state = 'ready'
              AND child.candidate_admission_id = NEW.admission_id
       )
    THEN
        RAISE EXCEPTION
            'verified evidence fork flow does not bind selected and resolved lineage';
    END IF;

    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF to_regclass(
        'quant_system.agent_v02_candidate_evidence_sets'
    ) IS NOT NULL
    THEN
        DROP TRIGGER IF EXISTS
            trg_agent_v02_candidate_resolved_fork_lineage
            ON quant_system.agent_v02_candidate_evidence_sets;
        CREATE TRIGGER
            trg_agent_v02_candidate_resolved_fork_lineage
        BEFORE INSERT
        ON quant_system.agent_v02_candidate_evidence_sets
        FOR EACH ROW
        EXECUTE FUNCTION
            quant_system.guard_agent_v02_candidate_resolved_fork_lineage();
        ALTER TABLE quant_system.agent_v02_candidate_evidence_sets
            ENABLE ALWAYS TRIGGER
                trg_agent_v02_candidate_resolved_fork_lineage;
    END IF;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime') THEN
        GRANT UPDATE (resolved_source_session_id)
            ON quant_system.hermes_workspace_sessions
            TO quant_runtime;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator') THEN
        ALTER FUNCTION
            quant_system.reject_hermes_external_session_mutation()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.guard_agent_v02_candidate_resolved_fork_lineage()
            OWNER TO quant_migrator;
    END IF;
END $$;

COMMIT;
