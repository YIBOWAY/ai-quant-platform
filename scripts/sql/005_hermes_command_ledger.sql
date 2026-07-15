-- PostgreSQL authority for durable Hermes transport commands.
--
-- Ownership boundary:
--   * this schema owns command intent, client idempotency, versions, leases,
--     outbox wake-ups, and exact run links;
--   * Hermes owns Session/Run/messages/provider evidence;
--   * HQA owns research Task/Attempt/Gate/result references.
--
-- This migration performs no network calls and stores no prompt, bearer token,
-- provider credential, broker data, or trading instruction.

CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS quant_system.hermes_ledger_meta (
    singleton       BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    schema_version  INTEGER NOT NULL CHECK (schema_version > 0),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO quant_system.hermes_ledger_meta (singleton, schema_version)
VALUES (TRUE, 1)
ON CONFLICT (singleton) DO NOTHING;

DO $$
DECLARE
    installed_version INTEGER;
BEGIN
    SELECT schema_version
    INTO installed_version
    FROM quant_system.hermes_ledger_meta
    WHERE singleton IS TRUE;

    IF installed_version > 1 THEN
        RAISE EXCEPTION
            'Hermes command ledger schema version % is newer than this binary supports (1)',
            installed_version;
    ELSIF installed_version <> 1 THEN
        RAISE EXCEPTION
            'Hermes command ledger schema version % is incompatible with this binary (expected 1)',
            installed_version;
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS quant_system.hermes_commands (
    command_id                UUID PRIMARY KEY,
    owner_user_id             UUID NOT NULL REFERENCES quant_system.app_users(id),
    platform_session_id       TEXT NOT NULL,
    client_request_id         TEXT NOT NULL,
    kind                      TEXT NOT NULL,
    intent_schema_version     INTEGER NOT NULL DEFAULT 1,
    canonical_request_digest  CHAR(64) NOT NULL,
    payload_ref               TEXT NOT NULL,
    provider_policy_digest    CHAR(64),
    state                     TEXT NOT NULL DEFAULT 'queued',
    version                   BIGINT NOT NULL DEFAULT 1,
    attempt_count             INTEGER NOT NULL DEFAULT 0,
    next_attempt_at           TIMESTAMPTZ,
    lease_owner               TEXT,
    lease_token               UUID,
    lease_until               TIMESTAMPTZ,
    dispatch_started_at       TIMESTAMPTZ,
    hermes_session_id         TEXT,
    hermes_run_id             TEXT,
    last_error_code           TEXT,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_user_id, platform_session_id, client_request_id),
    UNIQUE (command_id, version),
    CONSTRAINT ck_hermes_commands_platform_session_id
        CHECK (char_length(platform_session_id) BETWEEN 1 AND 200),
    CONSTRAINT ck_hermes_commands_client_request_id
        CHECK (char_length(client_request_id) BETWEEN 1 AND 200),
    CONSTRAINT ck_hermes_commands_kind
        CHECK (char_length(kind) BETWEEN 1 AND 64),
    CONSTRAINT ck_hermes_commands_intent_schema_version
        CHECK (intent_schema_version > 0),
    CONSTRAINT ck_hermes_commands_request_digest
        CHECK (canonical_request_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_hermes_commands_payload_ref
        CHECK (char_length(payload_ref) BETWEEN 1 AND 1000),
    CONSTRAINT ck_hermes_commands_provider_digest
        CHECK (
            provider_policy_digest IS NULL
            OR provider_policy_digest ~ '^[0-9a-f]{64}$'
        ),
    CONSTRAINT ck_hermes_commands_state
        CHECK (state IN (
            'queued',
            'leased',
            'delivered',
            'outcome_unknown',
            'succeeded',
            'failed',
            'cancelled'
        )),
    CONSTRAINT ck_hermes_commands_version
        CHECK (version > 0),
    CONSTRAINT ck_hermes_commands_attempt_count
        CHECK (attempt_count >= 0),
    CONSTRAINT ck_hermes_commands_lease_triplet
        CHECK (
            (lease_owner IS NULL AND lease_token IS NULL AND lease_until IS NULL)
            OR
            (lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lease_until IS NOT NULL)
        ),
    CONSTRAINT ck_hermes_commands_leased_state
        CHECK (state <> 'leased' OR lease_token IS NOT NULL),
    CONSTRAINT ck_hermes_commands_dispatch_state
        CHECK (dispatch_started_at IS NULL OR state <> 'queued'),
    CONSTRAINT ck_hermes_commands_run_requires_session
        CHECK (hermes_run_id IS NULL OR hermes_session_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS quant_system.hermes_command_events (
    event_id                  BIGSERIAL PRIMARY KEY,
    command_id                UUID NOT NULL REFERENCES quant_system.hermes_commands(command_id),
    command_version           BIGINT NOT NULL,
    event_type                TEXT NOT NULL,
    actor                     TEXT NOT NULL,
    from_state                TEXT,
    to_state                  TEXT NOT NULL,
    canonical_request_digest  CHAR(64) NOT NULL,
    attempt_count             INTEGER NOT NULL,
    next_attempt_at           TIMESTAMPTZ,
    lease_owner               TEXT,
    lease_token               UUID,
    lease_until               TIMESTAMPTZ,
    dispatch_started_at       TIMESTAMPTZ,
    hermes_session_id         TEXT,
    hermes_run_id             TEXT,
    error_code                TEXT,
    event_data                JSONB NOT NULL DEFAULT '{}'::jsonb,
    occurred_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (command_id, command_version),
    CONSTRAINT ck_hermes_command_events_version
        CHECK (command_version > 0),
    CONSTRAINT ck_hermes_command_events_event_type
        CHECK (char_length(event_type) BETWEEN 1 AND 64),
    CONSTRAINT ck_hermes_command_events_actor
        CHECK (actor IN ('bff', 'worker', 'reconciler', 'system')),
    CONSTRAINT ck_hermes_command_events_states
        CHECK (
            (from_state IS NULL OR from_state IN (
                'queued', 'leased', 'delivered', 'outcome_unknown',
                'succeeded', 'failed', 'cancelled'
            ))
            AND to_state IN (
                'queued', 'leased', 'delivered', 'outcome_unknown',
                'succeeded', 'failed', 'cancelled'
            )
        ),
    CONSTRAINT ck_hermes_command_events_request_digest
        CHECK (canonical_request_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_hermes_command_events_attempt_count
        CHECK (attempt_count >= 0),
    CONSTRAINT ck_hermes_command_events_lease_triplet
        CHECK (
            (lease_owner IS NULL AND lease_token IS NULL AND lease_until IS NULL)
            OR
            (lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lease_until IS NOT NULL)
        ),
    CONSTRAINT ck_hermes_command_events_run_requires_session
        CHECK (hermes_run_id IS NULL OR hermes_session_id IS NOT NULL),
    CONSTRAINT ck_hermes_command_events_data_object
        CHECK (jsonb_typeof(event_data) = 'object')
);

CREATE TABLE IF NOT EXISTS quant_system.hermes_outbox (
    outbox_id       BIGSERIAL PRIMARY KEY,
    command_id      UUID NOT NULL REFERENCES quant_system.hermes_commands(command_id),
    command_version BIGINT NOT NULL,
    topic           TEXT NOT NULL DEFAULT 'hermes.command.queued',
    available_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    consumed_by     TEXT,
    consumed_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (command_id, command_version, topic),
    CONSTRAINT ck_hermes_outbox_version
        CHECK (command_version > 0),
    CONSTRAINT ck_hermes_outbox_topic
        CHECK (topic IN ('hermes.command.queued', 'hermes.command.reconcile')),
    CONSTRAINT ck_hermes_outbox_consumed_pair
        CHECK ((consumed_by IS NULL) = (consumed_at IS NULL))
);

CREATE TABLE IF NOT EXISTS quant_system.hermes_run_links (
    link_id                 UUID PRIMARY KEY,
    command_id              UUID NOT NULL REFERENCES quant_system.hermes_commands(command_id),
    platform_resource_type  TEXT NOT NULL,
    platform_resource_id    TEXT NOT NULL,
    relation                TEXT NOT NULL,
    hermes_session_id       TEXT NOT NULL,
    hermes_run_id           TEXT NOT NULL,
    link_digest             CHAR(64) NOT NULL,
    source_event_id         TEXT,
    observed_at             TIMESTAMPTZ NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (
        hermes_session_id,
        hermes_run_id,
        platform_resource_type,
        platform_resource_id,
        relation
    ),
    CONSTRAINT ck_hermes_run_links_resource_type
        CHECK (char_length(platform_resource_type) BETWEEN 1 AND 64),
    CONSTRAINT ck_hermes_run_links_resource_id
        CHECK (char_length(platform_resource_id) BETWEEN 1 AND 500),
    CONSTRAINT ck_hermes_run_links_relation
        CHECK (relation IN ('input', 'output', 'context')),
    CONSTRAINT ck_hermes_run_links_session_id
        CHECK (char_length(hermes_session_id) BETWEEN 1 AND 256),
    CONSTRAINT ck_hermes_run_links_run_id
        CHECK (char_length(hermes_run_id) BETWEEN 1 AND 256),
    CONSTRAINT ck_hermes_run_links_digest
        CHECK (link_digest ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_hermes_commands_state_due
    ON quant_system.hermes_commands (state, next_attempt_at, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS uq_hermes_commands_upstream_run
    ON quant_system.hermes_commands (hermes_session_id, hermes_run_id)
    WHERE hermes_run_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_hermes_command_events_command
    ON quant_system.hermes_command_events (command_id, command_version);

CREATE INDEX IF NOT EXISTS idx_hermes_outbox_available
    ON quant_system.hermes_outbox (consumed_at, available_at, outbox_id);

CREATE INDEX IF NOT EXISTS idx_hermes_run_links_command
    ON quant_system.hermes_run_links (command_id, created_at);

CREATE UNIQUE INDEX IF NOT EXISTS uq_hermes_run_links_command_resource
    ON quant_system.hermes_run_links (
        command_id,
        platform_resource_type,
        platform_resource_id,
        relation
    );

CREATE INDEX IF NOT EXISTS idx_hermes_run_links_hermes_run
    ON quant_system.hermes_run_links (hermes_session_id, hermes_run_id);

CREATE OR REPLACE FUNCTION quant_system.reject_hermes_command_event_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'hermes_command_events is append-only';
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_hermes_command_events_append_only'
          AND tgrelid = 'quant_system.hermes_command_events'::regclass
          AND NOT tgisinternal
    ) THEN
        EXECUTE 'CREATE TRIGGER trg_hermes_command_events_append_only '
             || 'BEFORE UPDATE OR DELETE ON quant_system.hermes_command_events '
             || 'FOR EACH ROW '
             || 'EXECUTE FUNCTION quant_system.reject_hermes_command_event_mutation()';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_hermes_command_events_append_only_truncate'
          AND tgrelid = 'quant_system.hermes_command_events'::regclass
          AND NOT tgisinternal
    ) THEN
        EXECUTE 'CREATE TRIGGER trg_hermes_command_events_append_only_truncate '
             || 'BEFORE TRUNCATE ON quant_system.hermes_command_events '
             || 'FOR EACH STATEMENT '
             || 'EXECUTE FUNCTION quant_system.reject_hermes_command_event_mutation()';
    END IF;
END $$;

CREATE OR REPLACE FUNCTION quant_system.reject_hermes_run_link_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'hermes_run_links is append-only';
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_hermes_run_links_append_only'
          AND tgrelid = 'quant_system.hermes_run_links'::regclass
          AND NOT tgisinternal
    ) THEN
        EXECUTE 'CREATE TRIGGER trg_hermes_run_links_append_only '
             || 'BEFORE UPDATE OR DELETE ON quant_system.hermes_run_links '
             || 'FOR EACH ROW '
             || 'EXECUTE FUNCTION quant_system.reject_hermes_run_link_mutation()';
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_trigger
        WHERE tgname = 'trg_hermes_run_links_append_only_truncate'
          AND tgrelid = 'quant_system.hermes_run_links'::regclass
          AND NOT tgisinternal
    ) THEN
        EXECUTE 'CREATE TRIGGER trg_hermes_run_links_append_only_truncate '
             || 'BEFORE TRUNCATE ON quant_system.hermes_run_links '
             || 'FOR EACH STATEMENT '
             || 'EXECUTE FUNCTION quant_system.reject_hermes_run_link_mutation()';
    END IF;
END $$;
