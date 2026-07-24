-- DESTRUCTIVE MANUAL ROLLBACK FOR THROWAWAY/RESTORED DATABASES ONLY.
-- Take and verify a backup before executing this file against any durable DB.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:007_hermes_session_registry', 0)
);

DO $rollback$
BEGIN
    IF to_regclass('quant_system.hermes_workspace_sessions') IS NOT NULL THEN
        EXECUTE 'DROP TRIGGER IF EXISTS trg_hermes_workspace_session_immutability '
                'ON quant_system.hermes_workspace_sessions';
    END IF;
END
$rollback$;

DROP FUNCTION IF EXISTS quant_system.reject_hermes_external_session_mutation();

DROP TABLE IF EXISTS quant_system.hermes_workspace_sessions CASCADE;
DROP TABLE IF EXISTS quant_system.hermes_session_registry_meta CASCADE;

COMMIT;
