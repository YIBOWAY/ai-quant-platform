-- Fence candidate Session/Command writes to the still-current, frozen
-- canonical paper authority.  This is additive hardening over live-applied
-- 025: accepted-release binding remains intact, while a stale open candidate
-- now rejects writes instead of creating an unbound managed Session.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended(
        'quant_system:028_agent_v02_candidate_paper_epoch_fence',
        0
    )
);

DO $$
DECLARE
    release_hardening_version INTEGER;
    candidate_version INTEGER;
    ttl_ceiling INTEGER;
    always_trigger_count INTEGER;
BEGIN
    IF to_regclass(
        'quant_system.agent_v02_release_hardening_meta'
    ) IS NULL
       OR to_regclass(
           'quant_system.agent_v02_candidate_admission_meta'
       ) IS NULL
       OR to_regclass(
           'quant_system.paper_accounts'
       ) IS NULL
       OR to_regprocedure(
           'quant_system.current_agent_v02_paper_authority_epoch(uuid,text)'
       ) IS NULL
       OR NOT EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'quant_system'
              AND table_name = 'agent_v02_candidate_admission_meta'
              AND column_name = 'ttl_ceiling_seconds'
       )
    THEN
        RAISE EXCEPTION
            'candidate paper epoch fence requires migrations 020 and 027';
    END IF;

    SELECT schema_version
    INTO release_hardening_version
    FROM quant_system.agent_v02_release_hardening_meta
    WHERE singleton IS TRUE;
    SELECT schema_version, ttl_ceiling_seconds
    INTO candidate_version, ttl_ceiling
    FROM quant_system.agent_v02_candidate_admission_meta
    WHERE singleton IS TRUE;
    IF release_hardening_version IS DISTINCT FROM 1
       OR candidate_version IS DISTINCT FROM 1
       OR ttl_ceiling IS DISTINCT FROM 7200
    THEN
        RAISE EXCEPTION
            'candidate paper epoch fence requires current 020/027 metadata';
    END IF;

    SELECT count(*)
    INTO always_trigger_count
    FROM pg_trigger AS trigger_record
    JOIN pg_class AS relation
      ON relation.oid = trigger_record.tgrelid
    JOIN pg_namespace AS namespace
      ON namespace.oid = relation.relnamespace
    WHERE namespace.nspname = 'quant_system'
      AND (
          (
              relation.relname = 'hermes_workspace_sessions'
              AND trigger_record.tgname =
                    'trg_hermes_session_candidate_binding'
              AND trigger_record.tgfoid = to_regprocedure(
                    'quant_system.bind_agent_v02_candidate_session()'
              )
          )
          OR (
              relation.relname = 'hermes_commands'
              AND trigger_record.tgname =
                    'trg_hermes_command_candidate_binding'
              AND trigger_record.tgfoid = to_regprocedure(
                    'quant_system.bind_agent_v02_candidate_command()'
              )
          )
      )
      AND trigger_record.tgenabled = 'A'
      AND trigger_record.tgtype = 23
      AND NOT trigger_record.tgisinternal;
    IF always_trigger_count <> 2 THEN
        RAISE EXCEPTION
            'candidate paper epoch fence requires the exact 025 ALWAYS triggers';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS
quant_system.agent_v02_candidate_paper_fence_meta (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

INSERT INTO quant_system.agent_v02_candidate_paper_fence_meta (
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
    FROM quant_system.agent_v02_candidate_paper_fence_meta
    WHERE singleton IS TRUE;
    IF installed_version > 1 THEN
        RAISE EXCEPTION
            'candidate paper epoch fence schema version % is newer than this binary supports (1)',
            installed_version;
    ELSIF installed_version <> 1 THEN
        RAISE EXCEPTION
            'candidate paper epoch fence schema version % is incompatible with this binary (expected 1)',
            installed_version;
    END IF;
END $$;

ALTER TABLE quant_system.paper_accounts
    DROP CONSTRAINT IF EXISTS
        ck_agent_v02_default_paper_account_raw_consistency;
ALTER TABLE quant_system.paper_accounts
    ADD CONSTRAINT ck_agent_v02_default_paper_account_raw_consistency
    CHECK (
        account_id <> 'default'
        OR COALESCE(
            raw -> 'account_id' = to_jsonb(account_id)
            AND raw -> 'kill_switch' = to_jsonb(kill_switch),
            FALSE
        )
    );

CREATE OR REPLACE FUNCTION quant_system.bind_agent_v02_candidate_session()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    active_admission_id TEXT;
    release_admission_id TEXT;
    stale_admission_id TEXT;
    current_paper_authority_epoch BIGINT;
    canonical_account_count BIGINT;
    canonical_account_frozen BOOLEAN;
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
            'quant_system:agent_v02_admission:' || NEW.workspace_id,
            0
        )
    );
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'agent-v02-candidate:' || NEW.workspace_id,
            0
        )
    );
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'quant_system:agent_v02_release:' || NEW.workspace_id,
            0
        )
    );

    current_paper_authority_epoch :=
        quant_system.current_agent_v02_paper_authority_epoch(
            NEW.owner_user_id,
            NEW.workspace_id
        );
    SELECT
        count(*)::BIGINT,
        CASE
            WHEN count(*) = 1
            THEN bool_and(
                account.account_id = 'default'
                AND account.kill_switch
                AND account.raw -> 'account_id' =
                    to_jsonb(account.account_id)
                AND account.raw -> 'kill_switch' =
                    to_jsonb(account.kill_switch)
            )
            ELSE NULL
        END
    INTO canonical_account_count, canonical_account_frozen
    FROM quant_system.paper_accounts AS account
    WHERE account.owner_user_id = NEW.owner_user_id;

    SELECT candidate.admission_id
    INTO active_admission_id
    FROM quant_system.agent_v02_candidate_admissions AS candidate
    WHERE candidate.owner_user_id = NEW.owner_user_id
      AND candidate.workspace_id = NEW.workspace_id
      AND candidate.route = '/hermes'
      AND candidate.status = 'open'
      AND candidate.expires_at > clock_timestamp()
      AND candidate.paper_authority_epoch =
            current_paper_authority_epoch
      AND canonical_account_count = 1
      AND canonical_account_frozen IS TRUE
    LIMIT 1;

    IF active_admission_id IS NULL THEN
        SELECT candidate.admission_id
        INTO stale_admission_id
        FROM quant_system.agent_v02_candidate_admissions AS candidate
        WHERE candidate.owner_user_id = NEW.owner_user_id
          AND candidate.workspace_id = NEW.workspace_id
          AND candidate.route = '/hermes'
          AND candidate.status = 'open'
          AND candidate.expires_at > clock_timestamp()
        LIMIT 1;
        IF stale_admission_id IS NOT NULL THEN
            RAISE EXCEPTION
                'candidate paper authority epoch is stale';
        END IF;
    END IF;

    SELECT stamp.candidate_admission_id
    INTO release_admission_id
    FROM quant_system.agent_v02_release_stamps AS stamp
    JOIN quant_system.agent_v02_public_cutovers AS cutover
      ON cutover.stamp_id = stamp.stamp_id
     AND cutover.owner_user_id = stamp.owner_user_id
     AND cutover.workspace_id = stamp.workspace_id
     AND cutover.route = stamp.route
     AND cutover.release_digest = stamp.release_digest
     AND cutover.candidate_admission_id =
            stamp.candidate_admission_id
     AND cutover.candidate_admission_digest =
            stamp.candidate_admission_digest
     AND cutover.candidate_acceptance_digest =
            stamp.candidate_acceptance_digest
     AND cutover.evidence_set_id = stamp.evidence_set_id
     AND cutover.evidence_set_digest = stamp.evidence_set_digest
     AND cutover.final_order_snapshot_digest =
            stamp.final_order_snapshot_digest
     AND cutover.paper_authority_epoch =
            stamp.paper_authority_epoch
     AND cutover.status = 'open'
    JOIN quant_system.agent_v02_candidate_admissions AS candidate
      ON candidate.admission_id = stamp.candidate_admission_id
     AND candidate.owner_user_id = stamp.owner_user_id
     AND candidate.workspace_id = stamp.workspace_id
     AND candidate.route = stamp.route
     AND candidate.admission_digest =
            stamp.candidate_admission_digest
     AND candidate.acceptance_digest =
            stamp.candidate_acceptance_digest
     AND candidate.paper_authority_epoch =
            stamp.paper_authority_epoch
     AND candidate.status = 'accepted'
    JOIN quant_system.agent_v02_paper_authority_epochs AS paper_epoch
      ON paper_epoch.owner_user_id = stamp.owner_user_id
     AND paper_epoch.workspace_id = stamp.workspace_id
     AND paper_epoch.authority_epoch = stamp.paper_authority_epoch
    JOIN quant_system.agent_v02_paper_authority_owner_epochs AS owner_epoch
      ON owner_epoch.owner_user_id = stamp.owner_user_id
     AND owner_epoch.authority_epoch = stamp.paper_authority_epoch
    WHERE stamp.owner_user_id = NEW.owner_user_id
      AND stamp.workspace_id = NEW.workspace_id
      AND stamp.route = '/hermes'
      AND stamp.status = 'active'
      AND stamp.paper_authority_epoch =
            current_paper_authority_epoch
    LIMIT 1;

    IF active_admission_id IS NOT NULL
       AND release_admission_id IS NOT NULL
    THEN
        RAISE EXCEPTION
            'candidate and release admissions cannot both be open';
    END IF;

    NEW.candidate_admission_id :=
        COALESCE(active_admission_id, release_admission_id);
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
    release_admission_id TEXT;
    stale_admission_id TEXT;
    session_admission_id TEXT;
    session_workspace_id TEXT;
    session_kind TEXT;
    current_paper_authority_epoch BIGINT;
    canonical_account_count BIGINT;
    canonical_account_frozen BOOLEAN;
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
            'quant_system:agent_v02_admission:' || session_workspace_id,
            0
        )
    );
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'agent-v02-candidate:' || session_workspace_id,
            0
        )
    );
    PERFORM pg_advisory_xact_lock(
        hashtextextended(
            'quant_system:agent_v02_release:' || session_workspace_id,
            0
        )
    );

    current_paper_authority_epoch :=
        quant_system.current_agent_v02_paper_authority_epoch(
            NEW.owner_user_id,
            session_workspace_id
        );
    SELECT
        count(*)::BIGINT,
        CASE
            WHEN count(*) = 1
            THEN bool_and(
                account.account_id = 'default'
                AND account.kill_switch
                AND account.raw -> 'account_id' =
                    to_jsonb(account.account_id)
                AND account.raw -> 'kill_switch' =
                    to_jsonb(account.kill_switch)
            )
            ELSE NULL
        END
    INTO canonical_account_count, canonical_account_frozen
    FROM quant_system.paper_accounts AS account
    WHERE account.owner_user_id = NEW.owner_user_id;

    SELECT candidate.admission_id
    INTO active_admission_id
    FROM quant_system.agent_v02_candidate_admissions AS candidate
    WHERE candidate.owner_user_id = NEW.owner_user_id
      AND candidate.workspace_id = session_workspace_id
      AND candidate.route = '/hermes'
      AND candidate.status = 'open'
      AND candidate.expires_at > clock_timestamp()
      AND candidate.paper_authority_epoch =
            current_paper_authority_epoch
      AND canonical_account_count = 1
      AND canonical_account_frozen IS TRUE
    LIMIT 1;

    IF active_admission_id IS NULL THEN
        SELECT candidate.admission_id
        INTO stale_admission_id
        FROM quant_system.agent_v02_candidate_admissions AS candidate
        WHERE candidate.owner_user_id = NEW.owner_user_id
          AND candidate.workspace_id = session_workspace_id
          AND candidate.route = '/hermes'
          AND candidate.status = 'open'
          AND candidate.expires_at > clock_timestamp()
        LIMIT 1;
        IF stale_admission_id IS NOT NULL THEN
            RAISE EXCEPTION
                'candidate paper authority epoch is stale';
        END IF;
    END IF;

    SELECT stamp.candidate_admission_id
    INTO release_admission_id
    FROM quant_system.agent_v02_release_stamps AS stamp
    JOIN quant_system.agent_v02_public_cutovers AS cutover
      ON cutover.stamp_id = stamp.stamp_id
     AND cutover.owner_user_id = stamp.owner_user_id
     AND cutover.workspace_id = stamp.workspace_id
     AND cutover.route = stamp.route
     AND cutover.release_digest = stamp.release_digest
     AND cutover.candidate_admission_id = stamp.candidate_admission_id
     AND cutover.candidate_admission_digest =
            stamp.candidate_admission_digest
     AND cutover.candidate_acceptance_digest =
            stamp.candidate_acceptance_digest
     AND cutover.evidence_set_id = stamp.evidence_set_id
     AND cutover.evidence_set_digest = stamp.evidence_set_digest
     AND cutover.final_order_snapshot_digest =
            stamp.final_order_snapshot_digest
     AND cutover.paper_authority_epoch = stamp.paper_authority_epoch
     AND cutover.status = 'open'
    JOIN quant_system.agent_v02_candidate_admissions AS candidate
      ON candidate.admission_id = stamp.candidate_admission_id
     AND candidate.owner_user_id = stamp.owner_user_id
     AND candidate.workspace_id = stamp.workspace_id
     AND candidate.route = stamp.route
     AND candidate.admission_digest = stamp.candidate_admission_digest
     AND candidate.acceptance_digest = stamp.candidate_acceptance_digest
     AND candidate.paper_authority_epoch = stamp.paper_authority_epoch
     AND candidate.status = 'accepted'
    JOIN quant_system.agent_v02_paper_authority_epochs AS paper_epoch
      ON paper_epoch.owner_user_id = stamp.owner_user_id
     AND paper_epoch.workspace_id = stamp.workspace_id
     AND paper_epoch.authority_epoch = stamp.paper_authority_epoch
    JOIN quant_system.agent_v02_paper_authority_owner_epochs AS owner_epoch
      ON owner_epoch.owner_user_id = stamp.owner_user_id
     AND owner_epoch.authority_epoch = stamp.paper_authority_epoch
    WHERE stamp.owner_user_id = NEW.owner_user_id
      AND stamp.workspace_id = session_workspace_id
      AND stamp.route = '/hermes'
      AND stamp.status = 'active'
      AND stamp.paper_authority_epoch =
            current_paper_authority_epoch
    LIMIT 1;

    IF active_admission_id IS NOT NULL
       AND release_admission_id IS NOT NULL
    THEN
        RAISE EXCEPTION
            'candidate and release admissions cannot both be open';
    END IF;

    IF active_admission_id IS NOT NULL THEN
        IF session_admission_id IS DISTINCT FROM active_admission_id THEN
            RAISE EXCEPTION
                'candidate conversation requires its exact candidate session';
        END IF;
        NEW.candidate_admission_id := active_admission_id;
        RETURN NEW;
    END IF;

    IF release_admission_id IS NOT NULL THEN
        IF session_admission_id IS DISTINCT FROM release_admission_id THEN
            RAISE EXCEPTION
                'released conversation requires its exact release session';
        END IF;
        -- Final-release workers claim the historical, intentional NULL scope.
        -- The exact release generation is enforced through the immutable
        -- Session binding above; do not turn this into a candidate command.
        RETURN NEW;
    END IF;

    IF session_admission_id IS NOT NULL THEN
        RAISE EXCEPTION
            'candidate session is not writable outside its admission or exact release';
    END IF;
    RETURN NEW;
END;
$$;

ALTER TABLE quant_system.hermes_workspace_sessions
    ENABLE ALWAYS TRIGGER trg_hermes_session_candidate_binding;
ALTER TABLE quant_system.hermes_commands
    ENABLE ALWAYS TRIGGER trg_hermes_command_candidate_binding;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator') THEN
        ALTER TABLE quant_system.agent_v02_candidate_paper_fence_meta
            OWNER TO quant_migrator;
        ALTER FUNCTION quant_system.bind_agent_v02_candidate_session()
            OWNER TO quant_migrator;
        ALTER FUNCTION quant_system.bind_agent_v02_candidate_command()
            OWNER TO quant_migrator;
    END IF;
    REVOKE ALL ON TABLE
        quant_system.agent_v02_candidate_paper_fence_meta
        FROM PUBLIC;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime') THEN
        REVOKE ALL ON TABLE
            quant_system.agent_v02_candidate_paper_fence_meta
            FROM quant_runtime;
        GRANT SELECT ON TABLE
            quant_system.agent_v02_candidate_paper_fence_meta
            TO quant_runtime;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_readonly') THEN
        REVOKE ALL ON TABLE
            quant_system.agent_v02_candidate_paper_fence_meta
            FROM quant_readonly;
        GRANT SELECT ON TABLE
            quant_system.agent_v02_candidate_paper_fence_meta
            TO quant_readonly;
    END IF;
END $$;

COMMIT;
