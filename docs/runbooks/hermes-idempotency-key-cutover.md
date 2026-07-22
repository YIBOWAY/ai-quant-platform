# Hermes command idempotency-key cutover

The durable connector now derives the upstream key from the globally unique,
stable ledger command identity:

```text
platform-command:<command_uuid>
```

This replaces the old browser `client_request_id` key, whose uniqueness was
only scoped to `(owner_user_id, platform_session_id)` and could collide across
managed sessions.

## Mandatory preflight

Before deploying the new key derivation over a database used by the old
connector, stop and run this read-only check:

```sql
SELECT count(*) AS legacy_outcome_unknown
FROM quant_system.hermes_commands
WHERE state = 'outcome_unknown';
```

The result **must be zero**. A nonzero row may represent an old-key Run that
Hermes accepted before its acknowledgement or PostgreSQL link was lost.
Recovering that row with the new key could create a second Run. In that case,
fail closed: do not start supervised dispatch, do not replay the row, and do
not invent a compatibility result. Investigate and drain the exact legacy Run
identity under a separately reviewed procedure.

On 2026-07-23 the authorized local read-only preflight returned
`outcome_unknown=0` (`delivered=7`, `queued=3`). This is point-in-time evidence,
not a permanent invariant; repeat the query at the actual cutover.

## Registry-v2 companion migration

Managed-session create/fork is a control-plane registry action, not executable
Hermes work. Source migration `010_hermes_session_action_idempotency.sql`:

- stores immutable `(owner, workspace, creation_client_action_id,
  creation_action_digest)` identity on managed sessions;
- makes exact retries return the same session and rejects same-ID/different-body;
- retires only legacy queued `managed_session_create|managed_session_fork`
  control rows with an append-only `legacy_control_retired` event; and
- consumes only the matching old outbox records.

The migration is **not live-applied**. At cutover, stop legacy writers, repeat
the `outcome_unknown=0` check, back up/fingerprint the database, then explicitly
allowlist migrations 009 and 010 together. Do not manually delete the three
point-in-time queued rows and do not reinterpret them as provider work.
