-- Durable operator release authority for Agent v0.2.
--
-- This migration stores only content-addressed runtime/schema/evidence
-- identities, operator action receipts, cutover state, and append-only events.
-- It stores no prompt bodies, provider credentials, or trading instructions.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:012_agent_v0_2_release_authority', 0)
);

CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_release_authority_meta (
    singleton       BOOLEAN PRIMARY KEY DEFAULT TRUE,
    schema_version  INTEGER NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_agent_v02_release_meta_singleton CHECK (singleton),
    CONSTRAINT ck_agent_v02_release_meta_version CHECK (schema_version > 0)
);

INSERT INTO quant_system.agent_v02_release_authority_meta (
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
    FROM quant_system.agent_v02_release_authority_meta
    WHERE singleton IS TRUE;

    IF installed_version > 1 THEN
        RAISE EXCEPTION
            'Agent v0.2 release authority schema version % is newer than this binary supports (1)',
            installed_version;
    ELSIF installed_version <> 1 THEN
        RAISE EXCEPTION
            'Agent v0.2 release authority schema version % is incompatible with this binary (expected 1)',
            installed_version;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_release_stamps (
    stamp_id                      TEXT PRIMARY KEY,
    owner_user_id                 UUID NOT NULL
        REFERENCES quant_system.app_users(id),
    workspace_id                  TEXT NOT NULL,
    route                         TEXT NOT NULL,
    platform_runtime_digest       CHAR(64) NOT NULL,
    hqa_runtime_digest            CHAR(64) NOT NULL,
    hermes_runtime_digest         CHAR(64) NOT NULL,
    database_schema_fingerprint   CHAR(64) NOT NULL,
    evidence_digest               CHAR(64) NOT NULL,
    release_digest                CHAR(64) NOT NULL UNIQUE,
    status                        TEXT NOT NULL DEFAULT 'active',
    opened_at                     TIMESTAMPTZ NOT NULL,
    closed_at                     TIMESTAMPTZ,
    close_reason                  TEXT,
    CONSTRAINT ck_agent_v02_release_stamp_id
        CHECK (
            char_length(stamp_id) BETWEEN 1 AND 200
            AND stamp_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_release_workspace_id
        CHECK (
            char_length(workspace_id) BETWEEN 1 AND 200
            AND workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_release_route CHECK (route = '/hermes'),
    CONSTRAINT ck_agent_v02_release_platform_digest
        CHECK (platform_runtime_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_release_hqa_digest
        CHECK (hqa_runtime_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_release_hermes_digest
        CHECK (hermes_runtime_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_release_schema_fingerprint
        CHECK (database_schema_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_release_evidence_digest
        CHECK (evidence_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_release_digest
        CHECK (release_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_release_status
        CHECK (status IN ('active', 'closed')),
    CONSTRAINT ck_agent_v02_release_terminal_shape
        CHECK (
            (
                status = 'active'
                AND closed_at IS NULL
                AND close_reason IS NULL
            )
            OR
            (
                status = 'closed'
                AND closed_at IS NOT NULL
                AND char_length(close_reason) BETWEEN 1 AND 500
            )
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_v02_release_one_active_workspace
    ON quant_system.agent_v02_release_stamps (workspace_id)
    WHERE status = 'active';

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_public_cutovers (
    cutover_id       TEXT PRIMARY KEY,
    stamp_id         TEXT NOT NULL
        REFERENCES quant_system.agent_v02_release_stamps(stamp_id),
    owner_user_id    UUID NOT NULL
        REFERENCES quant_system.app_users(id),
    workspace_id     TEXT NOT NULL,
    route            TEXT NOT NULL,
    release_digest   CHAR(64) NOT NULL,
    cutover_digest   CHAR(64) NOT NULL UNIQUE,
    status            TEXT NOT NULL DEFAULT 'open',
    opened_at         TIMESTAMPTZ NOT NULL,
    closed_at         TIMESTAMPTZ,
    close_reason      TEXT,
    CONSTRAINT uq_agent_v02_cutover_stamp_digest
        UNIQUE (stamp_id, release_digest),
    CONSTRAINT ck_agent_v02_cutover_id
        CHECK (
            char_length(cutover_id) BETWEEN 1 AND 200
            AND cutover_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_cutover_workspace_id
        CHECK (
            char_length(workspace_id) BETWEEN 1 AND 200
            AND workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_cutover_route CHECK (route = '/hermes'),
    CONSTRAINT ck_agent_v02_cutover_release_digest
        CHECK (release_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_cutover_digest
        CHECK (cutover_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_cutover_status
        CHECK (status IN ('open', 'closed')),
    CONSTRAINT ck_agent_v02_cutover_terminal_shape
        CHECK (
            (
                status = 'open'
                AND closed_at IS NULL
                AND close_reason IS NULL
            )
            OR
            (
                status = 'closed'
                AND closed_at IS NOT NULL
                AND char_length(close_reason) BETWEEN 1 AND 500
            )
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_v02_cutover_one_open_workspace
    ON quant_system.agent_v02_public_cutovers (workspace_id)
    WHERE status = 'open';

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_release_events (
    event_cursor     BIGSERIAL PRIMARY KEY,
    event_id         TEXT NOT NULL UNIQUE,
    owner_user_id    UUID NOT NULL
        REFERENCES quant_system.app_users(id),
    workspace_id     TEXT NOT NULL,
    stamp_id         TEXT,
    cutover_id       TEXT,
    event_type       TEXT NOT NULL,
    event_data       JSONB NOT NULL,
    occurred_at      TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_agent_v02_release_event_id
        CHECK (
            char_length(event_id) BETWEEN 1 AND 200
            AND event_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_release_event_workspace_id
        CHECK (
            char_length(workspace_id) BETWEEN 1 AND 200
            AND workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_release_event_type
        CHECK (
            event_type IN (
                'release.opened',
                'release.closed',
                'public_cutover.opened',
                'public_cutover.closed'
            )
        ),
    CONSTRAINT ck_agent_v02_release_event_data_object
        CHECK (jsonb_typeof(event_data) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_agent_v02_release_events_workspace_cursor
    ON quant_system.agent_v02_release_events (workspace_id, event_cursor);

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_release_actions (
    owner_user_id       UUID NOT NULL
        REFERENCES quant_system.app_users(id),
    workspace_id        TEXT NOT NULL,
    client_action_id    TEXT NOT NULL,
    operation           TEXT NOT NULL,
    action_digest       CHAR(64) NOT NULL,
    receipt             JSONB NOT NULL,
    created_at          TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (workspace_id, client_action_id),
    CONSTRAINT ck_agent_v02_release_action_workspace_id
        CHECK (
            char_length(workspace_id) BETWEEN 1 AND 200
            AND workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_release_client_action_id
        CHECK (
            char_length(client_action_id) BETWEEN 1 AND 200
            AND client_action_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_release_operation
        CHECK (
            operation IN (
                'release.open',
                'release.close',
                'public_cutover.open',
                'public_cutover.close'
            )
        ),
    CONSTRAINT ck_agent_v02_release_action_digest
        CHECK (action_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_release_receipt_object
        CHECK (jsonb_typeof(receipt) = 'object')
);

CREATE OR REPLACE FUNCTION quant_system.reject_agent_v02_release_append_only()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    RAISE EXCEPTION 'Agent v0.2 release fact is append-only';
END;
$$;

CREATE OR REPLACE FUNCTION quant_system.guard_agent_v02_release_stamp_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION 'Agent v0.2 release stamp is append-only';
    END IF;
    IF OLD.status <> 'active'
       OR NEW.status <> 'closed'
       OR NEW.closed_at IS NULL
       OR NEW.close_reason IS NULL
       OR NEW.stamp_id IS DISTINCT FROM OLD.stamp_id
       OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.route IS DISTINCT FROM OLD.route
       OR NEW.platform_runtime_digest IS DISTINCT FROM OLD.platform_runtime_digest
       OR NEW.hqa_runtime_digest IS DISTINCT FROM OLD.hqa_runtime_digest
       OR NEW.hermes_runtime_digest IS DISTINCT FROM OLD.hermes_runtime_digest
       OR NEW.database_schema_fingerprint IS DISTINCT FROM OLD.database_schema_fingerprint
       OR NEW.evidence_digest IS DISTINCT FROM OLD.evidence_digest
       OR NEW.release_digest IS DISTINCT FROM OLD.release_digest
       OR NEW.opened_at IS DISTINCT FROM OLD.opened_at
    THEN
        RAISE EXCEPTION
            'Agent v0.2 release stamp permits only active-to-closed transition';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION quant_system.guard_agent_v02_cutover_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    IF TG_OP IN ('DELETE', 'TRUNCATE') THEN
        RAISE EXCEPTION 'Agent v0.2 public cutover is append-only';
    END IF;
    IF OLD.status <> 'open'
       OR NEW.status <> 'closed'
       OR NEW.closed_at IS NULL
       OR NEW.close_reason IS NULL
       OR NEW.cutover_id IS DISTINCT FROM OLD.cutover_id
       OR NEW.stamp_id IS DISTINCT FROM OLD.stamp_id
       OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.route IS DISTINCT FROM OLD.route
       OR NEW.release_digest IS DISTINCT FROM OLD.release_digest
       OR NEW.cutover_digest IS DISTINCT FROM OLD.cutover_digest
       OR NEW.opened_at IS DISTINCT FROM OLD.opened_at
    THEN
        RAISE EXCEPTION
            'Agent v0.2 public cutover permits only open-to-closed transition';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_agent_v02_release_stamps_update
    ON quant_system.agent_v02_release_stamps;
DROP TRIGGER IF EXISTS trg_agent_v02_release_stamps_delete
    ON quant_system.agent_v02_release_stamps;
DROP TRIGGER IF EXISTS trg_agent_v02_release_stamps_truncate
    ON quant_system.agent_v02_release_stamps;
CREATE TRIGGER trg_agent_v02_release_stamps_update
BEFORE UPDATE ON quant_system.agent_v02_release_stamps
FOR EACH ROW
EXECUTE FUNCTION quant_system.guard_agent_v02_release_stamp_transition();
CREATE TRIGGER trg_agent_v02_release_stamps_delete
BEFORE DELETE ON quant_system.agent_v02_release_stamps
FOR EACH ROW
EXECUTE FUNCTION quant_system.reject_agent_v02_release_append_only();
CREATE TRIGGER trg_agent_v02_release_stamps_truncate
BEFORE TRUNCATE ON quant_system.agent_v02_release_stamps
FOR EACH STATEMENT
EXECUTE FUNCTION quant_system.reject_agent_v02_release_append_only();

DROP TRIGGER IF EXISTS trg_agent_v02_cutovers_update
    ON quant_system.agent_v02_public_cutovers;
DROP TRIGGER IF EXISTS trg_agent_v02_cutovers_delete
    ON quant_system.agent_v02_public_cutovers;
DROP TRIGGER IF EXISTS trg_agent_v02_cutovers_truncate
    ON quant_system.agent_v02_public_cutovers;
CREATE TRIGGER trg_agent_v02_cutovers_update
BEFORE UPDATE ON quant_system.agent_v02_public_cutovers
FOR EACH ROW
EXECUTE FUNCTION quant_system.guard_agent_v02_cutover_transition();
CREATE TRIGGER trg_agent_v02_cutovers_delete
BEFORE DELETE ON quant_system.agent_v02_public_cutovers
FOR EACH ROW
EXECUTE FUNCTION quant_system.reject_agent_v02_release_append_only();
CREATE TRIGGER trg_agent_v02_cutovers_truncate
BEFORE TRUNCATE ON quant_system.agent_v02_public_cutovers
FOR EACH STATEMENT
EXECUTE FUNCTION quant_system.reject_agent_v02_release_append_only();

DROP TRIGGER IF EXISTS trg_agent_v02_release_events_update
    ON quant_system.agent_v02_release_events;
DROP TRIGGER IF EXISTS trg_agent_v02_release_events_delete
    ON quant_system.agent_v02_release_events;
DROP TRIGGER IF EXISTS trg_agent_v02_release_events_truncate
    ON quant_system.agent_v02_release_events;
CREATE TRIGGER trg_agent_v02_release_events_update
BEFORE UPDATE ON quant_system.agent_v02_release_events
FOR EACH ROW
EXECUTE FUNCTION quant_system.reject_agent_v02_release_append_only();
CREATE TRIGGER trg_agent_v02_release_events_delete
BEFORE DELETE ON quant_system.agent_v02_release_events
FOR EACH ROW
EXECUTE FUNCTION quant_system.reject_agent_v02_release_append_only();
CREATE TRIGGER trg_agent_v02_release_events_truncate
BEFORE TRUNCATE ON quant_system.agent_v02_release_events
FOR EACH STATEMENT
EXECUTE FUNCTION quant_system.reject_agent_v02_release_append_only();

DROP TRIGGER IF EXISTS trg_agent_v02_release_actions_update
    ON quant_system.agent_v02_release_actions;
DROP TRIGGER IF EXISTS trg_agent_v02_release_actions_delete
    ON quant_system.agent_v02_release_actions;
DROP TRIGGER IF EXISTS trg_agent_v02_release_actions_truncate
    ON quant_system.agent_v02_release_actions;
CREATE TRIGGER trg_agent_v02_release_actions_update
BEFORE UPDATE ON quant_system.agent_v02_release_actions
FOR EACH ROW
EXECUTE FUNCTION quant_system.reject_agent_v02_release_append_only();
CREATE TRIGGER trg_agent_v02_release_actions_delete
BEFORE DELETE ON quant_system.agent_v02_release_actions
FOR EACH ROW
EXECUTE FUNCTION quant_system.reject_agent_v02_release_append_only();
CREATE TRIGGER trg_agent_v02_release_actions_truncate
BEFORE TRUNCATE ON quant_system.agent_v02_release_actions
FOR EACH STATEMENT
EXECUTE FUNCTION quant_system.reject_agent_v02_release_append_only();

ALTER TABLE quant_system.agent_v02_release_stamps
    ENABLE ALWAYS TRIGGER trg_agent_v02_release_stamps_update;
ALTER TABLE quant_system.agent_v02_release_stamps
    ENABLE ALWAYS TRIGGER trg_agent_v02_release_stamps_delete;
ALTER TABLE quant_system.agent_v02_release_stamps
    ENABLE ALWAYS TRIGGER trg_agent_v02_release_stamps_truncate;
ALTER TABLE quant_system.agent_v02_public_cutovers
    ENABLE ALWAYS TRIGGER trg_agent_v02_cutovers_update;
ALTER TABLE quant_system.agent_v02_public_cutovers
    ENABLE ALWAYS TRIGGER trg_agent_v02_cutovers_delete;
ALTER TABLE quant_system.agent_v02_public_cutovers
    ENABLE ALWAYS TRIGGER trg_agent_v02_cutovers_truncate;
ALTER TABLE quant_system.agent_v02_release_events
    ENABLE ALWAYS TRIGGER trg_agent_v02_release_events_update;
ALTER TABLE quant_system.agent_v02_release_events
    ENABLE ALWAYS TRIGGER trg_agent_v02_release_events_delete;
ALTER TABLE quant_system.agent_v02_release_events
    ENABLE ALWAYS TRIGGER trg_agent_v02_release_events_truncate;
ALTER TABLE quant_system.agent_v02_release_actions
    ENABLE ALWAYS TRIGGER trg_agent_v02_release_actions_update;
ALTER TABLE quant_system.agent_v02_release_actions
    ENABLE ALWAYS TRIGGER trg_agent_v02_release_actions_delete;
ALTER TABLE quant_system.agent_v02_release_actions
    ENABLE ALWAYS TRIGGER trg_agent_v02_release_actions_truncate;

-- If V4-R roles already exist, apply the same least-privilege posture now.
-- If this migration is applied before V4-R, replaying migrations after V4-R
-- exists installs the policies/grants; readiness remains false until then.
DO $$
DECLARE
    table_name TEXT;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_readonly')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator')
    THEN
        GRANT USAGE ON SCHEMA quant_system
            TO quant_runtime, quant_readonly, quant_migrator;
        REVOKE CREATE ON SCHEMA quant_system
            FROM quant_runtime, quant_readonly;
        FOREACH table_name IN ARRAY ARRAY[
            'agent_v02_release_stamps',
            'agent_v02_public_cutovers',
            'agent_v02_release_events',
            'agent_v02_release_actions'
        ]
        LOOP
            EXECUTE format(
                'ALTER TABLE quant_system.%I ENABLE ROW LEVEL SECURITY',
                table_name
            );
            EXECUTE format(
                'ALTER TABLE quant_system.%I FORCE ROW LEVEL SECURITY',
                table_name
            );
            EXECUTE format(
                'DROP POLICY IF EXISTS v4r_root_scope ON quant_system.%I',
                table_name
            );
            EXECUTE format(
                'CREATE POLICY v4r_root_scope ON quant_system.%I '
                'FOR ALL TO quant_runtime, quant_readonly '
                'USING (owner_user_id = '
                '''00000000-0000-0000-0000-000000000001''::uuid) '
                'WITH CHECK (owner_user_id = '
                '''00000000-0000-0000-0000-000000000001''::uuid)',
                table_name
            );
            EXECUTE format(
                'DROP POLICY IF EXISTS v4r_migrator_all ON quant_system.%I',
                table_name
            );
            EXECUTE format(
                'CREATE POLICY v4r_migrator_all ON quant_system.%I '
                'FOR ALL TO quant_migrator USING (true) WITH CHECK (true)',
                table_name
            );
        END LOOP;

        GRANT SELECT, INSERT, UPDATE
            ON quant_system.agent_v02_release_stamps,
               quant_system.agent_v02_public_cutovers
            TO quant_runtime;
        GRANT SELECT, INSERT
            ON quant_system.agent_v02_release_events,
               quant_system.agent_v02_release_actions
            TO quant_runtime;
        GRANT SELECT
            ON quant_system.agent_v02_release_stamps,
               quant_system.agent_v02_public_cutovers,
               quant_system.agent_v02_release_events,
               quant_system.agent_v02_release_actions,
               quant_system.agent_v02_release_authority_meta
            TO quant_readonly;
        GRANT SELECT
            ON quant_system.agent_v02_release_authority_meta
            TO quant_runtime;
        GRANT USAGE, SELECT
            ON SEQUENCE quant_system.agent_v02_release_events_event_cursor_seq
            TO quant_runtime;
        REVOKE DELETE, TRUNCATE
            ON quant_system.agent_v02_release_stamps,
               quant_system.agent_v02_public_cutovers
            FROM quant_runtime;
        REVOKE UPDATE, DELETE, TRUNCATE
            ON quant_system.agent_v02_release_events,
               quant_system.agent_v02_release_actions
            FROM quant_runtime;
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE
            ON quant_system.agent_v02_release_authority_meta
            FROM quant_runtime;
        REVOKE ALL
            ON quant_system.agent_v02_release_stamps,
               quant_system.agent_v02_public_cutovers,
               quant_system.agent_v02_release_events,
               quant_system.agent_v02_release_actions,
               quant_system.agent_v02_release_authority_meta
            FROM PUBLIC;
        GRANT ALL
            ON quant_system.agent_v02_release_stamps,
               quant_system.agent_v02_public_cutovers,
               quant_system.agent_v02_release_events,
               quant_system.agent_v02_release_actions,
               quant_system.agent_v02_release_authority_meta
            TO quant_migrator;
        GRANT ALL
            ON SEQUENCE quant_system.agent_v02_release_events_event_cursor_seq
            TO quant_migrator;

        ALTER TABLE quant_system.agent_v02_release_stamps
            OWNER TO quant_migrator;
        ALTER TABLE quant_system.agent_v02_public_cutovers
            OWNER TO quant_migrator;
        ALTER TABLE quant_system.agent_v02_release_events
            OWNER TO quant_migrator;
        ALTER TABLE quant_system.agent_v02_release_actions
            OWNER TO quant_migrator;
        ALTER TABLE quant_system.agent_v02_release_authority_meta
            OWNER TO quant_migrator;
        ALTER SEQUENCE quant_system.agent_v02_release_events_event_cursor_seq
            OWNER TO quant_migrator;
        ALTER FUNCTION quant_system.reject_agent_v02_release_append_only()
            OWNER TO quant_migrator;
        ALTER FUNCTION quant_system.guard_agent_v02_release_stamp_transition()
            OWNER TO quant_migrator;
        ALTER FUNCTION quant_system.guard_agent_v02_cutover_transition()
            OWNER TO quant_migrator;
    END IF;
END $$;

COMMIT;
