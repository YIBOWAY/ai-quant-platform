# Agent v0.2 V4-R runtime-security remediation

Date: 2026-07-23

Status: **source accepted in an isolated PostgreSQL test environment; NOT live-applied**.
This record does not authorize a public composer, a worker, a provider call, or
any trading path.

## Decision

V4-R closes three fail-open boundaries found during the V6/V7 adversarial
review:

1. schema presence, constrained runtime identity, operational dispatch, local
   composer admission, and public V8 admission are separate facts;
2. managed-session provider and retention policy are server-owned and immutable;
3. the platform runtime no longer qualifies as a writer while connected as the
   historical `quant` superuser.

The prior V6 evidence remains historical. In particular, local flags plus
schema presence no longer make `chat_write_ready=true`. Until a durable worker
capability/liveness proof exists, `dark_dispatch_ready`, local composer readiness,
and public chat readiness all remain false. The health/blocker surface reports
`durable_dispatch_operational_unavailable` honestly.

## Delivered contracts

### Readiness layers

`composer_readiness.authority_readiness()` now distinguishes:

- `schema_ready` and `research_binding_schema_ready`;
- `runtime_security_ready` and `write_authority_ready`;
- `dark_dispatch_schema_ready` from `dark_dispatch_ready`;
- `local_chat_write_ready` from hard-false `public_chat_write_ready` and
  `chat_write_ready`.

Local mutation flags cannot clear upstream durable-Hermes blockers, independent
security review, user cutover approval, runtime-role failure, or missing durable
dispatch. `/api/health` projects the same layers rather than calling ledger-only
readiness `schema_ready`.

### Server-owned managed-session policy

The only admitted policy is:

- provider-policy digest
  `be9265ec683224ba28643b01938dba87d2642944f3a0516ccb9ff0126f872e31`;
- payload TTL exactly `7` days.

The browser may carry these fields for the closed action schema, but it cannot
choose them: create/fork rejects every other digest or TTL before a command
write. The session registry stores the canonical values. Composite submit reads
them back from the registry before Intent Payload Store `put`, and verifies the
store receipt matches before creating a conversation command. PostgreSQL binds
managed sessions to TTL `7`, external sessions to `NULL`, and rejects TTL,
provider-policy, identity, lineage, or row deletion after registration.

### PostgreSQL role and RLS boundary

`009_agent_v0_2_v4r_security.sql` creates three cluster-wide **NOLOGIN** group
roles:

- `quant_migrator` — schema/object owner and migration role;
- `quant_runtime` — application DML role;
- `quant_readonly` — read projection role.

All three are `NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE NOREPLICATION`.
A bootstrap-superuser replay repairs drifted group attributes, including
`SUPERUSER`, `BYPASSRLS`, or `LOGIN`. A non-superuser migrator replay verifies
the same signature and aborts if privileged repair is required.

The migration intentionally does **not** alter, drop, or reduce the historical
operator-owned `quant` login. It transfers `quant_system` object ownership to
the NOLOGIN migrator group and applies `ENABLE/FORCE ROW LEVEL SECURITY` plus
exact root-owner policies to:

- `app_users`;
- `hermes_commands`;
- `hermes_command_events`;
- `hermes_outbox`;
- `hermes_run_links`;
- `hermes_command_workflow_bindings`;
- `hermes_workspace_sessions`.

The runtime probe accepts only a real LOGIN principal that is non-superuser,
non-bypass, non-DDL, a `quant_runtime` member, not a `quant_migrator` member,
and executes with `current_user = session_user`. It also checks schema
privileges, exact table privileges, FORCE RLS, exact policy roles/bodies, the
canonical TTL constraint, and the exact immutable-session trigger body. Merely
running a process as `quant` therefore keeps every write-readiness gate closed.

## Isolated evidence

No command in this slice connected to the live `quantplatform` database. Tests
used a disposable PostgreSQL 16 Docker container and a database named
`quantplatform_v4r_test_tmp` on loopback port `52225`.

Covered evidence includes:

- migration replay and schema readiness;
- correction of drifted group-role attributes;
- a non-superuser migrator replaying the complete migration set twice;
- runtime and readonly root scoping, including denial of another owner's insert;
- denial of runtime DDL/delete and readonly mutation;
- RLS enable/force drift, policy-body drift, required-privilege drift, TTL
  constraint drift, and trigger-body drift all making readiness false;
- canonical TTL `7`, provider policy, immutable session rows, composite
  store-before-command binding, and fail-closed BFF behavior.

## Future live provisioning procedure (not executed)

These steps require a separate live authorization, backup, fingerprint, and
rollback decision. Passwords must come from the operator's secret store and
must never be committed.

1. Back up the target database and capture the pre-apply schema fingerprint.
2. Apply the single reviewed migration with the existing explicit gate:

   ```bash
   quant-system migrate --apply --allow scripts/sql/009_agent_v0_2_v4r_security.sql
   ```

   Initial bootstrap must run under the existing authorized database
   administrator because cluster-role creation/repair is not a runtime power.
3. Create a dedicated operator-owned LOGIN and grant only the runtime group:

   ```sql
   CREATE ROLE quant_app_runtime
       LOGIN INHERIT NOSUPERUSER NOCREATEDB NOCREATEROLE
       NOREPLICATION NOBYPASSRLS
       PASSWORD '<secret-from-operator-store>';
   GRANT quant_runtime TO quant_app_runtime;
   ```

   Do not grant `quant_migrator`, do not reuse `quant`, and do not configure a
   connection-level `SET ROLE` for the runtime process.
4. Point only the application runtime connection at `quant_app_runtime`, restart
   the backend, and verify the effective principal:

   ```sql
   SELECT session_user, current_user,
          r.rolsuper, r.rolbypassrls, r.rolcreatedb,
          r.rolcreaterole, r.rolreplication,
          pg_has_role(session_user, 'quant_runtime', 'MEMBER') AS runtime_member,
          pg_has_role(session_user, 'quant_migrator', 'MEMBER') AS migrator_member
   FROM pg_roles AS r
   WHERE r.rolname = session_user;
   ```

   Required evidence is `session_user=current_user=quant_app_runtime`, every
   privileged attribute false, `runtime_member=true`, and
   `migrator_member=false`.
5. Verify `/api/health` reports `runtime_security_ready=true` and
   `write_authority_ready=true`, while `dark_dispatch_ready`,
   `local_chat_write_ready`, `public_chat_write_ready`, and `chat_write_ready`
   remain false.

A separate operator-owned migration LOGIN may be granted `quant_migrator` and
use explicit `SET ROLE quant_migrator` only during authorized migration windows.
It must never be the application runtime credential.

## Residuals

- This slice does not provide a durable worker capability lease/heartbeat;
  dispatch and composer admission remain OFF.
- It does not repair the permanently queued `managed_session_create` claim
  contract or implement expired payload/session deletion.
- It does not apply migration 009, provision a live LOGIN, restart services, or
  change the live `quant` superuser.
- Runtime DML for the wider monolithic platform remains broader than the seven
  RLS-protected Hermes authority tables. Splitting trading/research services into
  narrower database roles is a later architecture slice, not implied by V4-R.
- Public V8 security review and user cutover approval remain independent gates.
