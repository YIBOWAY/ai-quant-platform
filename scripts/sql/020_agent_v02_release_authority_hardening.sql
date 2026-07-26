-- Agent v0.2 release-authority hardening.
--
-- This forward-only migration closes two authority gaps without rewriting the
-- already-live 012/016/019 migrations:
--
--   * release-stamp and public-cutover INSERTs are accepted only when they bind
--     the exact accepted candidate, verified evidence set, runtime identities,
--     live schema fingerprint, final evidence digest, and current paper epoch;
--   * every mutation of the four canonical paper execution authorities bumps a
--     server-owned owner/workspace epoch.  Candidate evidence, acceptance,
--     release stamps, and cutovers must all carry the same still-current epoch.
--
-- Existing pre-020 rows remain historical and readable.  Their nullable
-- binding columns can never satisfy the new INSERT guards or effective gate.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended(
        'quant_system:020_agent_v02_release_authority_hardening',
        0
    )
);

CREATE SCHEMA IF NOT EXISTS quant_system;

CREATE TABLE IF NOT EXISTS
quant_system.agent_v02_release_hardening_meta (
    singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
    schema_version INTEGER NOT NULL CHECK (schema_version > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO quant_system.agent_v02_release_hardening_meta (
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
    FROM quant_system.agent_v02_release_hardening_meta
    WHERE singleton IS TRUE;

    IF installed_version > 1 THEN
        RAISE EXCEPTION
            'Agent v0.2 release hardening schema version % is newer than this binary supports (1)',
            installed_version;
    ELSIF installed_version <> 1 THEN
        RAISE EXCEPTION
            'Agent v0.2 release hardening schema version % is incompatible with this binary (expected 1)',
            installed_version;
    END IF;
END $$;

CREATE SEQUENCE IF NOT EXISTS
    quant_system.agent_v02_paper_authority_epoch_seq
    AS BIGINT
    MINVALUE 1
    START WITH 1
    INCREMENT BY 1
    NO CYCLE;

-- Paper tables carry owner identity but no workspace identity.  The owner row
-- therefore exists even before the first workspace candidate and is the lock
-- that serializes concurrent paper mutations with workspace-epoch creation.
CREATE TABLE IF NOT EXISTS
quant_system.agent_v02_paper_authority_owner_epochs (
    owner_user_id UUID PRIMARY KEY
        REFERENCES quant_system.app_users(id),
    authority_epoch BIGINT NOT NULL CHECK (authority_epoch > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS
quant_system.agent_v02_paper_authority_epochs (
    owner_user_id UUID NOT NULL
        REFERENCES quant_system.app_users(id),
    workspace_id TEXT NOT NULL,
    authority_epoch BIGINT NOT NULL CHECK (authority_epoch > 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (owner_user_id, workspace_id),
    CONSTRAINT ck_agent_v02_paper_authority_epoch_workspace
        CHECK (
            char_length(workspace_id) BETWEEN 1 AND 200
            AND workspace_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
        )
);

ALTER TABLE quant_system.agent_v02_candidate_admissions
    ADD COLUMN IF NOT EXISTS paper_authority_epoch BIGINT;
ALTER TABLE quant_system.agent_v02_candidate_evidence_sets
    ADD COLUMN IF NOT EXISTS paper_authority_epoch BIGINT;

ALTER TABLE quant_system.agent_v02_release_stamps
    ADD COLUMN IF NOT EXISTS candidate_admission_id TEXT;
ALTER TABLE quant_system.agent_v02_release_stamps
    ADD COLUMN IF NOT EXISTS candidate_admission_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_release_stamps
    ADD COLUMN IF NOT EXISTS candidate_acceptance_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_release_stamps
    ADD COLUMN IF NOT EXISTS evidence_set_id TEXT;
ALTER TABLE quant_system.agent_v02_release_stamps
    ADD COLUMN IF NOT EXISTS evidence_set_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_release_stamps
    ADD COLUMN IF NOT EXISTS final_order_snapshot_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_release_stamps
    ADD COLUMN IF NOT EXISTS paper_authority_epoch BIGINT;

ALTER TABLE quant_system.agent_v02_public_cutovers
    ADD COLUMN IF NOT EXISTS candidate_admission_id TEXT;
ALTER TABLE quant_system.agent_v02_public_cutovers
    ADD COLUMN IF NOT EXISTS candidate_admission_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_public_cutovers
    ADD COLUMN IF NOT EXISTS candidate_acceptance_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_public_cutovers
    ADD COLUMN IF NOT EXISTS evidence_set_id TEXT;
ALTER TABLE quant_system.agent_v02_public_cutovers
    ADD COLUMN IF NOT EXISTS evidence_set_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_public_cutovers
    ADD COLUMN IF NOT EXISTS final_order_snapshot_digest CHAR(64);
ALTER TABLE quant_system.agent_v02_public_cutovers
    ADD COLUMN IF NOT EXISTS paper_authority_epoch BIGINT;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_agent_v02_candidate_paper_epoch'
          AND conrelid =
              'quant_system.agent_v02_candidate_admissions'::regclass
    ) THEN
        ALTER TABLE quant_system.agent_v02_candidate_admissions
            ADD CONSTRAINT ck_agent_v02_candidate_paper_epoch
            CHECK (
                paper_authority_epoch IS NULL
                OR paper_authority_epoch > 0
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_agent_v02_candidate_evidence_paper_epoch'
          AND conrelid =
              'quant_system.agent_v02_candidate_evidence_sets'::regclass
    ) THEN
        ALTER TABLE quant_system.agent_v02_candidate_evidence_sets
            ADD CONSTRAINT ck_agent_v02_candidate_evidence_paper_epoch
            CHECK (
                paper_authority_epoch IS NULL
                OR paper_authority_epoch > 0
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_agent_v02_release_candidate_binding'
          AND conrelid =
              'quant_system.agent_v02_release_stamps'::regclass
    ) THEN
        ALTER TABLE quant_system.agent_v02_release_stamps
            ADD CONSTRAINT ck_agent_v02_release_candidate_binding
            CHECK (
                (
                    candidate_admission_id IS NULL
                    AND candidate_admission_digest IS NULL
                    AND candidate_acceptance_digest IS NULL
                    AND evidence_set_id IS NULL
                    AND evidence_set_digest IS NULL
                    AND final_order_snapshot_digest IS NULL
                    AND paper_authority_epoch IS NULL
                )
                OR
                (
                    candidate_admission_id
                        ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$'
                    AND candidate_admission_digest
                        ~ '^[0-9a-f]{64}$'
                    AND candidate_acceptance_digest
                        ~ '^[0-9a-f]{64}$'
                    AND evidence_set_id
                        ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$'
                    AND evidence_set_digest
                        ~ '^[0-9a-f]{64}$'
                    AND final_order_snapshot_digest
                        ~ '^[0-9a-f]{64}$'
                    AND paper_authority_epoch > 0
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_agent_v02_cutover_candidate_binding'
          AND conrelid =
              'quant_system.agent_v02_public_cutovers'::regclass
    ) THEN
        ALTER TABLE quant_system.agent_v02_public_cutovers
            ADD CONSTRAINT ck_agent_v02_cutover_candidate_binding
            CHECK (
                (
                    candidate_admission_id IS NULL
                    AND candidate_admission_digest IS NULL
                    AND candidate_acceptance_digest IS NULL
                    AND evidence_set_id IS NULL
                    AND evidence_set_digest IS NULL
                    AND final_order_snapshot_digest IS NULL
                    AND paper_authority_epoch IS NULL
                )
                OR
                (
                    candidate_admission_id
                        ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$'
                    AND candidate_admission_digest
                        ~ '^[0-9a-f]{64}$'
                    AND candidate_acceptance_digest
                        ~ '^[0-9a-f]{64}$'
                    AND evidence_set_id
                        ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$'
                    AND evidence_set_digest
                        ~ '^[0-9a-f]{64}$'
                    AND final_order_snapshot_digest
                        ~ '^[0-9a-f]{64}$'
                    AND paper_authority_epoch > 0
                )
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_agent_v02_release_candidate_admission'
          AND conrelid =
              'quant_system.agent_v02_release_stamps'::regclass
    ) THEN
        ALTER TABLE quant_system.agent_v02_release_stamps
            ADD CONSTRAINT fk_agent_v02_release_candidate_admission
            FOREIGN KEY (candidate_admission_id)
            REFERENCES quant_system.agent_v02_candidate_admissions(
                admission_id
            );
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'fk_agent_v02_release_evidence_set'
          AND conrelid =
              'quant_system.agent_v02_release_stamps'::regclass
    ) THEN
        ALTER TABLE quant_system.agent_v02_release_stamps
            ADD CONSTRAINT fk_agent_v02_release_evidence_set
            FOREIGN KEY (evidence_set_id)
            REFERENCES quant_system.agent_v02_candidate_evidence_sets(
                evidence_set_id
            );
    END IF;
END $$;

CREATE OR REPLACE FUNCTION
quant_system.ensure_agent_v02_paper_authority_epoch(
    requested_owner UUID,
    requested_workspace TEXT
)
RETURNS BIGINT
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    observed_epoch BIGINT;
BEGIN
    IF requested_workspace IS NULL
       OR char_length(requested_workspace) NOT BETWEEN 1 AND 200
       OR requested_workspace
            !~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
    THEN
        RAISE EXCEPTION 'paper authority workspace is invalid';
    END IF;

    INSERT INTO quant_system.agent_v02_paper_authority_owner_epochs
        AS owner_epoch (
        owner_user_id,
        authority_epoch,
        updated_at
    )
    VALUES (
        requested_owner,
        nextval(
            'quant_system.agent_v02_paper_authority_epoch_seq'::regclass
        ),
        clock_timestamp()
    )
    ON CONFLICT (owner_user_id) DO NOTHING;

    SELECT authority_epoch
    INTO observed_epoch
    FROM quant_system.agent_v02_paper_authority_owner_epochs
    WHERE owner_user_id = requested_owner
    FOR UPDATE;

    IF observed_epoch IS NULL THEN
        RAISE EXCEPTION 'paper authority epoch could not be established';
    END IF;

    INSERT INTO quant_system.agent_v02_paper_authority_epochs
        AS workspace_epoch (
        owner_user_id,
        workspace_id,
        authority_epoch,
        updated_at
    )
    VALUES (
        requested_owner,
        requested_workspace,
        observed_epoch,
        clock_timestamp()
    )
    ON CONFLICT (owner_user_id, workspace_id) DO UPDATE
    SET authority_epoch = GREATEST(
            workspace_epoch.authority_epoch,
            EXCLUDED.authority_epoch
        ),
        updated_at = CASE
            WHEN workspace_epoch.authority_epoch
                < EXCLUDED.authority_epoch
            THEN EXCLUDED.updated_at
            ELSE workspace_epoch.updated_at
        END;

    SELECT authority_epoch
    INTO observed_epoch
    FROM quant_system.agent_v02_paper_authority_epochs
    WHERE owner_user_id = requested_owner
      AND workspace_id = requested_workspace;
    RETURN observed_epoch;
END;
$$;

CREATE OR REPLACE FUNCTION
quant_system.current_agent_v02_paper_authority_epoch(
    requested_owner UUID,
    requested_workspace TEXT
)
RETURNS BIGINT
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    owner_authority_epoch BIGINT;
    workspace_authority_epoch BIGINT;
BEGIN
    -- All candidate/release guards take these locks in owner -> workspace
    -- order.  Paper mutations take the same order with UPDATE locks, so a
    -- post-snapshot mutation cannot commit between validation and the guarded
    -- candidate/evidence/stamp/cutover write.
    SELECT owner_epoch.authority_epoch
    INTO owner_authority_epoch
    FROM quant_system.agent_v02_paper_authority_owner_epochs
        AS owner_epoch
    WHERE owner_epoch.owner_user_id = requested_owner
    FOR SHARE;

    IF owner_authority_epoch IS NULL THEN
        RETURN NULL;
    END IF;

    SELECT workspace_epoch.authority_epoch
    INTO workspace_authority_epoch
    FROM quant_system.agent_v02_paper_authority_epochs
        AS workspace_epoch
    WHERE workspace_epoch.owner_user_id = requested_owner
      AND workspace_epoch.workspace_id = requested_workspace
    FOR SHARE;

    IF workspace_authority_epoch IS DISTINCT FROM owner_authority_epoch THEN
        RETURN NULL;
    END IF;
    RETURN workspace_authority_epoch;
END;
$$;

CREATE OR REPLACE FUNCTION
quant_system.bump_agent_v02_paper_authority_owner(
    affected_owner UUID
)
RETURNS VOID
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    next_epoch BIGINT;
BEGIN
    IF affected_owner IS NULL THEN
        RETURN;
    END IF;

    next_epoch := nextval(
        'quant_system.agent_v02_paper_authority_epoch_seq'::regclass
    );

    INSERT INTO quant_system.agent_v02_paper_authority_owner_epochs
        AS owner_epoch (
        owner_user_id,
        authority_epoch,
        updated_at
    )
    VALUES (
        affected_owner,
        next_epoch,
        clock_timestamp()
    )
    ON CONFLICT (owner_user_id) DO UPDATE
    SET authority_epoch = GREATEST(
            owner_epoch.authority_epoch,
            EXCLUDED.authority_epoch
        ),
        updated_at = CASE
            WHEN owner_epoch.authority_epoch < EXCLUDED.authority_epoch
            THEN EXCLUDED.updated_at
            ELSE owner_epoch.updated_at
        END
    RETURNING authority_epoch INTO next_epoch;

    UPDATE quant_system.agent_v02_paper_authority_epochs
    SET authority_epoch = GREATEST(authority_epoch, next_epoch),
        updated_at = CASE
            WHEN authority_epoch < next_epoch
            THEN clock_timestamp()
            ELSE updated_at
        END
    WHERE owner_user_id = affected_owner;
END;
$$;

CREATE OR REPLACE FUNCTION
quant_system.bump_agent_v02_paper_authority_epoch()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    old_owner UUID;
    new_owner UUID;
BEGIN
    IF TG_TABLE_NAME = 'paper_accounts' THEN
        IF TG_OP <> 'INSERT' THEN
            old_owner := OLD.owner_user_id;
        END IF;
        IF TG_OP <> 'DELETE' THEN
            new_owner := NEW.owner_user_id;
        END IF;
    ELSE
        IF TG_OP <> 'INSERT' THEN
            SELECT owner_user_id
            INTO old_owner
            FROM quant_system.paper_accounts
            WHERE account_id = OLD.account_id;
        END IF;
        IF TG_OP <> 'DELETE' THEN
            SELECT owner_user_id
            INTO new_owner
            FROM quant_system.paper_accounts
            WHERE account_id = NEW.account_id;
        END IF;
    END IF;

    PERFORM quant_system.bump_agent_v02_paper_authority_owner(
        old_owner
    );
    IF new_owner IS DISTINCT FROM old_owner THEN
        PERFORM quant_system.bump_agent_v02_paper_authority_owner(
            new_owner
        );
    END IF;

    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DO $$
DECLARE
    table_name TEXT;
    trigger_name TEXT;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'paper_accounts',
        'paper_account_ledger',
        'paper_pending_orders',
        'paper_positions_current'
    ]
    LOOP
        trigger_name := 'trg_agent_v02_paper_epoch_' || table_name;
        EXECUTE format(
            'DROP TRIGGER IF EXISTS %I ON quant_system.%I',
            trigger_name,
            table_name
        );
        EXECUTE format(
            'CREATE TRIGGER %I '
            'BEFORE INSERT OR UPDATE OR DELETE ON quant_system.%I '
            'FOR EACH ROW EXECUTE FUNCTION '
            'quant_system.bump_agent_v02_paper_authority_epoch()',
            trigger_name,
            table_name
        );
        EXECUTE format(
            'ALTER TABLE quant_system.%I ENABLE ALWAYS TRIGGER %I',
            table_name,
            trigger_name
        );
    END LOOP;
END $$;

CREATE OR REPLACE FUNCTION
quant_system.bind_agent_v02_candidate_paper_epoch()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    observed_epoch BIGINT;
BEGIN
    observed_epoch :=
        quant_system.ensure_agent_v02_paper_authority_epoch(
            NEW.owner_user_id,
            NEW.workspace_id
        );
    IF NEW.paper_authority_epoch IS NULL THEN
        NEW.paper_authority_epoch := observed_epoch;
    ELSIF NEW.paper_authority_epoch <> observed_epoch THEN
        RAISE EXCEPTION
            'candidate admission paper authority epoch is stale';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_agent_v02_candidate_admission_epoch_bind
    ON quant_system.agent_v02_candidate_admissions;
CREATE TRIGGER trg_agent_v02_candidate_admission_epoch_bind
BEFORE INSERT ON quant_system.agent_v02_candidate_admissions
FOR EACH ROW
EXECUTE FUNCTION
    quant_system.bind_agent_v02_candidate_paper_epoch();
ALTER TABLE quant_system.agent_v02_candidate_admissions
    ENABLE ALWAYS TRIGGER
        trg_agent_v02_candidate_admission_epoch_bind;

CREATE OR REPLACE FUNCTION
quant_system.bind_agent_v02_candidate_evidence_paper_epoch()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    candidate_epoch BIGINT;
    current_epoch BIGINT;
BEGIN
    SELECT paper_authority_epoch
    INTO candidate_epoch
    FROM quant_system.agent_v02_candidate_admissions
    WHERE admission_id = NEW.admission_id
      AND owner_user_id = NEW.owner_user_id
      AND workspace_id = NEW.workspace_id
      AND admission_digest = NEW.admission_digest
      AND status = 'open'
    FOR SHARE;

    current_epoch :=
        quant_system.current_agent_v02_paper_authority_epoch(
            NEW.owner_user_id,
            NEW.workspace_id
        );

    IF candidate_epoch IS NULL
       OR current_epoch IS NULL
       OR candidate_epoch <> current_epoch
    THEN
        RAISE EXCEPTION
            'candidate evidence paper authority epoch is stale';
    END IF;

    IF NEW.paper_authority_epoch IS NULL THEN
        NEW.paper_authority_epoch := candidate_epoch;
    ELSIF NEW.paper_authority_epoch <> candidate_epoch THEN
        RAISE EXCEPTION
            'candidate evidence paper authority epoch binding mismatch';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_agent_v02_candidate_evidence_epoch_bind
    ON quant_system.agent_v02_candidate_evidence_sets;
CREATE TRIGGER trg_agent_v02_candidate_evidence_epoch_bind
BEFORE INSERT ON quant_system.agent_v02_candidate_evidence_sets
FOR EACH ROW
EXECUTE FUNCTION
    quant_system.bind_agent_v02_candidate_evidence_paper_epoch();
ALTER TABLE quant_system.agent_v02_candidate_evidence_sets
    ENABLE ALWAYS TRIGGER
        trg_agent_v02_candidate_evidence_epoch_bind;

CREATE OR REPLACE FUNCTION
quant_system.guard_agent_v02_candidate_acceptance_paper_epoch()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    canonical_payload TEXT;
    current_epoch BIGINT;
    expected_acceptance_digest TEXT;
BEGIN
    IF NEW.paper_authority_epoch
        IS DISTINCT FROM OLD.paper_authority_epoch
    THEN
        RAISE EXCEPTION
            'candidate admission paper authority epoch is immutable';
    END IF;

    IF OLD.status = 'open' AND NEW.status = 'accepted' THEN
        current_epoch :=
            quant_system.current_agent_v02_paper_authority_epoch(
                OLD.owner_user_id,
                OLD.workspace_id
            );
        IF current_epoch IS NULL
           OR OLD.paper_authority_epoch IS NULL
           OR current_epoch <> OLD.paper_authority_epoch
           OR NOT EXISTS (
                SELECT 1
                FROM quant_system.agent_v02_candidate_evidence_sets
                    AS evidence_set
                WHERE evidence_set.evidence_set_id =
                        NEW.evidence_set_id
                  AND evidence_set.admission_id =
                        NEW.admission_id
                  AND evidence_set.owner_user_id =
                        NEW.owner_user_id
                  AND evidence_set.workspace_id =
                        NEW.workspace_id
                  AND evidence_set.admission_digest =
                        NEW.admission_digest
                  AND evidence_set.facts_digest =
                        NEW.evidence_set_digest
                  AND evidence_set.final_order_snapshot_digest =
                        NEW.final_order_snapshot_digest
                  AND evidence_set.baseline_order_snapshot_digest =
                        NEW.baseline_order_snapshot_digest
                  AND evidence_set.paper_authority_epoch =
                        OLD.paper_authority_epoch
            )
        THEN
            RAISE EXCEPTION
                'candidate acceptance requires the current paper authority epoch';
        END IF;

        canonical_payload := format(
            '{"admission_digest":"%s",'
            '"closed_at":"%s",'
            '"evidence_set_digest":"%s",'
            '"evidence_set_id":"%s",'
            '"final_evidence_digest":"%s",'
            '"final_order_snapshot_digest":"%s",'
            '"paper_authority_epoch":%s,'
            '"status":"accepted"}',
            NEW.admission_digest,
            to_char(
                NEW.closed_at AT TIME ZONE 'UTC',
                'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
            ),
            NEW.evidence_set_digest,
            NEW.evidence_set_id,
            NEW.final_evidence_digest,
            NEW.final_order_snapshot_digest,
            OLD.paper_authority_epoch
        );
        expected_acceptance_digest := encode(
            sha256(convert_to(canonical_payload, 'UTF8')),
            'hex'
        );
        IF NEW.acceptance_digest
            IS DISTINCT FROM expected_acceptance_digest
        THEN
            RAISE EXCEPTION
                'candidate acceptance digest does not match its canonical paper epoch binding';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS
    trg_agent_v02_candidate_acceptance_epoch_guard
    ON quant_system.agent_v02_candidate_admissions;
CREATE TRIGGER trg_agent_v02_candidate_acceptance_epoch_guard
BEFORE UPDATE ON quant_system.agent_v02_candidate_admissions
FOR EACH ROW
EXECUTE FUNCTION
    quant_system.guard_agent_v02_candidate_acceptance_paper_epoch();
ALTER TABLE quant_system.agent_v02_candidate_admissions
    ENABLE ALWAYS TRIGGER
        trg_agent_v02_candidate_acceptance_epoch_guard;

CREATE OR REPLACE FUNCTION
quant_system.guard_agent_v02_release_stamp_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    accepted_binding BOOLEAN;
    canonical_payload TEXT;
    current_epoch BIGINT;
    expected_release_digest TEXT;
BEGIN
    current_epoch :=
        quant_system.current_agent_v02_paper_authority_epoch(
            NEW.owner_user_id,
            NEW.workspace_id
        );
    SELECT TRUE
    INTO accepted_binding
        FROM quant_system.agent_v02_candidate_admissions AS candidate
        JOIN quant_system.agent_v02_candidate_evidence_sets
            AS evidence_set
          ON evidence_set.evidence_set_id =
                candidate.evidence_set_id
         AND evidence_set.admission_id =
                candidate.admission_id
         AND evidence_set.owner_user_id =
                candidate.owner_user_id
         AND evidence_set.workspace_id =
                candidate.workspace_id
         AND evidence_set.admission_digest =
                candidate.admission_digest
         AND evidence_set.facts_digest =
                candidate.evidence_set_digest
         AND evidence_set.final_order_snapshot_digest =
                candidate.final_order_snapshot_digest
         AND evidence_set.baseline_order_snapshot_digest =
                candidate.baseline_order_snapshot_digest
         AND evidence_set.paper_authority_epoch =
                candidate.paper_authority_epoch
        JOIN quant_system.agent_v02_paper_authority_epochs
            AS paper_epoch
          ON paper_epoch.owner_user_id = candidate.owner_user_id
         AND paper_epoch.workspace_id = candidate.workspace_id
         AND paper_epoch.authority_epoch =
                candidate.paper_authority_epoch
        JOIN quant_system.agent_v02_paper_authority_owner_epochs
            AS owner_epoch
          ON owner_epoch.owner_user_id = candidate.owner_user_id
         AND owner_epoch.authority_epoch =
                candidate.paper_authority_epoch
        WHERE candidate.admission_id =
                NEW.candidate_admission_id
          AND candidate.owner_user_id = NEW.owner_user_id
          AND candidate.workspace_id = NEW.workspace_id
          AND candidate.route = NEW.route
          AND candidate.status = 'accepted'
          AND candidate.admission_digest =
                NEW.candidate_admission_digest
          AND candidate.acceptance_digest =
                NEW.candidate_acceptance_digest
          AND candidate.evidence_set_id = NEW.evidence_set_id
          AND candidate.evidence_set_digest =
                NEW.evidence_set_digest
          AND candidate.platform_runtime_digest =
                NEW.platform_runtime_digest
          AND candidate.hqa_runtime_digest =
                NEW.hqa_runtime_digest
          AND candidate.hermes_runtime_digest =
                NEW.hermes_runtime_digest
          AND candidate.database_schema_fingerprint =
                NEW.database_schema_fingerprint
          AND candidate.final_evidence_digest =
                NEW.evidence_digest
          AND candidate.final_order_snapshot_digest =
                NEW.final_order_snapshot_digest
          AND candidate.final_order_snapshot_digest =
                candidate.baseline_order_snapshot_digest
          AND candidate.paper_authority_epoch =
                NEW.paper_authority_epoch
          AND candidate.closed_at <= NEW.opened_at
        FOR SHARE OF candidate, evidence_set;

    IF current_epoch IS DISTINCT FROM NEW.paper_authority_epoch
       OR accepted_binding IS DISTINCT FROM TRUE
    THEN
        RAISE EXCEPTION
            'release stamp requires the exact current accepted candidate binding';
    END IF;

    canonical_payload := format(
        '{"candidate_acceptance_digest":"%s",'
        '"candidate_admission_digest":"%s",'
        '"candidate_admission_id":"%s",'
        '"database_schema_fingerprint":"%s",'
        '"evidence_digest":"%s",'
        '"evidence_set_digest":"%s",'
        '"evidence_set_id":"%s",'
        '"final_order_snapshot_digest":"%s",'
        '"hermes_runtime_digest":"%s",'
        '"hqa_runtime_digest":"%s",'
        '"opened_at":"%s",'
        '"paper_authority_epoch":%s,'
        '"platform_runtime_digest":"%s",'
        '"route":"%s",'
        '"stamp_id":"%s",'
        '"workspace_id":"%s"}',
        NEW.candidate_acceptance_digest,
        NEW.candidate_admission_digest,
        NEW.candidate_admission_id,
        NEW.database_schema_fingerprint,
        NEW.evidence_digest,
        NEW.evidence_set_digest,
        NEW.evidence_set_id,
        NEW.final_order_snapshot_digest,
        NEW.hermes_runtime_digest,
        NEW.hqa_runtime_digest,
        to_char(
            NEW.opened_at AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ),
        NEW.paper_authority_epoch,
        NEW.platform_runtime_digest,
        NEW.route,
        NEW.stamp_id,
        NEW.workspace_id
    );
    expected_release_digest := encode(
        sha256(convert_to(canonical_payload, 'UTF8')),
        'hex'
    );
    IF NEW.release_digest IS DISTINCT FROM expected_release_digest THEN
        RAISE EXCEPTION
            'release stamp digest does not match its canonical binding';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_agent_v02_release_stamps_insert_guard
    ON quant_system.agent_v02_release_stamps;
CREATE TRIGGER trg_agent_v02_release_stamps_insert_guard
BEFORE INSERT ON quant_system.agent_v02_release_stamps
FOR EACH ROW
EXECUTE FUNCTION
    quant_system.guard_agent_v02_release_stamp_insert();
ALTER TABLE quant_system.agent_v02_release_stamps
    ENABLE ALWAYS TRIGGER
        trg_agent_v02_release_stamps_insert_guard;

CREATE OR REPLACE FUNCTION
quant_system.guard_agent_v02_public_cutover_insert()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
DECLARE
    active_stamp_binding BOOLEAN;
    canonical_payload TEXT;
    current_epoch BIGINT;
    expected_cutover_digest TEXT;
BEGIN
    current_epoch :=
        quant_system.current_agent_v02_paper_authority_epoch(
            NEW.owner_user_id,
            NEW.workspace_id
        );
    SELECT TRUE
    INTO active_stamp_binding
        FROM quant_system.agent_v02_release_stamps AS stamp
        JOIN quant_system.agent_v02_paper_authority_epochs
            AS paper_epoch
          ON paper_epoch.owner_user_id = stamp.owner_user_id
         AND paper_epoch.workspace_id = stamp.workspace_id
         AND paper_epoch.authority_epoch =
                stamp.paper_authority_epoch
        JOIN quant_system.agent_v02_paper_authority_owner_epochs
            AS owner_epoch
          ON owner_epoch.owner_user_id = stamp.owner_user_id
         AND owner_epoch.authority_epoch =
                stamp.paper_authority_epoch
        WHERE stamp.stamp_id = NEW.stamp_id
          AND stamp.owner_user_id = NEW.owner_user_id
          AND stamp.workspace_id = NEW.workspace_id
          AND stamp.route = NEW.route
          AND stamp.release_digest = NEW.release_digest
          AND stamp.status = 'active'
          AND stamp.candidate_admission_id =
                NEW.candidate_admission_id
          AND stamp.candidate_admission_digest =
                NEW.candidate_admission_digest
          AND stamp.candidate_acceptance_digest =
                NEW.candidate_acceptance_digest
          AND stamp.evidence_set_id = NEW.evidence_set_id
          AND stamp.evidence_set_digest =
                NEW.evidence_set_digest
          AND stamp.final_order_snapshot_digest =
                NEW.final_order_snapshot_digest
          AND stamp.paper_authority_epoch =
                NEW.paper_authority_epoch
          AND stamp.opened_at <= NEW.opened_at
        FOR SHARE OF stamp;

    IF current_epoch IS DISTINCT FROM NEW.paper_authority_epoch
       OR active_stamp_binding IS DISTINCT FROM TRUE
    THEN
        RAISE EXCEPTION
            'public cutover requires the exact current active release stamp';
    END IF;

    canonical_payload := format(
        '{"candidate_acceptance_digest":"%s",'
        '"candidate_admission_digest":"%s",'
        '"candidate_admission_id":"%s",'
        '"cutover_id":"%s",'
        '"evidence_set_digest":"%s",'
        '"evidence_set_id":"%s",'
        '"final_order_snapshot_digest":"%s",'
        '"opened_at":"%s",'
        '"paper_authority_epoch":%s,'
        '"release_digest":"%s",'
        '"route":"%s",'
        '"stamp_id":"%s",'
        '"workspace_id":"%s"}',
        NEW.candidate_acceptance_digest,
        NEW.candidate_admission_digest,
        NEW.candidate_admission_id,
        NEW.cutover_id,
        NEW.evidence_set_digest,
        NEW.evidence_set_id,
        NEW.final_order_snapshot_digest,
        to_char(
            NEW.opened_at AT TIME ZONE 'UTC',
            'YYYY-MM-DD"T"HH24:MI:SS.US"Z"'
        ),
        NEW.paper_authority_epoch,
        NEW.release_digest,
        NEW.route,
        NEW.stamp_id,
        NEW.workspace_id
    );
    expected_cutover_digest := encode(
        sha256(convert_to(canonical_payload, 'UTF8')),
        'hex'
    );
    IF NEW.cutover_digest IS DISTINCT FROM expected_cutover_digest THEN
        RAISE EXCEPTION
            'public cutover digest does not match its canonical binding';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_agent_v02_cutovers_insert_guard
    ON quant_system.agent_v02_public_cutovers;
CREATE TRIGGER trg_agent_v02_cutovers_insert_guard
BEFORE INSERT ON quant_system.agent_v02_public_cutovers
FOR EACH ROW
EXECUTE FUNCTION
    quant_system.guard_agent_v02_public_cutover_insert();
ALTER TABLE quant_system.agent_v02_public_cutovers
    ENABLE ALWAYS TRIGGER trg_agent_v02_cutovers_insert_guard;

CREATE OR REPLACE FUNCTION
quant_system.insert_agent_v02_release_stamp(
    requested_stamp_id TEXT,
    requested_workspace_id TEXT,
    requested_route TEXT,
    requested_platform_runtime_digest TEXT,
    requested_hqa_runtime_digest TEXT,
    requested_hermes_runtime_digest TEXT,
    requested_database_schema_fingerprint TEXT,
    requested_evidence_digest TEXT,
    requested_release_digest TEXT,
    requested_opened_at TIMESTAMPTZ,
    requested_candidate_admission_id TEXT,
    requested_candidate_admission_digest TEXT,
    requested_candidate_acceptance_digest TEXT,
    requested_evidence_set_id TEXT,
    requested_evidence_set_digest TEXT,
    requested_final_order_snapshot_digest TEXT,
    requested_paper_authority_epoch BIGINT
)
RETURNS VOID
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    INSERT INTO quant_system.agent_v02_release_stamps (
        stamp_id,
        owner_user_id,
        workspace_id,
        route,
        platform_runtime_digest,
        hqa_runtime_digest,
        hermes_runtime_digest,
        database_schema_fingerprint,
        evidence_digest,
        release_digest,
        status,
        opened_at,
        candidate_admission_id,
        candidate_admission_digest,
        candidate_acceptance_digest,
        evidence_set_id,
        evidence_set_digest,
        final_order_snapshot_digest,
        paper_authority_epoch
    )
    VALUES (
        requested_stamp_id,
        '00000000-0000-0000-0000-000000000001'::uuid,
        requested_workspace_id,
        requested_route,
        requested_platform_runtime_digest,
        requested_hqa_runtime_digest,
        requested_hermes_runtime_digest,
        requested_database_schema_fingerprint,
        requested_evidence_digest,
        requested_release_digest,
        'active',
        requested_opened_at,
        requested_candidate_admission_id,
        requested_candidate_admission_digest,
        requested_candidate_acceptance_digest,
        requested_evidence_set_id,
        requested_evidence_set_digest,
        requested_final_order_snapshot_digest,
        requested_paper_authority_epoch
    )
$$;
REVOKE ALL ON FUNCTION
    quant_system.insert_agent_v02_release_stamp(
        TEXT,
        TEXT,
        TEXT,
        TEXT,
        TEXT,
        TEXT,
        TEXT,
        TEXT,
        TEXT,
        TIMESTAMPTZ,
        TEXT,
        TEXT,
        TEXT,
        TEXT,
        TEXT,
        TEXT,
        BIGINT
    )
    FROM PUBLIC;

CREATE OR REPLACE FUNCTION
quant_system.insert_agent_v02_public_cutover(
    requested_cutover_id TEXT,
    requested_stamp_id TEXT,
    requested_workspace_id TEXT,
    requested_route TEXT,
    requested_release_digest TEXT,
    requested_cutover_digest TEXT,
    requested_opened_at TIMESTAMPTZ,
    requested_candidate_admission_id TEXT,
    requested_candidate_admission_digest TEXT,
    requested_candidate_acceptance_digest TEXT,
    requested_evidence_set_id TEXT,
    requested_evidence_set_digest TEXT,
    requested_final_order_snapshot_digest TEXT,
    requested_paper_authority_epoch BIGINT
)
RETURNS VOID
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
    INSERT INTO quant_system.agent_v02_public_cutovers (
        cutover_id,
        stamp_id,
        owner_user_id,
        workspace_id,
        route,
        release_digest,
        cutover_digest,
        status,
        opened_at,
        candidate_admission_id,
        candidate_admission_digest,
        candidate_acceptance_digest,
        evidence_set_id,
        evidence_set_digest,
        final_order_snapshot_digest,
        paper_authority_epoch
    )
    VALUES (
        requested_cutover_id,
        requested_stamp_id,
        '00000000-0000-0000-0000-000000000001'::uuid,
        requested_workspace_id,
        requested_route,
        requested_release_digest,
        requested_cutover_digest,
        'open',
        requested_opened_at,
        requested_candidate_admission_id,
        requested_candidate_admission_digest,
        requested_candidate_acceptance_digest,
        requested_evidence_set_id,
        requested_evidence_set_digest,
        requested_final_order_snapshot_digest,
        requested_paper_authority_epoch
    )
$$;
REVOKE ALL ON FUNCTION
    quant_system.insert_agent_v02_public_cutover(
        TEXT,
        TEXT,
        TEXT,
        TEXT,
        TEXT,
        TEXT,
        TIMESTAMPTZ,
        TEXT,
        TEXT,
        TEXT,
        TEXT,
        TEXT,
        TEXT,
        BIGINT
    )
    FROM PUBLIC;

CREATE OR REPLACE FUNCTION
quant_system.guard_agent_v02_release_binding_transition()
RETURNS TRIGGER
LANGUAGE plpgsql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog
AS $$
BEGIN
    IF NEW.candidate_admission_id
            IS DISTINCT FROM OLD.candidate_admission_id
       OR NEW.candidate_admission_digest
            IS DISTINCT FROM OLD.candidate_admission_digest
       OR NEW.candidate_acceptance_digest
            IS DISTINCT FROM OLD.candidate_acceptance_digest
       OR NEW.evidence_set_id IS DISTINCT FROM OLD.evidence_set_id
       OR NEW.evidence_set_digest
            IS DISTINCT FROM OLD.evidence_set_digest
       OR NEW.final_order_snapshot_digest
            IS DISTINCT FROM OLD.final_order_snapshot_digest
       OR NEW.paper_authority_epoch
            IS DISTINCT FROM OLD.paper_authority_epoch
    THEN
        RAISE EXCEPTION
            'Agent v0.2 release candidate binding is immutable';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_agent_v02_release_stamps_binding_update
    ON quant_system.agent_v02_release_stamps;
CREATE TRIGGER trg_agent_v02_release_stamps_binding_update
BEFORE UPDATE ON quant_system.agent_v02_release_stamps
FOR EACH ROW
EXECUTE FUNCTION
    quant_system.guard_agent_v02_release_binding_transition();
ALTER TABLE quant_system.agent_v02_release_stamps
    ENABLE ALWAYS TRIGGER
        trg_agent_v02_release_stamps_binding_update;

DROP TRIGGER IF EXISTS trg_agent_v02_cutovers_binding_update
    ON quant_system.agent_v02_public_cutovers;
CREATE TRIGGER trg_agent_v02_cutovers_binding_update
BEFORE UPDATE ON quant_system.agent_v02_public_cutovers
FOR EACH ROW
EXECUTE FUNCTION
    quant_system.guard_agent_v02_release_binding_transition();
ALTER TABLE quant_system.agent_v02_public_cutovers
    ENABLE ALWAYS TRIGGER trg_agent_v02_cutovers_binding_update;

DO $$
DECLARE
    table_name TEXT;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_runtime')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_readonly')
       AND EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'quant_migrator')
    THEN
        ALTER TABLE
            quant_system.agent_v02_release_hardening_meta
            OWNER TO quant_migrator;
        ALTER TABLE
            quant_system.agent_v02_paper_authority_epochs
            OWNER TO quant_migrator;
        ALTER TABLE
            quant_system.agent_v02_paper_authority_owner_epochs
            OWNER TO quant_migrator;
        ALTER SEQUENCE
            quant_system.agent_v02_paper_authority_epoch_seq
            OWNER TO quant_migrator;

        ALTER TABLE
            quant_system.agent_v02_paper_authority_epochs
            ENABLE ROW LEVEL SECURITY;
        ALTER TABLE
            quant_system.agent_v02_paper_authority_epochs
            FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS v4r_root_scope
            ON quant_system.agent_v02_paper_authority_epochs;
        CREATE POLICY v4r_root_scope
            ON quant_system.agent_v02_paper_authority_epochs
            FOR ALL TO quant_runtime, quant_readonly
            USING (
                owner_user_id =
                    '00000000-0000-0000-0000-000000000001'::uuid
            )
            WITH CHECK (
                owner_user_id =
                    '00000000-0000-0000-0000-000000000001'::uuid
            );
        DROP POLICY IF EXISTS v4r_migrator_all
            ON quant_system.agent_v02_paper_authority_epochs;
        CREATE POLICY v4r_migrator_all
            ON quant_system.agent_v02_paper_authority_epochs
            FOR ALL TO quant_migrator
            USING (true)
            WITH CHECK (true);

        ALTER TABLE
            quant_system.agent_v02_paper_authority_owner_epochs
            ENABLE ROW LEVEL SECURITY;
        ALTER TABLE
            quant_system.agent_v02_paper_authority_owner_epochs
            FORCE ROW LEVEL SECURITY;
        DROP POLICY IF EXISTS v4r_root_scope
            ON quant_system.agent_v02_paper_authority_owner_epochs;
        CREATE POLICY v4r_root_scope
            ON quant_system.agent_v02_paper_authority_owner_epochs
            FOR ALL TO quant_runtime, quant_readonly
            USING (
                owner_user_id =
                    '00000000-0000-0000-0000-000000000001'::uuid
            )
            WITH CHECK (
                owner_user_id =
                    '00000000-0000-0000-0000-000000000001'::uuid
            );
        DROP POLICY IF EXISTS v4r_migrator_all
            ON quant_system.agent_v02_paper_authority_owner_epochs;
        CREATE POLICY v4r_migrator_all
            ON quant_system.agent_v02_paper_authority_owner_epochs
            FOR ALL TO quant_migrator
            USING (true)
            WITH CHECK (true);

        GRANT USAGE ON SCHEMA quant_system
            TO quant_runtime, quant_readonly, quant_migrator;
        REVOKE CREATE ON SCHEMA quant_system
            FROM quant_runtime, quant_readonly;

        GRANT SELECT
            ON quant_system.agent_v02_release_hardening_meta,
               quant_system.agent_v02_paper_authority_owner_epochs,
               quant_system.agent_v02_paper_authority_epochs
            TO quant_runtime, quant_readonly;
        REVOKE INSERT, UPDATE, DELETE, TRUNCATE
            ON quant_system.agent_v02_release_hardening_meta,
               quant_system.agent_v02_paper_authority_owner_epochs,
               quant_system.agent_v02_paper_authority_epochs
            FROM quant_runtime, quant_readonly;
        REVOKE INSERT
            ON quant_system.agent_v02_release_stamps,
               quant_system.agent_v02_public_cutovers
            FROM quant_runtime, quant_readonly;
        REVOKE ALL
            ON SEQUENCE
                quant_system.agent_v02_paper_authority_epoch_seq
            FROM quant_runtime, quant_readonly, PUBLIC;

        GRANT ALL
            ON quant_system.agent_v02_release_hardening_meta,
               quant_system.agent_v02_paper_authority_owner_epochs,
               quant_system.agent_v02_paper_authority_epochs
            TO quant_migrator;
        GRANT ALL
            ON SEQUENCE
                quant_system.agent_v02_paper_authority_epoch_seq
            TO quant_migrator;

        FOREACH table_name IN ARRAY ARRAY[
            'agent_v02_release_hardening_meta',
            'agent_v02_paper_authority_owner_epochs',
            'agent_v02_paper_authority_epochs'
        ]
        LOOP
            EXECUTE format(
                'REVOKE ALL ON quant_system.%I FROM PUBLIC',
                table_name
            );
        END LOOP;

        ALTER FUNCTION
            quant_system.ensure_agent_v02_paper_authority_epoch(
                UUID,
                TEXT
            )
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.current_agent_v02_paper_authority_epoch(
                UUID,
                TEXT
            )
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.bump_agent_v02_paper_authority_owner(UUID)
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.bump_agent_v02_paper_authority_epoch()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.bind_agent_v02_candidate_paper_epoch()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.bind_agent_v02_candidate_evidence_paper_epoch()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.guard_agent_v02_candidate_acceptance_paper_epoch()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.guard_agent_v02_release_stamp_insert()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.guard_agent_v02_public_cutover_insert()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.guard_agent_v02_release_binding_transition()
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.insert_agent_v02_release_stamp(
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TIMESTAMPTZ,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                BIGINT
            )
            OWNER TO quant_migrator;
        ALTER FUNCTION
            quant_system.insert_agent_v02_public_cutover(
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TIMESTAMPTZ,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                BIGINT
            )
            OWNER TO quant_migrator;

        REVOKE EXECUTE ON FUNCTION
            quant_system.ensure_agent_v02_paper_authority_epoch(
                UUID,
                TEXT
            )
            FROM PUBLIC, quant_runtime, quant_readonly;
        REVOKE EXECUTE ON FUNCTION
            quant_system.bump_agent_v02_paper_authority_owner(UUID)
            FROM PUBLIC, quant_runtime, quant_readonly;
        REVOKE EXECUTE ON FUNCTION
            quant_system.bump_agent_v02_paper_authority_epoch()
            FROM PUBLIC, quant_runtime, quant_readonly;
        REVOKE EXECUTE ON FUNCTION
            quant_system.bind_agent_v02_candidate_paper_epoch()
            FROM PUBLIC, quant_runtime, quant_readonly;
        REVOKE EXECUTE ON FUNCTION
            quant_system.bind_agent_v02_candidate_evidence_paper_epoch()
            FROM PUBLIC, quant_runtime, quant_readonly;
        REVOKE EXECUTE ON FUNCTION
            quant_system.guard_agent_v02_candidate_acceptance_paper_epoch()
            FROM PUBLIC, quant_runtime, quant_readonly;
        REVOKE EXECUTE ON FUNCTION
            quant_system.guard_agent_v02_release_stamp_insert()
            FROM PUBLIC, quant_runtime, quant_readonly;
        REVOKE EXECUTE ON FUNCTION
            quant_system.guard_agent_v02_public_cutover_insert()
            FROM PUBLIC, quant_runtime, quant_readonly;
        REVOKE EXECUTE ON FUNCTION
            quant_system.guard_agent_v02_release_binding_transition()
            FROM PUBLIC, quant_runtime, quant_readonly;
        REVOKE EXECUTE ON FUNCTION
            quant_system.insert_agent_v02_release_stamp(
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TIMESTAMPTZ,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                BIGINT
            )
            FROM PUBLIC, quant_readonly;
        GRANT EXECUTE ON FUNCTION
            quant_system.insert_agent_v02_release_stamp(
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TIMESTAMPTZ,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                BIGINT
            )
            TO quant_runtime, quant_migrator;
        REVOKE EXECUTE ON FUNCTION
            quant_system.insert_agent_v02_public_cutover(
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TIMESTAMPTZ,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                BIGINT
            )
            FROM PUBLIC, quant_readonly;
        GRANT EXECUTE ON FUNCTION
            quant_system.insert_agent_v02_public_cutover(
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TIMESTAMPTZ,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                TEXT,
                BIGINT
            )
            TO quant_runtime, quant_migrator;

        REVOKE EXECUTE ON FUNCTION
            quant_system.current_agent_v02_paper_authority_epoch(
                UUID,
                TEXT
            )
            FROM PUBLIC, quant_runtime, quant_readonly;
        GRANT EXECUTE ON FUNCTION
            quant_system.current_agent_v02_paper_authority_epoch(
                UUID,
                TEXT
            )
            TO quant_migrator;
    END IF;
END $$;

COMMIT;
