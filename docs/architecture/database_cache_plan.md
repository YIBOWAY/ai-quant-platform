# 数据库缓存方案

状态（2026-07-15）：本地存储分为六类能力：

1. DuckDB 富途期权报价缓存。
2. 可选 PostgreSQL run index；研究 artifact 仍以文件为事实源。
3. 可选 PostgreSQL AI HOT items/fetch cache。
4. PostgreSQL root user、不可变 brief issue/snapshot/source 和 owner-scoped
   AI daily report 业务事实。
5. paper account repository：`file`、file-authoritative `mirror`、
   PostgreSQL-authoritative `canonical` 三种显式模式，并提供结构化 reconciliation。
6. Hermes transport ledger：schema metadata、command、append-only event、outbox 与 exact
   run link；它只保存平台拥有的耐久传输事实，不保存 provider secret，也不代表 Hermes
   已接收或执行命令。

数据库功能在代码中已实现，但不能把“实现 canonical”写成“运行环境已经切到
canonical”。截至本快照，live `quantplatform` 的五份 migration 共 19 张表全部存在
（003/004 为 11 张业务表，005 为五张 Hermes transport-ledger 表）；当前 8765 以
`QS_DATABASE_AUTO_MIGRATE=true` 启动并幂等
重放 migration，health 确认数据库可达。现有账户已显式 backfill，并在 mirror/canonical 临时进程中得到
`in_sync` reconciliation。默认 8765 仍是 `file` 模式，这是一项尚未执行的运营切换，
不是代码缺失。迁移器不维护 `schema_migrations` 表，而是按词法序幂等重放 SQL。

2026-07-14 最终运行验收快照：Docker `quantplatform-db` 正在运行且可接受 SQL 查询
（容器未配置 Docker healthcheck），8765 health 报 database reachable；库内
`brief_issues=2`、`brief_snapshots=3`、
`brief_snapshot_sources=16`、`ai_news_items=240`、`ai_news_fetches=166`、
`ai_news_daily_reports=4`（latest `2026-07-14`）、`paper_accounts=1`。其中
`brf_20260714_kxsm9b` 已由真实浏览器更新为 v2，保存 payload 含 1 个账户权益点、4 个
市场、6 条 AI 新闻、8 条研究活动与 8 个独立来源水位；这些是验收时点证据，不是永久计数。

Slice 9G 本身没有新增 SQL migration 或数据库表。HQA opportunity ledger 是 HQA
仓库内的本地 JSONL 事实源；平台 `paper strategies observations` 只读取现有
file-backed strategy-sleeve 事实。9G 验收时仍是四份 migration / 14 张表；之后 D-31
Wave 3B 才独立增加 migration 005 与五张 transport-ledger 表，不能倒算为 9G 交付。

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
    因此 `/brief` 的 live server render 虽然只发 GET，仍可能外联 AI HOT，并写入这两张
    可选缓存/审计表；它不是“数据库字节完全不变”的观察操作，但不会写 brief 历史、
    paper account、审批、回测或交易事实。
  - 实时失败时尝试按 mode/category/q/since/take 读取缓存；命中则返回 `200`、
    `warnings` 中标注本地缓存和上游错误；未命中则保留原 `502/503`。
  - cursor 请求不使用缓存兜底，避免把不透明上游 cursor 伪装成本地分页。
  - `GET /api/news/aihot/daily` 实时成功后 best-effort upsert 到
    `ai_news_daily_reports`;缓存失败不影响响应。上游失败时按 requested date
    或 `Asia/Shanghai` 当天读取缓存;命中则返回 `200`,并在 `warnings` 中标注 cache 来源和上游错误。
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
`GET /api/brief/issues/latest`、`GET /api/brief/issues/{public_id}`、
`/brief/{public_id}` 前端归档页和 contract tests 已存在。生成接口只接受 factual v1
聚合 payload（paper account、equity curve、markets、AI news、research activity）与逐源
watermark；嵌套结构拒绝未知字段。paper-account watermark 必须明确 available/stale，
权威账户源不可用时前端显示 `--` 并禁用保存，后端也拒绝占位 payload。数据库关闭/
不可达时归档路径明确失败；历史页只渲染保存的 snapshot，不用当日 live 数据覆盖历史。
当前 payload 由仓库内官方 `/brief` UI 聚合，后端验证 schema、日期、locale 和来源水位，
但不会独立重抓每个上游来源；这是本地单用户可信客户端边界。若未来开放多客户端或远程写入，
应把聚合移到后端，或增加可验证的 source receipt，不能把现状表述成服务端来源证明。

## PostgreSQL Paper Account Repositories（已实现，运行切换未完成）

`scripts/sql/004_paper_account_tables.sql` 创建 paper account 的显式镜像表：

- `quant_system.paper_accounts`：账户 current metadata 与完整 account JSON raw。
- `quant_system.paper_account_ledger`：按当前 JSON ledger 整体替换的事件镜像。
- `quant_system.paper_pending_orders`：当前 pending order payload 镜像。
- `quant_system.paper_positions_current`：当前持仓、均价和 source quantity 镜像。
- `quant_system.paper_position_snapshots` 与
  `quant_system.paper_position_snapshot_rows`：每次 backfill 追加的审计快照。

`src/quant_system/execution/account_backfill.py` 暴露
`backfill_account_file(account_path, settings=..., source="account_json")`。它只读取调用方传入的
JSON 文件，使用 `PaperAccount.model_validate` 校验，再在同一事务内写入 DB。
它不是自动扫描全部 archive 的 runner。

`src/quant_system/execution/account_repository_factory.py` 是 API、CLI 和 operations 的
唯一选择入口：

- `file`（默认）：`PaperAccountStorage`，文件事实源。
- `mirror`：`DualWritePaperAccountRepository`，先写文件，再 best-effort 写 PostgreSQL。
- `canonical`：`PostgresPaperAccountRepository`，PostgreSQL 对 load/open/save/reset
  authoritative；数据库不可用时 mutation fail closed，不静默回退文件。DB 中缺账户
  时返回 `paper_account_bootstrap_required`，必须显式 backfill/reconciliation，普通 GET
  不会新建一套默认账户。

account ID 统一通过 `validate_paper_account_id` 校验，避免路径逃逸或非法 DB key；repository
key/path 与载荷内 `PaperAccount.account_id` 也必须相同。读到不匹配载荷会按损坏状态处理，
保存不匹配载荷会在任何文件/数据库写入前拒绝，不能跨账户返回或串写。

`src/quant_system/execution/account_snapshot.py` 的 `PaperAccountSnapshotReader` 是 API、CLI
和 HQA 的统一观察读模型：

```text
repository factory → repository.load → quote/provenance → reconciliation → response
```

`GET /api/paper/account/snapshot` 与
`quant-system paper account-show --account default --format json` 共用该 reader 和
`{account_id, account_exists, account}` envelope；默认 text 仍是同一命令的人工入口。
snapshot 不拿 mutation lock、不开户、不修复/重命名损坏文件，接受弱一致观察。file/mirror
缺账户返回 `account_exists=false`；canonical 缺账户返回
`paper_account_bootstrap_required`，数据库不可用返回
`paper_account_database_unavailable`，均不回退文件。主 JSON 损坏时纯读取最多使用有效
backup 并返回 warning；主备份都不可读时返回 `paper_account_storage_corrupt`。corrupt
preservation/restore 只在持锁的 `load_or_open`/save 变更路径发生。

当前估值只来自 repository 当前账户和只读 quote source；
`positions_snapshot.parquet` 与 PostgreSQL position snapshots 是保存/审计派生产物，不是
snapshot reader 的当前账户来源。行情不可用时允许以 `avg_cost_fallback` 保持结构可读，
但必须附 `paper_account_price_unavailable`，不得把成本价描述成实时价。

`PaperAccountResponse` 以 additive 字段暴露：

- `storage_mode`：请求实际配置的 `file|mirror|canonical`。
- `reconciliation`：`status`、source/target、checked time、expected/actual summary、
  typed differences。
- `stale`：reconciliation 为 `different` 或 `unavailable` 时为 true。
- `warnings`：mirror/reconciliation 不可用、repository out-of-sync、backup fallback 或
  quote unavailable 等稳定 warning code；不可读 storage 则以稳定错误失败。

reconciliation 使用摘要 hash 对比 raw account、`paper_accounts` 物化列、完整 ledger
物化字段/row raw/sequence、positions、pending orders，以及最新 position snapshot 的
cash/position state、行内算术、metadata counts 和 freshness：
snapshot source 还必须属于当前 repository/backfill 的已知 provenance 集合；任意非空
字符串不再被视为有效来源。

- file 模式：`not_applicable`，纯观察且不创建账户。
- mirror 模式：用 file account 作为 expected，对比 PostgreSQL materialized state。
- canonical 模式：对比 PostgreSQL raw account 与同库 ledger/position/pending/snapshot
  materialized tables，发现内部漂移。

持久化语义保持：ledger/current positions/pending orders 写入同一事务；ledger 按当前
完整事件流替换，current-state 表清理已不存在的行；position snapshots append-only。
结构化 reconciliation 是切换证据，不会自动把模式从 file/mirror 改成 canonical。

paper-account 迁移验证曾在 throwaway `quantplatform_codex_tmp` 跑过 13 个 PostgreSQL
tests；D-31 migration 005 另在 throwaway 库完成完整 schema-signature 与状态机测试。
live `quantplatform` 已确认五份 migration 的 19 张表存在；live 备份/auto-migrate/API
smoke 与 throwaway 破坏性 drift 测试没有混用。

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
| `paper_accounts` | 已实现；mirror/canonical 共用的 root-owned raw account 与 metadata。 |
| `paper_account_ledger` | 已实现；完整事件流 materialization 与 reconciliation 输入。 |
| `paper_pending_orders` | 已实现；当前挂单 materialization 与 reconciliation 输入。 |
| `paper_positions_current` | 已实现；当前持仓/source quantity materialization。 |
| `paper_position_snapshots` | 已实现；append-only 持仓审计快照与 freshness 证据。 |
| `paper_position_snapshot_rows` | 已实现；持仓审计快照明细。 |

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

- 数据库存储研究/只读内容和本地 paper simulation 业务事实；不存实盘状态。
- 不存储密钥、账户解锁状态、券商凭证、私钥、钱包数据或实盘下单指令。
- 不添加富途交易上下文。
- 不添加真实订单表。
- 所有由缓存支撑的产出都标注为研究数据。

## 尚未解决的问题

- PostgreSQL 仍是可选能力；paper account 默认 `file`。是否切 mirror/canonical 是
  独立运营决策，必须先完成 live migration、backfill、连续 reconciliation 和回滚验证。
- live backend 已完成 migrations 003/004、brief API 与 paper
  `storage_mode/reconciliation` smoke；仍需积累连续 reconciliation 和回滚演练，才可
  考虑把运营模式从 `file` 切到 mirror/canonical。
- 是否将期权缓存和雷达运行记录迁入 PostgreSQL 仍未确定。
- 用户本地的 Docker 镜像中是否提供 TimescaleDB 仍待确认。
- 运行索引以 JSONB 形式存储完整的运行元数据。若期权报价快照（日后迁入 PostgreSQL）
  应采用压缩 JSONB 还是完全归一化的行，仍未确定。首个 DuckDB 实现存储的是
  归一化的期权报价行。
