-- L2a-Send: allow claim of store-backed conversation_turn commands without a
-- research workflow binding row. Research commands remain binding-gated.
-- Idempotent: CREATE OR REPLACE only.

CREATE OR REPLACE FUNCTION quant_system.enforce_hermes_claim_binding_eligibility()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.state = 'queued' AND NEW.state = 'leased' THEN
        -- Research path: exact immutable workflow binding still required.
        IF EXISTS (
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
            RETURN NEW;
        END IF;

        -- L2a chat path: conversation_turn with store-mapped payload_ref only.
        -- Binding table is intentionally unused; Intent Payload Store is body
        -- authority. Provider policy digest must still be present.
        IF NEW.kind = 'conversation_turn'
           AND NEW.payload_ref ~ '^platform-payload://sha256/[0-9a-f]{64}$'
           AND NEW.provider_policy_digest IS NOT NULL
           AND NEW.provider_policy_digest ~ '^[0-9a-f]{64}$'
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
        THEN
            RETURN NEW;
        END IF;

        RAISE EXCEPTION 'Hermes claim binding is missing, mismatched, or expired'
            USING ERRCODE = '23514',
                  CONSTRAINT = 'ck_hermes_claim_binding_eligible';
    END IF;
    RETURN NEW;
END;
$$;
