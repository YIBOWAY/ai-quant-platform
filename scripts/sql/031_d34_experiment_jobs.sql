-- D-34 durable jobs, leases, attempts, events, and budget consumption.
-- Applying this migration is an explicit operator action.

BEGIN;
SELECT pg_advisory_xact_lock(hashtextextended('quant_system:hermes_schema_runtime_gate', 0));
SELECT pg_advisory_xact_lock(hashtextextended('quant_system:031_d34_experiment_jobs', 0));

DO $$
DECLARE predecessor_version INTEGER;
BEGIN
    IF to_regclass('quant_system.d34_mandate_policy_meta') IS NULL THEN
        RAISE EXCEPTION 'D-34 experiment jobs require migration 030';
    END IF;
    SELECT schema_version INTO predecessor_version
    FROM quant_system.d34_mandate_policy_meta WHERE singleton IS TRUE;
    IF predecessor_version IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION 'D-34 experiment jobs require current migration 030 metadata';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS quant_system.d34_experiment_jobs_meta (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO quant_system.d34_experiment_jobs_meta (singleton, schema_version)
VALUES (TRUE, 1) ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS quant_system.d34_experiment_jobs (
    job_id TEXT PRIMARY KEY,
    mandate_id TEXT NOT NULL REFERENCES quant_system.d34_mandates(mandate_id),
    owner_user_id UUID NOT NULL,
    workspace_id TEXT NOT NULL,
    job_key TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'queued',
    attempt_count INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    input_digest TEXT NOT NULL,
    input_document JSONB NOT NULL,
    lease_id TEXT,
    lease_owner TEXT,
    leased_at TIMESTAMPTZ,
    heartbeat_at TIMESTAMPTZ,
    lease_expires_at TIMESTAMPTZ,
    budget_reserved_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
    budget_spent_usd NUMERIC(12,6) NOT NULL DEFAULT 0,
    outcome_code TEXT,
    outcome_document JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ,
    version BIGINT NOT NULL DEFAULT 1,
    UNIQUE (mandate_id, job_key),
    CHECK (job_id ~ '^job-[0-9a-f-]{36}$'),
    CHECK (length(job_key) BETWEEN 1 AND 512),
    CHECK (state IN ('queued', 'leased', 'running', 'succeeded', 'rejected', 'outcome_unknown', 'cancelled')),
    CHECK (attempt_count >= 0 AND max_attempts BETWEEN 1 AND 20 AND attempt_count <= max_attempts),
    CHECK (input_digest ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(input_document) = 'object'),
    CHECK (budget_reserved_usd >= 0 AND budget_spent_usd >= 0),
    CHECK (outcome_document IS NULL OR jsonb_typeof(outcome_document) = 'object'),
    CHECK (version >= 1),
    CHECK (
        (state IN ('leased', 'running') AND lease_id IS NOT NULL AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
        OR state NOT IN ('leased', 'running')
    )
);
CREATE INDEX IF NOT EXISTS idx_d34_jobs_queue
ON quant_system.d34_experiment_jobs (owner_user_id, workspace_id, state, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS uq_d34_active_lease
ON quant_system.d34_experiment_jobs (lease_id) WHERE lease_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS quant_system.d34_experiment_attempts (
    attempt_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES quant_system.d34_experiment_jobs(job_id),
    attempt_number INTEGER NOT NULL,
    lease_id TEXT NOT NULL,
    state TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    container_id TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    finished_at TIMESTAMPTZ,
    outcome_code TEXT,
    recovery_document JSONB NOT NULL DEFAULT '{}'::jsonb,
    UNIQUE (job_id, attempt_number),
    CHECK (attempt_number >= 1),
    CHECK (state IN ('leased', 'running', 'succeeded', 'rejected', 'outcome_unknown', 'cancelled')),
    CHECK (jsonb_typeof(recovery_document) = 'object')
);

CREATE TABLE IF NOT EXISTS quant_system.d34_job_events (
    event_seq BIGSERIAL UNIQUE NOT NULL,
    event_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES quant_system.d34_experiment_jobs(job_id),
    attempt_id TEXT REFERENCES quant_system.d34_experiment_attempts(attempt_id),
    event_type TEXT NOT NULL,
    job_version BIGINT NOT NULL,
    event_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (event_type IN ('queued', 'leased', 'running', 'heartbeat', 'succeeded', 'rejected', 'outcome_unknown', 'cancelled', 'requeued')),
    CHECK (jsonb_typeof(event_data) = 'object')
);

CREATE TABLE IF NOT EXISTS quant_system.d34_budget_events (
    event_seq BIGSERIAL UNIQUE NOT NULL,
    event_id TEXT PRIMARY KEY,
    mandate_id TEXT NOT NULL REFERENCES quant_system.d34_mandates(mandate_id),
    job_id TEXT NOT NULL REFERENCES quant_system.d34_experiment_jobs(job_id),
    attempt_id TEXT REFERENCES quant_system.d34_experiment_attempts(attempt_id),
    event_type TEXT NOT NULL,
    amount_usd NUMERIC(12,6) NOT NULL,
    provider_receipt_digest TEXT,
    event_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (event_type IN ('reserved', 'consumed', 'released', 'outcome_unknown')),
    CHECK (amount_usd >= 0),
    CHECK (provider_receipt_digest IS NULL OR provider_receipt_digest ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(event_data) = 'object')
);

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY['d34_job_events', 'd34_budget_events'] LOOP
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
        ALTER TABLE quant_system.d34_experiment_jobs_meta OWNER TO quant_migrator;
        ALTER TABLE quant_system.d34_experiment_jobs OWNER TO quant_migrator;
        ALTER TABLE quant_system.d34_experiment_attempts OWNER TO quant_migrator;
        ALTER TABLE quant_system.d34_job_events OWNER TO quant_migrator;
        ALTER TABLE quant_system.d34_budget_events OWNER TO quant_migrator;
        ALTER SEQUENCE quant_system.d34_job_events_event_seq_seq OWNER TO quant_migrator;
        ALTER SEQUENCE quant_system.d34_budget_events_event_seq_seq OWNER TO quant_migrator;
    END IF;

    REVOKE ALL ON TABLE
        quant_system.d34_experiment_jobs_meta,
        quant_system.d34_experiment_jobs,
        quant_system.d34_experiment_attempts,
        quant_system.d34_job_events,
        quant_system.d34_budget_events
        FROM PUBLIC;
    REVOKE ALL ON SEQUENCE
        quant_system.d34_job_events_event_seq_seq,
        quant_system.d34_budget_events_event_seq_seq
        FROM PUBLIC;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime') THEN
        GRANT SELECT ON TABLE quant_system.d34_experiment_jobs_meta TO quant_runtime;
        GRANT SELECT, INSERT, UPDATE ON TABLE
            quant_system.d34_experiment_jobs,
            quant_system.d34_experiment_attempts
            TO quant_runtime;
        GRANT SELECT, INSERT ON TABLE
            quant_system.d34_job_events,
            quant_system.d34_budget_events
            TO quant_runtime;
        GRANT USAGE, SELECT ON SEQUENCE
            quant_system.d34_job_events_event_seq_seq,
            quant_system.d34_budget_events_event_seq_seq
            TO quant_runtime;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_readonly') THEN
        GRANT SELECT ON TABLE
            quant_system.d34_experiment_jobs_meta,
            quant_system.d34_experiment_jobs,
            quant_system.d34_experiment_attempts,
            quant_system.d34_job_events,
            quant_system.d34_budget_events
            TO quant_readonly;
    END IF;
END $$;

COMMIT;
