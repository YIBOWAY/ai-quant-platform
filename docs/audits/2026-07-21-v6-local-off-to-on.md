# V6 local OFF→ON evidence — 2026-07-21

## Authorization

User authorized full local exercise of previously-OFF items: real Hermes adapter wiring,
provider smoke, supervised worker path, public composer / browser mutation gates.
Trading remains fail-closed (`kill_switch=true`, `dry_run`, `paper`, `live_trading_enabled=false`).
No commit requested.

## Code

| Area | Path |
|---|---|
| HTTP adapter | `src/quant_system/hermes/dispatch_adapter.py` (`HttpHermesDispatchAdapter`, factory, resolvers) |
| CLI | `connector_cli.py` `--mode` / `--fixed-input` / `--worker-id`; auto-build adapter |
| Readiness | `composer_readiness.py` settings-gated via `LocalMutationSettings` |
| Settings | `QS_HERMES_GATEWAY_DISPATCH_TIMEOUT_SECONDS`, `ALLOW_EPHEMERAL_RUNS`, `QS_LOCAL_MUTATION_*` |
| Schema | `api/schemas/hermes.py` `chat_write_ready: bool` (was `Literal[False]`) |
| Workspace public | `agent_workspace.py` / `ActionReceipt.mutation_enabled` no longer hard-false |
| Worker scripts | HQA + `~/.hermes` allowlist for new flags |
| FE | `featureFlags` chat unlock; `.env.local` `QS_HERMES_CHAT_ENABLED=true` |

## Tests

Focused suite green (adapter unit + connector CLI/dispatch + composer readiness +
gateway/health/local_session with `.env` isolation).

## Live smoke

1. `ensure_bound_command` created queued command `d4ae3de5-5a88-4d03-aad4-8732dba5d0b9`
   (saga `hqs_31dd7e08bca34f818324719d`).
2. `quant-system hermes connector-worker --once --mode supervised_dispatch --fixed-input "Reply with exactly: pong" --worker-id smoke-worker-v6-1`
   → JSON: `claimed_count=1`, `delivered_count=1`, `provider_call_count=1`,
   `last_dispatch_outcome=delivered`, `mode=supervised_dispatch`.
3. Empty supervised loop `--max-cycles 2` → zero claims/provider.
4. Restarted API `127.0.0.1:8765` + FE `127.0.0.1:3001`.
5. `/api/health` hermes_command_ledger: `mutation_enabled=composer_write_ready=chat_write_ready=true`;
   safety kill_switch true.
6. `/api/hermes/gateway`: `chat_write_ready=true`, `blockers=[]`, `connected=true`,
   `run_submission=true`.

## Still open

- ComposerDock network submit (still `preventDefault` only).
- Launchd/default always-on supervised daemon.
- Commit/push (await user).
