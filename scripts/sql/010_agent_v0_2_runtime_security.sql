-- Agent v0.2 V4-R: managed-session retention policy and least-privilege DB roles.
--
-- This migration is schema/provisioning only.  It creates NOLOGIN group roles;
-- operator-owned LOGIN principals/passwords are deliberately out of band.  It
-- performs no Hermes/provider/trading call and never enables a public writer.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:010_agent_v0_2_runtime_security', 0)
);

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator') THEN
        CREATE ROLE quant_migrator
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime') THEN
        CREATE ROLE quant_runtime
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_readonly') THEN
        CREATE ROLE quant_readonly
            NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
END $$;

-- Replay is corrective, not merely additive: a pre-existing or drifted role
-- must not retain LOGIN, superuser, DDL, replication, or RLS-bypass powers.
-- The bootstrap superuser repairs drift.  A later non-superuser migrator
-- cannot alter cluster roles, so it verifies the same signature and aborts on
-- drift instead of silently accepting it.
DO $$
DECLARE
    role_name TEXT;
BEGIN
    IF EXISTS (
        SELECT 1 FROM pg_roles
        WHERE rolname = current_user AND rolsuper
    ) THEN
        FOREACH role_name IN ARRAY ARRAY[
            'quant_migrator', 'quant_runtime', 'quant_readonly'
        ]
        LOOP
            EXECUTE format(
                'ALTER ROLE %I NOLOGIN NOSUPERUSER NOCREATEDB '
                'NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS',
                role_name
            );
        END LOOP;
    ELSIF EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname IN (
            'quant_migrator', 'quant_runtime', 'quant_readonly'
        )
          AND (
              rolcanlogin OR rolsuper OR rolcreatedb OR rolcreaterole
              OR rolinherit OR rolreplication OR rolbypassrls
          )
    ) THEN
        RAISE EXCEPTION
            'V4-R group role attributes drifted; superuser repair required';
    END IF;
END $$;

DO $$
BEGIN
    EXECUTE format(
        'GRANT CONNECT, TEMPORARY, CREATE ON DATABASE %I TO quant_migrator',
        current_database()
    );
END $$;

CREATE TABLE IF NOT EXISTS quant_system.hermes_security_meta (
    singleton       BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    schema_version  INTEGER NOT NULL CHECK (schema_version = 1),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO quant_system.hermes_security_meta (singleton, schema_version)
VALUES (TRUE, 1)
ON CONFLICT (singleton) DO UPDATE
SET schema_version = EXCLUDED.schema_version,
    updated_at = now();

-- The policy belongs to the managed session and is immutable after create.
-- External observed sessions never own Intent Payload Store bodies, hence NULL.
ALTER TABLE quant_system.hermes_workspace_sessions
    ADD COLUMN IF NOT EXISTS payload_ttl_days SMALLINT;

UPDATE quant_system.hermes_workspace_sessions
SET payload_ttl_days = 7
WHERE kind = 'web_managed_session'
  AND payload_ttl_days IS NULL;

ALTER TABLE quant_system.hermes_workspace_sessions
    DROP CONSTRAINT IF EXISTS ck_hermes_workspace_session_payload_ttl;
ALTER TABLE quant_system.hermes_workspace_sessions
    ADD CONSTRAINT ck_hermes_workspace_session_payload_ttl
    CHECK (
        (kind = 'observed_external_session' AND payload_ttl_days IS NULL)
        OR
        (
            kind = 'web_managed_session'
            AND payload_ttl_days = 7
        )
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
       OR NEW.parent_platform_session_id IS DISTINCT FROM OLD.parent_platform_session_id
       OR NEW.fork_point IS DISTINCT FROM OLD.fork_point
       OR NEW.source_channel IS DISTINCT FROM OLD.source_channel
       OR NEW.platform_session_id IS DISTINCT FROM OLD.platform_session_id
    THEN
        RAISE EXCEPTION
            'Hermes workspace session identity, lineage and payload policy are immutable';
    END IF;

    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

ALTER TABLE quant_system.hermes_workspace_sessions
    ENABLE ALWAYS TRIGGER trg_hermes_workspace_session_immutability;

GRANT USAGE ON SCHEMA quant_system
    TO quant_runtime, quant_readonly, quant_migrator;
GRANT CREATE ON SCHEMA quant_system TO quant_migrator;

-- Runtime must continue to serve the wider local platform without inheriting
-- superuser/DDL powers.  Hermes tables are narrowed again below.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA quant_system
    TO quant_runtime;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA quant_system TO quant_runtime;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA quant_system TO quant_runtime;

GRANT SELECT ON ALL TABLES IN SCHEMA quant_system TO quant_readonly;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA quant_system TO quant_readonly;

GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA quant_system TO quant_migrator;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA quant_system TO quant_migrator;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA quant_system TO quant_migrator;

REVOKE DELETE, TRUNCATE ON
    quant_system.hermes_commands,
    quant_system.hermes_command_events,
    quant_system.hermes_outbox,
    quant_system.hermes_run_links,
    quant_system.hermes_command_workflow_bindings,
    quant_system.hermes_workspace_sessions
FROM quant_runtime;

REVOKE UPDATE ON
    quant_system.hermes_command_events,
    quant_system.hermes_run_links,
    quant_system.hermes_command_workflow_bindings,
    quant_system.hermes_workspace_sessions
FROM quant_runtime;

REVOKE ALL ON
    quant_system.hermes_commands,
    quant_system.hermes_command_events,
    quant_system.hermes_outbox,
    quant_system.hermes_run_links,
    quant_system.hermes_command_workflow_bindings,
    quant_system.hermes_workspace_sessions
FROM PUBLIC;

-- Policies are recreated deterministically so replay repairs definition drift.
DROP POLICY IF EXISTS v4r_root_scope ON quant_system.app_users;
CREATE POLICY v4r_root_scope ON quant_system.app_users
    TO quant_runtime, quant_readonly
    USING (id = '00000000-0000-0000-0000-000000000001'::uuid)
    WITH CHECK (id = '00000000-0000-0000-0000-000000000001'::uuid);

DROP POLICY IF EXISTS v4r_migrator_all ON quant_system.app_users;
CREATE POLICY v4r_migrator_all ON quant_system.app_users
    TO quant_migrator USING (TRUE) WITH CHECK (TRUE);

DROP POLICY IF EXISTS v4r_root_scope ON quant_system.hermes_commands;
CREATE POLICY v4r_root_scope ON quant_system.hermes_commands
    TO quant_runtime, quant_readonly
    USING (owner_user_id = '00000000-0000-0000-0000-000000000001'::uuid)
    WITH CHECK (owner_user_id = '00000000-0000-0000-0000-000000000001'::uuid);

DROP POLICY IF EXISTS v4r_migrator_all ON quant_system.hermes_commands;
CREATE POLICY v4r_migrator_all ON quant_system.hermes_commands
    TO quant_migrator USING (TRUE) WITH CHECK (TRUE);

DROP POLICY IF EXISTS v4r_root_scope ON quant_system.hermes_command_workflow_bindings;
CREATE POLICY v4r_root_scope ON quant_system.hermes_command_workflow_bindings
    TO quant_runtime, quant_readonly
    USING (owner_user_id = '00000000-0000-0000-0000-000000000001'::uuid)
    WITH CHECK (owner_user_id = '00000000-0000-0000-0000-000000000001'::uuid);

DROP POLICY IF EXISTS v4r_migrator_all ON quant_system.hermes_command_workflow_bindings;
CREATE POLICY v4r_migrator_all ON quant_system.hermes_command_workflow_bindings
    TO quant_migrator USING (TRUE) WITH CHECK (TRUE);

DROP POLICY IF EXISTS v4r_root_scope ON quant_system.hermes_workspace_sessions;
CREATE POLICY v4r_root_scope ON quant_system.hermes_workspace_sessions
    TO quant_runtime, quant_readonly
    USING (owner_user_id = '00000000-0000-0000-0000-000000000001'::uuid)
    WITH CHECK (owner_user_id = '00000000-0000-0000-0000-000000000001'::uuid);

DROP POLICY IF EXISTS v4r_migrator_all ON quant_system.hermes_workspace_sessions;
CREATE POLICY v4r_migrator_all ON quant_system.hermes_workspace_sessions
    TO quant_migrator USING (TRUE) WITH CHECK (TRUE);

DROP POLICY IF EXISTS v4r_root_scope ON quant_system.hermes_command_events;
CREATE POLICY v4r_root_scope ON quant_system.hermes_command_events
    TO quant_runtime, quant_readonly
    USING (
        EXISTS (
            SELECT 1 FROM quant_system.hermes_commands AS command
            WHERE command.command_id = hermes_command_events.command_id
              AND command.owner_user_id =
                  '00000000-0000-0000-0000-000000000001'::uuid
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM quant_system.hermes_commands AS command
            WHERE command.command_id = hermes_command_events.command_id
              AND command.owner_user_id =
                  '00000000-0000-0000-0000-000000000001'::uuid
        )
    );

DROP POLICY IF EXISTS v4r_migrator_all ON quant_system.hermes_command_events;
CREATE POLICY v4r_migrator_all ON quant_system.hermes_command_events
    TO quant_migrator USING (TRUE) WITH CHECK (TRUE);

DROP POLICY IF EXISTS v4r_root_scope ON quant_system.hermes_outbox;
CREATE POLICY v4r_root_scope ON quant_system.hermes_outbox
    TO quant_runtime, quant_readonly
    USING (
        EXISTS (
            SELECT 1 FROM quant_system.hermes_commands AS command
            WHERE command.command_id = hermes_outbox.command_id
              AND command.owner_user_id =
                  '00000000-0000-0000-0000-000000000001'::uuid
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM quant_system.hermes_commands AS command
            WHERE command.command_id = hermes_outbox.command_id
              AND command.owner_user_id =
                  '00000000-0000-0000-0000-000000000001'::uuid
        )
    );

DROP POLICY IF EXISTS v4r_migrator_all ON quant_system.hermes_outbox;
CREATE POLICY v4r_migrator_all ON quant_system.hermes_outbox
    TO quant_migrator USING (TRUE) WITH CHECK (TRUE);

DROP POLICY IF EXISTS v4r_root_scope ON quant_system.hermes_run_links;
CREATE POLICY v4r_root_scope ON quant_system.hermes_run_links
    TO quant_runtime, quant_readonly
    USING (
        EXISTS (
            SELECT 1 FROM quant_system.hermes_commands AS command
            WHERE command.command_id = hermes_run_links.command_id
              AND command.owner_user_id =
                  '00000000-0000-0000-0000-000000000001'::uuid
        )
    )
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM quant_system.hermes_commands AS command
            WHERE command.command_id = hermes_run_links.command_id
              AND command.owner_user_id =
                  '00000000-0000-0000-0000-000000000001'::uuid
        )
    );

DROP POLICY IF EXISTS v4r_migrator_all ON quant_system.hermes_run_links;
CREATE POLICY v4r_migrator_all ON quant_system.hermes_run_links
    TO quant_migrator USING (TRUE) WITH CHECK (TRUE);

ALTER TABLE quant_system.app_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_system.app_users FORCE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_commands ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_commands FORCE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_command_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_command_events FORCE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_outbox ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_outbox FORCE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_run_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_run_links FORCE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_command_workflow_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_command_workflow_bindings FORCE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_workspace_sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE quant_system.hermes_workspace_sessions FORCE ROW LEVEL SECURITY;

-- Ownership is the DDL capability boundary: grants alone cannot ALTER an
-- existing object.  Moving the schema's objects to the NOLOGIN migrator group
-- lets an operator-owned non-superuser LOGIN SET ROLE quant_migrator and replay
-- the lexical migration set without inheriting the old quant superuser.
DO $$
DECLARE
    object_row RECORD;
    object_kind TEXT;
BEGIN
    FOR object_row IN
        SELECT relation.relname, relation.relkind
        FROM pg_class AS relation
        JOIN pg_namespace AS namespace
          ON namespace.oid = relation.relnamespace
        WHERE namespace.nspname = 'quant_system'
          AND relation.relkind IN ('r', 'p', 'v', 'm', 'f')
    LOOP
        object_kind := CASE object_row.relkind
            WHEN 'v' THEN 'VIEW'
            WHEN 'm' THEN 'MATERIALIZED VIEW'
            WHEN 'f' THEN 'FOREIGN TABLE'
            ELSE 'TABLE'
        END;
        EXECUTE format(
            'ALTER %s quant_system.%I OWNER TO quant_migrator',
            object_kind,
            object_row.relname
        );
    END LOOP;

    FOR object_row IN
        SELECT
            routine.oid,
            routine.proname,
            routine.prokind,
            pg_get_function_identity_arguments(routine.oid) AS identity_arguments
        FROM pg_proc AS routine
        JOIN pg_namespace AS namespace
          ON namespace.oid = routine.pronamespace
        WHERE namespace.nspname = 'quant_system'
          AND routine.prokind IN ('f', 'p')
    LOOP
        object_kind := CASE object_row.prokind
            WHEN 'p' THEN 'PROCEDURE'
            ELSE 'FUNCTION'
        END;
        EXECUTE format(
            'ALTER %s quant_system.%I(%s) OWNER TO quant_migrator',
            object_kind,
            object_row.proname,
            object_row.identity_arguments
        );
    END LOOP;
END $$;

ALTER SCHEMA quant_system OWNER TO quant_migrator;

ALTER DEFAULT PRIVILEGES FOR ROLE quant_migrator IN SCHEMA quant_system
    REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE quant_migrator IN SCHEMA quant_system
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO quant_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE quant_migrator IN SCHEMA quant_system
    GRANT SELECT ON TABLES TO quant_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE quant_migrator IN SCHEMA quant_system
    GRANT USAGE, SELECT ON SEQUENCES TO quant_runtime;
ALTER DEFAULT PRIVILEGES FOR ROLE quant_migrator IN SCHEMA quant_system
    GRANT SELECT ON SEQUENCES TO quant_readonly;
ALTER DEFAULT PRIVILEGES FOR ROLE quant_migrator IN SCHEMA quant_system
    REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE quant_migrator IN SCHEMA quant_system
    GRANT EXECUTE ON FUNCTIONS TO quant_runtime;

COMMIT;
