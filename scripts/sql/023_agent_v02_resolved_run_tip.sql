-- Agent v0.2 exact Run-tip identity.
--
-- `hermes_session_id` remains the stable managed-conversation root.  The new
-- `resolved_hermes_session_id` records the immutable compression tip used by
-- one exact Hermes Run.  Legacy uncompressed rows are backfilled root == tip.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:023_agent_v02_resolved_run_tip', 0)
);

ALTER TABLE quant_system.hermes_commands
    ADD COLUMN IF NOT EXISTS resolved_hermes_session_id TEXT;
ALTER TABLE quant_system.hermes_command_events
    ADD COLUMN IF NOT EXISTS resolved_hermes_session_id TEXT;
ALTER TABLE quant_system.hermes_run_links
    ADD COLUMN IF NOT EXISTS resolved_hermes_session_id TEXT;

-- The two evidence tables are append-only at runtime.  The global migration
-- gate fences writers while this one-time legacy projection is repaired.
ALTER TABLE quant_system.hermes_command_events
    DISABLE TRIGGER trg_hermes_command_events_append_only;
ALTER TABLE quant_system.hermes_run_links
    DISABLE TRIGGER trg_hermes_run_links_append_only;

UPDATE quant_system.hermes_commands
SET resolved_hermes_session_id = hermes_session_id
WHERE hermes_run_id IS NOT NULL
  AND resolved_hermes_session_id IS NULL;

UPDATE quant_system.hermes_command_events
SET resolved_hermes_session_id = hermes_session_id
WHERE hermes_run_id IS NOT NULL
  AND resolved_hermes_session_id IS NULL;

UPDATE quant_system.hermes_run_links
SET resolved_hermes_session_id = hermes_session_id
WHERE resolved_hermes_session_id IS NULL;

ALTER TABLE quant_system.hermes_command_events
    ENABLE ALWAYS TRIGGER trg_hermes_command_events_append_only;
ALTER TABLE quant_system.hermes_run_links
    ENABLE ALWAYS TRIGGER trg_hermes_run_links_append_only;

ALTER TABLE quant_system.hermes_commands
    DROP CONSTRAINT IF EXISTS ck_hermes_commands_resolved_run_tip;
ALTER TABLE quant_system.hermes_commands
    ADD CONSTRAINT ck_hermes_commands_resolved_run_tip
    CHECK (
        resolved_hermes_session_id IS NULL
        OR (
            char_length(resolved_hermes_session_id) BETWEEN 1 AND 256
            AND resolved_hermes_session_id
                ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        )
    );
ALTER TABLE quant_system.hermes_commands
    DROP CONSTRAINT IF EXISTS ck_hermes_commands_run_requires_resolved_tip;
ALTER TABLE quant_system.hermes_commands
    ADD CONSTRAINT ck_hermes_commands_run_requires_resolved_tip
    CHECK (
        hermes_run_id IS NULL
        OR (
            hermes_session_id IS NOT NULL
            AND resolved_hermes_session_id IS NOT NULL
        )
    );

ALTER TABLE quant_system.hermes_command_events
    DROP CONSTRAINT IF EXISTS ck_hermes_command_events_resolved_run_tip;
ALTER TABLE quant_system.hermes_command_events
    ADD CONSTRAINT ck_hermes_command_events_resolved_run_tip
    CHECK (
        resolved_hermes_session_id IS NULL
        OR (
            char_length(resolved_hermes_session_id) BETWEEN 1 AND 256
            AND resolved_hermes_session_id
                ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        )
    );
ALTER TABLE quant_system.hermes_command_events
    DROP CONSTRAINT IF EXISTS
        ck_hermes_command_events_run_requires_resolved_tip;
ALTER TABLE quant_system.hermes_command_events
    ADD CONSTRAINT ck_hermes_command_events_run_requires_resolved_tip
    CHECK (
        hermes_run_id IS NULL
        OR (
            hermes_session_id IS NOT NULL
            AND resolved_hermes_session_id IS NOT NULL
        )
    );

ALTER TABLE quant_system.hermes_run_links
    ALTER COLUMN resolved_hermes_session_id SET NOT NULL;
ALTER TABLE quant_system.hermes_run_links
    DROP CONSTRAINT IF EXISTS ck_hermes_run_links_resolved_run_tip;
ALTER TABLE quant_system.hermes_run_links
    ADD CONSTRAINT ck_hermes_run_links_resolved_run_tip
    CHECK (
        char_length(resolved_hermes_session_id) BETWEEN 1 AND 256
        AND resolved_hermes_session_id
            ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
    );

DROP INDEX IF EXISTS quant_system.uq_hermes_commands_upstream_run;
CREATE UNIQUE INDEX uq_hermes_commands_upstream_run
    ON quant_system.hermes_commands (
        hermes_session_id,
        resolved_hermes_session_id,
        hermes_run_id
    )
    WHERE hermes_run_id IS NOT NULL;

ALTER TABLE quant_system.hermes_run_links
    DROP CONSTRAINT IF EXISTS
        hermes_run_links_hermes_session_id_hermes_run_id_platform_r_key;
ALTER TABLE quant_system.hermes_run_links
    ADD CONSTRAINT
        hermes_run_links_hermes_session_id_hermes_run_id_platform_r_key
    UNIQUE (
        hermes_session_id,
        resolved_hermes_session_id,
        hermes_run_id,
        platform_resource_type,
        platform_resource_id,
        relation
    );

DROP INDEX IF EXISTS quant_system.idx_hermes_run_links_hermes_run;
CREATE INDEX idx_hermes_run_links_hermes_run
    ON quant_system.hermes_run_links (
        hermes_session_id,
        resolved_hermes_session_id,
        hermes_run_id
    );

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime') THEN
        GRANT SELECT (resolved_hermes_session_id)
            ON quant_system.hermes_commands,
               quant_system.hermes_command_events,
               quant_system.hermes_run_links
            TO quant_runtime;
        GRANT INSERT (resolved_hermes_session_id),
              UPDATE (resolved_hermes_session_id)
            ON quant_system.hermes_commands
            TO quant_runtime;
        GRANT INSERT (resolved_hermes_session_id)
            ON quant_system.hermes_command_events,
               quant_system.hermes_run_links
            TO quant_runtime;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_readonly') THEN
        GRANT SELECT (resolved_hermes_session_id)
            ON quant_system.hermes_commands,
               quant_system.hermes_command_events,
               quant_system.hermes_run_links
            TO quant_readonly;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator') THEN
        ALTER TABLE quant_system.hermes_commands OWNER TO quant_migrator;
        ALTER TABLE quant_system.hermes_command_events OWNER TO quant_migrator;
        ALTER TABLE quant_system.hermes_run_links OWNER TO quant_migrator;
    END IF;
END $$;

ALTER TABLE quant_system.hermes_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_commands FORCE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_command_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_command_events FORCE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_run_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_run_links FORCE ROW LEVEL SECURITY;

COMMIT;
