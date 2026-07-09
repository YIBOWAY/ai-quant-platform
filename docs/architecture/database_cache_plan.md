# 数据库缓存方案

状态：目前已实现三个本地存储层 —— (1) 基于 DuckDB 的富途 (Futu)
期权缓存，(2) 一个可选的 PostgreSQL **运行索引 (run index)**，覆盖基于文件的
回测 / 因子 / 模拟盘 / 研报复现运行记录，以及 (3) 一个可选的 PostgreSQL
**AI HOT 新闻缓存**，用于 `/ai-news` 上游失败时的只读 stale fallback。2026-07-08
新增了第 (4) 个 PostgreSQL 业务事实层：
`app_users`、每日晨报 issue/snapshot/source 表和 owner-scoped
`ai_news_daily_reports`。这些表已经具备迁移、契约测试、brief archive 读写 API
和 AI HOT daily report fallback。2026-07-09 又新增 paper account mirror
schema、显式 backfill 模块，以及 API/CLI 共用的 file-first dual-write mirror；
当前 paper account API 仍以文件为事实源。

DuckDB 期权缓存位于 `src/quant_system/storage/options_cache.py`，
在 `QS_FUTU_USE_CACHE=true`（默认值）时，会将富途期权报价窗口持久化到
`data/futu/options_cache.duckdb`。

PostgreSQL 运行索引位于 `src/quant_system/storage/database.py` 和
`src/quant_system/storage/runs_repository.py`，其 schema 定义在
`scripts/sql/001_runs_index.sql` 中。它是**可选的，且默认关闭**；启用后
会对已有的基于文件的运行记录建立索引以实现快速列举，而当数据库被禁用或不可达时，
API 会退回到扫描文件系统。

AI HOT 新闻 item 缓存位于 `src/quant_system/news/repository.py`，schema 定义在
`scripts/sql/002_ai_news_cache.sql` 中。它复用同一套 `QS_DATABASE_*` 配置；启用后
缓存 AI HOT `items` 条目和 fetch audit，不启动调度器，也不会让新闻进入策略、回测、
paper account 或交易链路。`scripts/sql/003_app_users_brief_ai_reports.sql`
还创建了 `ai_news_daily_reports` 表。Slice 3 已将 `/api/news/aihot/daily` 接入
owner-scoped 持久化与 stale fallback;live 成功时 best-effort 写缓存,上游失败时按
日期读取缓存并在 warnings 中标明来源。

## PostgreSQL 运行索引（已实现）

`data/api_runs/<kind>/<run_id>/metadata.json` 下的文件仍然是事实来源 (source of
truth)。运行索引是一个可查询的镜像，而非替代品。

- 配置项（`config/settings.py` → `DatabaseSettings`，环境变量前缀 `QS_DATABASE_`）：
  - `QS_DATABASE_ENABLED`（默认 `false`）
  - `QS_DATABASE_URL`（例如 `postgresql://quant:quantpass@127.0.0.1:5432/quantplatform`；
    作为密钥保存，并在 `/api/settings` 中被脱敏处理）
  - `QS_DATABASE_CONNECT_TIMEOUT_SECONDS`（默认 `1`）
  - `QS_DATABASE_AUTO_MIGRATE`（默认 `true`）
- Schema：单张表 `quant_system.runs`（`kind`、`run_id`、`source`、
  `created_at`、`indexed_at`、`artifact_path`、`metadata` JSONB），以
  `(kind, run_id)` 为键。`kind` 取值为 `backtest`、`factor`、`paper` 或
  `replication`。
- 启动时（`api/server.py` lifespan）在后台线程中执行迁移 / 对账：它会回填已存在的
  文件运行记录，并清除那些对应文件已不存在的索引行（自愈机制，避免列举出一个
  其详情会返回 404 的运行），同时不会阻塞 API 启动。
- 连接失败会被短暂记住。可选的连接超时上限为 1 秒；健康数据库允许并发短生命周期连接，
  失败后才进入冷却窗口。在冷却期内重复请求会使用文件系统回退，而不是在每次调用时都去等待
  PostgreSQL。
- 列举端点（`/api/backtests`、`/api/factors/runs`、`/api/paper`）以文件系统决定
  记录是否存在及显示顺序，对已匹配的记录优先复用数据库元数据；因此 API 运行期间新复制
  或新生成但尚未入索引的文件记录也会立即显示。遇到任何数据库错误时完全回退到文件系统。
  运行端点会以即发即忘 (fire-and-forget) 的方式为每个新运行建立索引（数据库故障绝不会
  阻塞运行）。
- `/api/health` 会上报一个 `database` 区块（`enabled`、`reachable`、`error`）。
- 测试通过 `tests/conftest.py` 强制设置 `QS_DATABASE_ENABLED=false`，使整套测试
  永远不会写入共享容器。

直接使用 `psycopg`（无 ORM，无连接池 —— 采用每次操作单独建立的短生命周期
连接，与 DuckDB 缓存的风格一致）。

## PostgreSQL AI HOT 新闻缓存（已实现）

AI News 的事实来源仍是 AI HOT public API。PostgreSQL 只作为本地只读缓存，用于实时
请求成功后的镜像和上游失败时的兜底。

- 配置项：复用 `QS_DATABASE_ENABLED`、`QS_DATABASE_URL`、
  `QS_DATABASE_CONNECT_TIMEOUT_SECONDS` 和 `QS_DATABASE_AUTO_MIGRATE`。
- 业务配置仍在 `AiHotSettings`：
  `QS_AIHOT_ENABLED`、`QS_AIHOT_BASE_URL`、`QS_AIHOT_TIMEOUT_SECONDS`、
  `QS_AIHOT_CACHE_TTL_SECONDS`、`QS_AIHOT_USER_AGENT`。
- Schema：
  - `quant_system.ai_news_items`：`provider`、`item_id`、`title`、`title_en`、
    `url`、`source`、`published_at`、`summary`、`category`、`score`、`selected`、
    `raw`、`fetched_at`、`updated_at`，主键为 `(provider, item_id)`。
  - `quant_system.ai_news_fetches`：每次成功 fetch 的 provider、mode、category、
    search query、since、cursor、take、item count 和 warnings。
  - `quant_system.ai_news_daily_reports`：由
    `scripts/sql/003_app_users_brief_ai_reports.sql` 创建的 owner-scoped 日报缓存表,
    主键为 `(owner_user_id, provider, report_date)`。`/api/news/aihot/daily`
    成功响应会 best-effort upsert,上游失败时可按日期读取 stale fallback。
- API 行为：
  - `GET /api/news/aihot/items` 先调用 AI HOT 实时接口。
  - 实时成功后 best-effort upsert 到 `ai_news_items`，缓存失败不影响响应。
  - 实时失败时尝试按 mode/category/q/since/take 读取缓存；命中则返回 `200`、
    `warnings` 中标注本地缓存和上游错误；未命中则保留原 `502/503`。
  - cursor 请求不使用缓存兜底，避免把不透明上游 cursor 伪装成本地分页。
  - `GET /api/news/aihot/daily` 实时成功后 best-effort upsert 到
    `ai_news_daily_reports`;缓存失败不影响响应。上游失败时按 requested date
    或 UTC 当天读取缓存;命中则返回 `200`,并在 `warnings` 中标注 cache 来源和上游错误。
- 测试要求：默认测试不得连接真实 AI HOT 或真实 Postgres；API 测试 monkeypatch
  provider/repository，repository 测试使用 fake database。

## PostgreSQL Brief / Daily Report 业务事实（brief archive MVP 已实现）

每日晨报归档需要不可变 URL 和可回看 payload，因此它不能只依赖当天聚合 API 的现场结果。
`scripts/sql/003_app_users_brief_ai_reports.sql` 已经创建以下表：

- `quant_system.app_users`：固定 seed 本地 root 用户
  `00000000-0000-0000-0000-000000000001`，后续新业务表统一挂
  `owner_user_id`。
- `quant_system.brief_issues`：每日晨报 issue 元数据，包含 `public_id`、
  `issue_date`、`locale`、`latest_snapshot_id` 和可选 `share_token_hash`。
- `quant_system.brief_snapshots`：append-only 快照版本，存放 JSONB payload、
  rendered text 和 source watermark。
- `quant_system.brief_snapshot_sources`：快照来源引用和来源 payload，用于审计。
- `quant_system.ai_news_daily_reports`：AI HOT daily report 的 owner-scoped 本地缓存。

约束要点：

- root 用户 UUID 固定；如果已有 `root` username 指向不同 UUID，migration 会显式失败，
  避免静默污染 owner 关系。
- `brief_issues.latest_snapshot_id` 是 `(issue_id, latest_snapshot_id)` 复合外键，
  只能指向同一 issue 下的 snapshot。
- `ai_news_daily_reports` 可从旧版 `(provider, report_date)` primary key 原地升级为
  `(owner_user_id, provider, report_date)`，并保留已有日报行。
- 这些表是可查询业务事实，不承载研究 artifact、大体量行情宽表、DuckDB option cache
  或实盘交易状态。

当前实现边界：schema、brief repository、`POST /api/brief/issues/generate`、
`GET /api/brief/issues/{public_id}`、`/brief/{public_id}` 前端归档页和 contract
tests 已存在。`/api/brief/live`、`/api/brief/issues/latest`、`/brief` 生成入口、
paper account DB canonical 仍按
`docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md`
的 Slice 6 / Slice 7 推进。

## PostgreSQL Paper Account Mirror（schema/backfill/dual-write 已实现）

`scripts/sql/004_paper_account_tables.sql` 创建 paper account 的显式镜像表：

- `quant_system.paper_accounts`：账户 current metadata 与完整 account JSON raw。
- `quant_system.paper_account_ledger`：按当前 JSON ledger 整体替换的事件镜像。
- `quant_system.paper_pending_orders`：当前 pending order payload 镜像。
- `quant_system.paper_positions_current`：当前持仓、均价和 source quantity 镜像。
- `quant_system.paper_position_snapshots` 与
  `quant_system.paper_position_snapshot_rows`：每次 backfill 追加的审计快照。

`src/quant_system/execution/account_backfill.py` 暴露
`backfill_account_file(account_path, settings=..., source="account_json")`。它只读取调用方传入的
JSON 文件,使用 `PaperAccount.model_validate` 校验,然后在同一事务内写入 DB mirror。
`src/quant_system/execution/account_repository_factory.py` 负责 API route 与 CLI/调度共用的
repository 选择:`file` 为默认,`mirror` 使用 file-first `DualWritePaperAccountRepository`,
`canonical` 在 Slice 5 暂回落文件并记录 warning。

当前语义：

- 文件 JSON 仍是事实源；Postgres 只是 mirror。
- API 与 CLI paper-account mutation 在 `QS_PAPER_ACCOUNT_DB_MODE=mirror` 时先写文件,
  再 best-effort 写 PostgreSQL；DB 失败只写 warning log,不改变 API response contract。
- `paper_account_ledger` 每次按当前 JSON ledger 整体替换,避免 reset 或手工修正后残留旧
  entry 或 sequence 冲突。
- pending orders 与 current positions 是 current-state mirror,会清理 JSON 中已不存在的行。
- position snapshots 是 append-only audit points,重复 backfill 或在线 mirror 会新增 snapshot;
  在线 mirror 使用当次 quote 估值,显式 backfill 默认使用账户 avg cost。
- Slice 6 才会启用 DB canonical authoritative read/reset 和 mutation fail-closed。

## 为何需要它

交互式富途期权页面使用一个短生命周期的进程内缓存、一次针对限频响应的重试，
现在还增加了一个本地 DuckDB 缓存用于存储成功的期权报价窗口。DuckDB 缓存可在
后端重启之间持久保留，并由期权筛选器 (Options Screener)、期权雷达 (Options Radar)、
买方期权助手 (Buy-Side Options Assistant) 以及调用富途数据源的本地期权工具共享。

缓存层的存在使平台能够：

- 复用近期获取的期权链和快照。
- 减少对富途 OpenD 的重复请求。
- 让期权筛选器、期权雷达和买方期权助手在相同标的与时间戳下保持一致。
- 以可查询的格式存储扫描结果，供前端使用。
- 保持只读的安全边界。

## 推荐的存储划分

采用混合式本地存储模型：

| 存储 | 最适合的场景 |
|---|---|
| PostgreSQL | 元数据、期权链缓存索引、期权报价快照、雷达运行记录、API 任务记录、数据源请求日志。 |
| Parquet / DuckDB | 大规模 OHLCV 历史数据、回放数据集、宽分析表、批量研究。 |
| JSONL | 可移植的测试夹具 (fixtures) 以及小型的仅追加 (append-only) 研究产物。 |

PostgreSQL 很适合用户本地的 Docker 配置，尤其适用于查询最新的期权链快照以及
为前端视图提供数据。但它不应在所有大型历史研究数据集场景下替代 Parquet / DuckDB。

首个交付的缓存使用 DuckDB，以避免本地用户必须依赖 Docker 或数据库服务器。

## 拟定的表

最小化的首个版本：

| 表 | 用途 |
|---|---|
| `provider_requests` | 每次数据源调用一行，包含数据源、标的代码、端点类型、状态、错误码及获取时间。 |
| `equity_bars` | 可选的、用于前端小窗口的缓存 OHLCV 行。 |
| `option_chain_snapshots` | 快照元数据：标的、到期范围、期权类型、数据源、获取时间、缓存过期时间。 |
| `option_contract_quotes` | 与某个期权链快照关联的归一化期权行。 |
| `vix_history` | 若日后从 CSV 迁出，则存放 VIX/VIX3M 缓存行。 |
| `options_radar_runs` | 每日雷达运行的元数据。 |
| `options_radar_candidates` | 供 API 和前端过滤使用的雷达候选行。 |
| `ai_news_items` | 已实现；AI HOT `items` 的只读缓存行。 |
| `ai_news_fetches` | 已实现；AI HOT `items` 成功 fetch 的审计记录。 |
| `app_users` | 已实现 schema；本地 root 用户与后续 owner-scoped 业务事实的所有者。 |
| `brief_issues` | 已实现 schema；每日晨报 issue 元数据和不可变 public id。 |
| `brief_snapshots` | 已实现 schema；每日晨报 append-only payload 快照。 |
| `brief_snapshot_sources` | 已实现 schema；晨报快照来源审计。 |
| `ai_news_daily_reports` | 已实现；AI HOT daily report owner-scoped cache 与 `/api/news/aihot/daily` stale fallback。 |
| `paper_accounts` | 已实现 schema/backfill/dual-write；file-backed paper account 的 root-owned mirror。 |
| `paper_account_ledger` | 已实现 schema/backfill/dual-write；按 JSON ledger 整体替换的事件镜像。 |
| `paper_pending_orders` | 已实现 schema/backfill/dual-write；当前 pending order payload mirror。 |
| `paper_positions_current` | 已实现 schema/backfill/dual-write；当前持仓和 source quantity mirror。 |
| `paper_position_snapshots` | 已实现 schema/backfill/dual-write；每次 mirror 追加的持仓审计快照。 |
| `paper_position_snapshot_rows` | 已实现 schema/backfill/dual-write；持仓审计快照明细。 |

在首个 DuckDB 实现中已落地：

- `option_chain_snapshots`
- `option_contract_quotes`

## 缓存策略

建议的安全默认值：

- 股票日线：近期范围在 24 小时后过期；在测试内部绝不自动刷新。
- 期权链：盘中 15 分钟后过期，盘外时间更长。
- 期权快照：盘中 5 分钟后过期。
- 雷达运行：按 `run_date` 不可变，除非用户显式重新运行扫描。
- 数据源错误：存储类型化的错误码，以帮助诊断 OpenD 与限频问题。

所有缓存条目都必须记录：

- `provider`
- `ticker`
- 请求的日期或到期窗口
- `fetched_at`
- `expires_at`
- 归一化的来源标签
- 若请求失败则记录错误码

## API 行为

依赖数据源的端点应遵循以下顺序：

1. 若存在新鲜缓存则直接返回。
2. 若缓存陈旧或缺失，且显式请求了数据源，则从只读数据源获取。
3. 将成功归一化后的数据写入缓存。
4. 返回类型化的数据源错误，不暴露原始堆栈跟踪 (traceback)。

任何端点都不应加入下单或券商执行功能。

## 建议的实现阶段

1. 为可选的 PostgreSQL 支持模式添加数据库配置项。（已实现为
   `QS_DATABASE_ENABLED`、`QS_DATABASE_URL`、`QS_DATABASE_CONNECT_TIMEOUT_SECONDS`、
   `QS_DATABASE_AUTO_MIGRATE`；schema 名称 `quant_system` 在 SQL 中固定，不作为配置项）
2. 添加一个小型存储包：（已实现）
   - `src/quant_system/storage/database.py`（PostgreSQL 连接 + 迁移）
   - `src/quant_system/storage/runs_repository.py`（文件为准，数据库元数据镜像 + 回退）
   - `src/quant_system/storage/options_cache.py`（DuckDB 期权缓存）
3. 在 `scripts/sql/` 下添加纯 SQL 迁移。（已实现：
   `scripts/sql/001_runs_index.sql`、`scripts/sql/002_ai_news_cache.sql`、
   `scripts/sql/003_app_users_brief_ai_reports.sql`、
   `scripts/sql/004_paper_account_tables.sql`）
4. 优先缓存富途期权链和快照结果。（已为期权报价窗口实现）
5. 将期权筛选器和买方期权助手接入缓存优先的路径。
   （已通过共享的富途数据源实现）
6. 将期权雷达的 JSONL 读取置于一个存储门面 (storage facade) 之后，同时保留
   JSONL 导出以保证可移植性。
7. 添加前端可见的缓存元数据：来源、获取时间和缓存时长。

## 依赖建议

推荐的最小依赖：

- `psycopg[binary]`，用于访问 PostgreSQL。

在首轮实现中避免引入 SQLAlchemy 或 Alembic，除非项目开始需要复杂的 schema
迁移。对于首个本地缓存模块，纯 SQL 已经足够。

## 安全规则

- 数据库仅存储市场数据和研究产出。
- 不存储密钥、账户解锁状态、券商凭证、私钥、钱包数据或实盘下单指令。
- 不添加富途交易上下文。
- 不添加真实订单表。
- 所有由缓存支撑的产出都标注为研究数据。

## 尚未解决的问题

- PostgreSQL 现在是可选的且默认关闭；仅当 `QS_DATABASE_ENABLED=true` 时，运行索引
  和 AI HOT 新闻缓存才指向本地 Docker 容器 `quantplatform-db`。是否同时将期权缓存和雷达运行记录
  迁入 PostgreSQL 仍未确定。
- 用户本地的 Docker 镜像中是否提供 TimescaleDB 仍待确认。
- 运行索引以 JSONB 形式存储完整的运行元数据。若期权报价快照（日后迁入 PostgreSQL）
  应采用压缩 JSONB 还是完全归一化的行，仍未确定。首个 DuckDB 实现存储的是
  归一化的期权报价行。
