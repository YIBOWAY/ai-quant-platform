-- Append-only authority for paper-only factor automation lifecycle and quotas.
-- The table is the daily promote/demote authority.  JSON artifacts are caches.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:029_factor_automation_events', 0)
);

DO $$
DECLARE
    predecessor_version INTEGER;
BEGIN
    IF to_regclass(
        'quant_system.agent_v02_candidate_paper_fence_meta'
    ) IS NULL THEN
        RAISE EXCEPTION
            'factor automation events require migration 028';
    END IF;
    SELECT schema_version
    INTO predecessor_version
    FROM quant_system.agent_v02_candidate_paper_fence_meta
    WHERE singleton IS TRUE;
    IF predecessor_version IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION
            'factor automation events require current migration 028 metadata';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS quant_system.factor_automation_events_meta (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    schema_version INTEGER NOT NULL CHECK (schema_version = 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

INSERT INTO quant_system.factor_automation_events_meta (
    singleton,
    schema_version
)
VALUES (TRUE, 1)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS quant_system.factor_automation_events (
    event_seq BIGSERIAL UNIQUE NOT NULL,
    event_id TEXT PRIMARY KEY,
    owner_user_id UUID NOT NULL,
    workspace_id TEXT NOT NULL,
    event_day DATE NOT NULL,
    event_type TEXT NOT NULL,
    automation_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    candidate_digest TEXT NOT NULL,
    factor_id TEXT NOT NULL,
    manifest_digest TEXT NOT NULL,
    automation_policy_digest TEXT NOT NULL,
    intake_contract_digest TEXT NOT NULL,
    gate1_digest TEXT NOT NULL,
    gate2_digest TEXT NOT NULL,
    gate3_digest TEXT NOT NULL,
    commit_sha TEXT NOT NULL,
    sleeve_id TEXT,
    promotion_scope TEXT NOT NULL DEFAULT 'paper_only',
    reviewer TEXT NOT NULL DEFAULT 'auto',
    lifecycle_state TEXT NOT NULL,
    details JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT ck_factor_automation_event_id
        CHECK (event_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CONSTRAINT ck_factor_automation_workspace
        CHECK (workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'),
    CONSTRAINT ck_factor_automation_type
        CHECK (event_type IN (
            'promotion_committed',
            'sleeve_created',
            'sleeve_paused',
            'demote_started',
            'quarantined_hold',
            'flattened',
            'transferred',
            'manually_accepted',
            'demoted_complete'
        )),
    CONSTRAINT ck_factor_automation_ids
        CHECK (
            automation_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
            AND candidate_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
            AND factor_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
            AND (
                sleeve_id IS NULL
                OR sleeve_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'
            )
        ),
    CONSTRAINT ck_factor_automation_digests
        CHECK (
            candidate_digest ~ '^[0-9a-f]{64}$'
            AND manifest_digest ~ '^[0-9a-f]{64}$'
            AND automation_policy_digest ~ '^[0-9a-f]{64}$'
            AND intake_contract_digest ~ '^[0-9a-f]{64}$'
            AND gate1_digest ~ '^[0-9a-f]{64}$'
            AND gate2_digest ~ '^[0-9a-f]{64}$'
            AND gate3_digest ~ '^[0-9a-f]{64}$'
            AND commit_sha ~ '^[0-9a-f]{40,64}$'
        ),
    CONSTRAINT ck_factor_automation_qualification
        CHECK (
            promotion_scope = 'paper_only'
            AND reviewer = 'auto'
        ),
    CONSTRAINT ck_factor_automation_sleeve_shape
        CHECK (
            (event_type = 'promotion_committed' AND sleeve_id IS NULL)
            OR (event_type <> 'promotion_committed' AND sleeve_id IS NOT NULL)
        ),
    CONSTRAINT ck_factor_automation_details
        CHECK (
            jsonb_typeof(details) = 'object'
            AND octet_length(details::text) <= 16384
        )
);

CREATE INDEX IF NOT EXISTS idx_factor_automation_daily_quota
    ON quant_system.factor_automation_events (
        owner_user_id,
        workspace_id,
        event_day,
        event_type
    );
CREATE INDEX IF NOT EXISTS idx_factor_automation_lifecycle
    ON quant_system.factor_automation_events (
        owner_user_id,
        workspace_id,
        automation_id,
        event_seq
    );
CREATE UNIQUE INDEX IF NOT EXISTS uq_factor_automation_promotion
    ON quant_system.factor_automation_events (
        owner_user_id,
        workspace_id,
        automation_id
    )
    WHERE event_type = 'promotion_committed';
CREATE UNIQUE INDEX IF NOT EXISTS uq_factor_automation_sleeve
    ON quant_system.factor_automation_events (
        owner_user_id,
        workspace_id,
        sleeve_id
    )
    WHERE event_type = 'sleeve_created';

CREATE OR REPLACE FUNCTION quant_system.reject_factor_automation_event_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
BEGIN
    RAISE EXCEPTION 'factor automation events are append-only';
END;
$$;

DROP TRIGGER IF EXISTS trg_factor_automation_events_append_only
    ON quant_system.factor_automation_events;
CREATE TRIGGER trg_factor_automation_events_append_only
    BEFORE UPDATE OR DELETE ON quant_system.factor_automation_events
    FOR EACH ROW
    EXECUTE FUNCTION quant_system.reject_factor_automation_event_mutation();
ALTER TABLE quant_system.factor_automation_events
    ENABLE ALWAYS TRIGGER trg_factor_automation_events_append_only;

CREATE OR REPLACE FUNCTION quant_system.append_factor_automation_event(
    p_event_id TEXT,
    p_owner_user_id UUID,
    p_workspace_id TEXT,
    p_event_type TEXT,
    p_automation_id TEXT,
    p_candidate_id TEXT,
    p_candidate_digest TEXT,
    p_factor_id TEXT,
    p_manifest_digest TEXT,
    p_automation_policy_digest TEXT,
    p_intake_contract_digest TEXT,
    p_gate1_digest TEXT,
    p_gate2_digest TEXT,
    p_gate3_digest TEXT,
    p_commit_sha TEXT,
    p_sleeve_id TEXT,
    p_lifecycle_state TEXT,
    p_details JSONB
)
RETURNS TABLE (
    event_seq BIGINT,
    event_day DATE,
    idempotent_replay BOOLEAN
)
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, quant_system
AS $$
DECLARE
    current_day DATE := (
        clock_timestamp() AT TIME ZONE 'Asia/Shanghai'
    )::date;
    existing quant_system.factor_automation_events%ROWTYPE;
    inserted_seq BIGINT;
    promotion_count BIGINT;
    demote_count BIGINT;
BEGIN
    IF p_owner_user_id <>
        '00000000-0000-0000-0000-000000000001'::uuid
    THEN
        RAISE EXCEPTION 'factor automation owner is invalid';
    END IF;
    IF p_event_type NOT IN (
        'promotion_committed', 'sleeve_created', 'sleeve_paused',
        'demote_started', 'quarantined_hold', 'flattened', 'transferred',
        'manually_accepted', 'demoted_complete'
    ) THEN
        RAISE EXCEPTION 'factor automation event type is invalid';
    END IF;
    IF p_details IS NULL OR jsonb_typeof(p_details) <> 'object' THEN
        RAISE EXCEPTION 'factor automation details are invalid';
    END IF;

    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'factor-automation:' || p_owner_user_id::text || ':' ||
            p_workspace_id || ':' || current_day::text,
            0
        )
    );

    SELECT *
    INTO existing
    FROM quant_system.factor_automation_events AS recorded
    WHERE recorded.event_id = p_event_id;
    IF FOUND THEN
        IF existing.owner_user_id IS DISTINCT FROM p_owner_user_id
           OR existing.workspace_id IS DISTINCT FROM p_workspace_id
           OR existing.event_type IS DISTINCT FROM p_event_type
           OR existing.automation_id IS DISTINCT FROM p_automation_id
           OR existing.candidate_id IS DISTINCT FROM p_candidate_id
           OR existing.candidate_digest IS DISTINCT FROM p_candidate_digest
           OR existing.factor_id IS DISTINCT FROM p_factor_id
           OR existing.manifest_digest IS DISTINCT FROM p_manifest_digest
           OR existing.automation_policy_digest IS DISTINCT FROM
                p_automation_policy_digest
           OR existing.intake_contract_digest IS DISTINCT FROM
                p_intake_contract_digest
           OR existing.gate1_digest IS DISTINCT FROM p_gate1_digest
           OR existing.gate2_digest IS DISTINCT FROM p_gate2_digest
           OR existing.gate3_digest IS DISTINCT FROM p_gate3_digest
           OR existing.commit_sha IS DISTINCT FROM p_commit_sha
           OR existing.sleeve_id IS DISTINCT FROM p_sleeve_id
           OR existing.lifecycle_state IS DISTINCT FROM p_lifecycle_state
           OR existing.details IS DISTINCT FROM p_details
        THEN
            RAISE EXCEPTION 'factor automation idempotency conflict';
        END IF;
        RETURN QUERY SELECT existing.event_seq, existing.event_day, TRUE;
        RETURN;
    END IF;

    IF p_event_type <> 'promotion_committed' AND NOT EXISTS (
        SELECT 1
        FROM quant_system.factor_automation_events AS prior
        WHERE prior.owner_user_id = p_owner_user_id
          AND prior.workspace_id = p_workspace_id
          AND prior.automation_id = p_automation_id
          AND prior.event_type = 'promotion_committed'
    ) THEN
        RAISE EXCEPTION 'factor automation promotion lineage is missing';
    END IF;
    IF p_event_type IN (
        'demote_started', 'quarantined_hold', 'flattened', 'transferred',
        'manually_accepted', 'demoted_complete'
    ) AND NOT EXISTS (
        SELECT 1
        FROM quant_system.factor_automation_events AS prior
        WHERE prior.owner_user_id = p_owner_user_id
          AND prior.workspace_id = p_workspace_id
          AND prior.automation_id = p_automation_id
          AND prior.sleeve_id = p_sleeve_id
          AND prior.event_type = 'sleeve_created'
    ) THEN
        RAISE EXCEPTION 'factor automation sleeve lineage is missing';
    END IF;

    IF p_event_type = 'promotion_committed' THEN
        SELECT count(*)
        INTO promotion_count
        FROM quant_system.factor_automation_events AS daily
        WHERE daily.owner_user_id = p_owner_user_id
          AND daily.workspace_id = p_workspace_id
          AND daily.event_day = current_day
          AND daily.event_type = 'promotion_committed';
        IF promotion_count >= 1 THEN
            RAISE EXCEPTION 'promotion daily quota exceeded';
        END IF;
    ELSIF p_event_type = 'demote_started' THEN
        SELECT count(*)
        INTO demote_count
        FROM quant_system.factor_automation_events AS daily
        WHERE daily.owner_user_id = p_owner_user_id
          AND daily.workspace_id = p_workspace_id
          AND daily.event_day = current_day
          AND daily.event_type = 'demote_started';
        IF demote_count >= 5 THEN
            RAISE EXCEPTION 'demote daily quota exceeded';
        END IF;
    END IF;

    INSERT INTO quant_system.factor_automation_events (
        event_id, owner_user_id, workspace_id, event_day, event_type,
        automation_id, candidate_id, candidate_digest, factor_id,
        manifest_digest, automation_policy_digest, intake_contract_digest,
        gate1_digest, gate2_digest, gate3_digest, commit_sha, sleeve_id,
        promotion_scope, reviewer, lifecycle_state, details
    )
    VALUES (
        p_event_id, p_owner_user_id, p_workspace_id, current_day, p_event_type,
        p_automation_id, p_candidate_id, p_candidate_digest, p_factor_id,
        p_manifest_digest, p_automation_policy_digest, p_intake_contract_digest,
        p_gate1_digest, p_gate2_digest, p_gate3_digest, p_commit_sha, p_sleeve_id,
        'paper_only', 'auto', p_lifecycle_state, p_details
    )
    RETURNING factor_automation_events.event_seq
    INTO inserted_seq;

    RETURN QUERY SELECT inserted_seq, current_day, FALSE;
END;
$$;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator') THEN
        ALTER TABLE quant_system.factor_automation_events_meta
            OWNER TO quant_migrator;
        ALTER TABLE quant_system.factor_automation_events
            OWNER TO quant_migrator;
        ALTER SEQUENCE quant_system.factor_automation_events_event_seq_seq
            OWNER TO quant_migrator;
        ALTER FUNCTION quant_system.reject_factor_automation_event_mutation()
            OWNER TO quant_migrator;
        ALTER FUNCTION quant_system.append_factor_automation_event(
            TEXT, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
            TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB
        ) OWNER TO quant_migrator;
    END IF;

    REVOKE ALL ON TABLE quant_system.factor_automation_events_meta FROM PUBLIC;
    REVOKE ALL ON TABLE quant_system.factor_automation_events FROM PUBLIC;
    REVOKE ALL ON SEQUENCE
        quant_system.factor_automation_events_event_seq_seq FROM PUBLIC;
    REVOKE ALL ON FUNCTION quant_system.append_factor_automation_event(
        TEXT, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
        TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB
    ) FROM PUBLIC;

    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime') THEN
        REVOKE INSERT, UPDATE, DELETE ON TABLE
            quant_system.factor_automation_events FROM quant_runtime;
        GRANT SELECT ON TABLE
            quant_system.factor_automation_events_meta,
            quant_system.factor_automation_events
            TO quant_runtime;
        GRANT EXECUTE ON FUNCTION quant_system.append_factor_automation_event(
            TEXT, UUID, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT,
            TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, TEXT, JSONB
        ) TO quant_runtime;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_readonly') THEN
        REVOKE INSERT, UPDATE, DELETE ON TABLE
            quant_system.factor_automation_events FROM quant_readonly;
        GRANT SELECT ON TABLE
            quant_system.factor_automation_events_meta,
            quant_system.factor_automation_events
            TO quant_readonly;
    END IF;
END $$;

COMMIT;
