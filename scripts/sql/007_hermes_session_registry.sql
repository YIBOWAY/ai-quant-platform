-- Additive platform session registry for Agent v0.2 Slice V4.
--
-- Separates observed_external_session (Web read-only) from web_managed_session
-- (Web control plane is the only writer). 1:1 exact Hermes Session identity.
-- No prompt body, provider credential, Hermes mutation, or trading instruction.
--
-- Independent of migration 006 workflow-binding cardinality. Live apply still
-- needs a separate explicit authorization after isolated evidence is green.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:007_hermes_session_registry', 0)
);

CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS quant_system.hermes_session_registry_meta (
    singleton       BOOLEAN PRIMARY KEY DEFAULT TRUE,
    schema_version  INTEGER NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_hermes_session_registry_meta_singleton CHECK (singleton),
    CONSTRAINT ck_hermes_session_registry_meta_version CHECK (schema_version > 0)
);

INSERT INTO quant_system.hermes_session_registry_meta (singleton, schema_version)
VALUES (TRUE, 1)
ON CONFLICT (singleton) DO NOTHING;

DO $$
DECLARE
    installed_version INTEGER;
BEGIN
    SELECT schema_version
    INTO installed_version
    FROM quant_system.hermes_session_registry_meta
    WHERE singleton IS TRUE;

    IF installed_version > 2 THEN
        RAISE EXCEPTION
            'Hermes session registry schema version % is newer than this migration chain supports (2)',
            installed_version;
    ELSIF installed_version < 1 THEN
        RAISE EXCEPTION
            'Hermes session registry schema version % is incompatible with this migration (minimum 1)',
            installed_version;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS quant_system.hermes_workspace_sessions (
    platform_session_id       TEXT PRIMARY KEY,
    hermes_session_id         TEXT NOT NULL,
    workspace_id              TEXT NOT NULL,
    owner_user_id             UUID NOT NULL,
    kind                      TEXT NOT NULL,
    source_channel            TEXT,
    parent_platform_session_id TEXT,
    fork_point                TEXT,
    provider_policy_digest    CHAR(64),
    writer                    TEXT NOT NULL,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_hermes_workspace_session_owner
        FOREIGN KEY (owner_user_id)
        REFERENCES quant_system.app_users(id),
    CONSTRAINT fk_hermes_workspace_session_parent
        FOREIGN KEY (parent_platform_session_id)
        REFERENCES quant_system.hermes_workspace_sessions(platform_session_id),
    CONSTRAINT uq_hermes_workspace_session_hermes
        UNIQUE (hermes_session_id),
    CONSTRAINT ck_hermes_workspace_session_platform_id
        CHECK (
            char_length(platform_session_id) BETWEEN 1 AND 200
            AND platform_session_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_hermes_workspace_session_hermes_id
        CHECK (
            char_length(hermes_session_id) BETWEEN 1 AND 255
            AND hermes_session_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_hermes_workspace_session_workspace_id
        CHECK (
            char_length(workspace_id) BETWEEN 1 AND 200
            AND workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_hermes_workspace_session_kind
        CHECK (kind IN ('observed_external_session', 'web_managed_session')),
    CONSTRAINT ck_hermes_workspace_session_writer
        CHECK (writer IN ('external_channel', 'web_control_plane')),
    CONSTRAINT ck_hermes_workspace_session_no_self_parent
        CHECK (
            parent_platform_session_id IS NULL
            OR parent_platform_session_id <> platform_session_id
        ),
    CONSTRAINT ck_hermes_workspace_session_external_shape
        CHECK (
            kind <> 'observed_external_session'
            OR (
                writer = 'external_channel'
                AND source_channel IN ('discord', 'historical')
                AND parent_platform_session_id IS NULL
                AND fork_point IS NULL
                AND provider_policy_digest IS NULL
            )
        ),
    CONSTRAINT ck_hermes_workspace_session_managed_root_shape
        CHECK (
            kind <> 'web_managed_session'
            OR writer = 'web_control_plane'
        ),
    CONSTRAINT ck_hermes_workspace_session_managed_provider
        CHECK (
            kind <> 'web_managed_session'
            OR (
                provider_policy_digest IS NOT NULL
                AND provider_policy_digest ~ '^[0-9a-f]{64}$'
            )
        ),
    -- Root web_managed sessions have no channel/fork lineage. External sessions
-- are always roots but keep their observed source_channel. Forked managed
-- sessions require both parent and fork metadata.
    CONSTRAINT ck_hermes_workspace_session_root_lineage
        CHECK (
            kind <> 'web_managed_session'
            OR parent_platform_session_id IS NOT NULL
            OR (
                source_channel IS NULL
                AND fork_point IS NULL
            )
        ),
    CONSTRAINT ck_hermes_workspace_session_fork_lineage
        CHECK (
            parent_platform_session_id IS NULL
            OR (
                kind = 'web_managed_session'
                AND source_channel IN ('discord', 'historical', 'web_managed')
                AND fork_point IS NOT NULL
                AND char_length(fork_point) BETWEEN 1 AND 2000
            )
        )
);

CREATE INDEX IF NOT EXISTS idx_hermes_workspace_sessions_owner_kind
    ON quant_system.hermes_workspace_sessions (owner_user_id, kind, created_at);

CREATE INDEX IF NOT EXISTS idx_hermes_workspace_sessions_workspace
    ON quant_system.hermes_workspace_sessions (workspace_id, created_at);

CREATE INDEX IF NOT EXISTS idx_hermes_workspace_sessions_parent
    ON quant_system.hermes_workspace_sessions (parent_platform_session_id)
    WHERE parent_platform_session_id IS NOT NULL;

CREATE OR REPLACE FUNCTION quant_system.reject_hermes_external_session_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        IF OLD.kind = 'observed_external_session' THEN
            RAISE EXCEPTION
                'observed_external_session rows are immutable once registered';
        END IF;
        RETURN OLD;
    END IF;

    IF OLD.kind = 'observed_external_session' THEN
        RAISE EXCEPTION
            'observed_external_session rows are immutable once registered';
    END IF;

    IF NEW.kind IS DISTINCT FROM OLD.kind
       OR NEW.hermes_session_id IS DISTINCT FROM OLD.hermes_session_id
       OR NEW.workspace_id IS DISTINCT FROM OLD.workspace_id
       OR NEW.owner_user_id IS DISTINCT FROM OLD.owner_user_id
       OR NEW.writer IS DISTINCT FROM OLD.writer
       OR NEW.provider_policy_digest IS DISTINCT FROM OLD.provider_policy_digest
       OR NEW.parent_platform_session_id IS DISTINCT FROM OLD.parent_platform_session_id
       OR NEW.fork_point IS DISTINCT FROM OLD.fork_point
       OR NEW.source_channel IS DISTINCT FROM OLD.source_channel
       OR NEW.platform_session_id IS DISTINCT FROM OLD.platform_session_id
    THEN
        RAISE EXCEPTION
            'web_managed_session identity and lineage fields are immutable';
    END IF;

    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_hermes_workspace_session_immutability'
          AND tgrelid = 'quant_system.hermes_workspace_sessions'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_hermes_workspace_session_immutability
        BEFORE UPDATE OR DELETE ON quant_system.hermes_workspace_sessions
        FOR EACH ROW
        EXECUTE FUNCTION quant_system.reject_hermes_external_session_mutation();
    END IF;
END $$;

ALTER TABLE quant_system.hermes_workspace_sessions
    ENABLE ALWAYS TRIGGER trg_hermes_workspace_session_immutability;

COMMIT;
