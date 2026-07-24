# AI News Integration MVP-1 / MVP-2 设计文档

> 状态：MVP-1 已实现；MVP-2 可选 Postgres 读穿缓存已补齐；**Horizon Bridge Phase A（热备 failover）已实现**——见 [superpowers/specs/2026-07-23-ai-news-horizon-bridge-design.md](../superpowers/specs/2026-07-23-ai-news-horizon-bridge-design.md) 与 [guides/ai-news.md](../guides/ai-news.md)。
> 日期：2026-06-15；最近更新：2026-07-23。
> 命名说明：本文的 **AI News Integration MVP-1** 指「外部 AI 新闻只读接入」的第一阶段，不属于项目历史 Phase 阶段地图，也不属于 Paper Strategy Sleeves 路线。

## 1. 背景与目标

当前平台是本地优先的量化研究、模拟交易和只读行情分析工具。它不是实盘交易平台。接入 AI 新闻的目标不是产生交易信号，也不是让新闻自动驱动策略，而是增加一个只读研究入口，让用户快速查看 AI 行业热点、日报和原文链接。

用户目前关注两个外部开源/公开项目：

- **AI HOT**：提供匿名 REST API、RSS、Skill 接入、精选流、分类、时间窗、关键词搜索和日报端点。接入成本低，但其页面明确标注 RSS / API / Skill 仍处于测试阶段，生产业务不应强依赖。
- **Horizon**：完整自托管新闻雷达，支持多源抓取、去重、AI 评分、摘要、双语日报、站点发布、邮件、Webhook、MCP 等。能力更强，但会引入模型 key、调度、数据产物、源稳定性和运行成本。

MVP-1 推荐先接 **AI HOT**，只做 `AI News Research Feed`。Horizon 保留为二期「自有多源情报流水线」方向。

## 2. 设计原则

1. **只读研究。** 新闻内容只用于阅读、检索、日报浏览和原文跳转。
2. **不触发策略。** 新闻页面不能创建、启动、暂停或改变策略、因子、回测、paper account。
3. **不生成交易建议。** 页面文案必须明确：摘要由外部/LLM 生成，引用前回原文核对，不构成投资建议。
4. **后端代理，前端不直连。** 前端只调用本地 FastAPI；外部 API base URL、超时、错误语义由后端封装。
5. **测试不打真实外网。** 后端测试必须 mock AI HOT 响应；不能依赖 `aihot.virxact.com` 当前可用。
6. **轻量接入。** MVP-1 不引入数据库、不引入常驻调度器、不拉取 Horizon 仓库、不存长期新闻归档。MVP-2 只允许使用现有可选 Postgres 作为读穿缓存，不新增调度器或自有抓取流水线。
7. **显式 beta 风险。** UI 和 API 响应保留 provider beta / upstream unstable 的提示。
8. **状态端点不探测外网。** `status` 只返回本地配置、beta/read-only 声明和进程内最近错误；不能为了显示状态主动访问 AI HOT。
9. **可测试的 HTTP 边界。** AI HOT client 必须支持注入 HTTP transport/client；单元测试通过 mock transport 构造上游响应，禁止真实 DNS/网络请求。

## 3. 当前项目匹配点

当前代码中已有类似形态可参考：

- `/options-radar` 是只读外部/本地数据页面，带筛选、刷新、状态、风险文案。
- `src/frontend/components/Sidebar.tsx` 已有 `markets` 分组，当前包含预测市场和 Agent Studio 等研究入口，适合放 `/ai-news`。
- `src/frontend/components/ui/primitives.tsx` 提供 `PageHeader`、`Card`、`StatusPill` 等统一 UI primitive。
- API 路由集中注册在 `src/quant_system/api/server.py`。
- 前端 API client 集中在 `src/frontend/lib/api.ts`。

MVP-1 应尽量复用这些模式，不新增独立前端 app，也不引入和量化核心强耦合的新框架。

## 4. AI HOT 一期范围

### 4.1 目标能力

MVP-1 只做以下能力：

- 查看精选 AI 新闻流。
- 按分类筛选。
- 按关键词搜索。
- 按时间窗筛选。
- 查看今日 AI 日报。
- 查看最近日报列表。
- 打开原文链接。
- 显示来源、发布时间、分类、score、selected 状态。
- 显示外部摘要可信度提示。

### 4.2 非目标

MVP-1 / MVP-2 不做：

- 新闻长期全量归档或自有多源抓取。
- 新闻到因子或策略的自动映射。
- 新闻情绪分数。
- 自动生成交易信号。
- 自动触发 backtest、paper account、strategy sleeve。
- 用户自定义新闻源。
- Horizon 自托管流水线。
- 邮件、Webhook、MCP 输出。
- 前端大改版。
- 实时推送或 WebSocket。
- 生产级 SLA 或本地镜像缓存。

## 5. 外部数据源

### 5.1 AI HOT

参考入口：

- Agent 接入页：`https://aihot.virxact.com/agent`
- Skill/API 说明：`https://aihot.virxact.com/aihot-skill/SKILL.md`

MVP-1 使用的上游端点：

```text
GET https://aihot.virxact.com/api/public/items
GET https://aihot.virxact.com/api/public/daily
GET https://aihot.virxact.com/api/public/dailies
```

可透传的查询能力：

```text
items:
  mode=selected | all
  category=<category>
  q=<keyword>
  since=<ISO-8601 datetime>
  cursor=<pagination cursor>

dailies:
  take=<N>
```

注意：上游仍是测试版，字段和限流可能变化。后端 parser 必须容忍未知字段和部分缺失字段。

### 5.2 Horizon

参考入口：

- GitHub：`https://github.com/Thysrael/Horizon`

Horizon 二期定位：

- 作为独立自托管任务运行。
- 由它抓取多源、去重、评分、摘要、产出日报。
- 当前项目只读取它的产物或通过 MCP/CLI 获取结果。

不建议二期直接把 Horizon 整仓库硬塞进当前后端。更稳的方式是：

1. Horizon 独立运行，当前项目读取其 Markdown/JSON 产物。
2. 或只借鉴 Horizon 的模型和调度思想，在当前项目内重写小型 news 模块。

## 6. 后端设计

### 6.1 模块边界

建议新增：

```text
src/quant_system/news/
  __init__.py
  aihot_client.py
  models.py
  repository.py

src/quant_system/api/routes/news.py
src/quant_system/api/schemas/news.py
```

职责划分：

- `news/aihot_client.py`：只负责调用 AI HOT、超时、解析、错误归一化。
- `news/models.py`：内部 provider 模型，不依赖 FastAPI。
- `news/repository.py`：可选 Postgres 读穿缓存；只缓存 AI HOT items，不是长期新闻仓库。
- `api/schemas/news.py`：API 请求/响应 schema。
- `api/routes/news.py`：FastAPI 路由、query 参数校验、把 provider 错误映射成 HTTP 错误。

实现约束：

- `AiHotClient` 构造参数必须允许注入 `httpx.Client` 或等价 fetcher；生产默认创建短超时 client，测试使用 `httpx.MockTransport`。
- parser 先把上游 payload 转成内部模型，再由 route 转成 API schema；不要把上游原始 dict 直接作为前端契约。
- `status` route 不能调用 `AiHotClient.items()` / `daily()` / `dailies()`，否则页面加载状态就会隐式打外网。
- 所有新增路由必须是 `GET`，不引入后台线程、run artifact、strategy/backtest/paper-account 调用。
- `items` 成功响应可以 best-effort 写入现有可选 Postgres 缓存；数据库关闭、慢或不可达时必须静默降级为实时代理。

不要把 AI HOT 调用写进前端，也不要写进 strategies、factors、execution、options 模块。

### 6.2 配置

建议新增环境变量：

```text
QS_AIHOT_ENABLED=true
QS_AIHOT_BASE_URL=https://aihot.virxact.com
QS_AIHOT_TIMEOUT_SECONDS=8
QS_AIHOT_CACHE_TTL_SECONDS=120
QS_AIHOT_USER_AGENT=Mozilla/5.0 ... Safari/537.36
```

说明：

- `QS_AIHOT_ENABLED=false` 时，本地 API 返回 `503`，说明功能被关闭。
- `QS_AIHOT_BASE_URL` 便于测试和未来切换 mirror。
- timeout 不宜过长，避免页面卡死。
- cache TTL 是短期 in-process cache，不是长期存档。
- 可选 Postgres 缓存复用 `QS_DATABASE_*`；`QS_DATABASE_ENABLED=false` 时不连接数据库。启用后由现有 `scripts/sql/*.sql` 迁移创建 `quant_system.ai_news_items` 和 `quant_system.ai_news_fetches`。
- AI HOT `/api/public/*` 需要浏览器式 `User-Agent`；生产默认应带安全的只读 UA，测试要断言该 header 被发送。
- 这些变量需要落到 `src/quant_system/config/settings.py` 的独立 `AiHotSettings`，并同步 `.env.example`；不要只写在文档里。
- `QS_AIHOT_BASE_URL` 需要在 client 内部去掉尾部 `/` 后再拼接路径，避免 `//api/...`。

### 6.3 API 草案

本地 API 路径：

| 方法 | 路径 | 作用 |
|---|---|---|
| `GET` | `/api/news/aihot/items` | 获取 AI HOT 新闻流 |
| `GET` | `/api/news/aihot/daily` | 获取今日或指定日期日报 |
| `GET` | `/api/news/aihot/dailies` | 获取可用日报列表 |
| `GET` | `/api/news/aihot/status` | 查看 provider 配置、beta 提示和最近错误 |

`items` query：

```text
mode=selected | all
category=<string>
q=<string>
since=<ISO-8601 datetime>
cursor=<string>
take=<int, 1..100>
```

`daily` query：

```text
date=YYYY-MM-DD optional
```

`dailies` query：

```text
take=1..180
```

### 6.4 API 响应模型

`AiHotItem`：

```text
id
title
title_en
url
source
published_at
summary
category
score
selected
raw
```

`AiHotItemsResponse`：

```text
provider = "aihot"
provider_beta = true
fetched_at
count
has_next
next_cursor
items
warnings
research_safety
```

`AiHotDailyResponse`：

```text
provider = "aihot"
provider_beta = true
date
generated_at
window_start
window_end
lead
sections
flashes
warnings
research_safety
raw
```

注意：本项目已有全局 API middleware 会注入顶层 `safety` footer，并会覆盖 route payload 中的同名字段。AI News 的研究边界字段必须命名为 `research_safety`，不能使用顶层 `safety`。

`research_safety` 建议固定包含：

```text
research_only = true
not_investment_advice = true
does_not_trigger_trading = true
verify_original_source = true
```

### 6.5 错误语义

| 情况 | 本地 HTTP | 语义 |
|---|---:|---|
| 功能关闭 | `503` | `aihot_disabled` |
| 上游超时 | `503` | `aihot_timeout` |
| 上游 4xx/5xx | `502` | `aihot_bad_gateway` |
| JSON 结构无法解析 | `502` | `aihot_invalid_response` |
| 本地 query 参数非法 | `422` | FastAPI validation |

MVP-1 使用短期 in-process TTL cache；MVP-2 增加可选 Postgres stale fallback。`items` 上游成功时返回实时结果并 best-effort 写缓存；上游失败时，如果本地 Postgres 有匹配缓存，返回 `200` 和缓存条目，并在 `warnings` 中写明上游错误和本地缓存来源；没有缓存时保留原来的 `502/503` 结构化错误。

## 7. 前端设计

### 7.1 页面与导航

新增页面：

```text
src/frontend/app/ai-news/page.tsx
```

新增组件：

```text
src/frontend/components/forms/AiNewsView.tsx
```

新增 API client：

```text
src/frontend/lib/api.ts
  getAiHotItems()
  getAiHotDaily()
  getAiHotDailies()
  getAiHotStatus()
```

Sidebar：

- 在 `markets` 分组加入 `/ai-news`。
- 图标建议使用 lucide `Newspaper` 或 `Rss`。
- 文案：英文 `AI News`，中文 `AI 新闻`。

### 7.2 页面布局

MVP-1 使用现有 dense dashboard 风格，不做营销页。

建议布局：

```text
┌─────────────────────────────────────────────────────────────┐
│ PageHeader: AI News Research Feed                           │
│ subtitle: external AI news summaries, research-only          │
├───────────────┬─────────────────────────────────────────────┤
│ Filters       │ Status strip                                │
│ - mode        │ - provider: AI HOT beta                     │
│ - category    │ - fetched_at                                │
│ - keyword     │ - research-only / verify original source    │
│ - time window ├─────────────────────────────────────────────┤
│ - daily date  │ Tabs: Feed | Daily                          │
│               │ Feed list / Daily sections                  │
└───────────────┴─────────────────────────────────────────────┘
```

主要控件：

- mode segmented control：`selected` / `all`
- category select
- keyword input
- time window select：`24h` / `3d` / `7d`
- refresh button
- tab：`Feed` / `Daily`

列表项展示：

- title / title_en
- summary
- source
- published_at
- category
- score
- selected badge
- open original link

### 7.3 安全文案

页面顶部必须明确：

```text
AI HOT is an external beta source. Summaries may be LLM-generated.
Use this page for research reading only. Verify against the original source
before citing. This page does not create trading signals, trigger strategies,
or mutate the paper account.
```

中文：

```text
AI HOT 是外部测试版数据源，摘要可能由 LLM 生成。此页仅用于研究阅读；
引用前请回原文核对。此页不会生成交易信号，不会触发策略，也不会修改模拟账户。
```

## 8. 数据流

```text
User
  -> /ai-news frontend
  -> src/frontend/lib/api.ts
  -> GET /api/news/aihot/*
  -> src/quant_system/api/routes/news.py
  -> src/quant_system/news/aihot_client.py
  -> https://aihot.virxact.com/api/public/*

Successful items fetch
  -> src/quant_system/news/repository.py
  -> optional Postgres quant_system.ai_news_items / ai_news_fetches

Upstream items failure
  -> optional Postgres cache fallback
  -> response warnings mark cached data and upstream error
```

禁止的数据流：

```text
AI News -> factors
AI News -> strategies
AI News -> backtest auto-run
AI News -> paper account
AI News -> strategy sleeves
AI News -> Futu trading
```

如果未来要做「新闻启发研究」，也只能进入 candidate/research workflow，且必须人工确认，不能直接进入执行链路。

## 9. Horizon 二期设计占位

二期名称建议：

```text
Owned News Radar / Horizon Bridge
```

二期目标：

- 自有多源新闻抓取。
- 可配置 source list。
- 本地或自托管 LLM scoring。
- 去重、主题聚类、双语日报。
- 读取 Horizon 产物或独立重写小型 pipeline。

二期非目标仍然包括：

- 不把新闻直接变成交易指令。
- 不把情绪分数自动接入策略 sleeve。
- 不做实盘交易。

二期触发条件：

- AI HOT 连续使用后确认稳定性不足，或用户需要自定义信源。
- 用户愿意承担 LLM API key、调度和存储成本。
- 当前项目已有更成熟的 research artifact 管理能力。

## 10. 实现拆分

### 10.1 串行基础层

1. **后端 schema 与 client**
   - 定义 `AiHotItem`、`AiHotItemsResponse`、`AiHotDailyResponse`。
   - 实现 `AiHotClient`，封装 base URL、timeout、query、错误映射。
   - 单元测试全部 mock 上游 HTTP。

2. **FastAPI 路由**
   - 新增 `src/quant_system/api/routes/news.py`。
   - 在 `server.py` 注册 router。
   - 只暴露 `GET` 只读端点。
   - `status` 只读本地 settings 和最近错误，不触发上游请求。

3. **前端 API client**
   - 在 `src/frontend/lib/api.ts` 加类型和函数。
   - 保持与后端 schema 对齐。

### 10.2 可并行工作

基础 API contract 稳定后，可以并行：

- **前端页面**：新增 `/ai-news` 和 `AiNewsView`。
- **Sidebar 导航**：在 markets 分组加入 AI News。
- **文档更新**：补 `docs/guides/ai-news.md`，说明外部摘要和只读边界。
- **Playwright smoke**：页面加载、筛选控件、原文链接存在。

### 10.3 验证闭环

MVP-1 / MVP-2 验收：

- 后端测试在无网络环境下通过。
- AI HOT 上游错误会返回明确 `502/503`；如果启用数据库且存在匹配缓存，则返回缓存并标注 warning。
- `/ai-news` 显示 provider beta 和 research-only 文案。
- 页面不存在任何下单、策略启动、paper account mutation 按钮。
- `tests/test_api_safety.py` 或等价安全测试仍通过。

## 11. 测试计划

后端：

```powershell
python -m pytest tests/test_api_news_aihot.py -q
python -m pytest tests/test_news_aihot_repository.py -q
python -m pytest tests/test_settings_aihot.py -q
python -m pytest tests/test_api_safety.py -q
ruff check src/quant_system tests
```

测试约束：

- `tests/test_api_news_aihot.py` 必须通过 mock client/transport 覆盖成功、关闭、超时、上游错误、无效 JSON/结构容错。
- `tests/test_news_aihot_repository.py` 必须使用 fake database / monkeypatch；默认测试不能访问真实 Postgres。
- 测试中不允许访问真实 `https://aihot.virxact.com`；可通过 monkeypatch 把 route 的 client factory 替换成 fake client，或直接用 `httpx.MockTransport`。
- `status` 测试应断言不会调用 fake 上游 client。

前端：

```powershell
npm --prefix src/frontend run lint
```

如果改动较大，再跑：

```powershell
npm --prefix src/frontend run build
```

注意：不要在前端 dev server 正在运行时执行 build。

浏览器 smoke：

```powershell
cd src/frontend
$env:PW_E2E="1"
npx playwright test --config playwright.config.ts --workers=1
```

当前仓库还没有独立的 `ai-news-smoke.spec.ts`；如果后续补专用 e2e，可以再把命令收窄到该文件。

## 12. 风险与缓解

| 风险 | 缓解 |
|---|---|
| AI HOT 测试版接口变化 | 后端 parser 容忍未知字段；错误清晰显示；不作为核心依赖 |
| 上游慢或不可用 | 短 timeout；前端重试；短 TTL cache；可选 Postgres stale fallback |
| 摘要不准确 | 强制显示回原文核对提示 |
| 用户误以为是交易信号 | 页面和 API safety 字段明确 research-only / not investment advice |
| 与策略 sleeve 混淆 | 禁止任何自动联动；文档中明确两条路线独立 |
| 依赖膨胀 | Horizon 放二期；MVP-2 只复用现有可选 Postgres，不引入调度或 LLM key |

## 13. 文档与索引

MVP-1 设计文档：

- `docs/design/ai_news_integration_plan.md`

实现后应补：

- `docs/guides/ai-news.md`
- `docs/INDEX.md`

暂时不需要 `docs/execution/ai_news.md`。只有当后续引入 CLI、调度、Horizon 本地流水线或定时抓取任务时，才需要 execution runbook。

## 14. 与 Paper Strategy Sleeves 的并行边界

这两条路线可以并行推进，但要限制文件重叠。

AI News 路线主要改：

- `src/quant_system/news/`
- `src/quant_system/api/routes/news.py`
- `src/quant_system/api/schemas/news.py`
- `src/frontend/app/ai-news/`
- `src/frontend/components/forms/AiNewsView.tsx`
- `src/frontend/components/Sidebar.tsx`
- `src/frontend/lib/api.ts`

Paper Strategy Sleeves 路线第一切片主要改：

- `src/quant_system/execution/`
- `src/quant_system/api/routes/paper.py`
- `src/quant_system/api/schemas/paper.py`
- `tests/` 中 paper/sleeve 相关测试

并行时的注意事项：

- 不要让两个 agent 同时大改 `src/frontend/lib/api.ts`。
- 不要让 AI News agent 修改 `execution`、`strategies`、`factors`。
- 不要让 Paper Strategy Sleeves agent 修改 `/ai-news` 或 news 模块。
- 如果两个路线都要改 `server.py` 注册 router，后合并的一方需要手动处理 import/router 顺序。

## 15. 推荐启动 prompt

AI News 路线：

```text
按照 docs/design/ai_news_integration_plan.md 开始实现 AI News Integration MVP-1。先做后端只读 AI HOT proxy、schema、mocked tests，再做 /ai-news 前端页面和 Sidebar 入口。测试不得打真实外网；不得触发策略、回测、paper account 或任何交易链路。
```

Paper Strategy Sleeves 路线：

```text
按照 docs/design/paper_strategy_sleeves_plan.md 开始实现 Paper Strategy Sleeves MVP-1 第一切片。只做后端领域模型/schema、本地文件存储、cash/lot 分账基础和测试；不要做前端大改，不要做自动成交，不要改变旧全账户 rebalance 行为。
```

如果要两个 agent 同时开工，建议使用两个独立 git worktree 或至少严格分配文件范围。更安全的并行组合是：

- Agent A：Paper Strategy Sleeves 后端第一切片，不碰前端。
- Agent B：AI News 后端 + 前端，只读新闻接入。

## 16. 决策日志

| 日期 | 决策 |
|---|---|
| 2026-06-15 | 一期接 AI HOT，定位为只读 AI News Research Feed。 |
| 2026-06-15 | Horizon 放二期，作为自托管多源新闻雷达或产物桥接方向。 |
| 2026-06-15 | AI News 不触发策略、因子、回测、paper account 或 strategy sleeve。 |
| 2026-06-15 | MVP-1 不写 execution 文档；只有引入 CLI/调度/Horizon 本地流水线时再写 runbook。 |
| 2026-06-29 | MVP-2 复用现有可选 Postgres 增加 AI HOT items 读穿缓存；测试仍 mock 外网和数据库。 |
| 2026-07-23 | **Horizon Bridge Phase A 已实现**：同机 Docker Horizon 产物桥 + `NewsFacade` 热备 failover（auto：aihot live → horizon PG fresh → aihot cache → unavailable）。权威设计：[superpowers/specs/2026-07-23-ai-news-horizon-bridge-design.md](../superpowers/specs/2026-07-23-ai-news-horizon-bridge-design.md)；计划：[superpowers/plans/2026-07-23-ai-news-horizon-bridge.md](../superpowers/plans/2026-07-23-ai-news-horizon-bridge.md)；runbook：[execution/ai-news-horizon.md](../execution/ai-news-horizon.md)；指南：[guides/ai-news.md](../guides/ai-news.md)。中性路由 `GET /api/news/items|daily|dailies|status`；`/api/news/aihot/*` 为兼容别名。LLM key 仅在 Horizon 容器 env_file。 |
