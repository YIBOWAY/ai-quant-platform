# V5 dark supervised claim/dispatch — acceptance (2026-07-21)

## Verdict

**DARK CODE + CRASH-MATRIX ACCEPT.**  
Public write / composer / real provider smoke remain **OFF**.  
Production CLI default remains **`reconcile_only`**.

## Scope delivered

| Artifact | Change |
|---|---|
| `src/quant_system/hermes/dispatch_adapter.py` | NEW: `HermesDispatchPort`, metadata-only request/result, `FakeHermesDispatchAdapter` (accept / recover-by-`client_request_id` / timeout / transport_error / rejected / unavailable / accept_drop_ack). Default zero provider burn. |
| `src/quant_system/hermes/connector_worker.py` | Modes: `reconcile_only` (default) \| `supervised_dispatch` (requires adapter). Flow: reconcile → claim → gate → `mark_dispatch_started` → adapter **outside TX** → delivered / rejected / `outcome_unknown`. |
| `src/quant_system/hermes/connector_cli.py` | `build_connector_runtime(mode=..., dispatch_adapter=...)`. Supervised without adapter → `ConnectorRuntimeUnavailable`. |
| `src/quant_system/hermes/composer_readiness.py` | `command_dispatch_adapter_unavailable` is schema-gated (binding not ready), not permanent. Adds `dark_dispatch_ready` (schema-only). Public write flags stay false. |
| `tests/test_hermes_connector_dispatch.py` | NEW unit + PG crash matrix. |
| readiness/CLI/worker tests | Updated for extended cycle JSON + blocker semantics. |
| docs | `docs/INDEX.md`, `docs/OVERVIEW.md`, `docs/guides/hermes-sessions.md`. |

## Crash matrix covered (fake / PG)

```text
empty queue                         → zero Hermes, zero provider
happy path claim → deliver          → command.state=delivered + command_delivered event
gate deny after claim               → failed, zero Hermes
timeout / transport                 → outcome_unknown, not reclaimed
accept_drop_ack then recover-by-key → same hermes_run_id, no second Run
claim without dispatch_started      → leased left for lease reconcile (no Hermes)
```

`mark_delivered` binds Hermes IDs on the command row and emits events; it does **not** auto-insert `hermes_run_links` (that remains the separate exact resource-link primitive).

## Verification commands

```bash
cd /Users/sunyibo/programs/ai-quant-platform
export QS_TEST_DATABASE_URL='postgresql://quant:quantpass@127.0.0.1:5432/quantplatform_v4_tmp'
.venv/bin/python -m pytest \
  tests/test_hermes_connector_dispatch.py \
  tests/test_hermes_connector_cli.py \
  tests/test_hermes_connector_worker.py \
  tests/test_composer_readiness.py \
  -q
# Result 2026-07-21: all green (35 tests in this set)
```

## Explicitly NOT authorized / NOT done

- Real Hermes HTTP dispatch adapter wiring into production CLI
- Real provider smoke (requires separate low-cost authorization)
- Default-on supervised daemon / launchd change
- Public composer / browser mutation / `chat_write_ready=true`
- HQA Attempt start/terminal/provider observation full path
- SSE event replay / stop reconciliation (V6+)

## Next slice

**V6** — Workspace snapshot/follow and final Web Chat UI (still dark; public chat OFF).
