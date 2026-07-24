-- DESTRUCTIVE MANUAL ROLLBACK FOR THROWAWAY/RESTORED DATABASES ONLY.
-- Take and verify a backup before executing this file against any durable DB.

BEGIN;

DROP TABLE IF EXISTS quant_system.hermes_run_links;
DROP TABLE IF EXISTS quant_system.hermes_outbox;
DROP TABLE IF EXISTS quant_system.hermes_command_events;
DROP TABLE IF EXISTS quant_system.hermes_commands;
DROP TABLE IF EXISTS quant_system.hermes_ledger_meta;
DROP FUNCTION IF EXISTS quant_system.reject_hermes_command_event_mutation();
DROP FUNCTION IF EXISTS quant_system.reject_hermes_run_link_mutation();

COMMIT;
