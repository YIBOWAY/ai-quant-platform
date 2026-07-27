-- Keep the private Agent v0.2 release-candidate admission short-lived without
-- forcing the honest operator flow into the original 30-minute race.
--
-- This is an additive, replay-safe constraint change.  It does not open the
-- public composer, authorize release, alter trading safety, renew an existing
-- admission, or weaken any identity/evidence binding.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended(
        'quant_system:027_agent_v02_candidate_ttl_window',
        0
    )
);

DO $$
DECLARE
    installed_version INTEGER;
BEGIN
    IF to_regclass(
        'quant_system.agent_v02_candidate_admissions'
    ) IS NULL
       OR to_regclass(
           'quant_system.agent_v02_candidate_admission_meta'
       ) IS NULL
    THEN
        RAISE EXCEPTION
            'candidate operator window requires migration 016';
    END IF;

    SELECT schema_version
    INTO installed_version
    FROM quant_system.agent_v02_candidate_admission_meta
    WHERE singleton IS TRUE;
    IF installed_version IS DISTINCT FROM 1 THEN
        RAISE EXCEPTION
            'candidate operator window requires candidate admission schema version 1';
    END IF;
END $$;

-- Keep an independent, migrator-owned generation marker.  The runtime uses
-- this marker together with the constraint definition so a current schema
-- drifted back to the legacy window cannot masquerade as a valid old schema.
ALTER TABLE quant_system.agent_v02_candidate_admission_meta
    ADD COLUMN IF NOT EXISTS ttl_ceiling_seconds INTEGER;

ALTER TABLE quant_system.agent_v02_candidate_admission_meta
    DROP CONSTRAINT IF EXISTS ck_agent_v02_candidate_ttl_ceiling;

UPDATE quant_system.agent_v02_candidate_admission_meta
SET
    ttl_ceiling_seconds = 7200,
    updated_at = clock_timestamp()
WHERE singleton IS TRUE
  AND ttl_ceiling_seconds IS DISTINCT FROM 7200;

ALTER TABLE quant_system.agent_v02_candidate_admission_meta
    ALTER COLUMN ttl_ceiling_seconds SET DEFAULT 7200,
    ALTER COLUMN ttl_ceiling_seconds SET NOT NULL;

ALTER TABLE quant_system.agent_v02_candidate_admission_meta
    ADD CONSTRAINT ck_agent_v02_candidate_ttl_ceiling
    CHECK (ttl_ceiling_seconds = 7200);

ALTER TABLE quant_system.agent_v02_candidate_admissions
    DROP CONSTRAINT IF EXISTS ck_agent_v02_candidate_ttl;

ALTER TABLE quant_system.agent_v02_candidate_admissions
    ADD CONSTRAINT ck_agent_v02_candidate_ttl
    CHECK (
        expires_at > opened_at
        AND expires_at <= opened_at + interval '2 hours'
    );

COMMIT;
