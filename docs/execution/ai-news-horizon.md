# AI News — Horizon sidecar execution runbook

Research-only dual-source news path. Horizon runs as an isolated Docker
sidecar that writes the inbox contract under `data/horizon_inbox/`. The
platform process **never** calls Horizon LLMs directly and the container
**never** connects to Postgres.

Upstream pin: [Thysrael/Horizon](https://github.com/Thysrael/Horizon)
`1e2fdc7ccb177f33c59aef2082c4093e1e82b22c` (main as of 2026-07-17).

## Prerequisites

- Docker + Docker Compose
- Platform venv with `quant-system` CLI
- Postgres reachable for **host-side** ingest only
- LLM provider key for Horizon (OpenAI / Anthropic / etc.)

## 1. Keys and config (container only)

LLM secrets live **only** in the container env file. Do **not** put them in
`QS_*` settings or expose them via the status API.

```bash
mkdir -p data/horizon_config data/horizon_inbox
cp data/horizon_config/config.example.json data/horizon_config/config.json
# or: cp deploy/horizon/config.example.json data/horizon_config/config.json

cat > data/horizon_config/.env <<'EOF'
OPENAI_API_KEY=sk-...
# Optional alternates depending on config.ai.provider / api_key_env:
# ANTHROPIC_API_KEY=...
# GOOGLE_API_KEY=...
# GITHUB_TOKEN=...   # higher HN/GitHub rate limits
EOF
chmod 600 data/horizon_config/.env
```

Edit `data/horizon_config/config.json`:

- `ai.provider` / `ai.model` / `ai.api_key_env` (env **name**, not the secret)
- `sources.*` enable the feeds you want
- `filtering.ai_score_threshold` (default 6.0)

`data/horizon_config/` is gitignored except examples (see `.gitignore`).

## 2. Start the sidecar

```bash
docker compose -f docker-compose.horizon.yml up -d --build
docker compose -f docker-compose.horizon.yml logs -f horizon
```

Loop behaviour (`deploy/horizon/entrypoint.sh`):

1. `uv run horizon --hours 24` (failures logged, loop continues)
2. `python /opt/bin/export_run.py --horizon-data /opt/horizon/data --inbox /inbox`
3. sleep `HORIZON_RUN_INTERVAL_SECONDS` (default **21600** = 6h)

Mounts:

| Host | Container | Mode |
|------|-----------|------|
| `./data/horizon_inbox` | `/inbox` | rw — inbox contract |
| `./data/horizon_config` | `/config` | ro — `config.json` + `.env` via env_file |
| volume `horizon-data` | `/opt/horizon/data` | rw — upstream summaries / mcp-runs |

The container does **not** receive database URLs and must not mount Postgres
sockets.

### Inbox contract (export)

Each successful export writes:

```
data/horizon_inbox/runs/<YYYYMMDDTHHMMSSZ-xxxx>/
  meta.json          # run_id, generated_at, item_count, status
  items.json         # list of inbox items
  summary-zh.md      # optional
  summary-en.md      # optional
  READY              # written LAST; absent on any export exception
```

Empty-item policy: export still emits `items.json=[]`, `item_count=0`, and
`READY` so ops can see the attempt. Platform ingest treats empty runs as not
fresh and skips promoting them.

Mapping (ContentItem → inbox):

| Inbox field | Upstream |
|-------------|----------|
| `id` | `id` |
| `title` | `title` |
| `title_en` | `title` (or metadata title_en) |
| `url` | `url` |
| `source` | `source_type` |
| `published_at` | `published_at` ISO |
| `summary` | `ai_summary` or truncated `content` |
| `category` | first `ai_tags[]` or metadata category or `"industry"` |
| `score` | `ai_score` |

Stage preference when discovering MCP run-store artifacts:
`enriched_items.json` > `filtered_items.json` > `scored_items.json`.

**CLI vs MCP artifacts:** `uv run horizon` (this sidecar’s default) persists
daily markdown under `data/summaries/horizon-{date}-{lang}.md` and does **not**
write the MCP run-store item JSON. Export still succeeds: it copies any
summaries it finds and emits `items.json` (possibly empty) + `READY`. Structured
item lists appear when upstream also wrote `data/mcp-runs/<run_id>/*_items.json`
(e.g. via `horizon-mcp`) or when loose stage files are present under the data
dir. Empty `item_count=0` with READY is intentional so ops can see the attempt;
platform ingest skips empty runs as not fresh.

## 3. Apply migration 009 (host)

Once per environment:

```bash
quant-system migrate --apply --allow 009_ai_news_provider_runs.sql --yes
```

SQL: `scripts/sql/009_ai_news_provider_runs.sql`
(`quant_system.ai_news_provider_runs`).

## 4. First ingest (host)

After the sidecar has produced at least one `READY` run:

```bash
ls data/horizon_inbox/runs/*/READY
quant-system news horizon-ingest --once
# optional:
# quant-system news horizon-ingest --inbox data/horizon_inbox --run-id 20260723T120000Z-ab12
```

Default inbox dir: `data/horizon_inbox` (`QS_HORIZON_INBOX_DIR`).

## 5. Cron: ingest every 10 minutes

Host crontab (or launchd) — **ingest only**, never run Horizon LLM work on the host:

```cron
*/10 * * * * cd /path/to/ai-quant-platform && .venv/bin/quant-system news horizon-ingest --once >> logs/horizon-ingest.log 2>&1
```

Platform settings of interest:

| Env | Default | Role |
|-----|---------|------|
| `QS_HORIZON_ENABLED` | `true` | Serve Horizon-backed news |
| `QS_HORIZON_INBOX_DIR` | `data/horizon_inbox` | Inbox root |
| `QS_HORIZON_MAX_AGE_SECONDS` | (settings default) | Freshness window |
| `QS_HORIZON_INGEST_ON_READ` | (settings default) | Opportunistic ingest on API read |
| `QS_AIHOT_ENABLED` | `true` | Legacy AI HOT source |

## 6. Failover drill (`QS_AIHOT_ENABLED=false`)

Prove Horizon can serve the facade without AI HOT:

```bash
export QS_AIHOT_ENABLED=false
export QS_HORIZON_ENABLED=true
# restart API / use env for the process under test
quant-system news horizon-ingest --once
curl -sS "$API/api/news/items" | jq '{provider: .provider, count: (.items|length), warnings}'
```

Expected: responses come from the Horizon provider (or cached Horizon rows),
with AI HOT disabled messaging only if Horizon is also empty/disabled.
Restore:

```bash
unset QS_AIHOT_ENABLED
# or export QS_AIHOT_ENABLED=true
```

## 7. Offline verification (no Docker)

```bash
.venv/bin/python -m pytest \
  tests/test_horizon_export_run.py \
  tests/test_news_horizon_inbox.py \
  tests/test_news_facade.py \
  tests/test_api_news_facade.py \
  -q
```

Host unit tests seed a fake upstream `mcp-runs/` tree and assert `READY` plus
parseability via `load_run` / `iter_ready_runs`. They never call real LLMs or
the network.

## 8. Ops checklist

- [ ] `data/horizon_config/.env` present, mode `600`, not committed
- [ ] `data/horizon_config/config.json` tuned; example is not secret-bearing
- [ ] `docker compose -f docker-compose.horizon.yml ps` healthy
- [ ] Recent `data/horizon_inbox/runs/*/READY` exists
- [ ] Migration 009 applied
- [ ] `quant-system news horizon-ingest --once` returns ingested/skipped JSON
- [ ] Cron every 10m for ingest
- [ ] Failover drill documented above passes once per release train

## 9. Troubleshooting

| Symptom | Check |
|---------|--------|
| No `READY` files | `docker compose ... logs horizon`; export errors leave partial dirs without READY |
| `item_count: 0` + READY | Upstream produced no scored items / wrong data mount; still intentional empty emit |
| Ingest skips run | Already ingested (content_digest) or empty/not fresh |
| Config missing in container | Ensure host `data/horizon_config/config.json` exists (entrypoint symlinks to `/opt/horizon/data/config.json`) |
| Auth errors from LLM | `.env` key name must match `config.ai.api_key_env` |
