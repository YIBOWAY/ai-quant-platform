-- Immutable command -> HQA Task/Attempt/plan binding foundation.
--
-- This migration is deliberately separate from hermes_ledger_meta v1. Migration
-- 005 is an already-applied transport-ledger contract and is replayed before this
-- file on every idempotent migration run. No prompt, provider credential, Hermes
-- mutation, or trading instruction is stored here.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(hashtextextended('quant_system:006_hermes_workflow_binding', 0));

CREATE SCHEMA IF NOT EXISTS quant_system;

-- Re-assert the append-only evidence functions inherited from migration 005.
-- Migration 005 is immutable historical evidence; 006 is the first additive
-- migration whose runtime contract depends on these exact function bodies.
CREATE OR REPLACE FUNCTION quant_system.reject_hermes_command_event_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    RAISE EXCEPTION 'hermes_command_events is append-only';
END;
$$;

CREATE OR REPLACE FUNCTION quant_system.reject_hermes_run_link_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    RAISE EXCEPTION 'hermes_run_links is append-only';
END;
$$;

CREATE TABLE IF NOT EXISTS quant_system.hermes_workflow_binding_meta (
    singleton       BOOLEAN PRIMARY KEY DEFAULT TRUE,
    schema_version  INTEGER NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_hermes_workflow_binding_meta_singleton CHECK (singleton),
    CONSTRAINT ck_hermes_workflow_binding_meta_version CHECK (schema_version > 0)
);

INSERT INTO quant_system.hermes_workflow_binding_meta (singleton, schema_version)
VALUES (TRUE, 1)
ON CONFLICT (singleton) DO NOTHING;

DO $$
DECLARE
    installed_version INTEGER;
BEGIN
    SELECT schema_version
    INTO installed_version
    FROM quant_system.hermes_workflow_binding_meta
    WHERE singleton IS TRUE;

    IF installed_version > 1 THEN
        RAISE EXCEPTION
            'Hermes workflow binding schema version % is newer than this binary supports (1)',
            installed_version;
    ELSIF installed_version <> 1 THEN
        RAISE EXCEPTION
            'Hermes workflow binding schema version % is incompatible with this binary (expected 1)',
            installed_version;
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_hermes_command_events_binding_anchor'
          AND conrelid = 'quant_system.hermes_command_events'::regclass
    ) THEN
        ALTER TABLE quant_system.hermes_command_events
            ADD CONSTRAINT uq_hermes_command_events_binding_anchor
            UNIQUE (command_id, command_version, canonical_request_digest);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS quant_system.hermes_command_workflow_bindings (
    command_id                    UUID PRIMARY KEY,
    command_version               BIGINT NOT NULL DEFAULT 1,
    preparation_schema_version    TEXT NOT NULL DEFAULT '1.0',
    workflow_saga_id              TEXT NOT NULL,
    owner_user_id                 UUID NOT NULL,
    platform_session_id           TEXT NOT NULL,
    client_request_id             TEXT NOT NULL,
    command_kind                  TEXT NOT NULL,
    canonical_request_digest      CHAR(64) NOT NULL,
    payload_ref                   TEXT NOT NULL,
    payload_digest                CHAR(64) NOT NULL,
    payload_expires_at            TIMESTAMPTZ NOT NULL,
    provider_policy_digest        CHAR(64) NOT NULL,
    task_id                       TEXT NOT NULL,
    task_version                  BIGINT NOT NULL,
    attempt_id                    TEXT NOT NULL,
    attempt_number                INTEGER NOT NULL,
    prepared_event_id             TEXT NOT NULL,
    prepared_event_digest         CHAR(64) NOT NULL,
    plan_schema_version           INTEGER NOT NULL DEFAULT 1,
    plan_version                  BIGINT NOT NULL,
    plan_digest                   CHAR(64) NOT NULL,
    workflow_preparation_digest   CHAR(64) NOT NULL,
    binding_schema_version        INTEGER NOT NULL DEFAULT 1,
    binding_digest                CHAR(64) NOT NULL,
    created_at                    TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT fk_hermes_workflow_binding_command
        FOREIGN KEY (command_id)
        REFERENCES quant_system.hermes_commands(command_id),
    CONSTRAINT fk_hermes_workflow_binding_owner
        FOREIGN KEY (owner_user_id)
        REFERENCES quant_system.app_users(id),
    CONSTRAINT fk_hermes_workflow_binding_event_anchor
        FOREIGN KEY (command_id, command_version, canonical_request_digest)
        REFERENCES quant_system.hermes_command_events(
            command_id,
            command_version,
            canonical_request_digest
        ),
    CONSTRAINT uq_hermes_workflow_binding_saga UNIQUE (workflow_saga_id),
    CONSTRAINT uq_hermes_workflow_binding_task UNIQUE (task_id),
    CONSTRAINT uq_hermes_workflow_binding_attempt UNIQUE (attempt_id),
    CONSTRAINT uq_hermes_workflow_binding_prepared_event
        UNIQUE (task_id, prepared_event_id),
    CONSTRAINT uq_hermes_workflow_binding_digest UNIQUE (binding_digest),
    CONSTRAINT ck_hermes_workflow_binding_command_version CHECK (command_version = 1),
    CONSTRAINT ck_hermes_workflow_binding_preparation_schema
        CHECK (preparation_schema_version = '1.0'),
    CONSTRAINT ck_hermes_workflow_binding_saga
        CHECK (workflow_saga_id ~ '^hqs_[0-9a-f]{24}$'),
    CONSTRAINT ck_hermes_workflow_binding_platform_session
        CHECK (
            char_length(platform_session_id) BETWEEN 1 AND 200
            AND platform_session_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_hermes_workflow_binding_client_request
        CHECK (
            char_length(client_request_id) BETWEEN 1 AND 200
            AND client_request_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        ),
    CONSTRAINT ck_hermes_workflow_binding_command_kind
        CHECK (command_kind = 'research_chat'),
    CONSTRAINT ck_hermes_workflow_binding_request_digest
        CHECK (canonical_request_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_hermes_workflow_binding_payload_digest
        CHECK (payload_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_hermes_workflow_binding_payload_ref
        CHECK (payload_ref = 'hqa-payload:sha256:' || payload_digest::TEXT),
    CONSTRAINT ck_hermes_workflow_binding_provider_digest
        CHECK (provider_policy_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_hermes_workflow_binding_task
        CHECK (task_id ~ '^hqt_[0-9a-f]{24}$'),
    CONSTRAINT ck_hermes_workflow_binding_task_version CHECK (task_version > 0),
    CONSTRAINT ck_hermes_workflow_binding_attempt
        CHECK (attempt_id ~ '^hqa_[0-9a-f]{24}$'),
    CONSTRAINT ck_hermes_workflow_binding_attempt_number CHECK (attempt_number > 0),
    CONSTRAINT ck_hermes_workflow_binding_prepared_event
        CHECK (prepared_event_id ~ '^hqe_[0-9a-f]{24}$'),
    CONSTRAINT ck_hermes_workflow_binding_prepared_event_digest
        CHECK (prepared_event_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_hermes_workflow_binding_plan_schema CHECK (plan_schema_version = 1),
    CONSTRAINT ck_hermes_workflow_binding_plan_version CHECK (plan_version > 0),
    CONSTRAINT ck_hermes_workflow_binding_plan_digest
        CHECK (plan_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_hermes_workflow_binding_preparation_digest
        CHECK (workflow_preparation_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_hermes_workflow_binding_schema CHECK (binding_schema_version = 1),
    CONSTRAINT ck_hermes_workflow_binding_digest
        CHECK (binding_digest ~ '^[0-9a-f]{64}$')
);

-- CREATE TABLE IF NOT EXISTS does not reconcile constraints on an already
-- installed table. Re-assert the v1 Task/Attempt identity cardinality on every
-- migration run. ALTER TABLE deliberately fails (and rolls back this whole
-- migration) if legacy rows violate either invariant.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_hermes_workflow_binding_task'
          AND conrelid =
              'quant_system.hermes_command_workflow_bindings'::regclass
    ) THEN
        ALTER TABLE quant_system.hermes_command_workflow_bindings
            ADD CONSTRAINT uq_hermes_workflow_binding_task UNIQUE (task_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_hermes_workflow_binding_attempt'
          AND conrelid =
              'quant_system.hermes_command_workflow_bindings'::regclass
    ) THEN
        ALTER TABLE quant_system.hermes_command_workflow_bindings
            ADD CONSTRAINT uq_hermes_workflow_binding_attempt UNIQUE (attempt_id);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_hermes_workflow_binding_task_attempt
    ON quant_system.hermes_command_workflow_bindings (
        task_id,
        attempt_id,
        created_at,
        command_id
    );

CREATE OR REPLACE FUNCTION quant_system.reject_hermes_workflow_binding_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'hermes_command_workflow_bindings is append-only';
END;
$$;

CREATE OR REPLACE FUNCTION quant_system.protect_hermes_command_intent_identity()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF ROW(
        NEW.owner_user_id,
        NEW.platform_session_id,
        NEW.client_request_id,
        NEW.kind,
        NEW.intent_schema_version,
        NEW.canonical_request_digest,
        NEW.payload_ref,
        NEW.provider_policy_digest,
        NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.owner_user_id,
        OLD.platform_session_id,
        OLD.client_request_id,
        OLD.kind,
        OLD.intent_schema_version,
        OLD.canonical_request_digest,
        OLD.payload_ref,
        OLD.provider_policy_digest,
        OLD.created_at
    ) THEN
        RAISE EXCEPTION 'Hermes command intent identity is immutable';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION quant_system.validate_hermes_workflow_binding()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    command_owner UUID;
    command_session TEXT;
    command_request_id TEXT;
    command_kind_value TEXT;
    command_digest TEXT;
    command_payload_ref TEXT;
    command_provider_digest TEXT;
BEGIN
    SELECT owner_user_id,
           platform_session_id,
           client_request_id,
           kind,
           canonical_request_digest::TEXT,
           payload_ref,
           provider_policy_digest::TEXT
    INTO command_owner,
         command_session,
         command_request_id,
         command_kind_value,
         command_digest,
         command_payload_ref,
         command_provider_digest
    FROM quant_system.hermes_commands
    WHERE command_id = NEW.command_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'workflow binding command does not exist';
    END IF;
    IF ROW(
        NEW.owner_user_id,
        NEW.platform_session_id,
        NEW.client_request_id,
        NEW.command_kind,
        NEW.canonical_request_digest::TEXT,
        NEW.payload_ref,
        NEW.provider_policy_digest::TEXT
    ) IS DISTINCT FROM ROW(
        command_owner,
        command_session,
        command_request_id,
        command_kind_value,
        command_digest,
        command_payload_ref,
        command_provider_digest
    ) THEN
        RAISE EXCEPTION 'workflow binding does not match immutable command intent';
    END IF;
    IF NOT EXISTS (
        SELECT 1
        FROM quant_system.hermes_command_events
        WHERE command_id = NEW.command_id
          AND command_version = NEW.command_version
          AND canonical_request_digest = NEW.canonical_request_digest
          AND event_type = 'command_created'
          AND from_state IS NULL
          AND to_state = 'queued'
          AND event_data = jsonb_build_object(
              'binding_digest', NEW.binding_digest::TEXT,
              'workflow_preparation_digest', NEW.workflow_preparation_digest::TEXT,
              'workflow_saga_id', NEW.workflow_saga_id
          )
    ) THEN
        RAISE EXCEPTION 'workflow binding has no exact command_created event anchor';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION quant_system.enforce_hermes_claim_binding_eligibility()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.state = 'queued' AND NEW.state = 'leased' AND NOT EXISTS (
        SELECT 1
        FROM quant_system.hermes_command_workflow_bindings AS binding
        WHERE binding.command_id = NEW.command_id
          AND binding.command_version = 1
          AND binding.preparation_schema_version = '1.0'
          AND binding.binding_schema_version = 1
          AND binding.owner_user_id = NEW.owner_user_id
          AND binding.platform_session_id = NEW.platform_session_id
          AND binding.client_request_id = NEW.client_request_id
          AND binding.command_kind = NEW.kind
          AND binding.canonical_request_digest = NEW.canonical_request_digest
          AND binding.payload_ref = NEW.payload_ref
          AND binding.provider_policy_digest = NEW.provider_policy_digest
          AND binding.payload_expires_at > clock_timestamp()
          AND EXISTS (
              SELECT 1
              FROM quant_system.hermes_ledger_meta AS ledger_meta
              WHERE ledger_meta.singleton IS TRUE
                AND ledger_meta.schema_version = 1
          )
          AND EXISTS (
              SELECT 1
              FROM quant_system.hermes_workflow_binding_meta AS binding_meta
              WHERE binding_meta.singleton IS TRUE
                AND binding_meta.schema_version = 1
          )
    ) THEN
        RAISE EXCEPTION 'Hermes claim binding is missing, mismatched, or expired'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_hermes_claim_binding_eligible';
    END IF;
    RETURN NEW;
END;
$$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_hermes_workflow_binding_validate'
          AND tgrelid = 'quant_system.hermes_command_workflow_bindings'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_hermes_workflow_binding_validate
        BEFORE INSERT ON quant_system.hermes_command_workflow_bindings
        FOR EACH ROW
        EXECUTE FUNCTION quant_system.validate_hermes_workflow_binding();
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_hermes_command_claim_binding_guard'
          AND tgrelid = 'quant_system.hermes_commands'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_hermes_command_claim_binding_guard
        AFTER UPDATE OF state ON quant_system.hermes_commands
        FOR EACH ROW
        EXECUTE FUNCTION quant_system.enforce_hermes_claim_binding_eligibility();
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_hermes_workflow_binding_append_only'
          AND tgrelid = 'quant_system.hermes_command_workflow_bindings'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_hermes_workflow_binding_append_only
        BEFORE UPDATE OR DELETE ON quant_system.hermes_command_workflow_bindings
        FOR EACH ROW
        EXECUTE FUNCTION quant_system.reject_hermes_workflow_binding_mutation();
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_hermes_workflow_binding_append_only_truncate'
          AND tgrelid = 'quant_system.hermes_command_workflow_bindings'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_hermes_workflow_binding_append_only_truncate
        BEFORE TRUNCATE ON quant_system.hermes_command_workflow_bindings
        FOR EACH STATEMENT
        EXECUTE FUNCTION quant_system.reject_hermes_workflow_binding_mutation();
    END IF;
END $$;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_trigger
        WHERE tgname = 'trg_hermes_command_intent_immutable'
          AND tgrelid = 'quant_system.hermes_commands'::regclass
          AND NOT tgisinternal
    ) THEN
        CREATE TRIGGER trg_hermes_command_intent_immutable
        BEFORE UPDATE ON quant_system.hermes_commands
        FOR EACH ROW
        EXECUTE FUNCTION quant_system.protect_hermes_command_intent_identity();
    END IF;
END $$;

ALTER TABLE quant_system.hermes_command_workflow_bindings
    ENABLE ALWAYS TRIGGER trg_hermes_workflow_binding_validate;
ALTER TABLE quant_system.hermes_command_workflow_bindings
    ENABLE ALWAYS TRIGGER trg_hermes_workflow_binding_append_only;
ALTER TABLE quant_system.hermes_command_workflow_bindings
    ENABLE ALWAYS TRIGGER trg_hermes_workflow_binding_append_only_truncate;
ALTER TABLE quant_system.hermes_commands
    ENABLE ALWAYS TRIGGER trg_hermes_command_intent_immutable;
ALTER TABLE quant_system.hermes_commands
    ENABLE ALWAYS TRIGGER trg_hermes_command_claim_binding_guard;

COMMIT;
