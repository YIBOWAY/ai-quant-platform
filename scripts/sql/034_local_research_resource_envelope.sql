-- Fixed local paper-only research resources and mandate-free new D-34 writes.
-- Applying this migration is an explicit operator action; startup never applies it.

BEGIN;

SELECT pg_advisory_xact_lock(hashtextextended('quant_system:hermes_schema_runtime_gate', 0));
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:034_local_research_resource_envelope', 0)
);

DO $$
BEGIN
    IF to_regclass('quant_system.brief_rollup_issues') IS NULL THEN
        RAISE EXCEPTION 'local research resources require migration 033';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS quant_system.d34_research_resource_envelopes (
    resource_envelope_id TEXT PRIMARY KEY,
    owner_user_id UUID NOT NULL,
    workspace_id TEXT NOT NULL,
    policy_digest TEXT NOT NULL,
    policy_document JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CHECK (resource_envelope_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CHECK (workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CHECK (policy_digest ~ '^[0-9a-f]{64}$'),
    CHECK (jsonb_typeof(policy_document) = 'object'),
    UNIQUE (owner_user_id, workspace_id)
);

INSERT INTO quant_system.d34_research_resource_envelopes (
    resource_envelope_id, owner_user_id, workspace_id, policy_digest, policy_document
) VALUES (
    'local-paper-research-v1',
    '00000000-0000-0000-0000-000000000001',
    'default',
    'f539564775cd6f0c51fbd8478697265c1f4df86987513dad5e7a842b92191270',
    '{
      "contract":"hqa.local_research_resource_envelope/v1",
      "experiments_per_iteration":3,
      "llm_budget_usd":"10.000000",
      "max_concurrent_jobs":1,
      "max_iterations":3,
      "max_universe_size":64,
      "paper_only":true,
      "research_only":true,
      "timeout_seconds":7200
    }'::jsonb
) ON CONFLICT (resource_envelope_id) DO NOTHING;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM quant_system.d34_research_resource_envelopes
        WHERE resource_envelope_id = 'local-paper-research-v1'
          AND owner_user_id = '00000000-0000-0000-0000-000000000001'
          AND workspace_id = 'default'
          AND policy_digest =
              'f539564775cd6f0c51fbd8478697265c1f4df86987513dad5e7a842b92191270'
          AND policy_document = '{
            "contract":"hqa.local_research_resource_envelope/v1",
            "experiments_per_iteration":3,
            "llm_budget_usd":"10.000000",
            "max_concurrent_jobs":1,
            "max_iterations":3,
            "max_universe_size":64,
            "paper_only":true,
            "research_only":true,
            "timeout_seconds":7200
          }'::jsonb
    ) THEN
        RAISE EXCEPTION 'local research resource envelope does not match the fixed contract';
    END IF;
END $$;

ALTER TABLE quant_system.d34_experiment_jobs
    ALTER COLUMN mandate_id DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS resource_envelope_id TEXT
        REFERENCES quant_system.d34_research_resource_envelopes(resource_envelope_id);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_d34_job_single_resource_authority'
          AND conrelid = 'quant_system.d34_experiment_jobs'::regclass
    ) THEN
        ALTER TABLE quant_system.d34_experiment_jobs
        ADD CONSTRAINT ck_d34_job_single_resource_authority CHECK (
            (mandate_id IS NOT NULL)::INTEGER
            + (resource_envelope_id IS NOT NULL)::INTEGER = 1
        );
    END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_d34_local_research_job_key
ON quant_system.d34_experiment_jobs (owner_user_id, workspace_id, job_key)
WHERE resource_envelope_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS uq_d34_one_active_local_research_job
ON quant_system.d34_experiment_jobs (owner_user_id, workspace_id)
WHERE state IN ('queued', 'leased', 'running')
  AND resource_envelope_id IS NOT NULL;

ALTER TABLE quant_system.d34_budget_events
    ALTER COLUMN mandate_id DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS resource_envelope_id TEXT
        REFERENCES quant_system.d34_research_resource_envelopes(resource_envelope_id);

ALTER TABLE quant_system.d34_policy_decisions
    ALTER COLUMN mandate_id DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS resource_envelope_id TEXT
        REFERENCES quant_system.d34_research_resource_envelopes(resource_envelope_id);

ALTER TABLE quant_system.d34_engine_receipts
    ALTER COLUMN mandate_id DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS resource_envelope_id TEXT
        REFERENCES quant_system.d34_research_resource_envelopes(resource_envelope_id);

ALTER TABLE quant_system.d34_artifacts
    ALTER COLUMN mandate_id DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS resource_envelope_id TEXT
        REFERENCES quant_system.d34_research_resource_envelopes(resource_envelope_id);

DO $$
DECLARE
    table_name TEXT;
    constraint_name TEXT;
BEGIN
    FOR table_name, constraint_name IN
        SELECT * FROM (VALUES
            ('d34_budget_events', 'ck_d34_budget_event_single_resource_authority'),
            ('d34_policy_decisions', 'ck_d34_policy_single_resource_authority'),
            ('d34_engine_receipts', 'ck_d34_receipt_single_resource_authority'),
            ('d34_artifacts', 'ck_d34_artifact_single_resource_authority')
        ) AS constraints(table_name, constraint_name)
    LOOP
        IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = constraint_name
              AND conrelid = format('quant_system.%I', table_name)::regclass
        ) THEN
            EXECUTE format(
                'ALTER TABLE quant_system.%I ADD CONSTRAINT %I CHECK ((mandate_id IS NOT NULL)::INTEGER + (resource_envelope_id IS NOT NULL)::INTEGER = 1)',
                table_name,
                constraint_name
            );
        END IF;
    END LOOP;
END $$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator') THEN
        ALTER TABLE quant_system.d34_research_resource_envelopes OWNER TO quant_migrator;
    END IF;
    REVOKE ALL ON TABLE quant_system.d34_research_resource_envelopes FROM PUBLIC;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime') THEN
        GRANT SELECT ON TABLE quant_system.d34_research_resource_envelopes TO quant_runtime;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_readonly') THEN
        GRANT SELECT ON TABLE quant_system.d34_research_resource_envelopes TO quant_readonly;
    END IF;
END $$;

COMMIT;
