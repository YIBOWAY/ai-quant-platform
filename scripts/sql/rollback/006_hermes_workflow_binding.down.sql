-- DESTRUCTIVE MANUAL ROLLBACK FOR THROWAWAY/RESTORED DATABASES ONLY.
-- Take and verify a backup before executing this file against any durable DB.

BEGIN;

SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:hermes_schema_runtime_gate', 0)
);
SELECT pg_advisory_xact_lock(
    hashtextextended('quant_system:006_hermes_workflow_binding', 0)
);

-- DROP TRIGGER is relation-dependent: IF EXISTS applies to the trigger, not to
-- every possible partial relation state. Resolve each owning relation first so
-- this destructive recovery script remains reentrant after a partial rollback.
DO $rollback$
BEGIN
    IF to_regclass('quant_system.hermes_commands') IS NOT NULL THEN
        EXECUTE 'DROP TRIGGER IF EXISTS trg_hermes_command_intent_immutable '
                'ON quant_system.hermes_commands';
        EXECUTE 'DROP TRIGGER IF EXISTS trg_hermes_command_claim_binding_guard '
                'ON quant_system.hermes_commands';
    END IF;

    IF to_regclass(
        'quant_system.hermes_command_workflow_bindings'
    ) IS NOT NULL THEN
        EXECUTE 'DROP TRIGGER IF EXISTS trg_hermes_workflow_binding_validate '
                'ON quant_system.hermes_command_workflow_bindings';
        EXECUTE 'DROP TRIGGER IF EXISTS trg_hermes_workflow_binding_append_only '
                'ON quant_system.hermes_command_workflow_bindings';
        EXECUTE 'DROP TRIGGER IF EXISTS '
                'trg_hermes_workflow_binding_append_only_truncate '
                'ON quant_system.hermes_command_workflow_bindings';
    END IF;
END
$rollback$;

DO $rollback$
BEGIN
    IF to_regclass(
        'quant_system.hermes_command_workflow_bindings'
    ) IS NOT NULL THEN
        EXECUTE 'DROP TABLE quant_system.hermes_command_workflow_bindings';
    END IF;
    IF to_regclass('quant_system.hermes_workflow_binding_meta') IS NOT NULL THEN
        EXECUTE 'DROP TABLE quant_system.hermes_workflow_binding_meta';
    END IF;
    IF to_regclass('quant_system.hermes_command_events') IS NOT NULL THEN
        EXECUTE 'ALTER TABLE quant_system.hermes_command_events '
                'DROP CONSTRAINT IF EXISTS '
                'uq_hermes_command_events_binding_anchor';
    END IF;

    IF EXISTS (
        SELECT 1
        FROM pg_namespace
        WHERE nspname = 'quant_system'
    ) THEN
        EXECUTE 'DROP FUNCTION IF EXISTS '
                'quant_system.reject_hermes_workflow_binding_mutation()';
        EXECUTE 'DROP FUNCTION IF EXISTS '
                'quant_system.protect_hermes_command_intent_identity()';
        EXECUTE 'DROP FUNCTION IF EXISTS '
                'quant_system.validate_hermes_workflow_binding()';
        EXECUTE 'DROP FUNCTION IF EXISTS '
                'quant_system.enforce_hermes_claim_binding_eligibility()';
    END IF;
END
$rollback$;

COMMIT;
