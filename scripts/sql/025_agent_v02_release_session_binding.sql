-- Keep every newly-created managed Web Session bound to the exact Agent v0.2
-- admission generation after the candidate has been accepted and the public
-- release is open.  Without this post-release branch, the original candidate
-- trigger only binds sessions while a candidate is open and emits NULL after
-- cutover, weakening cross-generation isolation.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:025_agent_v02_release_session_binding', 0)
);

DO $$
DECLARE
    installed_version INTEGER;
    missing_column_count INTEGER;
    always_trigger_count INTEGER;
BEGIN
    IF to_regclass(
        'quant_system.agent_v02_release_hardening_meta'
    ) IS NULL
       OR to_regclass(
           'quant_system.agent_v02_paper_authority_owner_epochs'
       ) IS NULL
       OR to_regclass(
           'quant_system.agent_v02_paper_authority_epochs'
       ) IS NULL
       OR to_regprocedure(
           'quant_system.current_agent_v02_paper_authority_epoch(uuid,text)'
       ) IS NULL
    THEN
        RAISE EXCEPTION
            'release session binding requires migration 020';
    END IF;

    SELECT schema_version
    INTO installed_version
    FROM quant_system.agent_v02_release_hardening_meta
    WHERE singleton IS TRUE;
    IF installed_version IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION
            'release session binding requires release hardening schema version 1';
    END IF;

    WITH required_columns(table_name, column_name) AS (
        VALUES
            ('hermes_workspace_sessions', 'candidate_admission_id'),
            ('hermes_commands', 'candidate_admission_id'),
            ('agent_v02_candidate_admissions', 'admission_digest'),
            ('agent_v02_candidate_admissions', 'acceptance_digest'),
            ('agent_v02_candidate_admissions', 'paper_authority_epoch'),
            ('agent_v02_release_stamps', 'candidate_admission_id'),
            ('agent_v02_release_stamps', 'candidate_admission_digest'),
            ('agent_v02_release_stamps', 'candidate_acceptance_digest'),
            ('agent_v02_release_stamps', 'evidence_set_id'),
            ('agent_v02_release_stamps', 'evidence_set_digest'),
            ('agent_v02_release_stamps', 'final_order_snapshot_digest'),
            ('agent_v02_release_stamps', 'paper_authority_epoch'),
            ('agent_v02_public_cutovers', 'candidate_admission_id'),
            ('agent_v02_public_cutovers', 'candidate_admission_digest'),
            ('agent_v02_public_cutovers', 'candidate_acceptance_digest'),
            ('agent_v02_public_cutovers', 'evidence_set_id'),
            ('agent_v02_public_cutovers', 'evidence_set_digest'),
            ('agent_v02_public_cutovers', 'final_order_snapshot_digest'),
            ('agent_v02_public_cutovers', 'paper_authority_epoch'),
            ('agent_v02_paper_authority_owner_epochs', 'authority_epoch'),
            ('agent_v02_paper_authority_epochs', 'authority_epoch')
    )
    SELECT count(*)
    INTO missing_column_count
    FROM required_columns AS required
    LEFT JOIN information_schema.columns AS observed
      ON observed.table_schema = 'quant_system'
     AND observed.table_name = required.table_name
     AND observed.column_name = required.column_name
    WHERE observed.column_name IS NULL;
    IF missing_column_count <> 0 THEN
        RAISE EXCEPTION
            'release session binding prerequisite columns are unavailable';
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
            'release session binding requires the exact candidate ALWAYS triggers';
    END IF;
END $$;

CREATE OR REPLACE FUNCTION quant_system.bind_agent_v02_candidate_session()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY INVOKER
AS $$
DECLARE
    active_admission_id TEXT;
    release_admission_id TEXT;
    current_paper_authority_epoch BIGINT;
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

    SELECT admission_id
    INTO active_admission_id
    FROM quant_system.agent_v02_candidate_admissions
    WHERE owner_user_id = NEW.owner_user_id
      AND workspace_id = NEW.workspace_id
      AND route = '/hermes'
      AND status = 'open'
      AND expires_at > clock_timestamp()
    LIMIT 1;

    current_paper_authority_epoch :=
        quant_system.current_agent_v02_paper_authority_epoch(
            NEW.owner_user_id,
            NEW.workspace_id
        );

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
    session_admission_id TEXT;
    session_workspace_id TEXT;
    session_kind TEXT;
    current_paper_authority_epoch BIGINT;
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

    SELECT admission_id
    INTO active_admission_id
    FROM quant_system.agent_v02_candidate_admissions
    WHERE owner_user_id = NEW.owner_user_id
      AND workspace_id = session_workspace_id
      AND route = '/hermes'
      AND status = 'open'
      AND expires_at > clock_timestamp()
    LIMIT 1;

    current_paper_authority_epoch :=
        quant_system.current_agent_v02_paper_authority_epoch(
            NEW.owner_user_id,
            session_workspace_id
        );

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

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator') THEN
        ALTER FUNCTION quant_system.bind_agent_v02_candidate_session()
            OWNER TO quant_migrator;
        ALTER FUNCTION quant_system.bind_agent_v02_candidate_command()
            OWNER TO quant_migrator;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_readonly')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator')
    THEN
        -- The SECURITY INVOKER binding triggers execute as quant_runtime.  The
        -- helper is a read/lock-only SECURITY DEFINER capability and is needed
        -- to serialize those trigger writes with paper-authority epoch bumps.
        REVOKE EXECUTE ON FUNCTION
            quant_system.current_agent_v02_paper_authority_epoch(
                UUID,
                TEXT
            )
            FROM PUBLIC, quant_readonly;
        GRANT EXECUTE ON FUNCTION
            quant_system.current_agent_v02_paper_authority_epoch(
                UUID,
                TEXT
            )
            TO quant_runtime, quant_migrator;
    END IF;
END $$;

COMMIT;
