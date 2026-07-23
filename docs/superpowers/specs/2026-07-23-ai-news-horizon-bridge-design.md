# AI News × Horizon Bridge 设计文档（Phase A）

> **状态：** Phase A **已实现**（Tasks 1–10）。实现计划见 [plans/2026-07-23-ai-news-horizon-bridge.md](../plans/2026-07-23-ai-news-horizon-bridge.md)；操作指南 [guides/ai-news.md](../../guides/ai-news.md)；runbook [execution/ai-news-horizon.md](../../execution/ai-news-horizon.md)。  
> **日期：** 2026-07-23  
> **范围：** Phase A — 热备 failover + 合同可升 Phase B 双源合并。  
> **前序：** [docs/design/ai_news_integration_plan.md](../../design/ai_news_integration_plan.md)（MVP-1/MVP-2 AI HOT 只读接入；本文落实其 §9 Horizon 二期占位）。  
> **非目标总纲：** 不把新闻接入策略/交易/paper；不在请求路径跑 Horizon pipeline；不把 Horizon 源码嵌进 `quant_system` 运行时。

---

## 1. 背景与问题

### 1.1 现状

平台 `/ai-news` 与每日晨报 Brief 的 `ai_news` digest 均依赖 **AI HOT** 单一外部 beta 服务：

```text
/ai-news | Brief
  → GET /api/news/aihot/*
  → AiHotClient
  → https://aihot.virxact.com/api/public/*
  → 可选 Postgres stale cache（ai_news_items / ai_news_daily_reports）
```

已有韧性：进程内 TTL、可选 PG 读穿缓存、上游失败时 cache fallback、`research_safety` 文案。  
**未覆盖：** AI HOT 服务永久停服或产品下线时的 bus-factor 风险——cache 会过期，页面与 Brief 最终无粮。

### 1.2 动机（已确认）

| 优先级 | 诉求 | 说明 |
|---|---|---|
| P0 | **供应商单点风险** | AI HOT 目前可用，但停服后本地 AI 新闻不可用 |
| P1 | 自动切换 | 不需要人工监控/改配置才能切备用源 |
| P2 | 产物进 PostgreSQL | 便于后续调用、日报存档、与现有 cache 同构 |
| P3 | 多源互证 / 双语日报 | 加分项；Phase A 不合并，合同预留 Phase B |

### 1.3 已锁定产品决策

| 决策 | 选择 |
|---|---|
| 运维承担 | **B：轻量自托管** — 同机 Docker 跑 Horizon sidecar + 一个 LLM API key |
| 结合深度 | **方案 1：产物桥 + 平台内 News Facade**（不内嵌、不请求内同步跑 pipeline） |
| Phase 策略 | **先 A（热备 failover），合同按能升 B（双源合并）设计** |
| Brief | 与 `/ai-news` **同一 Facade**，一起自动切换 |
| 运行位置 | **同机 Docker**（与现有 `quantplatform-db` 并列） |
| 权威可读层 | **PostgreSQL**；volume 仅作入境与审计 |
| Failover 读路径 | **只认 PG**（不做请求路径 volume 直读） |
| 切换方式 | **`preference=auto` 默认全自动**，无需人工开关 |

### 1.4 明确不选的路径

- 把 Horizon 整仓库 submodule/vendoring 进 monorepo 运行时（与前序设计文档一致）。
- 请求路径 `docker exec` / MCP `hz_run_pipeline`（延迟、费用、测试与 8s timeout 冲突）。
- 在平台内重写完整抓取/评分/调度 pipeline（对 bus-factor 目标过重）。
- 另起一套与 `ai_news_*` 无关的平行新闻库（放弃现有 provider 列与 Brief 归档同构）。

---

## 2. 目标与成功标准

### 2.1 Phase A 目标

1. AI HOT 失败、超时、disabled 或无效响应时，**自动**改用本地已 ingest 的 Horizon 数据，HTTP 200 + 明确 `provider`/`served_from`/`warnings`。
2. AI HOT 恢复后，**自动**回到主源，无需改配置。
3. Horizon 在同机 Docker 定时产粮；包装脚本写入 inbox 合同；平台 Ingest 写入 PostgreSQL。
4. `/ai-news` 与 Brief `ai_news` digest 共用 News Facade。
5. 旧 `/api/news/aihot/*` 兼容保留，默认语义变为 auto facade（路径名是历史别名）。
6. 测试不打真外网、不依赖真 Horizon 容器/真 LLM；用 inbox 夹具 + mock client + fake/测试 PG。

### 2.2 成功标准（可验收）

1. 在 PG 中已有未过期 `provider=horizon` 粮的前提下，`QS_AIHOT_ENABLED=false` 或 mock 上游全失败时：  
   `GET /api/news/items?preference=auto`（及兼容 `/api/news/aihot/items`）返回 200，`provider=horizon`，`served_from=failover`，`warnings` 含 failover 说明。
2. Brief 生成在同等条件下仍能填 `ai_news`（或在两路皆空时 `ai_news=[]` 且不阻断其余 Brief 区块），watermark/meta 记录实际 provider。
3. AI HOT 恢复后同 auto 请求回到 `provider=aihot`，`served_from=primary`。
4. `quant-system news horizon-ingest`（或等价 CLI）能将带 `READY` 的 inbox run 幂等写入 items/daily/runs。
5. `GET /api/news/status` 展示双源配置、aihot 最近错误、horizon last_run/fresh，且 **不** 主动请求 AI HOT、不启动 Horizon pipeline。
6. 全量相关单测离线绿；无交易/策略/paper mutation 新路径。

### 2.3 非目标（Phase A）

1. 不把 Horizon 源码嵌进 `quant_system` 运行时。  
2. 不在 HTTP 请求路径同步跑 pipeline / MCP。  
3. 不做 active-active 双源合并、去重互证 UI（Phase B）。  
4. 不做新闻 → 策略 / 因子 / 回测 / paper / 任何交易。  
5. 不做用户可配置信源 UI（Horizon `config.json` 仍文件级人工维护）。  
6. 不做实时推送 / WebSocket。  
7. 不做请求路径 volume 直读 failover。  
8. 不做跨机远程 Horizon、不多租户新闻 ACL 产品化。  
9. 不要求 Horizon daily 与 AI HOT daily 版式像素一致。  
10. 不承诺 horizon 侧 cursor 分页与 AI HOT 完全同语义。

---

## 3. 架构

### 3.1 一句话

**AI HOT 仍是 Phase A 主源；Horizon 在同机 Docker 定时生产；产物经 volume 入境、Ingest 进 PostgreSQL；`NewsFacade` 以 `auto` 默认供给 `/ai-news` 与 Brief。合同预留 Phase B 合并，第一期只做热备 failover。**

### 3.2 运行时拓扑

```text
┌─ 同机 Docker Compose ───────────────────────────────────────┐
│  quantplatform-db     (现有 Postgres)                         │
│  horizon              (钉死版本镜像 + 包装 entrypoint)         │
│    → 定时 pipeline → 导出 inbox 合同 → touch READY            │
│  volume: <repo>/data/horizon_inbox/                           │
│  volume: <repo>/data/horizon_config/  (config + secrets)      │
└───────────────┬─────────────────────────────────────────────┘
                │
                ▼
   宿主机: quant-system news horizon-ingest   (cron / launchd)
                │
                ▼
        PostgreSQL quant_system.ai_news_*
        provider = 'aihot' | 'horizon'
                │
                ▼
           NewsFacade (preference=auto|aihot|horizon)
                │
        ┌───────┴────────┐
        ▼                ▼
   /api/news/*      Brief ai_news digest
   UI /ai-news      (含兼容 /api/news/aihot/*)
```

**进程边界**

| 进程 | 职责 |
|---|---|
| `horizon` 容器 | 抓源、评分、摘要、导出 inbox；持有 LLM key |
| 宿主机 `horizon-ingest` | 读 inbox、校验、事务写 PG；**不**持有 LLM key |
| 宿主机 / 容器 `quant-api` | 只读 Facade；短超时打 AI HOT；读 PG；不跑 pipeline |
| 前端 | 只打本地 API |

### 3.3 平台内模块边界

| 单元 | 职责 | 禁止 |
|---|---|---|
| `news/aihot_client.py` | 保持：AI HOT HTTP 只读客户端 | 不知 Horizon |
| `news/horizon_inbox.py`（新） | 扫描/解析 inbox 合同、校验 READY | 不跑 pipeline、不写业务 API 响应 |
| `news/horizon_ingest.py`（新） | 归一化 → upsert PG + provider_runs | 不服务 HTTP 热路径重逻辑 |
| `news/facade.py`（新） | preference 选择、stamp provider/served_from/warnings | 不抓多源、不调 LLM |
| `news/models.py` | provider-neutral 模型（可由 AiHot* 升格或并存别名） | 不依赖 FastAPI |
| `news/repository.py` 等 | items/daily cache + horizon 读写 | 缓存失败不得破坏 live 主路径语义 |
| `api/routes/news.py` | GET only；中性路由 + aihot 兼容别名 | 不引入 POST 交易/策略 |
| `api/schemas/news.py` | 响应合同扩展字段 | 顶层不用 `safety` 名 |
| UI `AiNewsView` / Brief | 消费 facade；展示实际 provider | 不直连外网、不读 volume |

### 3.4 存储两层分工

| 层 | 位置 | 权威性 | 用途 |
|---|---|---|---|
| Inbox volume | `data/horizon_inbox/runs/<run_id>/` | 入境原文 | 调试、重放 ingest、审计、版本对照 |
| PostgreSQL | `quant_system.ai_news_*` | **API/Brief 权威读** | failover、日报归档、后续调用 |

Horizon **永不**直写平台 PG。平台 Ingest 是唯一写入 `provider=horizon` 的路径。

### 3.5 Phase 划分

| Phase | 行为 |
|---|---|
| **A（本文）** | `auto` = AI HOT live → Horizon PG fresh → AI HOT PG cache → 错误；Brief 同路 |
| **B（预留）** | 同合同下 merge/dedupe、双 provider 标记、互证；UI 主路径字段名尽量不变 |

---

## 4. Inbox 产物合同

### 4.1 目录布局

```text
data/horizon_inbox/
  runs/
    <run_id>/
      meta.json
      items.json
      summary-zh.md      # 可选
      summary-en.md      # 可选
      daily.json         # 可选；若存在优先于从 markdown 合成 daily
      READY              # 原子完成标记：存在才允许 ingest
      INGESTED           # 可选；ingest 成功后写入（PG runs 表仍是权威去重）
  .gitkeep
```

`run_id`：建议 `YYYYMMDDTHHMMSSZ-<short>` 或上游原生 id；平台原样存储，不解析语义。

### 4.2 原子性

1. 包装脚本先写齐内容文件并 fsync。  
2. **最后** `touch READY`。  
3. 无 `READY` 的目录：ingest **忽略**。  
4. 导出失败：不写 `READY`。

### 4.3 `meta.json` 最小字段

```text
run_id: string
generated_at: ISO-8601
window_start?: ISO-8601
window_end?: ISO-8601
horizon_version?: string
item_count: int
status: "ok" | "empty" | "error"
error?: string
source_counts?: object
```

### 4.4 `items.json` 最小字段

数组，元素：

```text
id: string                 # 稳定 id；缺失则 ingest 用 url 规范化哈希生成
title: string
title_en?: string | null
url: string
source: string
published_at?: string | null
summary?: string | null
category?: string | null
score?: number | null      # 建议 0–10
language?: string | null
raw?: object               # 可选子集，进 jsonb
```

### 4.5 日报

优先级：

1. 若存在合法 `daily.json` → 映射为平台 `NewsDaily`（lead/sections/flashes）。  
2. 否则用 `summary-zh.md` / `summary-en.md` + `meta` **弱合成**：  
   - `date` 取 `generated_at` 的 UTC 日期（或 meta 显式 daily_date）  
   - `sections` 可为一至两段 markdown 包装  
   - `flashes` 可为 `[]`  
   - `lead` 可取首段标题/摘要  

Phase A **不**要求与 AI HOT sections 语义一致，但字段必须存在以便 UI/归档不崩。

### 4.6 包装导出层（唯一允许“脏知识”的地方）

- 路径：`deploy/horizon/` 下 entrypoint + export 脚本。  
- 负责把 Horizon 原生 `data/summaries/`、`data/mcp-runs/` 等 **映射** 为上述 inbox 合同。  
- 平台 Ingest **只认 inbox 合同**，不依赖 Horizon 内部路径长期稳定。  
- Horizon 镜像 **钉死 git tag/commit**；升级显式、可回滚；不用漂浮 `latest`。

### 4.7 安全（inbox 当不可信输入）

- 限制单 run 目录总大小、`items.json` 条数上限、单字段长度。  
- 仅接受 UTF-8 JSON/Markdown 文本；不执行、不渲染 HTML。  
- URL 做基本校验；前端外链保持 `rel="noopener noreferrer"`。  
- Ingest 不读取 LLM key。

---

## 5. PostgreSQL

### 5.1 复用现有表

| 表 | Phase A 用法 |
|---|---|
| `ai_news_items` | `provider='aihot' \| 'horizon'`；`(provider, item_id)` 冲突更新已存在 |
| `ai_news_fetches` | 记录成功拉取/ingest 指纹与时间（若现逻辑可扩展 provider） |
| `ai_news_daily_reports` | `provider + report_date`（+ 现有 owner 约定）归档 Horizon 日报 |

**items 主路径 Phase A 可不改 schema**（已有 provider 列）。实现时若发现 NOT NULL / check 约束把 provider 钉死为 `aihot`，再加最小 migration 放宽。

### 5.2 新增表 `ai_news_provider_runs`

```text
ai_news_provider_runs
  provider          text        not null   -- 'horizon'（未来可扩展）
  run_id            text        not null
  generated_at      timestamptz not null
  window_start      timestamptz null
  window_end        timestamptz null
  item_count        int         not null default 0
  daily_date        date        null
  inbox_path        text        not null
  content_digest    text        not null   -- 产物哈希，幂等
  ingested_at       timestamptz not null
  status            text        not null   -- ingested | failed | stale
  error             text        null
  raw_meta          jsonb       not null default '{}'
  primary key (provider, run_id)
```

用途：freshness 判断、status 页、幂等 ingest、failover 选择“最新合法 run”，避免扫 items 表猜测。

索引建议：`(provider, status, generated_at desc)`。

### 5.3 Owner 约定

与现有 AI HOT daily 一致（当前 `root` / settings 中的 owner 约定）。Phase A 不新增多租户新闻模型。

### 5.4 Ingest 算法

```text
for each run_dir under inbox/runs:
  if no READY: skip
  if (provider, run_id) already status=ingested with same content_digest: skip
  parse meta.json + items.json (+ daily)
  validate minima
  begin transaction:
    upsert ai_news_items (provider=horizon)
    upsert ai_news_daily_reports if daily present
    upsert ai_news_provider_runs status=ingested
  on failure:
    record status=failed + error when possible; do not half-commit items/daily/run
  optional: write INGESTED marker in run_dir
```

**CLI**

```text
quant-system news horizon-ingest
  [--inbox DIR]
  [--once]
  [--run-id ID]
```

默认读 `QS_HORIZON_INBOX_DIR`。

### 5.5 Freshness

| 配置 | 默认 | 含义 |
|---|---|---|
| `QS_HORIZON_MAX_AGE_SECONDS` | `129600`（36h） | horizon run `generated_at` 早于此时视为不 fresh，不可作 failover 成功源 |

Daily：`report_date` 为 UTC 今天或昨天视为可服务（与现有 daily 日期习惯对齐）；更旧的仍可 `preference=horizon&date=` 强查归档，但不作为 auto failover 的“今日日报”成功源。

`item_count=0` 的 ingested run：**不**视为 fresh failover 源（避免空页装成功）。

---

## 6. NewsFacade 与 API 合同

### 6.1 路由

#### 中性路由（Phase A 新增，前端/Brief 新代码优先）

| 方法 | 路径 |
|---|---|
| `GET` | `/api/news/items` |
| `GET` | `/api/news/daily` |
| `GET` | `/api/news/dailies` |
| `GET` | `/api/news/status` |

#### 兼容别名（保留）

| 方法 | 路径 | 行为 |
|---|---|---|
| `GET` | `/api/news/aihot/items` | 转 Facade，默认 `preference=auto` |
| `GET` | `/api/news/aihot/daily` | 同上 |
| `GET` | `/api/news/aihot/dailies` | 同上 |
| `GET` | `/api/news/aihot/status` | 聚合 status（与中性 status 同形或超集） |

路径中的 `aihot` 是 **历史兼容名**，不再表示“只读 AI HOT”。文档与 UI 必须改掉绝对表述。

### 6.2 Query

**items**

```text
preference=auto|aihot|horizon   # 默认 auto（或 QS_NEWS_SOURCE_PREFERENCE）
mode=selected|all               # aihot 语义；horizon 无 selected 时 selected≈全部已入库条目
category=<string>
q=<string>
since=<ISO-8601>
cursor=<string>                 # aihot 透传；horizon/PG 阶段可空或 offset 退化
take=1..100
```

**daily**

```text
preference=auto|aihot|horizon
date=YYYY-MM-DD                 # 可选
```

**dailies**

```text
preference=auto|aihot|horizon
take=1..180
```

### 6.3 响应扩展字段

在现有 items/daily/dailies 字段之上 **固定增加**：

```text
provider: "aihot" | "horizon"     # 实际服务者
provider_beta: bool
preference: "auto" | "aihot" | "horizon"
served_from: "primary" | "failover" | "cache" | "forced"
warnings: string[]
research_safety: { ... 保持现有四元组 ... }
fetched_at / 既有业务字段
```

| `served_from` | 含义 |
|---|---|
| `primary` | auto 下 AI HOT live 成功 |
| `failover` | auto 下主源失败，Horizon PG 顶上 |
| `cache` | 该 provider 的 stale PG cache（含现有 AI HOT cache 语义） |
| `forced` | 调用方强指定 `preference=aihot\|horizon` |

**warnings 示例（人可读，建议含稳定 token 便于扫）：**

```text
aihot_upstream: AI HOT request timed out
served_from=horizon_failover
horizon_run_id=20260723T120000Z-ab12
horizon_generated_at=2026-07-23T12:00:00+00:00
```

**research_safety** 继续使用该名；**禁止**用顶层 `safety`（全局 middleware 会覆盖）。

内容模型与现 `AiHotItem` / `AiHotDaily` 字段对齐，升格命名可为 `NewsItem` / `NewsDaily`，序列化字段名保持前端兼容。

### 6.4 auto 算法（items；daily 同序）

```text
auto:
  1. try AI HOT live
     success → stamp provider=aihot, served_from=primary; best-effort cache aihot; return
  2. on AI HOT failure/disabled/invalid:
     load fresh horizon from PG (provider_runs ingested + generated_at within max_age + item_count>0)
     found → stamp provider=horizon, served_from=failover; warnings include upstream error + run meta; return 200
  3. else try existing AI HOT PG cache for query
     found → stamp served_from=cache; warnings; return 200
  4. else structured error news_unavailable (detail: aihot_error + horizon_error)
```

**强指定**

- `aihot`：live → aihot cache → 错误；**不**切 horizon。  
- `horizon`：仅 PG horizon；无粮/不 fresh → `horizon_unavailable` / `horizon_stale`。

**开关**

- `QS_NEWS_FAILOVER_ENABLED=false`：auto 退化成今日 AI HOT-only（+ cache）。  
- `QS_HORIZON_ENABLED=false`：同上。  
- `QS_AIHOT_ENABLED=false`：auto 直接从步骤 2 开始（演练主源停服）。

**请求路径不做重 ingest**（默认 `QS_HORIZON_INGEST_ON_READ=false`）。

### 6.5 Status 合同

`GET /api/news/status` **只读本地**（settings + 进程内 last_error + PG runs 元数据）：

```text
preference_default: "auto"
research_only: true
providers:
  aihot:
    enabled, base_url, timeout_seconds, cache_ttl_seconds
    provider_beta: true
    last_error: { code, message, at } | null
  horizon:
    enabled, inbox_dir, max_age_seconds
    provider_beta: false   # 或 QS_HORIZON_PROVIDER_BETA
    last_run: { run_id, generated_at, ingested_at, item_count, status } | null
    fresh: bool
failover:
  auto_enabled: true
  order: ["aihot_live", "horizon_pg", "aihot_cache"]
warnings: string[]   # 例如 inbox READY 积压、horizon stale
```

**禁止**：为 status 探活而请求 AI HOT 或启动 Horizon。

### 6.6 错误语义

| 情况 | HTTP | code |
|---|---:|---|
| 新闻功能总关（若有总开关） | 503 | `news_disabled` |
| auto 两路皆不可用且无 cache | 502/503 | `news_unavailable` |
| 强指定 aihot 失败 | 同现网 | `aihot_disabled` / `aihot_timeout` / `aihot_bad_gateway` / `aihot_invalid_response` |
| 强指定 horizon 无粮 | 503 | `horizon_unavailable` |
| 强指定 horizon 仅过期粮 | 503 | `horizon_stale` |
| query 非法 | 422 | validation |

Failover **成功仍是 200**，不靠 5xx 表达“用了备用源”。

### 6.7 配置清单

```text
# News facade
QS_NEWS_SOURCE_PREFERENCE=auto
QS_NEWS_FAILOVER_ENABLED=true

# AI HOT（保持现有）
QS_AIHOT_ENABLED=true
QS_AIHOT_BASE_URL=https://aihot.virxact.com
QS_AIHOT_TIMEOUT_SECONDS=8
QS_AIHOT_CACHE_TTL_SECONDS=120
QS_AIHOT_USER_AGENT=...

# Horizon bridge
QS_HORIZON_ENABLED=true
QS_HORIZON_INBOX_DIR=<repo>/data/horizon_inbox
QS_HORIZON_MAX_AGE_SECONDS=129600
QS_HORIZON_PROVIDER_BETA=false
QS_HORIZON_INGEST_ON_READ=false

# 既有 DB
QS_DATABASE_ENABLED=true
QS_DATABASE_URL=...
```

LLM key **只**进入 Horizon 容器 env / `data/horizon_config/`，**不**进入 `QS_*` 平台 settings、不进入 status 响应。

---

## 7. Brief 接入

### 7.1 现状

`src/frontend/app/brief/page.tsx` 等通过 `getAiHotItems({ take: 6 })` 填充归档 payload 的 `ai_news`。

### 7.2 Phase A 行为

```text
Brief 生成
  → getNewsItems({ take: 6, preference: "auto" })
    （或 getAiHotItems 内部改为走 facade auto）
  → 映射 BriefAiNewsItem（主字段保持）
  → source_watermark / 区块 meta 增加可选：
       provider, served_from, warnings 摘要
```

| 规则 | 说明 |
|---|---|
| 与 `/ai-news` 同 Facade | 避免“页有报无”分裂 |
| 两路皆空 | `ai_news=[]` + warning；**不阻断** Brief 其余部分 |
| 归档诚实 | snapshot 记录实际 provider/served_from，可回放 |
| 严格 zod | 新 meta 字段必须 optional，避免老归档解析失败 |
| 不写交易 | 仅 research payload |

---

## 8. 前端 `/ai-news`

### 8.1 最小改动

- 优先改 `lib/api.ts` 走中性路径，或继续旧 URL（已 auto）。  
- Status strip：显示 **实际 provider**、failover 标记、Horizon fresh。  
- 文案从“仅 AI HOT beta”改为：  
  - 主源 AI HOT（外部 beta）；  
  - 备用自托管 Horizon；  
  - 摘要可能 LLM 生成，引用请回原文；  
  - 只读研究，不触发交易。  
- Feed / Daily 布局与筛选控件保持；Horizon daily 版式可较弱但可读。  
- **不**做主按钮“手动切源”（调试可用 query `preference=`）。

### 8.2 契约测试

扩展 `tests/test_frontend_ai_news_contract.py`（及前端 vitest 若有）：响应含 `provider`/`served_from`；failover warning 可渲染。

---

## 9. Docker 与运维

### 9.1 Compose 服务

| 服务 | 角色 |
|---|---|
| `quantplatform-db` | 已有 |
| `horizon` | 钉版本构建；loop 或 cron-once 跑 pipeline + export inbox |
| 可选 `horizon-ingest` | 容器内周期 ingest；**默认更推荐宿主机 cron 调 CLI** |

网络：`horizon` 需出网（源 + LLM）；**不**需连 PG。  
`ingest` / API 连 PG；ingest 默认不需出网。

### 9.2 Volume

| 宿主 | 容器 | 写 | 读 |
|---|---|---|---|
| `data/horizon_inbox/` | `/inbox` | horizon export | ingest、人工 |
| `data/horizon_config/` | `/config` | 人 | horizon |

API 若在宿主机 serve：直接使用宿主 `QS_HORIZON_INBOX_DIR`。

### 9.3 调度默认

| 组件 | 默认 |
|---|---|
| Horizon run interval | 6h（`21600s`，可配） |
| Ingest interval | 宿主机每 5–15 分钟 `horizon-ingest --once` |
| 镜像标签 | 固定 commit/tag，写入 `deploy/horizon` 与 runbook |

### 9.4 密钥

- `data/horizon_config/.env` 或 compose `env_file`：`OPENAI_API_KEY` / `ANTHROPIC_API_KEY` 等。  
- gitignore 真配置；仓库只留 `config.example.json` / `.env.example` 片段。  
- 无 key ⇒ horizon 无法产粮 ⇒ failover 无效；**上线验收必须先成功一轮 ingest**。

### 9.5 仓库落点

```text
deploy/horizon/Dockerfile
deploy/horizon/entrypoint.sh
deploy/horizon/export_run.py   # 或 .sh
deploy/horizon/config.example.json
docker-compose.horizon.yml     # 或主 compose profile: horizon
docs/guides/ai-news.md         # 更新
docs/execution/ai-news-horizon.md   # 新 runbook（前序文档已预告需要）
data/horizon_inbox/.gitkeep
data/horizon_config/.gitignore
scripts/sql/0xx_ai_news_provider_runs.sql
```

### 9.6 手运维与演练

```text
# 跑一轮 horizon
docker compose -f docker-compose.horizon.yml run --rm horizon

# 入库
quant-system news horizon-ingest --once

# 演练停服自动切
QS_AIHOT_ENABLED=false
curl 'http://127.0.0.1:8765/api/news/items?preference=auto&take=5'
# 期望 provider=horizon served_from=failover

# 恢复主源后应自动 primary
QS_AIHOT_ENABLED=true
```

### 9.7 磁盘 GC（最小）

- inbox 保留最近 N 个 run（建议 14）或 7 天；ingest 成功且超龄可删。  
- PG 生命周期不在 Phase A 产品化；沿用现新闻缓存态度。

### 9.8 故障预期

| 故障 | 用户侧 | 要否人手 |
|---|---|---|
| AI HOT 停服 + PG 有新鲜 horizon | 自动 failover | 否 |
| AI HOT 停服 + 从未 ingest 成功 | 错误或仅旧 aihot cache | 是：修 key/网络并手跑 |
| LLM key 失效 | 备用停产；主源可用时无感 | 是：换 key |
| READY 积压 ingest 失败 | status 警告；API 用旧粮至 max_age | 是：看 ingest 日志 |
| PG 挂了 | 与全站 DB 降级一致；**不**做 volume 直读 | 修 DB 后重放 ingest |

---

## 10. 降级矩阵

| # | AI HOT | Horizon PG fresh | AI HOT cache | auto 结果 | HTTP | served_from |
|---:|---|---|---|---|---:|---|
| 1 | 成功 | 任意 | 任意 | AI HOT | 200 | primary |
| 2 | 失败/disabled | **有** | 任意 | Horizon | 200 | failover |
| 3 | 失败 | 无/过期 | **有** | AI HOT cache | 200 | cache |
| 4 | 失败 | 无/过期 | 无 | 不可用 | 502/503 | — |
| 5 | disabled 演练 | 有 | 任意 | 同 #2 | 200 | failover |
| 6 | 成功 | 有 | 任意 | **仍 AI HOT**（A 不合并） | 200 | primary |

Brief：#1–#3/#5 填 `ai_news`；#4 → `[]` + warning，其余 Brief 继续。

---

## 11. 风险与缓解

| 风险 | 缓解 |
|---|---|
| 主源停服且备用从未上膛 | 验收强制首轮 ingest；guide/runbook 前置条件 |
| Horizon 导出漂移 | 钉版本；READY 合同校验；失败不入库 |
| LLM 费用 | 6–12h interval；可配；主源可用时用户无感 |
| 静默 failover | 强制 warnings + UI 显示实际 provider |
| 密钥泄露 | key 仅 horizon 容器；API/status 不回显 |
| inbox 攻击面 | 大小/条数限制、schema、不执行内容 |
| 路径名 `aihot` 误导 | 中性路由 + 文档改写 |
| 误接交易 | 非目标写死；路由仅 GET；安全测试保留 |
| Phase B id 冲突 | 合同保留 provider+id；A 不 merge |

---

## 12. 测试计划

### 12.1 后端（离线）

```text
pytest tests/test_news_facade.py
pytest tests/test_news_horizon_inbox.py
pytest tests/test_news_horizon_ingest.py
pytest tests/test_api_news_aihot.py          # 兼容别名 + 新行为
pytest tests/test_api_news.py                # 中性路由（若拆分）
pytest tests/test_news_aihot_repository.py
pytest tests/test_news_daily_report_repository.py
pytest tests/test_settings_aihot.py          # 扩展 horizon settings
pytest tests/test_frontend_ai_news_contract.py
pytest tests/test_api_safety.py
```

覆盖矩阵：§10 行 1–6；forced aihot/horizon；status 不调 live client；ingest 幂等与失败不半写；max_age；item_count=0 不 fresh。

**禁止**：真实 DNS 访问 `aihot.virxact.com`；真实 LLM；依赖正在运行的 horizon 容器。

### 12.2 前端

```text
npm --prefix src/frontend run type-check
npm --prefix src/frontend run lint
# 若有 vitest 契约：AiNewsView provider/failover 展示
```

### 12.3 本机联调（人工，非 CI 默认）

按 §9.6 演练：有 key → 产粮 → ingest → 关 AI HOT → auto failover → 开 AI HOT → primary。

---

## 13. 实施切片（供 writing-plans）

| Slice | 内容 | 交付物 |
|---|---|---|
| **S0 合同** | provider-neutral schema；`preference`/`served_from`；中性路由 + 别名 | mock 单测绿 |
| **S1 Facade** | auto 算法 + 聚合 status | API 矩阵 #1–#6 |
| **S2 PG** | `ai_news_provider_runs` migration；horizon upsert | repo 单测 |
| **S3 Inbox+Ingest** | 合同解析、夹具、CLI、幂等 | 无 Docker 可测 |
| **S4 Brief** | digest 走 facade；watermark；空列表不炸 | 契约测 |
| **S5 UI 文案** | status strip、双源说明 | 手动/契约 |
| **S6 Docker** | deploy/horizon、compose、export、example config | runbook 本机通 |
| **S7 文档** | guides、execution runbook、INDEX、本设计状态 | 人可读 |

依赖：S0→S1→S2→S3 串行；S4/S5 依赖 S1；S6 与 S3 合同对齐后可并行；S7 收尾。

**建议第一里程碑：** S0–S4 + 夹具模拟 horizon 粮（可不配真 LLM）。  
**保险上膛：** S6 + 首轮真跑 ingest。  
**文档闭环：** S7。

---

## 14. Phase B 预留（不实现，仅钉接口方向）

- 新增或扩展 `preference=merge`（或 auto 升级策略）。  
- 去重键：规范化 URL / 标题指纹。  
- 卡片 multi-provider badge；Brief 可标“双源互证”。  
- 仍禁止进入交易/策略自动链路。  
- Facade/响应字段在 A 已具备 `provider`，B 主要加 merge 与 UI，不推倒重来。

---

## 15. 文档与索引（实现时更新）

| 文件 | 动作 |
|---|---|
| `docs/superpowers/specs/2026-07-23-ai-news-horizon-bridge-design.md` | 本文 |
| `docs/design/ai_news_integration_plan.md` | 决策日志追加指向本文；§9 标为 Phase A 已设计 |
| `docs/guides/ai-news.md` | 双源、failover、配置、演练 |
| `docs/execution/ai-news-horizon.md` | 新建：compose、key、cron、排障 |
| `docs/INDEX.md` | 链到 spec / guide / execution |

---

## 16. 决策日志

| 日期 | 决策 |
|---|---|
| 2026-06-15 | 一期接 AI HOT；Horizon 放二期（见 ai_news_integration_plan）。 |
| 2026-06-29 | MVP-2 PG items cache。 |
| 2026-07-08 | daily_reports 表与 Brief 归档联动。 |
| 2026-07-23 | **Phase A：** 同机 Docker Horizon 产物桥 + NewsFacade 热备 failover；合同可升 B。 |
| 2026-07-23 | 动机确认：bus factor，非当前 AI HOT 不稳。 |
| 2026-07-23 | 运维：轻量自托管 B；不选完整平台内重写 C。 |
| 2026-07-23 | 先 A 后可 B；Brief 与 `/ai-news` 同 Facade。 |
| 2026-07-23 | 产物 volume 入境，**PostgreSQL 权威读**；failover 只认 PG。 |
| 2026-07-23 | `preference=auto` 默认全自动切换与切回；无需人工监控开关。 |
| 2026-07-23 | 默认宿主机 cron ingest + 容器内 loop 跑 Horizon；API 可继续宿主机 serve。 |
| 2026-07-23 | 不做请求路径 volume 直读、不做请求内 pipeline、不嵌 Horizon 源码。 |

---

## 17. 总览图

```text
目标：防 AI HOT 停服（bus factor）
手段：Docker Horizon 产粮 → inbox → Ingest → PostgreSQL
读：  NewsFacade auto = aihot live → horizon PG → aihot cache
谁用：/ai-news + Brief 同路
切：  全自动（auto），成功 200 + provider/served_from/warnings
权威：PG；volume 入境/审计
不做：内嵌 Horizon、请求内跑 pipeline、Phase A 双源合并、交易联动
```
