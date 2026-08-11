-- D-34 engine receipts, comparisons, Artifact Registry, and paper canaries.
-- Applying this migration is an explicit operator action.

BEGIN;
SELECT pg_advisory_xact_lock(hashtextextended('quant_system:hermes_schema_runtime_gate', 0));
SELECT pg_advisory_xact_lock(hashtextextended('quant_system:032_d34_artifact_canary', 0));

DO $$
DECLARE predecessor_version INTEGER;
BEGIN
    IF to_regclass('quant_system.d34_experiment_jobs_meta') IS NULL THEN
        RAISE EXCEPTION 'D-34 Artifact Registry requires migration 031';
    END IF;
    SELECT schema_version INTO predecessor_version
    FROM quant_system.d34_experiment_jobs_meta WHERE singleton IS TRUE;
    IF predecessor_version IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION 'D-34 Artifact Registry requires current migration 031 metadata';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS quant_system.d34_artifact_canary_meta (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);
INSERT INTO quant_system.d34_artifact_canary_meta (singleton, schema_version)
VALUES (TRUE, 1) ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS quant_system.d34_engine_receipts (
    receipt_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES quant_system.d34_experiment_jobs(job_id),
    mandate_id TEXT NOT NULL REFERENCES quant_system.d34_mandates(mandate_id),
    owner_user_id UUID NOT NULL,
    workspace_id TEXT NOT NULL,
    engine TEXT NOT NULL,
    snapshot_digest TEXT NOT NULL,
    universe_digest TEXT NOT NULL,
    calendar_digest TEXT NOT NULL,
    target_weights_digest TEXT NOT NULL,
    receipt_digest TEXT NOT NULL UNIQUE,
    receipt_document JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (job_id, engine),
    CHECK (engine IN ('qlib', 'platform')),
    CHECK (snapshot_digest ~ '^[0-9a-f]{64}$'),
    CHECK (universe_digest ~ '^[0-9a-f]{64}$'),
    CHECK (calendar_digest ~ '^[0-9a-f]{64}$'),
    CHECK (target_weights_digest ~ '^[0-9a-f]{64}$'),
    CHECK (receipt_digest ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(receipt_document) = 'object')
);

CREATE TABLE IF NOT EXISTS quant_system.d34_comparisons (
    comparison_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE REFERENCES quant_system.d34_experiment_jobs(job_id),
    qlib_receipt_id TEXT NOT NULL REFERENCES quant_system.d34_engine_receipts(receipt_id),
    platform_receipt_id TEXT NOT NULL REFERENCES quant_system.d34_engine_receipts(receipt_id),
    policy_digest TEXT NOT NULL,
    comparison_digest TEXT NOT NULL UNIQUE,
    accepted BOOLEAN NOT NULL,
    daily_return_correlation DOUBLE PRECISION NOT NULL,
    terminal_nav_difference_bps DOUBLE PRECISION NOT NULL,
    max_symbol_weight_difference_bps DOUBLE PRECISION NOT NULL,
    comparison_document JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (policy_digest ~ '^[0-9a-f]{64}$'),
    CHECK (comparison_digest ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(comparison_document) = 'object')
);

CREATE TABLE IF NOT EXISTS quant_system.d34_artifacts (
    artifact_id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL UNIQUE REFERENCES quant_system.d34_experiment_jobs(job_id),
    mandate_id TEXT NOT NULL REFERENCES quant_system.d34_mandates(mandate_id),
    owner_user_id UUID NOT NULL,
    workspace_id TEXT NOT NULL,
    status TEXT NOT NULL,
    qualification_scope TEXT NOT NULL DEFAULT 'paper_only',
    policy_digest TEXT NOT NULL,
    snapshot_digest TEXT NOT NULL,
    candidate_code_digest TEXT NOT NULL,
    qlib_config_digest TEXT NOT NULL,
    rdagent_commit TEXT NOT NULL,
    qlib_commit TEXT NOT NULL,
    docker_image_digest TEXT NOT NULL,
    qlib_receipt_digest TEXT NOT NULL,
    platform_receipt_digest TEXT NOT NULL,
    comparison_digest TEXT NOT NULL REFERENCES quant_system.d34_comparisons(comparison_digest),
    policy_decision_id TEXT NOT NULL REFERENCES quant_system.d34_policy_decisions(decision_id),
    artifact_document JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    version BIGINT NOT NULL DEFAULT 1,
    CHECK (status IN ('qualified', 'canary_active', 'paused', 'demoted', 'rejected', 'rolled_back')),
    CHECK (qualification_scope = 'paper_only'),
    CHECK (policy_digest ~ '^[0-9a-f]{64}$'),
    CHECK (snapshot_digest ~ '^[0-9a-f]{64}$'),
    CHECK (candidate_code_digest ~ '^[0-9a-f]{64}$'),
    CHECK (qlib_config_digest ~ '^[0-9a-f]{64}$'),
    CHECK (rdagent_commit ~ '^[0-9a-f]{40}$'),
    CHECK (qlib_commit ~ '^[0-9a-f]{40}$'),
    CHECK (docker_image_digest ~ '^sha256:[0-9a-f]{64}$'),
    CHECK (qlib_receipt_digest ~ '^[0-9a-f]{64}$'),
    CHECK (platform_receipt_digest ~ '^[0-9a-f]{64}$'),
    CHECK (comparison_digest ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(artifact_document) = 'object'),
    CHECK (version >= 1)
);

CREATE TABLE IF NOT EXISTS quant_system.d34_artifact_events (
    event_seq BIGSERIAL UNIQUE NOT NULL,
    event_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL REFERENCES quant_system.d34_artifacts(artifact_id),
    event_type TEXT NOT NULL,
    artifact_version BIGINT NOT NULL,
    event_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (event_type IN ('registered', 'canary_started', 'paused', 'demoted', 'rolled_back')),
    CHECK (jsonb_typeof(event_data) = 'object')
);

CREATE TABLE IF NOT EXISTS quant_system.d34_canaries (
    canary_id TEXT PRIMARY KEY,
    artifact_id TEXT NOT NULL UNIQUE REFERENCES quant_system.d34_artifacts(artifact_id),
    mandate_id TEXT NOT NULL REFERENCES quant_system.d34_mandates(mandate_id),
    owner_user_id UUID NOT NULL,
    workspace_id TEXT NOT NULL,
    sleeve_id TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL,
    allocated_cash NUMERIC(18,2) NOT NULL,
    nav_fraction NUMERIC(12,9) NOT NULL,
    daily_pnl NUMERIC(18,2) NOT NULL DEFAULT 0,
    drawdown_fraction NUMERIC(12,9) NOT NULL DEFAULT 0,
    peak_equity NUMERIC(18,2),
    canary_document JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    version BIGINT NOT NULL DEFAULT 1,
    CHECK (status IN ('provisioning', 'running', 'paused', 'demoted', 'rolled_back')),
    CHECK (allocated_cash >= 0),
    CHECK (nav_fraction >= 0 AND nav_fraction <= 1),
    CHECK (drawdown_fraction >= 0),
    CHECK (jsonb_typeof(canary_document) = 'object'),
    CHECK (version >= 1)
);

CREATE TABLE IF NOT EXISTS quant_system.d34_canary_events (
    event_seq BIGSERIAL UNIQUE NOT NULL,
    event_id TEXT PRIMARY KEY,
    canary_id TEXT NOT NULL REFERENCES quant_system.d34_canaries(canary_id),
    event_type TEXT NOT NULL,
    canary_version BIGINT NOT NULL,
    event_data JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (event_type IN ('provisioned', 'running', 'observed', 'paused', 'demoted', 'rolled_back')),
    CHECK (jsonb_typeof(event_data) = 'object')
);

DO $$
DECLARE table_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'd34_engine_receipts', 'd34_comparisons', 'd34_artifact_events', 'd34_canary_events'
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
        ALTER TABLE quant_system.d34_artifact_canary_meta OWNER TO quant_migrator;
        ALTER TABLE quant_system.d34_engine_receipts OWNER TO quant_migrator;
        ALTER TABLE quant_system.d34_comparisons OWNER TO quant_migrator;
        ALTER TABLE quant_system.d34_artifacts OWNER TO quant_migrator;
        ALTER TABLE quant_system.d34_artifact_events OWNER TO quant_migrator;
        ALTER TABLE quant_system.d34_canaries OWNER TO quant_migrator;
        ALTER TABLE quant_system.d34_canary_events OWNER TO quant_migrator;
        ALTER SEQUENCE quant_system.d34_artifact_events_event_seq_seq OWNER TO quant_migrator;
        ALTER SEQUENCE quant_system.d34_canary_events_event_seq_seq OWNER TO quant_migrator;
    END IF;

    REVOKE ALL ON TABLE
        quant_system.d34_artifact_canary_meta,
        quant_system.d34_engine_receipts,
        quant_system.d34_comparisons,
        quant_system.d34_artifacts,
        quant_system.d34_artifact_events,
        quant_system.d34_canaries,
        quant_system.d34_canary_events
        FROM PUBLIC;
    REVOKE ALL ON SEQUENCE
        quant_system.d34_artifact_events_event_seq_seq,
        quant_system.d34_canary_events_event_seq_seq
        FROM PUBLIC;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime') THEN
        GRANT SELECT ON TABLE quant_system.d34_artifact_canary_meta TO quant_runtime;
        GRANT SELECT, INSERT ON TABLE
            quant_system.d34_engine_receipts,
            quant_system.d34_comparisons,
            quant_system.d34_artifact_events,
            quant_system.d34_canary_events
            TO quant_runtime;
        GRANT SELECT, INSERT, UPDATE ON TABLE
            quant_system.d34_artifacts,
            quant_system.d34_canaries
            TO quant_runtime;
        GRANT USAGE, SELECT ON SEQUENCE
            quant_system.d34_artifact_events_event_seq_seq,
            quant_system.d34_canary_events_event_seq_seq
            TO quant_runtime;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_readonly') THEN
        GRANT SELECT ON TABLE
            quant_system.d34_artifact_canary_meta,
            quant_system.d34_engine_receipts,
            quant_system.d34_comparisons,
            quant_system.d34_artifacts,
            quant_system.d34_artifact_events,
            quant_system.d34_canaries,
            quant_system.d34_canary_events
            TO quant_readonly;
    END IF;
END $$;

COMMIT;
