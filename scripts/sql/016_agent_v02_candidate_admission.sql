-- Private, short-lived Agent v0.2 candidate admission.
--
-- Candidate admission exists only to collect the real /hermes evidence that a
-- final release stamp requires.  It is not a public cutover and does not make
-- release_authorized/public_write_authorized true.  PostgreSQL owns the clock,
-- one-open-per-workspace constraint, exact action receipts, and the binding of
-- candidate-created managed sessions/commands.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:016_agent_v02_candidate_admission', 0)
);

CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_candidate_admission_meta (
    singleton       BOOLEAN PRIMARY KEY DEFAULT TRUE,
    schema_version  INTEGER NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_agent_v02_candidate_meta_singleton CHECK (singleton),
    CONSTRAINT ck_agent_v02_candidate_meta_version CHECK (schema_version > 0)
);

INSERT INTO quant_system.agent_v02_candidate_admission_meta (
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
    FROM quant_system.agent_v02_candidate_admission_meta
    WHERE singleton IS TRUE;

    IF installed_version <> 1 THEN
        RAISE EXCEPTION
            'Agent v0.2 candidate admission schema version % is incompatible with this binary (expected 1)',
            installed_version;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_candidate_admissions (
    admission_id                    TEXT PRIMARY KEY,
    owner_user_id                   UUID NOT NULL
        REFERENCES quant_system.app_users(id),
    workspace_id                    TEXT NOT NULL,
    route                           TEXT NOT NULL,
    platform_runtime_digest         CHAR(64) NOT NULL,
    hqa_runtime_digest              CHAR(64) NOT NULL,
    hermes_runtime_digest           CHAR(64) NOT NULL,
    database_schema_fingerprint     CHAR(64) NOT NULL,
    preflight_evidence_digest       CHAR(64) NOT NULL,
    baseline_order_snapshot_digest  CHAR(64) NOT NULL,
    admission_digest                CHAR(64) NOT NULL UNIQUE,
    status                          TEXT NOT NULL DEFAULT 'open',
    opened_at                       TIMESTAMPTZ NOT NULL,
    expires_at                      TIMESTAMPTZ NOT NULL,
    closed_at                       TIMESTAMPTZ,
    close_reason                    TEXT,
    final_evidence_digest           CHAR(64),
    acceptance_digest               CHAR(64) UNIQUE,
    CONSTRAINT ck_agent_v02_candidate_admission_id
        CHECK (
            char_length(admission_id) BETWEEN 1 AND 200
            AND admission_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_candidate_workspace_id
        CHECK (
            char_length(workspace_id) BETWEEN 1 AND 200
            AND workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_candidate_route CHECK (route = '/hermes'),
    CONSTRAINT ck_agent_v02_candidate_platform_digest
        CHECK (platform_runtime_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_candidate_hqa_digest
        CHECK (hqa_runtime_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_candidate_hermes_digest
        CHECK (hermes_runtime_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_candidate_schema_fingerprint
        CHECK (database_schema_fingerprint ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_candidate_preflight_digest
        CHECK (preflight_evidence_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_candidate_order_digest
        CHECK (baseline_order_snapshot_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_candidate_admission_digest
        CHECK (admission_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_candidate_status
        CHECK (status IN ('open', 'accepted', 'revoked', 'expired')),
    CONSTRAINT ck_agent_v02_candidate_ttl
        CHECK (
            expires_at > opened_at
            AND expires_at <= opened_at + interval '30 minutes'
        ),
    CONSTRAINT ck_agent_v02_candidate_terminal_shape
        CHECK (
            (
                status = 'open'
                AND closed_at IS NULL
                AND close_reason IS NULL
                AND final_evidence_digest IS NULL
                AND acceptance_digest IS NULL
            )
            OR
            (
                status = 'accepted'
                AND closed_at IS NOT NULL
                AND char_length(close_reason) BETWEEN 1 AND 500
                AND final_evidence_digest ~ '^[0-9a-f]{64}$'
                AND acceptance_digest ~ '^[0-9a-f]{64}$'
            )
            OR
            (
                status IN ('revoked', 'expired')
                AND closed_at IS NOT NULL
                AND char_length(close_reason) BETWEEN 1 AND 500
                AND final_evidence_digest IS NULL
                AND acceptance_digest IS NULL
            )
        )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_v02_candidate_one_open_workspace
    ON quant_system.agent_v02_candidate_admissions (workspace_id)
    WHERE status = 'open';

CREATE INDEX IF NOT EXISTS idx_agent_v02_candidate_workspace_opened
    ON quant_system.agent_v02_candidate_admissions (
        workspace_id,
        opened_at DESC,
        admission_id
    );

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_candidate_events (
    event_cursor     BIGSERIAL PRIMARY KEY,
    event_id         TEXT NOT NULL UNIQUE,
    owner_user_id    UUID NOT NULL
        REFERENCES quant_system.app_users(id),
    workspace_id     TEXT NOT NULL,
    admission_id     TEXT NOT NULL
        REFERENCES quant_system.agent_v02_candidate_admissions(admission_id),
    event_type       TEXT NOT NULL,
    event_data       JSONB NOT NULL,
    occurred_at      TIMESTAMPTZ NOT NULL,
    CONSTRAINT ck_agent_v02_candidate_event_id
        CHECK (
            char_length(event_id) BETWEEN 1 AND 200
            AND event_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_candidate_event_type
        CHECK (
            event_type IN (
                'candidate.opened',
                'candidate.accepted',
                'candidate.revoked',
                'candidate.expired'
            )
        ),
    CONSTRAINT ck_agent_v02_candidate_event_data
        CHECK (jsonb_typeof(event_data) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_agent_v02_candidate_events_workspace_cursor
    ON quant_system.agent_v02_candidate_events (workspace_id, event_cursor);

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_candidate_actions (
    owner_user_id     UUID NOT NULL
        REFERENCES quant_system.app_users(id),
    workspace_id      TEXT NOT NULL,
    client_action_id  TEXT NOT NULL,
    operation         TEXT NOT NULL,
    action_digest     CHAR(64) NOT NULL,
    receipt           JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (workspace_id, client_action_id),
    CONSTRAINT ck_agent_v02_candidate_action_id
        CHECK (
            char_length(client_action_id) BETWEEN 1 AND 200
            AND client_action_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_agent_v02_candidate_operation
        CHECK (
            operation IN (
                'candidate.open',
                'candidate.accept',
                'candidate.revoke'
            )
        ),
    CONSTRAINT ck_agent_v02_candidate_action_digest
        CHECK (action_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_candidate_action_receipt
        CHECK (jsonb_typeof(receipt) = 'object')
);

ALTER TABLE quant_system.hermes_workspace_sessions
    ADD COLUMN IF NOT EXISTS candidate_admission_id TEXT
        REFERENCES quant_system.agent_v02_candidate_admissions(admission_id);
ALTER TABLE quant_system.hermes_commands
    ADD COLUMN IF NOT EXISTS candidate_admission_id TEXT
        REFERENCES quant_system.agent_v02_candidate_admissions(admission_id);

CREATE INDEX IF NOT EXISTS idx_hermes_sessions_candidate_admission
    ON quant_system.hermes_workspace_sessions (candidate_admission_id)
    WHERE candidate_admission_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_hermes_commands_candidate_due
    ON quant_system.hermes_commands (
        candidate_admission_id,
        state,
        next_attempt_at,
        created_at
    )
    WHERE candidate_admission_id IS NOT NULL;

CREATE OR REPLACE FUNCTION quant_system.guard_agent_v02_candidate_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Agent v0.2 candidate admission is not deletable';
    END IF;
    IF OLD.status <> 'open'
       OR NEW.status NOT IN ('accepted', 'revoked', 'expired')
       OR NEW.closed_at IS NULL
       OR NEW.close_reason IS NULL
       OR NEW.admission_id IS DISTINCT FROM OLD.admission_id
       OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.route IS DISTINCT FROM OLD.route
       OR NEW.platform_runtime_digest IS DISTINCT FROM OLD.platform_runtime_digest
       OR NEW.hqa_runtime_digest IS DISTINCT FROM OLD.hqa_runtime_digest
       OR NEW.hermes_runtime_digest IS DISTINCT FROM OLD.hermes_runtime_digest
       OR NEW.database_schema_fingerprint IS DISTINCT FROM OLD.database_schema_fingerprint
       OR NEW.preflight_evidence_digest IS DISTINCT FROM OLD.preflight_evidence_digest
       OR NEW.baseline_order_snapshot_digest IS DISTINCT FROM OLD.baseline_order_snapshot_digest
       OR NEW.admission_digest IS DISTINCT FROM OLD.admission_digest
       OR NEW.opened_at IS DISTINCT FROM OLD.opened_at
       OR NEW.expires_at IS DISTINCT FROM OLD.expires_at
    THEN
        RAISE EXCEPTION
            'Agent v0.2 candidate admission permits only one open-to-terminal transition';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION quant_system.reject_agent_v02_candidate_append_only()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    RAISE EXCEPTION 'Agent v0.2 candidate fact is append-only';
END;
$$;

CREATE OR REPLACE FUNCTION quant_system.bind_agent_v02_candidate_session()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    active_admission_id TEXT;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.candidate_admission_id IS DISTINCT FROM OLD.candidate_admission_id THEN
            RAISE EXCEPTION 'candidate session binding is immutable';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.candidate_admission_id IS NOT NULL THEN
        RAISE EXCEPTION 'candidate session binding is server-owned';
    END IF;
    IF NEW.kind <> 'web_managed_session' THEN
        RETURN NEW;
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'agent-v02-candidate:' || NEW.workspace_id,
            0
        )
    );
    SELECT admission_id
    INTO active_admission_id
    FROM quant_system.agent_v02_candidate_admissions
    WHERE owner_user_id = NEW.owner_user_id
      AND workspace_id = NEW.workspace_id
      AND route = '/hermes'
      AND status = 'open'
      AND expires_at > clock_timestamp()
    LIMIT 1;
    NEW.candidate_admission_id := active_admission_id;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION quant_system.bind_agent_v02_candidate_command()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    active_admission_id TEXT;
    session_admission_id TEXT;
    session_workspace_id TEXT;
    session_kind TEXT;
    session_admission_status TEXT;
    final_release_open BOOLEAN;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        IF NEW.candidate_admission_id IS DISTINCT FROM OLD.candidate_admission_id THEN
            RAISE EXCEPTION 'candidate command binding is immutable';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.candidate_admission_id IS NOT NULL THEN
        RAISE EXCEPTION 'candidate command binding is server-owned';
    END IF;
    IF NEW.kind <> 'conversation_turn' THEN
        RETURN NEW;
    END IF;

    SELECT
        session_row.candidate_admission_id,
        session_row.workspace_id,
        session_row.kind
    INTO
        session_admission_id,
        session_workspace_id,
        session_kind
    FROM quant_system.hermes_workspace_sessions AS session_row
    WHERE session_row.owner_user_id = NEW.owner_user_id
      AND session_row.platform_session_id = NEW.platform_session_id;
    IF session_workspace_id IS NULL OR session_kind <> 'web_managed_session' THEN
        RAISE EXCEPTION
            'conversation turn requires an exact managed session';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'agent-v02-candidate:' || session_workspace_id,
            0
        )
    );
    SELECT admission_id
    INTO active_admission_id
    FROM quant_system.agent_v02_candidate_admissions
    WHERE owner_user_id = NEW.owner_user_id
      AND workspace_id = session_workspace_id
      AND route = '/hermes'
      AND status = 'open'
      AND expires_at > clock_timestamp()
    LIMIT 1;

    IF active_admission_id IS NOT NULL THEN
        IF session_admission_id IS DISTINCT FROM active_admission_id THEN
            RAISE EXCEPTION
                'candidate conversation requires its exact candidate session';
        END IF;
        NEW.candidate_admission_id := active_admission_id;
        RETURN NEW;
    END IF;

    IF session_admission_id IS NOT NULL THEN
        SELECT status
        INTO session_admission_status
        FROM quant_system.agent_v02_candidate_admissions
        WHERE admission_id = session_admission_id;
        SELECT EXISTS (
            SELECT 1
            FROM quant_system.agent_v02_release_stamps AS stamp
            JOIN quant_system.agent_v02_public_cutovers AS cutover
              ON cutover.stamp_id = stamp.stamp_id
             AND cutover.workspace_id = stamp.workspace_id
             AND cutover.release_digest = stamp.release_digest
             AND cutover.status = 'open'
            WHERE stamp.owner_user_id = NEW.owner_user_id
              AND stamp.workspace_id = session_workspace_id
              AND stamp.route = '/hermes'
              AND stamp.status = 'active'
        )
        INTO final_release_open;
        IF session_admission_status <> 'accepted'
           OR final_release_open IS NOT TRUE
        THEN
            RAISE EXCEPTION
                'candidate session is not writable outside its admission or final release';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_agent_v02_candidate_admission_guard
    ON quant_system.agent_v02_candidate_admissions;
CREATE TRIGGER trg_agent_v02_candidate_admission_guard
BEFORE UPDATE OR DELETE ON quant_system.agent_v02_candidate_admissions
FOR EACH ROW
EXECUTE FUNCTION quant_system.guard_agent_v02_candidate_transition();
ALTER TABLE quant_system.agent_v02_candidate_admissions
    ENABLE ALWAYS TRIGGER trg_agent_v02_candidate_admission_guard;

DROP TRIGGER IF EXISTS trg_agent_v02_candidate_events_append_only
    ON quant_system.agent_v02_candidate_events;
CREATE TRIGGER trg_agent_v02_candidate_events_append_only
BEFORE UPDATE OR DELETE ON quant_system.agent_v02_candidate_events
FOR EACH ROW
EXECUTE FUNCTION quant_system.reject_agent_v02_candidate_append_only();
ALTER TABLE quant_system.agent_v02_candidate_events
    ENABLE ALWAYS TRIGGER trg_agent_v02_candidate_events_append_only;

DROP TRIGGER IF EXISTS trg_agent_v02_candidate_actions_append_only
    ON quant_system.agent_v02_candidate_actions;
CREATE TRIGGER trg_agent_v02_candidate_actions_append_only
BEFORE UPDATE OR DELETE ON quant_system.agent_v02_candidate_actions
FOR EACH ROW
EXECUTE FUNCTION quant_system.reject_agent_v02_candidate_append_only();
ALTER TABLE quant_system.agent_v02_candidate_actions
    ENABLE ALWAYS TRIGGER trg_agent_v02_candidate_actions_append_only;

DROP TRIGGER IF EXISTS trg_hermes_session_candidate_binding
    ON quant_system.hermes_workspace_sessions;
CREATE TRIGGER trg_hermes_session_candidate_binding
BEFORE INSERT OR UPDATE ON quant_system.hermes_workspace_sessions
FOR EACH ROW
EXECUTE FUNCTION quant_system.bind_agent_v02_candidate_session();
ALTER TABLE quant_system.hermes_workspace_sessions
    ENABLE ALWAYS TRIGGER trg_hermes_session_candidate_binding;

DROP TRIGGER IF EXISTS trg_hermes_command_candidate_binding
    ON quant_system.hermes_commands;
CREATE TRIGGER trg_hermes_command_candidate_binding
BEFORE INSERT OR UPDATE ON quant_system.hermes_commands
FOR EACH ROW
EXECUTE FUNCTION quant_system.bind_agent_v02_candidate_command();
ALTER TABLE quant_system.hermes_commands
    ENABLE ALWAYS TRIGGER trg_hermes_command_candidate_binding;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_readonly')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator')
    THEN
        ALTER TABLE quant_system.agent_v02_candidate_admission_meta
            OWNER TO quant_migrator;
        ALTER TABLE quant_system.agent_v02_candidate_admissions
            OWNER TO quant_migrator;
        ALTER TABLE quant_system.agent_v02_candidate_events
            OWNER TO quant_migrator;
        ALTER TABLE quant_system.agent_v02_candidate_actions
            OWNER TO quant_migrator;
        ALTER SEQUENCE
            quant_system.agent_v02_candidate_events_event_cursor_seq
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.guard_agent_v02_candidate_transition()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.reject_agent_v02_candidate_append_only()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.bind_agent_v02_candidate_session()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.bind_agent_v02_candidate_command()
            OWNER TO quant_migrator;

        GRANT USAGE ON SCHEMA quant_system
            TO quant_runtime, quant_readonly, quant_migrator;
        REVOKE CREATE ON SCHEMA quant_system
            FROM quant_runtime, quant_readonly;

        FOREACH table_name IN ARRAY ARRAY[
            'agent_v02_candidate_admissions',
            'agent_v02_candidate_events',
            'agent_v02_candidate_actions'
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
                || 'FOR ALL TO quant_runtime, quant_readonly '
                || 'USING (owner_user_id = '
                || quote_literal('00000000-0000-0000-0000-000000000001')
                || '::uuid) WITH CHECK (owner_user_id = '
                || quote_literal('00000000-0000-0000-0000-000000000001')
                || '::uuid)',
                table_name
            );
            EXECUTE format(
                'DROP POLICY IF EXISTS v4r_migrator_all ON quant_system.%I',
                table_name
            );
            EXECUTE format(
                'CREATE POLICY v4r_migrator_all ON quant_system.%I '
                || 'FOR ALL TO quant_migrator USING (true) WITH CHECK (true)',
                table_name
            );
        END LOOP;

        GRANT SELECT, INSERT, UPDATE
            ON quant_system.agent_v02_candidate_admissions
            TO quant_runtime;
        GRANT SELECT
            ON quant_system.agent_v02_candidate_admission_meta
            TO quant_runtime;
        REVOKE DELETE, TRUNCATE
            ON quant_system.agent_v02_candidate_admissions
            FROM quant_runtime;
        GRANT SELECT, INSERT
            ON quant_system.agent_v02_candidate_events,
               quant_system.agent_v02_candidate_actions
            TO quant_runtime;
        REVOKE UPDATE, DELETE, TRUNCATE
            ON quant_system.agent_v02_candidate_events,
               quant_system.agent_v02_candidate_actions
            FROM quant_runtime;
        GRANT USAGE, SELECT
            ON SEQUENCE quant_system.agent_v02_candidate_events_event_cursor_seq
            TO quant_runtime;

        GRANT SELECT
            ON quant_system.agent_v02_candidate_admission_meta,
               quant_system.agent_v02_candidate_admissions,
               quant_system.agent_v02_candidate_events,
               quant_system.agent_v02_candidate_actions
            TO quant_readonly;
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE
            ON quant_system.agent_v02_candidate_admissions,
               quant_system.agent_v02_candidate_events,
               quant_system.agent_v02_candidate_actions
            FROM quant_readonly;

        GRANT SELECT, INSERT, UPDATE, DELETE, TRUNCATE
            ON quant_system.agent_v02_candidate_admission_meta,
               quant_system.agent_v02_candidate_admissions,
               quant_system.agent_v02_candidate_events,
               quant_system.agent_v02_candidate_actions
            TO quant_migrator;
        GRANT USAGE, SELECT
            ON SEQUENCE quant_system.agent_v02_candidate_events_event_cursor_seq
            TO quant_migrator;
    END IF;
END $$;

COMMIT;
