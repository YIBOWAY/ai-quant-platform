-- Durable liveness authority for the Agent v0.2 connector daemon.
--
-- The live process holds one session-level PostgreSQL advisory lock for the
-- whole lease.  PostgreSQL releases that lock if the process/connection dies.
-- Rows are durable evidence only: they contain no prompt, provider, strategy,
-- order, or trading payload.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:014_agent_v02_connector_liveness', 0)
);

CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_connector_liveness_meta (
    singleton       BOOLEAN PRIMARY KEY DEFAULT TRUE,
    schema_version  INTEGER NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_agent_v02_connector_meta_singleton CHECK (singleton),
    CONSTRAINT ck_agent_v02_connector_meta_version CHECK (schema_version > 0)
);

INSERT INTO quant_system.agent_v02_connector_liveness_meta (
    singleton,
    schema_version
)
VALUES (TRUE, 1)
ON CONFLICT (singleton) DO NOTHING;

DO $$
DECLARE
    installed_version INTEGER;
BEGIN
    SELECT schema_version
    INTO installed_version
    FROM quant_system.agent_v02_connector_liveness_meta
    WHERE singleton IS TRUE;

    IF installed_version > 1 THEN
        RAISE EXCEPTION
            'Agent v0.2 connector liveness schema version % is newer than this binary supports (1)',
            installed_version;
    ELSIF installed_version <> 1 THEN
        RAISE EXCEPTION
            'Agent v0.2 connector liveness schema version % is incompatible with this binary (expected 1)',
            installed_version;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_connector_workers (
    generation_token  UUID PRIMARY KEY,
    owner_user_id     UUID NOT NULL
        REFERENCES quant_system.app_users(id),
    workspace_id      TEXT NOT NULL,
    worker_id         TEXT NOT NULL,
    mode              TEXT NOT NULL,
    runtime_digest    CHAR(64) NOT NULL,
    status            TEXT NOT NULL DEFAULT 'active',
    started_at        TIMESTAMPTZ NOT NULL,
    heartbeat_at      TIMESTAMPTZ NOT NULL,
    stopped_at        TIMESTAMPTZ,
    stop_reason       TEXT,
    CONSTRAINT ck_agent_v02_connector_workspace_id
        CHECK (
            char_length(workspace_id) BETWEEN 1 AND 200
            AND workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_connector_worker_id
        CHECK (
            char_length(worker_id) BETWEEN 1 AND 200
            AND worker_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_connector_mode
        CHECK (mode IN ('supervised_dispatch', 'reconcile_only')),
    CONSTRAINT ck_agent_v02_connector_runtime_digest
        CHECK (runtime_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_connector_status
        CHECK (status IN ('active', 'stopped', 'stale')),
    CONSTRAINT ck_agent_v02_connector_heartbeat_order
        CHECK (heartbeat_at >= started_at),
    CONSTRAINT ck_agent_v02_connector_terminal_shape
        CHECK (
            (
                status = 'active'
                AND stopped_at IS NULL
                AND stop_reason IS NULL
            )
            OR
            (
                status IN ('stopped', 'stale')
                AND stopped_at IS NOT NULL
                AND stopped_at >= heartbeat_at
                AND char_length(stop_reason) BETWEEN 1 AND 500
            )
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_v02_connector_one_active_workspace
    ON quant_system.agent_v02_connector_workers (workspace_id)
    WHERE status = 'active';

CREATE INDEX IF NOT EXISTS idx_agent_v02_connector_workspace_started
    ON quant_system.agent_v02_connector_workers (
        workspace_id,
        started_at DESC,
        generation_token
    );

CREATE OR REPLACE FUNCTION quant_system.guard_agent_v02_connector_worker()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION
            'Agent v0.2 connector liveness evidence is not deletable';
    END IF;

    IF NEW.generation_token IS DISTINCT FROM OLD.generation_token
       OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.worker_id IS DISTINCT FROM OLD.worker_id
       OR NEW.mode IS DISTINCT FROM OLD.mode
       OR NEW.runtime_digest IS DISTINCT FROM OLD.runtime_digest
       OR NEW.started_at IS DISTINCT FROM OLD.started_at
    THEN
        RAISE EXCEPTION
            'Agent v0.2 connector generation identity is immutable';
    END IF;

    IF OLD.status <> 'active' THEN
        RAISE EXCEPTION
            'Terminal Agent v0.2 connector generations are immutable';
    END IF;

    IF NEW.heartbeat_at < OLD.heartbeat_at THEN
        RAISE EXCEPTION
            'Agent v0.2 connector heartbeat cannot move backwards';
    END IF;

    IF NEW.status NOT IN ('active', 'stopped', 'stale') THEN
        RAISE EXCEPTION
            'Invalid Agent v0.2 connector status transition';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_agent_v02_connector_worker_guard
    ON quant_system.agent_v02_connector_workers;
CREATE TRIGGER trg_agent_v02_connector_worker_guard
BEFORE UPDATE OR DELETE ON quant_system.agent_v02_connector_workers
FOR EACH ROW
EXECUTE FUNCTION quant_system.guard_agent_v02_connector_worker();
ALTER TABLE quant_system.agent_v02_connector_workers
    ENABLE ALWAYS TRIGGER trg_agent_v02_connector_worker_guard;

-- V4-R roles are normally present because migration 010 precedes this file.
-- Keeping the block conditional makes an isolated source/readiness install
-- fail closed and lets a later replay repair grants once those roles exist.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_readonly')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator')
    THEN
        GRANT USAGE ON SCHEMA quant_system
            TO quant_runtime, quant_readonly, quant_migrator;
        REVOKE CREATE ON SCHEMA quant_system
            FROM quant_runtime, quant_readonly;

        ALTER TABLE quant_system.agent_v02_connector_workers
            ENABLE ROW LEVEL SECURITY;
        ALTER TABLE quant_system.agent_v02_connector_workers
            FORCE ROW LEVEL SECURITY;

        DROP POLICY IF EXISTS v4r_root_scope
            ON quant_system.agent_v02_connector_workers;
        CREATE POLICY v4r_root_scope
            ON quant_system.agent_v02_connector_workers
            FOR ALL TO quant_runtime, quant_readonly
            USING (
                owner_user_id =
                '00000000-0000-0000-0000-000000000001'::uuid
            )
            WITH CHECK (
                owner_user_id =
                '00000000-0000-0000-0000-000000000001'::uuid
            );

        DROP POLICY IF EXISTS v4r_migrator_all
            ON quant_system.agent_v02_connector_workers;
        CREATE POLICY v4r_migrator_all
            ON quant_system.agent_v02_connector_workers
            FOR ALL TO quant_migrator
            USING (true)
            WITH CHECK (true);

        GRANT SELECT, INSERT, UPDATE
            ON quant_system.agent_v02_connector_workers
            TO quant_runtime;
        REVOKE DELETE, TRUNCATE
            ON quant_system.agent_v02_connector_workers
            FROM quant_runtime;

        GRANT SELECT
            ON quant_system.agent_v02_connector_workers,
               quant_system.agent_v02_connector_liveness_meta
            TO quant_readonly;
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE
            ON quant_system.agent_v02_connector_workers,
               quant_system.agent_v02_connector_liveness_meta
            FROM quant_readonly;

        GRANT SELECT
            ON quant_system.agent_v02_connector_liveness_meta
            TO quant_runtime;
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE
            ON quant_system.agent_v02_connector_liveness_meta
            FROM quant_runtime;

        REVOKE ALL
            ON quant_system.agent_v02_connector_workers,
               quant_system.agent_v02_connector_liveness_meta
            FROM PUBLIC;
        REVOKE EXECUTE
            ON FUNCTION quant_system.guard_agent_v02_connector_worker()
            FROM PUBLIC;

        GRANT ALL
            ON quant_system.agent_v02_connector_workers,
               quant_system.agent_v02_connector_liveness_meta
            TO quant_migrator;
        GRANT EXECUTE
            ON FUNCTION quant_system.guard_agent_v02_connector_worker()
            TO quant_migrator;

        ALTER TABLE quant_system.agent_v02_connector_workers
            OWNER TO quant_migrator;
        ALTER TABLE quant_system.agent_v02_connector_liveness_meta
            OWNER TO quant_migrator;
        ALTER FUNCTION quant_system.guard_agent_v02_connector_worker()
            OWNER TO quant_migrator;
    END IF;
END $$;

COMMIT;
