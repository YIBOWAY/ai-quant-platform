# AI 新闻研究流（界面路由：`/ai-news`）

> 适用读者：想在量化研究平台里快速浏览 AI 行业热点，但不希望新闻自动影响策略或账户的人。
> 安全红线：本页面是外部/自托管新闻的只读入口，不生成交易信号，不触发回测，不调用 paper account，也不接任何真实交易链路。LLM API key 只存在于 Horizon 容器 `env_file`，不进平台 `QS_*` 设置，也不经 status API 外泄。

---

## 一句话定位

`/ai-news` 是 **双源 News Facade** 的本地只读页面。前端只访问本地 FastAPI：

```text
/ai-news
  -> GET /api/news/*          (中性路由，推荐)
  -> GET /api/news/aihot/*    (历史别名，默认语义同 auto facade)
  -> NewsFacade (preference=auto|aihot|horizon)
       primary:  AI HOT public API
       standby:  Horizon → inbox → Postgres (provider=horizon)
```

页面展示精选动态、分类 / 关键词 / 时间窗筛选、最新日报和近期日报归档。它只帮助阅读和追溯原文，不把新闻写入因子、策略、回测或模拟账户。Brief 的 `ai_news` digest 与本页共用同一 Facade。

## 双源与自动 failover

| 角色 | 源 | 说明 |
|---|---|---|
| 主源 (primary) | **AI HOT** | 外部 beta REST；实时代理 + 可选 PG 读穿缓存 |
| 热备 (standby) | **Horizon** | 同机 Docker sidecar 定时产粮；host 侧 ingest 写入 Postgres；请求路径**只读 PG**，不跑 pipeline、不 `docker exec` |

默认 `preference=auto` 的读取顺序：

```text
1. aihot live          → served_from=primary
2. horizon PG fresh    → served_from=failover   (主源失败/disabled/超时/无效响应)
3. aihot cache         → served_from=cache
4. news_unavailable    → 结构化错误（两路皆空）
```

- `preference=aihot|horizon` 强制单源，成功时 `served_from=forced`。
- `QS_NEWS_FAILOVER_ENABLED=false` 或 `QS_HORIZON_ENABLED=false` 时，auto 退化为 AI HOT-only（+ cache）。
- 成功响应始终带 `provider`、`preference`、`served_from`、`warnings`、`research_safety`。
- Horizon run 的 freshness 由 `QS_HORIZON_MAX_AGE_SECONDS`（默认 36h）与 `item_count>0` 约束；空 run 不作 failover 成功源。

运维细节与 sidecar 启停见 [execution/ai-news-horizon.md](../execution/ai-news-horizon.md)。设计见 [specs/2026-07-23-ai-news-horizon-bridge-design.md](../superpowers/specs/2026-07-23-ai-news-horizon-bridge-design.md)。

## 能做什么

- 看 AI HOT 精选/全部新闻流，或在主源失败时自动读 Horizon PG 粮。
- 按分类筛选：模型、产品、行业、论文、技巧观点。
- 按关键词搜索，例如 `OpenAI`、`Sora`、`agents`。
- 按 `24h` / `3d` / `7d` 时间窗收窄。
- 查看最新或指定日期的日报（主源或 failover）。
- 打开原文链接核对来源。
- 在 status 中查看双源配置、aihot 最近错误、horizon last_run/fresh（**不**主动打 AI HOT 外网，**不**启动 Horizon pipeline）。

## 本地 API 速查

前端页面只调用本地后端；不要在前端直连 `https://aihot.virxact.com`，也不要直连 Horizon 容器。

### 中性路由（推荐）

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/news/items` | 新闻流；`preference=auto\|aihot\|horizon`，以及 `mode`/`category`/`q`/`since`/`cursor`/`take=1..100`。 |
| `GET` | `/api/news/daily` | 最新或指定日期日报；`preference` + 可选 `date=YYYY-MM-DD`。 |
| `GET` | `/api/news/dailies` | 日报归档；`preference` + `take=1..180`。 |
| `GET` | `/api/news/status` | 双源本地配置、failover 开关、horizon last_run/fresh、进程内最近错误；不探测外网、不跑 pipeline。 |

### 兼容别名

| 方法 | 路径 | 说明 |
|---|---|---|
| `GET` | `/api/news/aihot/items` | 转 Facade，默认 `preference=auto`（路径名是历史别名）。 |
| `GET` | `/api/news/aihot/daily` | 同上。 |
| `GET` | `/api/news/aihot/dailies` | 同上。 |
| `GET` | `/api/news/aihot/status` | 与中性 status 同形或超集。 |

示例：

```bash
curl "http://127.0.0.1:8765/api/news/items?preference=auto&mode=selected&take=20"
curl "http://127.0.0.1:8765/api/news/items?preference=horizon&take=20"
curl "http://127.0.0.1:8765/api/news/daily"
curl "http://127.0.0.1:8765/api/news/status"
# 兼容别名仍可用
curl "http://127.0.0.1:8765/api/news/aihot/items?mode=selected&take=20"
```

响应关键字段：

| 字段 | 取值 |
|---|---|
| `provider` | `aihot` \| `horizon` |
| `preference` | `auto` \| `aihot` \| `horizon` |
| `served_from` | `primary` \| `failover` \| `cache` \| `forced` |
| `warnings` | failover / cache / upstream 说明 |
| `research_safety` | research-only 边界声明 |

## 不能做什么

- 不会自动生成交易建议。
- 不会创建、启动、暂停或修改策略。
- 不会启动回测。
- 不会修改 paper account 或 Paper Strategy Sleeves。
- 不会调用 Futu 交易接口、券商账户、钱包或签名逻辑。
- 不会在请求路径同步跑 Horizon pipeline 或调用容器内 LLM。
- 不会把 LLM key 放进平台 settings 或 status 响应。

## 数据可信度边界

AI HOT 是外部 beta 数据源；Horizon 摘要同样可能由 LLM 生成。页面会保留 `provider_beta` / `research_safety` 提示，并展示**实际** `provider` 与 `served_from`。引用任何内容前，应点击原文链接核对。

## 配置

`.env` 可覆盖：

```text
# 源选择与 failover
QS_NEWS_SOURCE_PREFERENCE=auto          # auto | aihot | horizon
QS_NEWS_FAILOVER_ENABLED=true

# AI HOT 主源
QS_AIHOT_ENABLED=true
QS_AIHOT_BASE_URL=https://aihot.virxact.com
QS_AIHOT_TIMEOUT_SECONDS=8
QS_AIHOT_CACHE_TTL_SECONDS=120
QS_AIHOT_USER_AGENT=Mozilla/5.0 ...

# Horizon 热备（产物桥；LLM key 不在这里）
QS_HORIZON_ENABLED=true
QS_HORIZON_INBOX_DIR=<repo>/data/horizon_inbox
QS_HORIZON_MAX_AGE_SECONDS=129600       # 36h freshness
QS_HORIZON_PROVIDER_BETA=false
QS_HORIZON_INGEST_ON_READ=false         # 默认不在读路径做 ingest
```

`QS_AIHOT_ENABLED=false` 时，若 Horizon PG 有新鲜粮，auto 仍可 `served_from=failover` 返回 200；两路皆不可用才落到 `news_unavailable`。

常见错误（强制单源或两路皆空时）：

| 情况 | HTTP | `detail.code`（或等价） |
|---|---:|---|
| 功能关闭且无可用 failover/cache | `503` | `aihot_disabled` / `news_unavailable` |
| 上游超时且无可用 failover/cache | `503` | `aihot_timeout` |
| 上游 4xx/5xx 或网络错误且无兜底 | `502` | `aihot_bad_gateway` |
| 上游 JSON 或字段结构异常且无兜底 | `502` | `aihot_invalid_response` |
| 本地 query 参数非法 | `422` | FastAPI validation |

## Horizon 启用（摘要）

完整 runbook：[execution/ai-news-horizon.md](../execution/ai-news-horizon.md)。Compose：`docker-compose.horizon.yml`。

一次环境：

```bash
# 1) migration 009 — provider runs 元数据表
quant-system migrate --apply --allow 009_ai_news_provider_runs.sql --yes

# 2) 启动 sidecar（LLM key 仅在 data/horizon_config/.env）
docker compose -f docker-compose.horizon.yml up -d --build

# 3) 等 READY 后 host 侧 ingest（不写 LLM，不进容器）
ls data/horizon_inbox/runs/*/READY
quant-system news horizon-ingest --once
```

建议 host cron 每 10 分钟跑一次 `news horizon-ingest --once`（只做 inbox→PG，不在 host 跑 Horizon LLM）。

Failover 演练：

```bash
export QS_AIHOT_ENABLED=false
# 重启 API 进程后
curl -sS "http://127.0.0.1:8765/api/news/items?preference=auto&take=5" \
  | jq '{provider, preference, served_from, count: (.items|length), warnings}'
# 期望：provider=horizon, served_from=failover
```

## 可选数据库缓存

如果启用现有 `QS_DATABASE_*` Postgres 配置：

- `/api/news/*/items`（及 aihot 别名）在 AI HOT 实时成功后 best-effort 写入 `quant_system.ai_news_items`。
- 日报写入 `quant_system.ai_news_daily_reports`（`owner_user_id + provider + report_date`）。
- Horizon ingest 写入同一套 `ai_news_*` 表，并以 `provider=horizon` 区分；migration **009** 增加 `quant_system.ai_news_provider_runs` 供 freshness / status / 幂等 ingest。
- 上游失败时 facade 按 §「双源与自动 failover」顺序回落，并在 `warnings` 标明来源。

这个路径只用于页面/Brief 只读兜底：

- 不在请求路径跑调度器或 Horizon pipeline。
- 不生成信号、因子或交易建议。
- 数据库不可用时，AI HOT 实时代理仍可用；Horizon failover 不可用。

本地 Docker 数据库检查：

```bash
docker start quantplatform-db

export QS_DATABASE_ENABLED=true
export QS_DATABASE_URL='postgresql://quant:quantpass@127.0.0.1:5432/quantplatform'
quant-system serve --host 127.0.0.1 --port 8765

curl http://127.0.0.1:8765/api/health
docker exec quantplatform-db psql -U quant -d quantplatform -c \
  "SELECT table_name FROM information_schema.tables WHERE table_schema = 'quant_system' AND table_name LIKE 'ai_news_%' ORDER BY table_name;"
```

正常情况下会看到：

```text
ai_news_daily_reports
ai_news_fetches
ai_news_items
ai_news_provider_runs
```

## 验证

离线测试不得访问真实 AI HOT、真实 Horizon 容器、真实 LLM 或真实 Postgres（除显式集成夹具外）：

```bash
python -m pytest \
  tests/test_api_news_aihot.py \
  tests/test_api_news_facade.py \
  tests/test_news_facade.py \
  tests/test_news_aihot_client.py \
  tests/test_news_aihot_repository.py \
  tests/test_news_daily_report_repository.py \
  tests/test_news_horizon_inbox.py \
  tests/test_horizon_export_run.py \
  tests/test_settings_aihot.py \
  -q
python -m pytest tests/test_frontend_ai_news_contract.py -q
npm --prefix src/frontend run type-check
npm --prefix src/frontend run lint
```

## 相关代码入口

- Facade：`src/quant_system/news/facade.py`
- AI HOT client：`src/quant_system/news/aihot_client.py`
- Horizon inbox / ingest：`src/quant_system/news/`（horizon inbox + CLI `news horizon-ingest`）
- 后端模型：`src/quant_system/news/models.py`
- 可选缓存 / provider runs：`src/quant_system/news/repository.py`
- API schema：`src/quant_system/api/schemas/news.py`
- API route：`src/quant_system/api/routes/news.py`
- 数据库迁移：`scripts/sql/002_ai_news_cache.sql`、`scripts/sql/009_ai_news_provider_runs.sql`
- Docker sidecar：`docker-compose.horizon.yml`、`deploy/horizon/`
- 前端页面：`src/frontend/app/ai-news/page.tsx`
- 前端组件：`src/frontend/components/forms/AiNewsView.tsx`
- 前端 API client：`src/frontend/lib/api.ts`

## 相关文档

- 操作 runbook：[execution/ai-news-horizon.md](../execution/ai-news-horizon.md)
- 设计 spec：[superpowers/specs/2026-07-23-ai-news-horizon-bridge-design.md](../superpowers/specs/2026-07-23-ai-news-horizon-bridge-design.md)
- 实现计划：[superpowers/plans/2026-07-23-ai-news-horizon-bridge.md](../superpowers/plans/2026-07-23-ai-news-horizon-bridge.md)
- 前序 MVP 设计：[design/ai_news_integration_plan.md](../design/ai_news_integration_plan.md)
