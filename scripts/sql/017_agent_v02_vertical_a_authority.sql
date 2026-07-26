-- Agent v0.2 durable Vertical-A options domain authority.
--
-- Browser /act only seeds an immutable domain request.  A separately invoked
-- Platform CLI binds that request to an already-canonical Hermes Session/Run,
-- commits the provider-attempt and one-call budget before any external I/O,
-- and later atomically stores the Futu read-only receipt, zero-order proof,
-- domain result and exact Hermes Run output link.
--
-- This schema intentionally owns no HQA Task/Attempt and no Hermes Run.  It
-- stores only exact references to those canonical authorities.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:017_agent_v02_vertical_a_authority', 0)
);

CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_vertical_a_meta (
    singleton       BOOLEAN PRIMARY KEY DEFAULT TRUE,
    schema_version  INTEGER NOT NULL,
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT ck_agent_v02_vertical_a_meta_singleton CHECK (singleton),
    CONSTRAINT ck_agent_v02_vertical_a_meta_version CHECK (schema_version = 2)
);

INSERT INTO quant_system.agent_v02_vertical_a_meta (singleton, schema_version)
VALUES (TRUE, 2)
ON CONFLICT (singleton) DO NOTHING;

DO $$
DECLARE
    installed_version INTEGER;
BEGIN
    SELECT schema_version
    INTO installed_version
    FROM quant_system.agent_v02_vertical_a_meta
    WHERE singleton IS TRUE;

    IF installed_version <> 2 THEN
        RAISE EXCEPTION
            'Vertical-A schema version % is incompatible with this binary (expected 2)',
            installed_version;
    END IF;
END $$;

-- Candidate admission is the server-owned authorization boundary.  The
-- composite identity prevents an admission id/digest from being mixed across
-- owner or workspace even if application code is bypassed.
CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_v02_candidate_exact_identity
    ON quant_system.agent_v02_candidate_admissions (
        admission_id,
        owner_user_id,
        workspace_id,
        admission_digest
    );

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_vertical_a_grants (
    grant_id          TEXT PRIMARY KEY,
    owner_user_id     UUID NOT NULL
        REFERENCES quant_system.app_users(id),
    workspace_id      TEXT NOT NULL,
    admission_id      TEXT NOT NULL,
    admission_digest  CHAR(64) NOT NULL,
    ticker            TEXT NOT NULL,
    fields            JSONB NOT NULL,
    max_calls         INTEGER NOT NULL DEFAULT 1,
    used_calls        INTEGER NOT NULL DEFAULT 0,
    window_start      TIMESTAMPTZ NOT NULL,
    window_end        TIMESTAMPTZ NOT NULL,
    grant_digest      CHAR(64) NOT NULL UNIQUE,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (admission_id),
    UNIQUE (
        grant_id,
        owner_user_id,
        workspace_id,
        admission_id,
        admission_digest,
        ticker,
        grant_digest
    ),
    CONSTRAINT fk_agent_v02_vertical_a_grant_admission
        FOREIGN KEY (
            admission_id,
            owner_user_id,
            workspace_id,
            admission_digest
        )
        REFERENCES quant_system.agent_v02_candidate_admissions (
            admission_id,
            owner_user_id,
            workspace_id,
            admission_digest
        ),
    CONSTRAINT ck_agent_v02_vertical_a_grant_id
        CHECK (
            char_length(grant_id) BETWEEN 1 AND 128
            AND grant_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'
        ),
    CONSTRAINT ck_agent_v02_vertical_a_grant_workspace
        CHECK (
            char_length(workspace_id) BETWEEN 1 AND 200
            AND workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'
        ),
    CONSTRAINT ck_agent_v02_vertical_a_grant_admission_digest
        CHECK (admission_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_grant_ticker
        CHECK (
            char_length(ticker) BETWEEN 1 AND 32
            AND ticker ~ '^[A-Z0-9][A-Z0-9.-]*$'
        ),
    CONSTRAINT ck_agent_v02_vertical_a_grant_fields
        CHECK (
            jsonb_typeof(fields) = 'array'
            AND fields = '["ask","bid","delta","expiry","iv","strike"]'::jsonb
        ),
    CONSTRAINT ck_agent_v02_vertical_a_grant_budget
        CHECK (
            max_calls = 1
            AND used_calls BETWEEN 0 AND max_calls
        ),
    CONSTRAINT ck_agent_v02_vertical_a_grant_window
        CHECK (window_start < window_end),
    CONSTRAINT ck_agent_v02_vertical_a_grant_digest
        CHECK (grant_digest ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_vertical_a_requests (
    request_id              TEXT PRIMARY KEY,
    owner_user_id           UUID NOT NULL
        REFERENCES quant_system.app_users(id),
    workspace_id            TEXT NOT NULL,
    client_action_id        TEXT NOT NULL,
    action_digest           CHAR(64) NOT NULL,
    admission_id            TEXT NOT NULL,
    admission_digest        CHAR(64) NOT NULL,
    grant_id                TEXT NOT NULL,
    grant_digest            CHAR(64) NOT NULL,
    ticker                  TEXT NOT NULL,
    expiry                  TEXT NOT NULL,
    strike                  DOUBLE PRECISION NOT NULL,
    option_type             TEXT NOT NULL DEFAULT 'PUT',
    requested_scope_digest  CHAR(64) NOT NULL,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (owner_user_id, workspace_id, client_action_id),
    UNIQUE (request_id, owner_user_id, workspace_id),
    UNIQUE (request_id, owner_user_id, workspace_id, action_digest),
    UNIQUE (
        request_id,
        owner_user_id,
        workspace_id,
        action_digest,
        admission_id,
        admission_digest,
        grant_id,
        grant_digest
    ),
    CONSTRAINT fk_agent_v02_vertical_a_request_grant
        FOREIGN KEY (
            grant_id,
            owner_user_id,
            workspace_id,
            admission_id,
            admission_digest,
            ticker,
            grant_digest
        )
        REFERENCES quant_system.agent_v02_vertical_a_grants (
            grant_id,
            owner_user_id,
            workspace_id,
            admission_id,
            admission_digest,
            ticker,
            grant_digest
        ),
    CONSTRAINT ck_agent_v02_vertical_a_request_id
        CHECK (
            char_length(request_id) BETWEEN 1 AND 128
            AND request_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'
        ),
    CONSTRAINT ck_agent_v02_vertical_a_request_workspace
        CHECK (
            char_length(workspace_id) BETWEEN 1 AND 200
            AND workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'
        ),
    CONSTRAINT ck_agent_v02_vertical_a_request_action_id
        CHECK (
            char_length(client_action_id) BETWEEN 1 AND 200
            AND client_action_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'
        ),
    CONSTRAINT ck_agent_v02_vertical_a_request_action_digest
        CHECK (action_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_request_admission_digest
        CHECK (admission_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_request_grant_digest
        CHECK (grant_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_request_ticker
        CHECK (
            char_length(ticker) BETWEEN 1 AND 32
            AND ticker ~ '^[A-Z0-9][A-Z0-9.-]*$'
        ),
    CONSTRAINT ck_agent_v02_vertical_a_request_expiry
        CHECK (char_length(expiry) BETWEEN 1 AND 32),
    CONSTRAINT ck_agent_v02_vertical_a_request_strike
        CHECK (strike > 0 AND strike < 'Infinity'::DOUBLE PRECISION),
    CONSTRAINT ck_agent_v02_vertical_a_request_option_type
        CHECK (option_type = 'PUT'),
    CONSTRAINT ck_agent_v02_vertical_a_request_scope_digest
        CHECK (requested_scope_digest ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_vertical_a_claims (
    claim_id                 TEXT PRIMARY KEY,
    request_id               TEXT NOT NULL UNIQUE,
    owner_user_id            UUID NOT NULL,
    workspace_id             TEXT NOT NULL,
    action_digest            CHAR(64) NOT NULL,
    admission_id             TEXT NOT NULL,
    admission_digest         CHAR(64) NOT NULL,
    grant_id                 TEXT NOT NULL,
    grant_digest             CHAR(64) NOT NULL,
    command_id               UUID NOT NULL
        REFERENCES quant_system.hermes_commands(command_id),
    platform_session_id      TEXT NOT NULL
        REFERENCES quant_system.hermes_workspace_sessions(platform_session_id),
    hermes_session_id        TEXT NOT NULL,
    hermes_run_id            TEXT NOT NULL,
    worker_id                TEXT NOT NULL,
    begin_snapshot_digest    CHAR(64) NOT NULL,
    begin_table_counts       JSONB NOT NULL,
    begin_table_digests      JSONB NOT NULL,
    claim_digest             CHAR(64) NOT NULL UNIQUE,
    claimed_at               TIMESTAMPTZ NOT NULL,
    UNIQUE (claim_id, request_id, owner_user_id, workspace_id),
    UNIQUE (
        claim_id,
        request_id,
        owner_user_id,
        workspace_id,
        action_digest,
        admission_id,
        admission_digest,
        begin_snapshot_digest
    ),
    UNIQUE (
        claim_id,
        request_id,
        owner_user_id,
        workspace_id,
        command_id,
        platform_session_id,
        hermes_session_id,
        hermes_run_id
    ),
    UNIQUE (
        claim_id,
        request_id,
        owner_user_id,
        workspace_id,
        action_digest,
        admission_id,
        admission_digest,
        grant_id,
        grant_digest,
        command_id,
        platform_session_id,
        hermes_session_id,
        hermes_run_id
    ),
    CONSTRAINT fk_agent_v02_vertical_a_claim_request
        FOREIGN KEY (
            request_id,
            owner_user_id,
            workspace_id,
            action_digest,
            admission_id,
            admission_digest,
            grant_id,
            grant_digest
        )
        REFERENCES quant_system.agent_v02_vertical_a_requests (
            request_id,
            owner_user_id,
            workspace_id,
            action_digest,
            admission_id,
            admission_digest,
            grant_id,
            grant_digest
        ),
    CONSTRAINT ck_agent_v02_vertical_a_claim_id
        CHECK (
            char_length(claim_id) BETWEEN 1 AND 128
            AND claim_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'
        ),
    CONSTRAINT ck_agent_v02_vertical_a_claim_action_digest
        CHECK (action_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_claim_admission_digest
        CHECK (admission_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_claim_grant_digest
        CHECK (grant_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_claim_session
        CHECK (
            char_length(platform_session_id) BETWEEN 1 AND 200
            AND char_length(hermes_session_id) BETWEEN 1 AND 256
        ),
    CONSTRAINT ck_agent_v02_vertical_a_claim_run
        CHECK (char_length(hermes_run_id) BETWEEN 1 AND 256),
    CONSTRAINT ck_agent_v02_vertical_a_claim_worker
        CHECK (
            char_length(worker_id) BETWEEN 1 AND 128
            AND worker_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'
        ),
    CONSTRAINT ck_agent_v02_vertical_a_claim_begin_digest
        CHECK (begin_snapshot_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_claim_begin_shapes
        CHECK (
            jsonb_typeof(begin_table_counts) = 'object'
            AND jsonb_typeof(begin_table_digests) = 'object'
        ),
    CONSTRAINT ck_agent_v02_vertical_a_claim_digest
        CHECK (claim_digest ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_vertical_a_zero_order_observations (
    observation_id          TEXT PRIMARY KEY,
    claim_id                TEXT NOT NULL UNIQUE,
    request_id              TEXT NOT NULL,
    owner_user_id           UUID NOT NULL,
    workspace_id            TEXT NOT NULL,
    action_digest           CHAR(64) NOT NULL,
    admission_id            TEXT NOT NULL,
    admission_digest        CHAR(64) NOT NULL,
    begin_snapshot_digest   CHAR(64) NOT NULL,
    end_snapshot_digest     CHAR(64) NOT NULL,
    begin_table_counts      JSONB NOT NULL,
    end_table_counts        JSONB NOT NULL,
    begin_table_digests     JSONB NOT NULL,
    end_table_digests       JSONB NOT NULL,
    orders_created          INTEGER NOT NULL,
    delta_zero              BOOLEAN NOT NULL,
    capture_digest          CHAR(64) NOT NULL UNIQUE,
    captured_at             TIMESTAMPTZ NOT NULL,
    UNIQUE (
        capture_digest,
        claim_id,
        request_id,
        owner_user_id,
        workspace_id
    ),
    UNIQUE (
        claim_id,
        request_id,
        owner_user_id,
        workspace_id,
        action_digest,
        admission_id,
        admission_digest,
        begin_snapshot_digest
    ),
    CONSTRAINT fk_agent_v02_vertical_a_zero_claim
        FOREIGN KEY (
            claim_id,
            request_id,
            owner_user_id,
            workspace_id,
            action_digest,
            admission_id,
            admission_digest,
            begin_snapshot_digest
        )
        REFERENCES quant_system.agent_v02_vertical_a_claims (
            claim_id,
            request_id,
            owner_user_id,
            workspace_id,
            action_digest,
            admission_id,
            admission_digest,
            begin_snapshot_digest
        ),
    CONSTRAINT ck_agent_v02_vertical_a_zero_action
        CHECK (action_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_zero_admission
        CHECK (admission_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_zero_begin_digest
        CHECK (begin_snapshot_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_zero_end_digest
        CHECK (end_snapshot_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_zero_capture_digest
        CHECK (capture_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_zero_table_shapes
        CHECK (
            jsonb_typeof(begin_table_counts) = 'object'
            AND jsonb_typeof(end_table_counts) = 'object'
            AND jsonb_typeof(begin_table_digests) = 'object'
            AND jsonb_typeof(end_table_digests) = 'object'
        ),
    CONSTRAINT ck_agent_v02_vertical_a_zero_exact
        CHECK (
            orders_created = 0
            AND delta_zero IS TRUE
            AND begin_snapshot_digest = end_snapshot_digest
            AND begin_table_counts = end_table_counts
            AND begin_table_digests = end_table_digests
        )
);

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_vertical_a_provider_receipts (
    provider_receipt_id   TEXT PRIMARY KEY,
    claim_id              TEXT NOT NULL UNIQUE,
    request_id            TEXT NOT NULL,
    owner_user_id         UUID NOT NULL,
    workspace_id          TEXT NOT NULL,
    action_digest         CHAR(64) NOT NULL,
    admission_id          TEXT NOT NULL,
    admission_digest      CHAR(64) NOT NULL,
    command_id            UUID NOT NULL,
    platform_session_id   TEXT NOT NULL,
    hermes_session_id     TEXT NOT NULL,
    hermes_run_id         TEXT NOT NULL,
    capture_digest        CHAR(64) NOT NULL,
    provider              TEXT NOT NULL,
    provider_request_id   TEXT NOT NULL,
    as_of                 TIMESTAMPTZ NOT NULL,
    ticker                TEXT NOT NULL,
    expiry                TEXT NOT NULL,
    strike                DOUBLE PRECISION NOT NULL,
    field_summary         JSONB NOT NULL,
    field_summary_digest  CHAR(64) NOT NULL,
    grant_id              TEXT NOT NULL,
    grant_digest          CHAR(64) NOT NULL,
    receipt_digest        CHAR(64) NOT NULL UNIQUE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (
        provider_receipt_id,
        claim_id,
        request_id,
        owner_user_id,
        workspace_id,
        command_id,
        platform_session_id,
        hermes_session_id,
        hermes_run_id
    ),
    CONSTRAINT fk_agent_v02_vertical_a_provider_claim
        FOREIGN KEY (
            claim_id,
            request_id,
            owner_user_id,
            workspace_id,
            action_digest,
            admission_id,
            admission_digest,
            grant_id,
            grant_digest,
            command_id,
            platform_session_id,
            hermes_session_id,
            hermes_run_id
        )
        REFERENCES quant_system.agent_v02_vertical_a_claims (
            claim_id,
            request_id,
            owner_user_id,
            workspace_id,
            action_digest,
            admission_id,
            admission_digest,
            grant_id,
            grant_digest,
            command_id,
            platform_session_id,
            hermes_session_id,
            hermes_run_id
        ),
    CONSTRAINT fk_agent_v02_vertical_a_provider_zero
        FOREIGN KEY (
            capture_digest,
            claim_id,
            request_id,
            owner_user_id,
            workspace_id
        )
        REFERENCES quant_system.agent_v02_vertical_a_zero_order_observations (
            capture_digest,
            claim_id,
            request_id,
            owner_user_id,
            workspace_id
        ),
    CONSTRAINT ck_agent_v02_vertical_a_provider_action
        CHECK (action_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_provider_admission
        CHECK (admission_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_provider_capture
        CHECK (capture_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_provider_name
        CHECK (provider = 'futu'),
    CONSTRAINT ck_agent_v02_vertical_a_provider_request
        CHECK (
            char_length(provider_request_id) BETWEEN 1 AND 128
            AND provider_request_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]*$'
        ),
    CONSTRAINT ck_agent_v02_vertical_a_provider_ticker
        CHECK (
            char_length(ticker) BETWEEN 1 AND 32
            AND ticker ~ '^[A-Z0-9][A-Z0-9.-]*$'
        ),
    CONSTRAINT ck_agent_v02_vertical_a_provider_expiry
        CHECK (char_length(expiry) BETWEEN 1 AND 32),
    CONSTRAINT ck_agent_v02_vertical_a_provider_strike
        CHECK (strike > 0 AND strike < 'Infinity'::DOUBLE PRECISION),
    CONSTRAINT ck_agent_v02_vertical_a_provider_field_summary
        CHECK (
            jsonb_typeof(field_summary) = 'object'
            AND field_summary ?& ARRAY[
                'ticker', 'expiry', 'strike', 'bid', 'ask', 'delta', 'iv', 'apr'
            ]
        ),
    CONSTRAINT ck_agent_v02_vertical_a_provider_field_digest
        CHECK (field_summary_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_provider_grant_digest
        CHECK (grant_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_provider_receipt_digest
        CHECK (receipt_digest ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_vertical_a_results (
    result_id             TEXT PRIMARY KEY,
    request_id            TEXT NOT NULL UNIQUE,
    claim_id              TEXT NOT NULL UNIQUE,
    owner_user_id         UUID NOT NULL,
    workspace_id          TEXT NOT NULL,
    command_id            UUID NOT NULL
        REFERENCES quant_system.hermes_commands(command_id),
    platform_session_id   TEXT NOT NULL,
    hermes_session_id     TEXT NOT NULL,
    hermes_run_id         TEXT NOT NULL,
    provider_receipt_id   TEXT NOT NULL UNIQUE,
    status                TEXT NOT NULL,
    sample_or_real        TEXT NOT NULL,
    public_payload        JSONB NOT NULL,
    public_payload_digest CHAR(64) NOT NULL,
    occurred_at           TIMESTAMPTZ NOT NULL,
    UNIQUE (result_id, request_id, claim_id, owner_user_id, workspace_id),
    UNIQUE (
        result_id,
        request_id,
        claim_id,
        owner_user_id,
        workspace_id,
        command_id,
        platform_session_id,
        hermes_session_id,
        hermes_run_id
    ),
    CONSTRAINT fk_agent_v02_vertical_a_result_claim
        FOREIGN KEY (
            claim_id,
            request_id,
            owner_user_id,
            workspace_id,
            command_id,
            platform_session_id,
            hermes_session_id,
            hermes_run_id
        )
        REFERENCES quant_system.agent_v02_vertical_a_claims (
            claim_id,
            request_id,
            owner_user_id,
            workspace_id,
            command_id,
            platform_session_id,
            hermes_session_id,
            hermes_run_id
        ),
    CONSTRAINT fk_agent_v02_vertical_a_result_provider
        FOREIGN KEY (
            provider_receipt_id,
            claim_id,
            request_id,
            owner_user_id,
            workspace_id,
            command_id,
            platform_session_id,
            hermes_session_id,
            hermes_run_id
        )
        REFERENCES quant_system.agent_v02_vertical_a_provider_receipts (
            provider_receipt_id,
            claim_id,
            request_id,
            owner_user_id,
            workspace_id,
            command_id,
            platform_session_id,
            hermes_session_id,
            hermes_run_id
        ),
    CONSTRAINT ck_agent_v02_vertical_a_result_status
        CHECK (status = 'completed'),
    CONSTRAINT ck_agent_v02_vertical_a_result_real
        CHECK (sample_or_real = 'real'),
    CONSTRAINT ck_agent_v02_vertical_a_result_payload
        CHECK (jsonb_typeof(public_payload) = 'object'),
    CONSTRAINT ck_agent_v02_vertical_a_result_payload_digest
        CHECK (public_payload_digest ~ '^[0-9a-f]{64}$')
);

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_vertical_a_outcomes (
    outcome_id       TEXT PRIMARY KEY,
    request_id       TEXT NOT NULL UNIQUE
        REFERENCES quant_system.agent_v02_vertical_a_requests(request_id),
    claim_id         TEXT NOT NULL UNIQUE
        REFERENCES quant_system.agent_v02_vertical_a_claims(claim_id),
    owner_user_id    UUID NOT NULL,
    workspace_id     TEXT NOT NULL,
    status           TEXT NOT NULL,
    result_id        TEXT
        REFERENCES quant_system.agent_v02_vertical_a_results(result_id),
    error_code       TEXT,
    public_receipt   JSONB NOT NULL,
    occurred_at      TIMESTAMPTZ NOT NULL,
    CONSTRAINT fk_agent_v02_vertical_a_outcome_request
        FOREIGN KEY (request_id, owner_user_id, workspace_id)
        REFERENCES quant_system.agent_v02_vertical_a_requests (
            request_id, owner_user_id, workspace_id
        ),
    CONSTRAINT fk_agent_v02_vertical_a_outcome_claim
        FOREIGN KEY (claim_id, request_id, owner_user_id, workspace_id)
        REFERENCES quant_system.agent_v02_vertical_a_claims (
            claim_id, request_id, owner_user_id, workspace_id
        ),
    CONSTRAINT fk_agent_v02_vertical_a_outcome_result
        FOREIGN KEY (
            result_id, request_id, claim_id, owner_user_id, workspace_id
        )
        REFERENCES quant_system.agent_v02_vertical_a_results (
            result_id, request_id, claim_id, owner_user_id, workspace_id
        ),
    CONSTRAINT ck_agent_v02_vertical_a_outcome_status
        CHECK (status IN ('completed', 'outcome_unknown')),
    CONSTRAINT ck_agent_v02_vertical_a_outcome_shape
        CHECK (
            (
                status = 'completed'
                AND result_id IS NOT NULL
                AND error_code IS NULL
            )
            OR
            (
                status = 'outcome_unknown'
                AND result_id IS NULL
                AND char_length(error_code) BETWEEN 1 AND 128
            )
        ),
    CONSTRAINT ck_agent_v02_vertical_a_outcome_receipt
        CHECK (jsonb_typeof(public_receipt) = 'object')
);

CREATE TABLE IF NOT EXISTS quant_system.agent_v02_vertical_a_actions (
    owner_user_id     UUID NOT NULL,
    workspace_id      TEXT NOT NULL,
    client_action_id  TEXT NOT NULL,
    action_digest     CHAR(64) NOT NULL,
    request_id        TEXT NOT NULL,
    seed_receipt      JSONB NOT NULL,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (owner_user_id, workspace_id, client_action_id),
    CONSTRAINT fk_agent_v02_vertical_a_action_request
        FOREIGN KEY (
            request_id,
            owner_user_id,
            workspace_id,
            action_digest
        )
        REFERENCES quant_system.agent_v02_vertical_a_requests (
            request_id,
            owner_user_id,
            workspace_id,
            action_digest
        ),
    CONSTRAINT ck_agent_v02_vertical_a_action_digest
        CHECK (action_digest ~ '^[0-9a-f]{64}$'),
    CONSTRAINT ck_agent_v02_vertical_a_action_receipt
        CHECK (jsonb_typeof(seed_receipt) = 'object')
);

CREATE INDEX IF NOT EXISTS idx_agent_v02_vertical_a_requests_workspace
    ON quant_system.agent_v02_vertical_a_requests (
        owner_user_id, workspace_id, created_at, request_id
    );
CREATE INDEX IF NOT EXISTS idx_agent_v02_vertical_a_results_workspace
    ON quant_system.agent_v02_vertical_a_results (
        owner_user_id, workspace_id, occurred_at, result_id
    );
CREATE INDEX IF NOT EXISTS idx_agent_v02_vertical_a_claims_run
    ON quant_system.agent_v02_vertical_a_claims (
        hermes_session_id, hermes_run_id, claimed_at
    );

CREATE OR REPLACE FUNCTION quant_system.protect_agent_v02_vertical_a_grant()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'Vertical-A grants cannot be deleted';
    END IF;
    IF ROW(
        NEW.grant_id,
        NEW.owner_user_id,
        NEW.workspace_id,
        NEW.admission_id,
        NEW.admission_digest,
        NEW.ticker,
        NEW.fields,
        NEW.max_calls,
        NEW.window_start,
        NEW.window_end,
        NEW.grant_digest,
        NEW.created_at
    ) IS DISTINCT FROM ROW(
        OLD.grant_id,
        OLD.owner_user_id,
        OLD.workspace_id,
        OLD.admission_id,
        OLD.admission_digest,
        OLD.ticker,
        OLD.fields,
        OLD.max_calls,
        OLD.window_start,
        OLD.window_end,
        OLD.grant_digest,
        OLD.created_at
    ) THEN
        RAISE EXCEPTION 'Vertical-A grant identity is immutable';
    END IF;
    IF NEW.used_calls < OLD.used_calls OR NEW.used_calls > NEW.max_calls THEN
        RAISE EXCEPTION 'Vertical-A grant budget is monotonic and bounded';
    END IF;
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION quant_system.reject_agent_v02_vertical_a_fact_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    RAISE EXCEPTION 'Vertical-A authority facts are append-only';
END;
$$;

CREATE OR REPLACE FUNCTION quant_system.guard_agent_v02_vertical_a_claim()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM quant_system.agent_v02_vertical_a_requests AS request
        JOIN quant_system.agent_v02_vertical_a_grants AS capability_grant
          ON capability_grant.grant_id = request.grant_id
         AND capability_grant.owner_user_id = request.owner_user_id
         AND capability_grant.workspace_id = request.workspace_id
         AND capability_grant.admission_id = request.admission_id
         AND capability_grant.admission_digest = request.admission_digest
        JOIN quant_system.agent_v02_candidate_admissions AS admission
          ON admission.admission_id = request.admission_id
         AND admission.owner_user_id = request.owner_user_id
         AND admission.workspace_id = request.workspace_id
         AND admission.admission_digest = request.admission_digest
        JOIN quant_system.hermes_workspace_sessions AS session
          ON session.platform_session_id = NEW.platform_session_id
         AND session.owner_user_id = request.owner_user_id
         AND session.workspace_id = request.workspace_id
         AND session.kind = 'web_managed_session'
         AND session.provision_state = 'ready'
         AND session.provisioning_receipt_digest IS NOT NULL
         AND session.provisioned_at IS NOT NULL
         AND session.hermes_session_id = NEW.hermes_session_id
         AND session.candidate_admission_id = request.admission_id
        JOIN quant_system.hermes_commands AS command
          ON command.command_id = NEW.command_id
         AND command.owner_user_id = request.owner_user_id
         AND command.platform_session_id = session.platform_session_id
         AND command.hermes_session_id = session.hermes_session_id
         AND command.hermes_run_id = NEW.hermes_run_id
         AND command.candidate_admission_id = request.admission_id
         AND command.state IN ('delivered', 'succeeded')
        WHERE request.request_id = NEW.request_id
          AND request.owner_user_id = NEW.owner_user_id
          AND request.workspace_id = NEW.workspace_id
          AND request.action_digest = NEW.action_digest
          AND request.admission_id = NEW.admission_id
          AND request.admission_digest = NEW.admission_digest
          AND request.grant_id = NEW.grant_id
          AND request.grant_digest = NEW.grant_digest
          AND admission.status = 'open'
          AND admission.expires_at > NEW.claimed_at
          AND capability_grant.used_calls = 1
    ) THEN
        RAISE EXCEPTION 'Vertical-A claim lacks exact live canonical authority';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_agent_v02_vertical_a_grant_protect
    ON quant_system.agent_v02_vertical_a_grants;
CREATE TRIGGER trg_agent_v02_vertical_a_grant_protect
BEFORE UPDATE OR DELETE ON quant_system.agent_v02_vertical_a_grants
FOR EACH ROW
EXECUTE FUNCTION quant_system.protect_agent_v02_vertical_a_grant();
ALTER TABLE quant_system.agent_v02_vertical_a_grants
    ENABLE ALWAYS TRIGGER trg_agent_v02_vertical_a_grant_protect;

DROP TRIGGER IF EXISTS trg_agent_v02_vertical_a_claim_guard
    ON quant_system.agent_v02_vertical_a_claims;
CREATE TRIGGER trg_agent_v02_vertical_a_claim_guard
BEFORE INSERT ON quant_system.agent_v02_vertical_a_claims
FOR EACH ROW
EXECUTE FUNCTION quant_system.guard_agent_v02_vertical_a_claim();
ALTER TABLE quant_system.agent_v02_vertical_a_claims
    ENABLE ALWAYS TRIGGER trg_agent_v02_vertical_a_claim_guard;

DO $$
DECLARE
    relation_name TEXT;
    trigger_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'agent_v02_vertical_a_requests',
        'agent_v02_vertical_a_claims',
        'agent_v02_vertical_a_zero_order_observations',
        'agent_v02_vertical_a_provider_receipts',
        'agent_v02_vertical_a_results',
        'agent_v02_vertical_a_outcomes',
        'agent_v02_vertical_a_actions'
    ]
    LOOP
        trigger_name := 'trg_' || relation_name || '_append_only';
        EXECUTE format(
            'DROP TRIGGER IF EXISTS %I ON quant_system.%I',
            trigger_name,
            relation_name
        );
        EXECUTE format(
            'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON quant_system.%I '
            'FOR EACH ROW EXECUTE FUNCTION '
            'quant_system.reject_agent_v02_vertical_a_fact_mutation()',
            trigger_name,
            relation_name
        );
        EXECUTE format(
            'ALTER TABLE quant_system.%I ENABLE ALWAYS TRIGGER %I',
            relation_name,
            trigger_name
        );
    END LOOP;
END $$;

DO $$
DECLARE
    relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'agent_v02_vertical_a_grants',
        'agent_v02_vertical_a_requests',
        'agent_v02_vertical_a_claims',
        'agent_v02_vertical_a_zero_order_observations',
        'agent_v02_vertical_a_provider_receipts',
        'agent_v02_vertical_a_results',
        'agent_v02_vertical_a_outcomes',
        'agent_v02_vertical_a_actions'
    ]
    LOOP
        EXECUTE format(
            'ALTER TABLE quant_system.%I ENABLE ROW LEVEL SECURITY',
            relation_name
        );
        EXECUTE format(
            'ALTER TABLE quant_system.%I FORCE ROW LEVEL SECURITY',
            relation_name
        );
        EXECUTE format(
            'DROP POLICY IF EXISTS v4r_root_scope ON quant_system.%I',
            relation_name
        );
        EXECUTE format(
            'CREATE POLICY v4r_root_scope ON quant_system.%I '
            'TO quant_runtime, quant_readonly '
            'USING (owner_user_id = '
            '''00000000-0000-0000-0000-000000000001''::uuid) '
            'WITH CHECK (owner_user_id = '
            '''00000000-0000-0000-0000-000000000001''::uuid)',
            relation_name
        );
        EXECUTE format(
            'DROP POLICY IF EXISTS v4r_migrator_all ON quant_system.%I',
            relation_name
        );
        EXECUTE format(
            'CREATE POLICY v4r_migrator_all ON quant_system.%I '
            'TO quant_migrator USING (TRUE) WITH CHECK (TRUE)',
            relation_name
        );
    END LOOP;
END $$;

GRANT USAGE ON SCHEMA quant_system
    TO quant_runtime, quant_readonly, quant_migrator;
REVOKE CREATE ON SCHEMA quant_system
    FROM quant_runtime, quant_readonly;

REVOKE ALL ON
    quant_system.agent_v02_vertical_a_meta,
    quant_system.agent_v02_vertical_a_grants,
    quant_system.agent_v02_vertical_a_requests,
    quant_system.agent_v02_vertical_a_claims,
    quant_system.agent_v02_vertical_a_zero_order_observations,
    quant_system.agent_v02_vertical_a_provider_receipts,
    quant_system.agent_v02_vertical_a_results,
    quant_system.agent_v02_vertical_a_outcomes,
    quant_system.agent_v02_vertical_a_actions
FROM PUBLIC, quant_runtime, quant_readonly;

GRANT SELECT ON
    quant_system.agent_v02_vertical_a_meta,
    quant_system.agent_v02_vertical_a_grants,
    quant_system.agent_v02_vertical_a_requests,
    quant_system.agent_v02_vertical_a_claims,
    quant_system.agent_v02_vertical_a_zero_order_observations,
    quant_system.agent_v02_vertical_a_provider_receipts,
    quant_system.agent_v02_vertical_a_results,
    quant_system.agent_v02_vertical_a_outcomes,
    quant_system.agent_v02_vertical_a_actions
TO quant_runtime, quant_readonly;

GRANT INSERT ON
    quant_system.agent_v02_vertical_a_grants,
    quant_system.agent_v02_vertical_a_requests,
    quant_system.agent_v02_vertical_a_claims,
    quant_system.agent_v02_vertical_a_zero_order_observations,
    quant_system.agent_v02_vertical_a_provider_receipts,
    quant_system.agent_v02_vertical_a_results,
    quant_system.agent_v02_vertical_a_outcomes,
    quant_system.agent_v02_vertical_a_actions
TO quant_runtime;

GRANT UPDATE (used_calls, updated_at)
    ON quant_system.agent_v02_vertical_a_grants
    TO quant_runtime;

GRANT ALL ON
    quant_system.agent_v02_vertical_a_meta,
    quant_system.agent_v02_vertical_a_grants,
    quant_system.agent_v02_vertical_a_requests,
    quant_system.agent_v02_vertical_a_claims,
    quant_system.agent_v02_vertical_a_zero_order_observations,
    quant_system.agent_v02_vertical_a_provider_receipts,
    quant_system.agent_v02_vertical_a_results,
    quant_system.agent_v02_vertical_a_outcomes,
    quant_system.agent_v02_vertical_a_actions
TO quant_migrator;

REVOKE EXECUTE
    ON FUNCTION quant_system.protect_agent_v02_vertical_a_grant(),
                quant_system.reject_agent_v02_vertical_a_fact_mutation(),
                quant_system.guard_agent_v02_vertical_a_claim()
    FROM PUBLIC, quant_runtime, quant_readonly;
GRANT EXECUTE
    ON FUNCTION quant_system.protect_agent_v02_vertical_a_grant(),
                quant_system.reject_agent_v02_vertical_a_fact_mutation(),
                quant_system.guard_agent_v02_vertical_a_claim()
    TO quant_migrator;

DO $$
DECLARE
    relation_name TEXT;
BEGIN
    FOREACH relation_name IN ARRAY ARRAY[
        'agent_v02_vertical_a_meta',
        'agent_v02_vertical_a_grants',
        'agent_v02_vertical_a_requests',
        'agent_v02_vertical_a_claims',
        'agent_v02_vertical_a_zero_order_observations',
        'agent_v02_vertical_a_provider_receipts',
        'agent_v02_vertical_a_results',
        'agent_v02_vertical_a_outcomes',
        'agent_v02_vertical_a_actions'
    ]
    LOOP
        EXECUTE format(
            'ALTER TABLE quant_system.%I OWNER TO quant_migrator',
            relation_name
        );
    END LOOP;
END $$;

ALTER FUNCTION quant_system.protect_agent_v02_vertical_a_grant()
    OWNER TO quant_migrator;
ALTER FUNCTION quant_system.reject_agent_v02_vertical_a_fact_mutation()
    OWNER TO quant_migrator;
ALTER FUNCTION quant_system.guard_agent_v02_vertical_a_claim()
    OWNER TO quant_migrator;

COMMIT;
