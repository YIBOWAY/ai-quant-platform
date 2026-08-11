-- D-34 Mandate, deterministic policy decision, and execution-authority facts.
-- Applying this migration is an explicit operator action; startup never applies it.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('quant_system:hermes_schema_runtime_gate', 0));
SELECT pg_advisory_xact_lock(hashtextextended('quant_system:030_d34_mandate_policy', 0));

DO $$
DECLARE predecessor_version INTEGER;
BEGIN
    IF to_regclass('quant_system.factor_automation_events_meta') IS NULL THEN
        RAISE EXCEPTION 'D-34 mandate policy requires migration 029';
    END IF;
    SELECT schema_version INTO predecessor_version
    FROM quant_system.factor_automation_events_meta WHERE singleton IS TRUE;
    IF predecessor_version IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION 'D-34 mandate policy requires current migration 029 metadata';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS quant_system.d34_mandate_policy_meta (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO quant_system.d34_mandate_policy_meta (singleton, schema_version)
VALUES (TRUE, 1) ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS quant_system.d34_mandates (
    mandate_id TEXT PRIMARY KEY,
    owner_user_id UUID NOT NULL,
    workspace_id TEXT NOT NULL,
    status TEXT NOT NULL,
    universe TEXT[] NOT NULL,
    hypotheses_per_cycle INTEGER NOT NULL,
    max_iterations INTEGER NOT NULL,
    max_experiments_per_iteration INTEGER NOT NULL,
    max_concurrent_jobs INTEGER NOT NULL,
    llm_budget_usd NUMERIC(12,2) NOT NULL,
    llm_warning_fraction NUMERIC(7,6) NOT NULL,
    llm_spent_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
    paper_execution_allowed BOOLEAN NOT NULL,
    policy_digest TEXT NOT NULL,
    policy_document JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    starts_at TIMESTAMPTZ NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    version BIGINT NOT NULL DEFAULT 1,
    CHECK (mandate_id ~ '^mandate-[0-9a-f-]{36}$'),
    CHECK (workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CHECK (status IN ('active', 'paused', 'revoked', 'expired')),
    CHECK (cardinality(universe) BETWEEN 1 AND 64),
    CHECK (hypotheses_per_cycle BETWEEN 1 AND 100),
    CHECK (max_iterations BETWEEN 1 AND 100),
    CHECK (max_experiments_per_iteration BETWEEN 1 AND 100),
    CHECK (max_concurrent_jobs BETWEEN 1 AND 32),
    CHECK (llm_budget_usd > 0 AND llm_spent_usd >= 0),
    CHECK (llm_warning_fraction > 0 AND llm_warning_fraction < 1),
    CHECK (policy_digest ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(policy_document) = 'object'),
    CHECK (expires_at > starts_at),
    CHECK (version >= 1)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_d34_one_open_mandate
ON quant_system.d34_mandates (owner_user_id, workspace_id)
WHERE status IN ('active', 'paused');

CREATE TABLE IF NOT EXISTS quant_system.d34_mandate_events (
    event_seq BIGSERIAL UNIQUE NOT NULL,
    event_id TEXT PRIMARY KEY,
    mandate_id TEXT NOT NULL REFERENCES quant_system.d34_mandates(mandate_id),
    owner_user_id UUID NOT NULL,
    workspace_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    mandate_version BIGINT NOT NULL,
    event_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (event_type IN ('created', 'renewed', 'paused', 'resumed', 'revoked', 'expired', 'budget_recorded')),
    CHECK (jsonb_typeof(event_data) = 'object')
);

CREATE TABLE IF NOT EXISTS quant_system.d34_policy_decisions (
    decision_seq BIGSERIAL UNIQUE NOT NULL,
    decision_id TEXT PRIMARY KEY,
    owner_user_id UUID NOT NULL,
    workspace_id TEXT NOT NULL,
    mandate_id TEXT NOT NULL REFERENCES quant_system.d34_mandates(mandate_id),
    subject_kind TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    policy_digest TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason_codes TEXT[] NOT NULL DEFAULT '{}',
    input_digest TEXT NOT NULL,
    decision_document JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (subject_kind IN ('experiment', 'artifact', 'canary', 'order_batch')),
    CHECK (outcome IN ('accepted', 'rejected', 'paused')),
    CHECK (policy_digest ~ '^[0-9a-f]{64}$'),
    CHECK (input_digest ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(decision_document) = 'object')
);

CREATE TABLE IF NOT EXISTS quant_system.d34_execution_authority_events (
    event_seq BIGSERIAL UNIQUE NOT NULL,
    event_id TEXT PRIMARY KEY,
    owner_user_id UUID NOT NULL,
    workspace_id TEXT NOT NULL,
    mandate_id TEXT REFERENCES quant_system.d34_mandates(mandate_id),
    event_type TEXT NOT NULL,
    enabled BOOLEAN NOT NULL,
    reason TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (event_type IN ('paper_execution', 'emergency_stop')),
    CHECK (length(reason) BETWEEN 1 AND 1000)
);

CREATE OR REPLACE FUNCTION quant_system.reject_d34_append_only_mutation()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN RAISE EXCEPTION 'D-34 audit records are append-only'; END;
$$;

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'd34_mandate_events', 'd34_policy_decisions', 'd34_execution_authority_events'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS trg_%I_append_only ON quant_system.%I', table_name, table_name);
        EXECUTE format(
            'CREATE TRIGGER trg_%I_append_only BEFORE UPDATE OR DELETE ON quant_system.%I FOR EACH ROW EXECUTE FUNCTION quant_system.reject_d34_append_only_mutation()',
            table_name, table_name
        );
        EXECUTE format('ALTER TABLE quant_system.%I ENABLE ALWAYS TRIGGER trg_%I_append_only', table_name, table_name);
    END LOOP;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator') THEN
        ALTER TABLE quant_system.d34_mandate_policy_meta OWNER TO quant_migrator;
        ALTER TABLE quant_system.d34_mandates OWNER TO quant_migrator;
        ALTER TABLE quant_system.d34_mandate_events OWNER TO quant_migrator;
        ALTER TABLE quant_system.d34_policy_decisions OWNER TO quant_migrator;
        ALTER TABLE quant_system.d34_execution_authority_events OWNER TO quant_migrator;
        ALTER SEQUENCE quant_system.d34_mandate_events_event_seq_seq OWNER TO quant_migrator;
        ALTER SEQUENCE quant_system.d34_policy_decisions_decision_seq_seq OWNER TO quant_migrator;
        ALTER SEQUENCE quant_system.d34_execution_authority_events_event_seq_seq OWNER TO quant_migrator;
        ALTER FUNCTION quant_system.reject_d34_append_only_mutation() OWNER TO quant_migrator;
    END IF;

    REVOKE ALL ON TABLE
        quant_system.d34_mandate_policy_meta,
        quant_system.d34_mandates,
        quant_system.d34_mandate_events,
        quant_system.d34_policy_decisions,
        quant_system.d34_execution_authority_events
        FROM PUBLIC;
    REVOKE ALL ON SEQUENCE
        quant_system.d34_mandate_events_event_seq_seq,
        quant_system.d34_policy_decisions_decision_seq_seq,
        quant_system.d34_execution_authority_events_event_seq_seq
        FROM PUBLIC;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime') THEN
        GRANT SELECT ON TABLE quant_system.d34_mandate_policy_meta TO quant_runtime;
        GRANT SELECT, INSERT, UPDATE ON TABLE quant_system.d34_mandates TO quant_runtime;
        GRANT SELECT, INSERT ON TABLE
            quant_system.d34_mandate_events,
            quant_system.d34_policy_decisions,
            quant_system.d34_execution_authority_events
            TO quant_runtime;
        GRANT USAGE, SELECT ON SEQUENCE
            quant_system.d34_mandate_events_event_seq_seq,
            quant_system.d34_policy_decisions_decision_seq_seq,
            quant_system.d34_execution_authority_events_event_seq_seq
            TO quant_runtime;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_readonly') THEN
        GRANT SELECT ON TABLE
            quant_system.d34_mandate_policy_meta,
            quant_system.d34_mandates,
            quant_system.d34_mandate_events,
            quant_system.d34_policy_decisions,
            quant_system.d34_execution_authority_events
            TO quant_readonly;
    END IF;
END $$;

COMMIT;
