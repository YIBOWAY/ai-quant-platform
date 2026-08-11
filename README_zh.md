# AI 辅助量化研究平台

本地优先的量化研究、回测、模拟交易、只读行情与期权研究平台。

历史 Phase、Wave 和 Workbench 文档是交付证据，不是当前实现或运维队列。先读
[docs/INDEX.md](docs/INDEX.md)。跨仓产品路线仍由
`/Users/sunyibo/programs/Hermes-quant-agent` 管理；本仓库是量化领域后端，不再
独立扩张 Phase 15。

Agent v0.2 已有受门禁控制的本地单用户 managed-session 写入、durable connector、
transcript/follow、approval/stop/result 与 candidate/release authority。历史和外部
会话在 Web 中保持只读；继续上下文必须显式 fork 到新的 managed Session。本地
`chat_write_ready` 不等于 public 授权；standing
`public_chat_write_ready`、`public_write_authorized` 与
`release_authorized` 继续 OFF。

当前 D-34 source worktree 包含有序 migration source 016–032；030–032 已通过隔离
PostgreSQL 验收，但未获授权 apply 到正式 `quantplatform`。默认
`QS_D34_WORKER_ENABLED=false`，因此 source 测试通过不等于 runtime 已部署或常驻。
migration、readiness、restart、E2E 与 restore 的唯一权威是
[Agent v0.2 local-stack runbook](docs/runbooks/agent-v0-2-local-stack.md)。

D-34 用 30 天 Mandate 驱动 Futu Parquet → RD-Agent/Qlib → Platform 独立执行重放 →
确定性 Policy → `paper_only` Artifact → 低额度 paper canary。它没有 live 升级接口，
不自动 push GitHub，也不自动 apply migration。参见
[架构](docs/architecture/d34-autonomous-paper.md)、
[owner 使用指南](docs/guides/d34-workbench.md)和
[本机运维手册](docs/runbooks/d34-autonomous-paper.md)。

- 美股及 ETF 历史数据流水线。
- 因子研究、因子实验室诊断（2026-06-11 起真实数据优先：默认 `futu`，数据源/股票池/择时标的/基准可在界面调整，可保存因子研究运行，并可预填发送至回测器）、策略/股票池注册、回测、实验和模拟交易。
- 本地 FastAPI 后端 + Next.js 前端。
- AI 研究助手，带候选池和人工审核门禁。
- 只读 Polymarket 预测市场研究、快照、回放和报告。
- 富途 OpenD 只读美股及期权数据。
- 期权收入筛选器（Options Income Screener）、期权雷达（Options Radar）、买方期权助手（Buy-Side Options Assistant）。
- 本地 AlphaGBM 风格期权工具箱及本地富途期权报价缓存。
- AI HOT 只读新闻研究流，支持精选/全部动态、分类/关键词/时间窗筛选、日报和原文链接。
- 策略目录：包含 reversal/momentum 论文复现、已注册的横截面 Top-N 回测策略、均值回归 Top-N 策略。
- reversal/momentum 复现运行会以 `replication-*` 形式本地持久化，并提供专门详情页。
- 回测引擎控制项：再平衡频率（每根 K 线 / 每周 / 每月）、单标的权重上限、提供行业映射时的 API 层面行业上限、以及按标的的收益归因。
- 可选 PostgreSQL 运行/新闻缓存，以及 brief、AI 日报和 paper account 业务事实；
  paper account 明确区分 `file` / `mirror` / `canonical` 三种模式。

本项目**不包含**实盘交易、券商下单、钱包连接、签名、富途账户解锁或真实订单提交。

## 快速开始

创建并激活 uv 管理的 `ai-quant` 虚拟环境，然后安装 Python 依赖：

```powershell
uv venv ai-quant --python 3.11
.\ai-quant\Scripts\Activate.ps1
uv pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[api,dev,prediction_market]"
```

安装前端依赖：

```powershell
cd src/frontend
npm install
```

启动后端：

```powershell
.\ai-quant\Scripts\Activate.ps1
quant-system serve --host 127.0.0.1 --port 8765
```

CLI 后端入口会把结构化 JSONL 运行日志写入
`data/_runtime/logs/backend.jsonl`，同时保留控制台输出。

等效的直接 FastAPI 命令：

```powershell
.\ai-quant\Scripts\Activate.ps1
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

直接 app factory 启动路径也会写入同一个 `backend.jsonl` 运行日志。

在另一个 PowerShell 窗口中启动前端：

```powershell
cd src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

打开浏览器访问：

```text
http://127.0.0.1:3001
```

健康检查：

```powershell
curl http://127.0.0.1:8765/api/health
```

离线本地健康摘要：

```powershell
quant-system doctor
```

`doctor` 不会连接行情源或 PostgreSQL；它只打印当前环境、安全开关、默认数据源、
Futu/OpenD 端点、可选数据库索引设置和运行日志路径。

### Agent v0.2 本地运维边界

不要从本 README 执行 Agent v0.2 migration 或 release。唯一完整流程在
[local-stack runbook](docs/runbooks/agent-v0-2-local-stack.md)，由它单独定义
精确顺序、验收证据和 restore 边界。

Migration 028 增加 current-paper-epoch fence，并要求 root owner 恰好一个 canonical
paper account：ID 为 `default`，materialized `kill_switch=true`，raw JSON 的
`account_id` 与 JSON boolean `kill_switch` 和物化列完全一致。新 runtime 安装后，
`GET /api/safety/effective` 只做 provider-free 观察，不授权 chat 或 release。

私有准入由操作者通过 `quant-system hermes candidate status|open|revoke` 控制。
HQA Keychain `probe` 不创建 key；普通 encrypt/put/bind 与 connector check 也不得
创建。只有人在核对 exact committed/installed runtime 后，才能单独执行
`initialize-key`，随后再次 `probe`。

## 主要页面

| 页面 | 用途 |
|---|---|
| `/hermes` | 可回滚 COO 工作台，展示 Today、managed-session 对话、任务、审批、Unified Results 预览，以及 D-34 source 的 Mandate/job/Artifact/paper canary 操作面。Composer 只在 exact local candidate/release window 且全部本地门禁通过时打开；public standing 继续 OFF。 |
| `/hermes/sessions` | 服务端 official API adapter GET-only 读取本机 Hermes 已保存会话；key 不下发浏览器，也不消耗 provider 额度。历史/外部 transcript 保持只读，继续上下文需显式 fork 到新 managed Session。 |
| `/hermes/results` | 汇总平台运行、实验、候选、HQA 产物及 exact run-link 的只读目录/详情；预览可见但 `unifiedResultsCutoverAccepted=false`。 |
| `/data-explorer` | 美股历史数据查看器。 |
| `/factor-lab` | 当前因子诊断面；HQA 工作台落地后应降级为 run/detail 分析面。 |
| `/backtest` | 运行策略、股票池、因子加权及基准回测。 |
| `/strategies` | 已注册研究策略的策略目录。 |
| `/strategies/[runId]` | 已落盘的 reversal/momentum 复现运行详情。 |
| `/docs/reversal-momentum` | 论文复现的前端可读笔记。 |
| `/experiments` | 运行可选数据源的实验扫描，可显式开启滚动验证折，查看被测试的固定因子组合，并将最佳参数和同一数据源发送至回测。 |
| `/paper-trading` | 持久模拟账户（手动下单 + 策略一键再平衡）＋历史回放（研究）。 |
| `/position-map` | 模拟账户实时持仓地图（净值/现金/暴露/来源归因），另含回测暴露对比块。 |
| `/options-screener` | 单标的卖方期权筛选器。 |
| `/options-radar` | 每日卖方期权雷达快照。 |
| `/options-radar/[symbol]` | 单标的雷达下钻与实时期权链加载。 |
| `/options-tools` | 本地 AlphaGBM 风格期权工具箱。 |
| `/options-buyside` | 买方期权策略助手。 |
| `/ai-news` | AI HOT 只读新闻研究流，含精选/全部动态、分类/关键词/时间窗筛选、日报和原文链接，不触发策略、回测或模拟账户。 |
| `/polymarket` | 只读预测市场研究页面。 |
| `/agent-studio` | 过渡期只读候选检查面；仅展示源码与 exact digest-bound review，不提供 task/审批 mutation。页面级 redirect gate 存在但默认关闭。 |
| `/settings` | 脱敏后的本地设置。 |

股票数据端点只接受显式 `provider=sample|futu|tiingo`。未知 provider，
或显式请求但不可用的真实 provider，会返回 `400 provider_unavailable`，
不会静默替换为 sample 数据。未传 provider 时，只读行情页面仍可在离线场景下
回退到明确标注的 sample 响应。
代码默认值和 `.env.example` 均使用 `QS_DEFAULT_DATA_PROVIDER="futu"`；只有在
明确做离线流程测试时才改为 `sample`。

## 异步回测任务

`POST /api/backtests/run` 默认保持历史同步 `200 BacktestRunResponse` 路径。
设置 `QS_BACKTEST_JOBS_ENABLED=true` 后，它会立即返回
`202 BacktestJobStateResponse`，其中 `poll_url` 指向
`GET /api/backtests/jobs/{run_id}`，任务完成后才暴露 `result_url`。
`POST /api/backtests/jobs/{run_id}/cancel` 可取消排队任务，并在回测流水线阶段之间
协作取消运行中的任务。

本地 runner 是进程内 `ThreadPoolExecutor`，默认
`QS_BACKTEST_JOBS_MAX_WORKERS=1`。API 关闭时最多等待
`QS_BACKTEST_JOBS_SHUTDOWN_TIMEOUT_SECONDS=5`；超过该时间仍未停止的任务会被标记为
cancelled。启动时，遗留的 queued / running / cancelling metadata 会被标记为 failed，
因为本地 runner 不是可恢复的分布式队列。

界面支持中英双语。使用顶栏语言切换按钮，或直接访问带语言前缀的路径，如
`/en/options-radar` 和 `/zh/options-radar`。语言选择也会存储在 `qs_lang` cookie
中，用于无前缀路径。详见
[docs/frontend/frontend_chinese_version.md](docs/frontend/frontend_chinese_version.md)。

## 富途只读数据

富途 OpenD 仅用于美股及期权行情数据的获取。

前置条件：

1. OpenD 本地运行且已登录。
2. `ai-quant` 环境中已安装 `futu-api`。
3. 平台仅使用行情 / 数据路径，不使用交易路径。

验证连接：

```powershell
.\ai-quant\Scripts\Activate.ps1
python scripts/verify_futu_connection.py
```

供机器消费的严格多标的 QFQ 日线命令：

```powershell
quant-system data prices --symbol AAPL --symbol SPY --start 2026-01-01 --end 2026-07-10 --provider futu --adjustment qfq --format json
```

该 leaf 的 stdout 恰好只有一个 JSON 文档，不读取 local/sample fallback，不保存 OHLCV，
也不会仅因 provider 构造就初始化期权 DuckDB。日期必须为 `YYYY-MM-DD`，窗口最多包含
首尾在内 500 个日期；配置、请求、OpenD 首连或查询失败均以 typed JSON + 非零 exit
返回。`QS_FUTU_REQUEST_TIMEOUT_SECONDS` 同时约束首连和查询 deadline。

**重要约束**：

- 不使用富途交易上下文（TradeContext）。
- 不进行账户解锁。
- 不进行下单。
- 不进行券商执行。

## 只读 Hermes 产物架

`GET /api/hermes/artifacts?limit=20` 只读 HQA 可重建、版本化的
`artifacts/hermes-feed/manifest.v1.json`。schema 1.0 精确包含三种来源
（`portfolio_risk`、`prediction`、`market_foresight`）；schema 1.1 精确包含六种，
再加入 `weekly_review`、`opportunity_summary` 与 `automation_status`。`/hermes`
会展示全部六类产物。平台不解析 HQA 原始 JSONL、不写 HQA 状态，也不会启用
Composer 或调用 `POST /api/agent/tasks`。

catalog 会稳定返回 `available`、`empty`、`degraded` 或 `unavailable`，校验 manifest
并限制文件大小，不向 API 暴露本地路径或原始异常。配置项为：

```text
QS_HERMES_ARTIFACT_FEED_PATH=/absolute/path/to/manifest.v1.json
QS_HERMES_ARTIFACT_FRESHNESS_BUDGET_SECONDS=10800
QS_HERMES_ARTIFACT_MAX_FUTURE_CLOCK_SKEW_SECONDS=300
QS_HERMES_ARTIFACT_MAX_MANIFEST_BYTES=4194304
```

默认路径指向同级 `Hermes-quant-agent` 仓库。某一来源可以合法地为 `empty`，
其他来源卡片仍可保持健康。完整 9H 的调度与外发投递运行在 HQA；平台仍只是只读
消费者，没有新增 Hermes scheduler、outbound worker、POST route 或数据库 migration。

交互式期权页面包含短期进程内缓存、本地 DuckDB 支持的富途期权报价缓存，以及针对富途限频响应的单次重试。宽泛的每日扫描仍应计划执行，并在富途限速下预计运行较慢。

## 可选 PostgreSQL 业务事实

回测、因子、paper-run 和 reversal/momentum 复现 artifact 仍保存在
`data/api_runs/<kind>/<run_id>/`；PostgreSQL 只索引这些运行记录。同一个可选数据库
还保存 AI HOT 缓存、不可变 brief 快照、owner-scoped AI 日报和持久 paper account
的模拟账本/当前状态，不保存券商凭证或真实订单。`QS_DATABASE_ENABLED` 默认
`false`，paper mode 默认 `file`。

paper account 有三种显式模式：

- `file`（默认）：本地 `account.json` 是事实源。
- `mirror`：文件仍是事实源，API/CLI/operations 写文件后 best-effort 镜像到
  PostgreSQL；数据库失败不回滚文件写入，但会返回 warning。
- `canonical`：PostgreSQL 是 load/open/save/reset 的事实源；数据库不可用时
  mutation fail closed，factory 不会静默切回文件模式；如果 canonical 中没有账户，
  普通 GET/写请求返回 `409 paper_account_bootstrap_required`，不会在空库新建替代账户。

所有 paper account 入口共用 repository factory。account ID 会统一校验，repository key
也必须与载荷 account ID 一致。API snapshot 与
`quant-system paper account-show --format text|json` 共用
`PaperAccountSnapshotReader`：file/mirror 缺账户时不会创建目录、锁文件或账户，canonical
则返回显式 bootstrap error；主文件损坏时只读路径最多读取有效备份，不会重命名或修复
磁盘文件。
API 额外返回 `storage_mode`、`stale`、`warnings` 和结构化 `reconciliation`：
它通过摘要 hash 对账 raw、账户物化列、完整 ledger、positions、pending orders 和
最新 snapshot 的状态/内部一致性/freshness，
状态为 `in_sync` / `different` / `unavailable` / `not_applicable`。

通过本地 Docker 容器启用：

```powershell
# 容器名为 quantplatform-db，数据库=quantplatform，用户=quant，密码=quantpass
docker start quantplatform-db
```

```text
# .env
QS_DATABASE_ENABLED=true
QS_DATABASE_URL="postgresql://quant:quantpass@127.0.0.1:5432/quantplatform"
QS_DATABASE_CONNECT_TIMEOUT_SECONDS=1
QS_DATABASE_AUTO_MIGRATE=false
QS_PAPER_ACCOUNT_DB_MODE="file"  # file | mirror | canonical
```

这是通用 file-mode 开发示例。Agent v0.2 private candidate stack 必须使用
`canonical`；只按 local-stack runbook 判定，不从这个示例推断 live mode。

后端启动从不应用 migration；`QS_DATABASE_AUTO_MIGRATE` 必须为 false。默认
`quant-system migrate` 只做 dry-run，真正 apply 必须使用
`--apply --allow <exact-file>`，非交互场景还要 `--yes`，并取得本次明确授权。

Migration 是有序、幂等 SQL，不使用通用 `schema_migrations` 台账。001–015 建立
run/news/business facts、Hermes ledger/workflow/session、安全与 provisioning 基线；
Agent v0.2 的 016–028 是一个 additive ladder，覆盖 private candidate、vertical/paper
authority、sealed evidence/release hardening、run/fork/control lineage、
release/session binding、research claim lineage、candidate TTL 与 current paper-epoch
fence。source 文件、isolated replay 或 backup 都不证明 live apply；只按 local-stack
runbook 执行和判定。

Migration apply 会在整个文件批次持有独占 schema-runtime gate；candidate open
则在同一事务中先拿匹配的共享 gate，再用同一连接读取 schema 指纹，之后才允许写入
authority，从而避免 migration 与 candidate 的检查后写入竞态。

启动流程仍会回填运行索引，并清理对应文件已删除的索引行。如果 PostgreSQL 不可用，
首次探测很短，后续失败请求在短暂的冷却窗口内继续从本地文件或实时上游读取；健康的 PostgreSQL
短连接可以并发执行。可通过以下命令检查：

```powershell
curl http://127.0.0.1:8765/api/health   # database.reachable 应为 true
```

`psycopg` 驱动随 `api` extra 一起安装；连接 URL 在 `/api/settings` 中已脱敏。
brief archive 的 generate/latest/by-public-id 路径只读取已落库快照，数据库不可用时
明确失败，不伪造历史。详见
[docs/architecture/database_cache_plan.md](docs/architecture/database_cache_plan.md)。

## AI 新闻研究流

`/ai-news` 是 AI HOT 公共端点的本地 FastAPI 代理。前端只调用
`/api/news/aihot/*`；后端负责发送 AI HOT API 所需的浏览器式 User-Agent、解析响应、
归一化错误，并保留 research-only 安全字段。

可选配置：

```text
QS_AIHOT_ENABLED=true
QS_AIHOT_BASE_URL="https://aihot.virxact.com"
QS_AIHOT_TIMEOUT_SECONDS=8
QS_AIHOT_CACHE_TTL_SECONDS=120
QS_AIHOT_USER_AGENT="Mozilla/5.0 ..."
```

当 `QS_DATABASE_ENABLED=true` 时，成功的新闻流请求会镜像到
`quant_system.ai_news_items`。如果 AI HOT 暂时不可用，items 端点可以返回匹配缓存并显示 warning。
该页面不会生成交易信号、启动回测、修改模拟账户或调用任何券商交易 API。详见
[docs/guides/ai-news.md](docs/guides/ai-news.md) 与
[docs/design/ai_news_integration_plan.md](docs/design/ai_news_integration_plan.md)。

## 模拟账户

一个持续存在、初始 100 万美元的模拟账户：你可以手动买卖，也可以让策略一键再平衡，
两者都汇入同一账户并实时反映到持仓地图。它**仅为模拟**——绝不触及真实下单、券商、钱包或账户解锁。

- 手动下单：`POST /api/paper/account/orders`（买/卖、按数量或金额、可选限价）。
  成交价优先使用 Futu 实时快照，OpenD 离线时只回退到本地缓存或 Tiingo
  的真实最近收盘价；未触及价格的限价单会保存在账户 `pending_orders`
  队列中，并可通过 `POST /api/paper/account/orders/process` 重新检查；
  也可通过 `POST /api/paper/account/orders/{order_id}/cancel` 取消；
  `/paper-trading` 页面会显示挂单列表、检查按钮和逐单取消按钮。待处理买入
  限价单会按 `数量 × 限价` 预留现金，待处理卖出限价单会预留可卖数量；
  账户响应同时暴露 `cash` 与 `available_cash`。API 后台 worker 默认每 30 秒
  检查已存在账户的待处理限价单，可通过
  `QS_PAPER_ACCOUNT_AUTO_PROCESS_PENDING_ORDERS_ENABLED` /
  `QS_PAPER_ACCOUNT_AUTO_PROCESS_INTERVAL_SECONDS` 控制；若当前纸面价格仍未触价，
  处理流程还会回看上次检查/创建之后、当前检查日之前完整自然日的真实 daily OHLCV
  高低价区间，命中则按原限价成交。该回看不使用 sample 数据，也不推断下单当天的日内先后顺序。
  持续账户绝不会使用 sample / 演示价格成交。
- 策略再平衡：`POST /api/paper/account/rebalance`（一键；任一腿无法成交则整体原子中止）。
  策略下拉由后端策略注册表的 `supports_account_rebalance` 字段驱动；当前账户路径支持
  `cross_sectional_top_n` 与 `mean_reversion_top_n`。它只接受真实市场历史；
  sample 演示历史不会改变持续账户。构建再平衡计划前，当前持仓和目标标的都必须有
  有限且大于 0 的纸面价格；缺价或无效价格会整体中止，不会生成部分订单计划。
- 查看 / 冻结 / 重置 / 账本：`GET /api/paper/account`、
  `POST /api/paper/account/kill-switch`、`POST /api/paper/account/reset`、
  `GET /api/paper/account/ledger`。
  模拟账户的领域错误会返回结构化 `detail.code` / `detail.message`，例如
  `price_unavailable`、`account_frozen` 或
  `unsupported_account_rebalance_strategy`。

定时自动再平衡（例如通过 Windows 任务计划程序）：

```powershell
.\ai-quant\Scripts\Activate.ps1
quant-system paper rebalance --account default --strategy cross_sectional_top_n
```

旧的 `POST /api/paper/run` 历史回放保持不变，自 2026-06-11 起位于同一页面的「历史回放（研究）」标签页。详见
[docs/guides/paper-trading.md](docs/guides/paper-trading.md) 与
[docs/design/paper_trading_position_map_redesign.md](docs/design/paper_trading_position_map_redesign.md)。

### Paper Strategy Sleeves

Paper Strategy Sleeves 是持久模拟账户的下一层分账模型：一个账户下区分
manual sleeve 和多个 strategy sleeve，各自拥有现金分配和 lot 归属。当前已落地
后端基础、API contract、daily signal、`/paper-trading` 工作区，以及手动
next-open 纸面执行：

- `src/quant_system/execution/paper_strategy_sleeves.py`：`StrategyConfig`、
  `StrategySleeve`、`SleeveLot`、`StrategySignal`、`SleeveLotBook`。
- `src/quant_system/execution/paper_strategy_sleeve_storage.py`：本地事实来源存储，
  路径为 `data/api_runs/paper_strategy_sleeves/`。
- `PaperAccount.sleeve_cash`：账内现金分配簿；`PaperAccount.cash` 继续作为旧账户路径的总现金字段。
- 后端 API 已覆盖策略配置创建 / 列表 / 版本，以及 sleeve 创建 / 列表 / 详情 / daily signal /
  pause / resume / stop：`/api/paper/strategy-configs` 与
  `/api/paper/strategy-sleeves`。
- daily signal 可通过
  `POST /api/paper/strategy-sleeves/{id}/signals` 或
  `quant-system paper strategies generate-signal --sleeve <id>` 手动触发。
- `/paper-trading` 实时账户页已包含 Strategy Sleeves 工作区：可以创建
  strategy config、开设 signal-only / allocated sleeve、生成信号、暂停 /
  恢复 / 停止 sleeve，并对 allocated sleeve 显式创建/处理一次性 pending
  execution plan。
- 手动执行入口包括 `POST /api/paper/strategy-sleeves/{id}/executions`、
  `POST /api/paper/strategy-sleeves/executions/process`、
  `GET /api/paper/strategy-sleeves/ops/status`、
  `quant-system paper strategies create-execution` 和
  `quant-system paper strategies execute-pending` / `execute-due` / `ops-status`。
  strategy GET/status 现在只做观察，绝不隐式对账或改写文件；crash journal 请显式运行
  `quant-system paper strategies recover-pending` 恢复。
- Slice 9G 新增独立的精确因果审计命令：
  `quant-system paper strategies observations --from-date 2026-07-01
  --to-date 2026-07-12 --signal-id <signal_id> --limit 200 --format json`。
  它只提供有界、纯只读 CLI 事实；没有 HTTP route，不访问 account/provider，不做恢复、
  mutation、调度或 missed-opportunity 判断。

尚未实现：常驻/调度式自动执行、near-close 模拟成交和 lot transfer。生成信号不会
自动成交，FastAPI 进程也不会启动常驻策略调度器。现有
`POST /api/paper/account/rebalance` 仍是全账户再平衡，不是 Strategy Sleeves
入口；当账户存在真实 sleeve-owned lot 时会被拒绝。详见
[docs/design/paper_strategy_sleeves_plan.md](docs/design/paper_strategy_sleeves_plan.md)、
[docs/design/paper_strategy_sleeves_mvp3_operations_plan.md](docs/design/paper_strategy_sleeves_mvp3_operations_plan.md) 与
[docs/execution/paper_strategy_sleeves.md](docs/execution/paper_strategy_sleeves.md)。

## 因子实验室刷新

自 2026-06-11 起，因子实验室界面默认使用真实数据（`provider=futu`），数据源/股票池/择时标的/基准可在侧栏调整，并支持可保存的因子研究运行。自 2026-06-15 起，查询卡还可以把当前数据源、股票池、基准和因子 ID 预填发送至回测器；该链接不会自动运行回测。下面的 CLI 用于从后端或计划任务刷新其本地诊断缓存：

```powershell
.\ai-quant\Scripts\Activate.ps1
quant-system factor refresh-lab --provider sample --universe-id etf --symbol QQQ --benchmark-symbol QQQ
```

该命令仅写入本地研究缓存文件，不会下单。

新因子通过实现并测试后端因子代码、然后注册到因子注册表来添加。前端读取已注册的因子；
它不是自由格式的因子表达式编辑器。

## 期权工作流

单标的卖方期权筛选器：

```text
http://127.0.0.1:3001/options-screener
```

该页面提供保守 / 平衡 / 激进预设，以及最低期权中间价、标的平均成交量、市值等质量过滤器。
`min_market_cap=0` 表示不启用市值硬过滤。结果默认隐藏 `Avoid` 合约；排查筛选原因时可打开
“显示避开合约” / `include_rejected=true`。备注列会说明合约被降级或过滤的原因。

每日卖方期权雷达：

```powershell
.\ai-quant\Scripts\Activate.ps1
quant-system options daily-scan --top 10
```

雷达界面：

```text
http://127.0.0.1:3001/options-radar
```

雷达页面可运行当日的只读扫描，并刷新本地股票池、财报和 VIX 缓存。公开数据源为默认；
本地样本数据源仅用于明确的离线测试。计划任务建议使用
`quant-system options daily-task --top 100 --universe-source public --earnings-source public --vix-source public`；
该命令会刷新输入、写入每日快照和 `daily_task_status.json`。雷达页面会通过
`GET /api/options/daily-scan/status` 读取同一状态文件并展示最近一次计划任务状态。
启动补跑默认关闭；只有在明确设置
`QS_OPTIONS_RADAR_STARTUP_CATCHUP_ENABLED=true` 后，API 启动才会在最近一个常规美股交易日快照缺失时，先刷新本地标的池、财报日历和 VIX 输入，再后台运行一次 `daily-scan` 补跑。临时闭市和半日交易仍由正式 `daily-task` 调度或人工流程覆盖。CLI 扫描、API 触发扫描、计划任务和启动补跑会共享雷达输出目录下的 `options_radar_scan.lock`；启动补跑遇到锁冲突时会跳过，且不会覆盖已有 `daily_task_status.json`。

本地期权工具箱：

```text
http://127.0.0.1:3001/options-tools
```

买方助手调试 CLI：

```powershell
.\ai-quant\Scripts\Activate.ps1
quant-system options buyside-screen --ticker AAPL --view long_term_aggressive_bullish --target-price 220 --target-date 2026-12-31
```

买方助手页面：

```text
http://127.0.0.1:3001/options-buyside
```

所有期权输出均为仅供研究的决策辅助，不构成投资建议，不能下单。

## Polymarket / 预测市场

预测市场模块为只读研究：

```powershell
.\ai-quant\Scripts\Activate.ps1
quant-system prediction-market collect --provider sample --duration 0 --limit 10
quant-system prediction-market timeseries-backtest --provider sample
```

该模块不进行签名、赎回、转账或提交真实市场订单。

## 验证

本地一键检查：

```powershell
.\ai-quant\Scripts\Activate.ps1
.\scripts\verify.ps1
```

该脚本会检查 Python 版本、后端 lint / 测试、前端 lint 和前端单元测试。默认不运行
`npm run build`，因为它会重写 `src/frontend/.next`；只有在前端 dev server 停止时才运行
`.\scripts\verify.ps1 -Build`。

仅后端：

```powershell
.\ai-quant\Scripts\Activate.ps1
quant-system doctor
python -m pytest -q
ruff check src/quant_system tests
```

仅前端：

```powershell
npm --prefix src/frontend run lint
npm --prefix src/frontend run test
npm --prefix src/frontend run build   # 仅在 dev server 停止时运行
```

浏览器冒烟测试：

```powershell
cd src/frontend
$env:PW_E2E="1"
npx playwright test --config playwright.config.ts --workers=1
```

## 推荐阅读

从这里开始：

- [docs/INDEX.md](docs/INDEX.md)
- [docs/OVERVIEW.md](docs/OVERVIEW.md)
- [Agent v0.2 local-stack 运维权威](docs/runbooks/agent-v0-2-local-stack.md)
- [前序前端/Hermes Slice 0-8 记录](docs/superpowers/plans/2026-07-08-frontend-redesign-hermes-integration.md)
- [本地存储与 PostgreSQL 状态](docs/architecture/database_cache_plan.md)

`docs/SYSTEM_DESIGN_RESEARCH.md`、phase 交付记录和 audits 是历史设计/证据，不是
当前待办队列。

当前交接：local managed-session write 只存在于 exact local-private gate 之内；
external/history session 继续只读，public standing 为 OFF。source 包含
016–028；2026-07-31 的 live 核对只有 016–027、没有 028。任何 candidate E2E
之前，先闭合 local-stack 的完整 operator window，再做非创建式 Keychain probe
并打开一个短时 candidate。旧页 cutover 仍是独立决策。

当前期权相关文档：

- [docs/futu/futu_environment_setup.md](docs/futu/futu_environment_setup.md)
- [docs/futu/futu_options_data_provider.md](docs/futu/futu_options_data_provider.md)
- [docs/options/options_screener_learning.md](docs/options/options_screener_learning.md)
- [docs/options/buyside_strategy_learning.md](docs/options/buyside_strategy_learning.md)
- [docs/options/local_alphagbm_tools.md](docs/options/local_alphagbm_tools.md)
- [docs/delivery/phase_14_delivery.md](docs/delivery/phase_14_delivery.md)

论文复现：

- [docs/replications/reversal_momentum_replication.md](docs/replications/reversal_momentum_replication.md)

AI 新闻：

- [docs/guides/ai-news.md](docs/guides/ai-news.md)
- [docs/design/ai_news_integration_plan.md](docs/design/ai_news_integration_plan.md)

本地缓存方案及当前状态：

- [docs/architecture/database_cache_plan.md](docs/architecture/database_cache_plan.md)

## 安全边界

平台默认安全姿态：

- `QS_DRY_RUN=true`
- `QS_PAPER_TRADING=true`
- `QS_PAPER_ACCOUNT_AUTO_PROCESS_PENDING_ORDERS_ENABLED=true`
- `QS_LIVE_TRADING_ENABLED=false`
- `QS_NO_LIVE_TRADE_WITHOUT_MANUAL_APPROVAL=true`
- `QS_KILL_SWITCH=true`

前端页面、API 路由、AI Agent、策略、回测以及模拟交易流程均**不得**绕过以上边界。
