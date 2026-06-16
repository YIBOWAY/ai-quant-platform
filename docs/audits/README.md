# 历史审计

本文件夹中的文件作为历史背景资料予以保留。它们记录了早期的评审发现与修复计划，其中部分发现至今已得到解决。

如需了解平台当前状态，请从以下文档开始：

- [../../README.md](../../README.md)
- [../INDEX.md](../INDEX.md)
- [../OVERVIEW.md](../OVERVIEW.md)
- [../delivery/phase_13_delivery.md](../delivery/phase_13_delivery.md)
- [../delivery/phase_14_delivery.md](../delivery/phase_14_delivery.md)
- [FRONTEND_REAL_DATA_REVIEW_2026-05-31.md](FRONTEND_REAL_DATA_REVIEW_2026-05-31.md)

2026-06-15 状态补充：评估报告中“显式 provider 请求失败静默降级 sample”的
小项已加固。股票数据 provider override 现在只接受 `sample` / `futu` /
`tiingo`；未知显式 provider 会返回 `400 provider_unavailable`，不会当作 sample
继续返回 200。未传 provider 的只读日线行情默认路径仍可使用带标注的 sample
fallback；`/api/market-data/history` 的日内频率仅允许 Futu，OpenD 不可用时不再
回退到 sample 伪装日内数据。底层 `SampleOHLCVProvider` 与 `TiingoEODProvider`
也已加 provider 级防线，非 `1d` interval 会在返回数据前被拒绝。

2026-06-15 状态补充：评估报告中“CLI doctor 仍停留在 Phase 0 foundation
口径”的小项已更新。`quant-system doctor` 现在输出离线本地平台健康摘要，覆盖
环境、安全开关、默认数据源、Futu/OpenD 端点、可选数据库索引设置和
`data/_runtime/logs/backend.jsonl` 路径；该命令不连接行情源或 PostgreSQL。

2026-06-15 状态补充：评估报告中“缺少本地一键启动/停止脚本”的小项已处理。
`scripts/dev.ps1` 会检查默认端口、按需启动本地 `quantplatform-db` 容器、探测
OpenD 端口、启动 FastAPI 与 Next.js，并写入 `data/_runtime/pids/` 与
`data/_runtime/logs/`；`scripts/dev-stop.ps1` 会按 pid 文件停止前后端进程树，
并可选停止数据库容器。README 和 `tests/test_frontend_e2e_config.py` 已锁定
这些本地运维约定。

2026-06-15 状态补充：评估报告中“`run_options_radar.ps1` 硬编码解释器、无日志、
缺少计划任务注册脚本”的小项已处理。`scripts/run_options_radar.ps1` 会按
conda base、`CONDA_PREFIX`、PATH 顺序寻找 Python，并把输出追加到
`data/_runtime/logs/options-radar.log`；`scripts/register_options_radar_task.ps1`
会用 `schtasks.exe /Create` 注册周一到周五 06:30 的 Windows 计划任务，
但不会立即启动扫描。README、`docs/execution/phase_13_scheduler_setup.md` 与
`tests/test_frontend_e2e_config.py` 已覆盖该入口。

2026-06-16 状态补充：评估报告中“phase 编号脚本残骸 + scripts/README.md
索引”的脚本目录卫生小项已先完成低风险部分。新增 `scripts/README.md`，
按 Daily Entry Points、Data And Maintenance、Options Radar Operations、
Legacy Or Historical Helpers 和 SQL 分组索引所有顶层 `.py` / `.ps1` / `.sh`
入口，并明确 `start_phase9_full_stack.ps1` / `stop_phase9_full_stack.ps1` /
`run_spy_qqq_phase5_full_check.py` 是兼容或历史验证用途；`tests/test_scripts_readme.py`
会要求新增顶层脚本必须进入索引。

2026-06-16 状态补充：评估报告中“Factor Lab 时间窗/lookback 只能直打 API”
和“发送至回测不带时间窗”的前端可复现性小项已处理。`/factor-lab` 范围卡
现在暴露 `start` / `end` / `lookback` / `force_refresh`，`getFactorLabDashboard()`
会把完整查询传给 `/api/factors/lab`；“发送至回测”会继续携带 `start` /
`end` / `lookback` 预填 Backtester 表单，但仍只填表、不自动运行回测。

2026-06-15 状态补充：评估报告中“缺少后端落盘日志”的小项已处理。后端
CLI 启动和 app-factory 路径都会把结构化 JSONL 运行日志写入
`data/_runtime/logs/backend.jsonl`，并由 `RotatingFileHandler` 控制文件大小；
`tests/test_logging_setup.py` 覆盖了 stdout JSON 与文件 JSONL 两条路径。

2026-06-15 状态补充：评估报告中“回测缺少下载 / 引擎 / 落盘分段耗时”的
可观测性小项已处理。`run_backtest` 现在会生成 `timings_ms`，包含
`data_fetch`、`engine`、`persist`、`total` 四段毫秒耗时；`POST /api/backtests/run`
会把该字段写入 run 的 `metadata.json`，`GET /api/backtests/{run_id}` 详情也会
随 `metadata` 返回。该字段只用于诊断慢点，不参与回测指标计算。
2026-06-16 继续把 `POST /api/backtests/run` 的 `timings_ms` 从匿名对象收敛为
`BacktestRunTimingsResponse`，OpenAPI 和前端共享类型都会锁定上述四段字段。
随后同一路径的 `request`、`metrics`、`benchmark` 与 `paths` 也收敛为结构化
response schema / 前端共享类型，避免 run-submit 结果继续依赖宽泛 `dict`。

2026-06-15 状态补充：评估报告中“.env.example 声称默认 sample 而代码默认
futu”的小项已对齐。`.env.example` 现在使用
`QS_DEFAULT_DATA_PROVIDER="futu"`，并说明 `sample` 只用于显式离线流程测试；
`tests/test_environment_file.py` 会锁定示例文件与 `DataSettings` 默认值一致。

2026-06-15 状态补充：评估报告中“QS_FUTU_* 与旧 QS_* 教法混杂”的快赢项
已处理并补强测试。`FutuSettings` 当前使用 `AliasChoices` 优先接受
`QS_FUTU_ENABLED` / `QS_FUTU_HOST` / `QS_FUTU_PORT` /
`QS_FUTU_REQUEST_TIMEOUT_SECONDS` / `QS_FUTU_USE_CACHE` 等规范变量，同时保留
`QS_ENABLED` / `QS_HOST` / `QS_PORT` / `QS_REQUEST_TIMEOUT_SECONDS` /
`QS_USE_CACHE` 旧别名兼容；`tests/test_settings.py` 已覆盖两套入口。

2026-06-15 状态补充：评估报告中“错误响应格式不一致”的一部分已收敛。
持续模拟账户 API 的领域错误现在返回结构化 `detail.code` / `detail.message`，
覆盖账户冻结、缺价、策略数据不可用、未知或不支持的账户再平衡策略等常见失败态。
历史回放 `POST /api/paper/run` 的两类 kill-switch 409 现在也返回同一结构化
detail，并且前端 `apiClient` 会把 `{code,message}` 格式化为可读错误文案。
backtest、factor、experiment、paper replay、agent candidate、reversal-momentum
replication、prediction-market backtest / timeseries 详情类 404 已统一为
`detail.code=not_found`、`detail.resource`、`detail.id` 与 `detail.message`。
prediction-market timeseries artifact 下载的缺失/越界 404 也已统一为同一结构。
2026-06-16 又补齐了两个仍返回裸字符串的非详情分支：agent candidate review
缺失候选和 prediction-market timeseries 无历史快照现在也返回同一 `not_found`
结构。其余业务 404 保留各自的结构化领域码，例如 options radar snapshot 缺失和
Futu option chain `no_data`。

2026-06-15 状态补充：评估报告中“`core/interfaces.py` 整文件死代码”的表述
需要下调。该文件没有进入当前 backtest / paper / option 运行路径，确实是早期
Phase 0 插件契约残留；但它仍由 `src/quant_system/core/__init__.py` 导出，并由
`tests/test_interfaces.py` 与 Phase 0 架构/交付文档覆盖。因此不按“可直接删除”
处理，后续若要收敛应作为 Phase 0 历史契约清理单独做迁移/删除测试，而不是在
安全或数据可信度批次里顺手移除。

2026-06-15 状态补充：同一条中的 provider 错误也已收敛为共享 helper。
`quant_system.api.errors.provider_unavailable_400()` 统一生成
`detail.code=provider_unavailable`、`detail.provider` 与 `detail.message`；
backtest、factor、experiment、paper、ohlcv、benchmark、market-data 等路由不再
各自复制该响应结构。

2026-06-15 状态补充：评估报告中“前端纯函数缺测试”的一部分已补强。
Strategy Catalog 的 schema-driven payload 构建逻辑已抽到
`src/frontend/lib/strategyPayload.ts`，并由 `strategyPayload.test.ts` 覆盖
symbol list、number、integer_or_null 和 factor weight map 转换。Buy-Side
Options Assistant 的请求 payload 构建逻辑已抽到
`src/frontend/lib/buySideOptionsPayload.ts`，并由
`buySideOptionsPayload.test.ts` 覆盖 ticker 规范化、scenario 数字列表解析、
无效输入回退、horizon day 与 EV scenario days 转换。

2026-06-16 状态补充：Options Tools 前端手写响应类型已继续收敛到共享 API
类型。`OptionsToolsWorkbench` 当前复用 `OptionsGreeksResponse`、
`OptionsSimulationResponse`、`OptionsVolSurfaceResponse`、`OptionsVolSmileResponse`、
`OptionsStrategyRankResponse` 和 `OptionsContractScoreResponse`；策略排名和合约
评分的后端返回字段（如 `breakevens`、`bid`、`ask`、`subscores`、`warnings`）
已在 `src/frontend/lib/api.ts` 中显式建模，并由
`tests/test_frontend_options_tools_response_type_contract.py` 防回归。

2026-06-16 状态补充：Prediction Market 前端 POST 响应类型也已收敛。
`PMRunForm` 当前使用 `PredictionMarketScanResponse`、
`PredictionMarketDryArbitrageResponse` 和 `PredictionMarketBacktestResponse` 的
union，不再用 `Record<string, unknown>` 接收后再强转 backtest 结果；scan
候选、dry-arbitrage proposal 与 backtest run 的共享字段已在
`src/frontend/lib/api.ts` 中显式建模，并由
`tests/test_frontend_prediction_market_response_type_contract.py` 防回归。
同日继续收敛 Prediction Market 只读 scanner 表单：`PMRunForm` 的 scan /
dry-arbitrage / quasi-backtest union response type 已上移为
`PredictionMarketRunResponse` 共享导出，组件不再维护本地 `PMRunResponse`。

2026-06-15 状态补充：评估报告中“Futu 实盘交易脚本需作为红线处理”的小项
已补强回归测试。`tests/test_api_safety.py` 现在会扫描本地已安装的
`.agents/skills/futuapi` Python 脚本，禁止重新引入 `.place_order(` /
`.modify_order(` / `.cancel_order(` / `unlock_trade(` 等 mutating broker 调用；
若本地存在 `place_order.py`、`modify_order.py`、`cancel_order.py`，测试还会执行
它们的 `--json` 模式并要求返回 disabled 错误。`.agents/` 是本地忽略目录，
因此该测试在未安装本地 skill 的干净 checkout 上会跳过入口执行检查。

2026-06-15 状态补充：评估报告中“`getOptionsRadarDates` 是死代码”的小项
已复核并收敛。该 helper 对应的后端端点仍在 `OptionsRadarView` 中使用，只是
组件曾直接调用 `apiRequest("/api/options/daily-scan/dates")`，导致 API client
helper 未被复用；现在日期查询已改为调用 `getOptionsRadarDates()`。

2026-06-15 状态补充：评估报告中“`getHealth` 在 layout 与页面重复 fetch”的
小项已处理。服务端页面和 `SafetyStrip` 现在通过
`src/frontend/lib/serverApi.ts` 的 `getCachedHealth()` 读取健康状态，该 helper
用 React `cache()` 在同一次服务端渲染内复用 `/api/health` 请求；客户端
`getHealth()` 仍保留为普通 API helper。

2026-06-15 状态补充：评估报告中“仪表盘活动日志硬编码为空数组”的小项
已处理。后端已有 `GET /api/runs/recent`，会从 backtest / factor / paper 三类
run metadata 聚合最近运行；首页 `src/frontend/app/page.tsx` 通过
`getRecentRuns(6)` 渲染真实 Activity log，并把该接口错误纳入页面错误横幅。
`tests/test_api_runs_recent.py` 覆盖跨类型倒序聚合，`tests/test_frontend_dashboard_recent_runs.py`
锁定前端接入点。

2026-06-15 状态补充：评估报告中“audits/ 的 `../src` 前缀可一次修复”的
文档卫生小项已处理。历史审计 Markdown 中指向仓库源码、测试、脚本和 `.env`
的相对链接已从 `../...` 修正为 `../../...`；同时把旧的
`src/quant_system/agent/llm.py` 链接改到当前存在的
`src/quant_system/agent/llm/stub.py`。本次只修链接，不改写历史审计结论。

2026-06-15 状态补充：评估报告中“AGENTS.md 结构清单缺 guides/”的小项
已处理。项目结构说明现在把 `docs/guides/` 标为当前用户工作流指南目录，避免
下次 Agent 只看到 phase/archive 类文档而忽略现行指南。

2026-06-15 状态补充：评估报告中“E2E 继承真实 PostgreSQL / 真实数据目录”的
高风险项当前已处理。`src/frontend/playwright.config.ts` 的后端 webServer 明确设置
`QS_ENVIRONMENT=test`、`QS_DATABASE_ENABLED=false`、`QS_DATABASE_AUTO_MIGRATE=false`
并把 `QS_DATA_DIR` / parquet / DuckDB / options radar 路径指向
`src/frontend/.tmp/e2e-data`；`tests/test_frontend_e2e_config.py` 会锁定这些隔离项。
在本地 `quantplatform-db` 容器运行时，使用隔离临时库
`QS_TEST_DATABASE_URL=postgresql://quant:quantpass@127.0.0.1:5432/quantplatform_codex_tmp`
运行 `tests/test_runs_repository_postgres.py` 通过，说明可选 run index 仍可用。
2026-06-16 复测本机 Docker 状态时，`quantplatform-db` 为 healthy，临时库集成测试
仍 1/1 通过，当前本地后端 `/api/health` 返回
`database.enabled=true` / `database.reachable=true`。
不要把该集成测试指向常用 `quantplatform` 库：测试会按临时文件系统视图对同 kind
索引行做 prune，隔离库能避免误删本地已有 run index。2026-06-16 继续补强该
测试入口：当 `QS_TEST_DATABASE_URL` 指向明显的临时/测试库（库名以 `_tmp` 结尾或
包含 `test`）时，测试会先通过 maintenance database 创建缺失的目标库；若 URL 指向
非临时库则直接失败，避免误跑到常用索引库。

2026-06-16 继续收敛 E2E 稳定性：`phase10-smoke.spec.ts` 的 POST 点击 helper
不再使用固定 `waitForTimeout(3000)` 或 `.click({ force: true })`，改为等待目标
button 可见且 enabled 后用 Playwright actionability 点击，并与 `waitForResponse`
并发等待目标 POST；同文件的巨型主流程也已按页面域拆成 backtest、factor lab、
paper replay safety、agent、prediction market、options screener 等独立用例。
`tests/test_frontend_e2e_config.py` 新增守护断言，禁止 E2E spec 回潮到固定等待或
强制点击。`src/frontend/playwright.config.ts` 现在支持 `PW_BACKEND_PORT` /
`PW_FRONTEND_PORT` 备用端口，并把对应 frontend origin 写入 E2E 后端
`QS_API_CORS_ORIGINS`，所以本地 8765/3001 已有 `environment=local` 开发栈时，
仍可在 8766/3002 跑隔离烟测。顺手修复了 test env 下
`GET /api/agent/llm-config` 因 `model` / `base_url` 为 null 而触发 FastAPI
response validation 500 的 schema 漏洞。备用端口命令已跑通完整
`phase10-smoke`，18/18 通过。

2026-06-15 状态补充：评估报告中“`environment.yml` 缺 `[api]` extra”的小项
已处理。`environment.yml` 当前通过 pip 安装 `-e .[api,dev]`，与 README 的
本地安装口径一致；`tests/test_environment_file.py` 会锁定该依赖声明，避免
恢复环境后缺 FastAPI / uvicorn / psycopg 等 API 运行依赖。

2026-06-15 状态补充：评估报告中“AI Studio 模板残留”的小项已继续收敛。
`src/frontend/package.json` 已使用项目包名且不包含 `@google/genai` /
`firebase-tools`，`next.config.ts` 不再跳过 lint/build 错误；本次进一步清理了
`src/frontend/.env.example` 中的 Gemini / AI Studio / Cloud Run / `APP_URL`
模板变量，只保留本地前端需要的 `NEXT_PUBLIC_QUANT_API_BASE_URL`。
2026-06-16 又删除了未被 Next.js 或项目代码引用的 `src/frontend/metadata.json`
模板文件，避免 `requestFramePermissions` / `majorCapabilities` 这类 AI Studio
app metadata 回流；同日移除了已被 `eslint.config.mjs` 取代且无引用的
`src/frontend/.eslintrc.json`，前端 lint 入口继续显式走 flat config。相关守护断言在
`tests/test_frontend_e2e_config.py`。

2026-06-15 状态补充：评估报告中“逐 run DuckDB 副本是纯死重”的高风险项
已处理到当前防回归状态。API 路径的 backtest / factor / paper / experiment run
已有测试断言不会在 `api_runs` 下生成 `.duckdb` 文件；历史遗留副本可用
`scripts/cleanup_api_run_duckdb.py` 先 dry-run 再 `--apply` 清理，且测试会确保
该脚本只处理 `api_runs` 下的 run 副本，不触碰 ingest DuckDB 或 Futu 期权缓存。

2026-06-16 状态补充：评估报告中“存储层 save_frame 复制粘贴”的结构项已先
完成一个低风险切片。Backtest、Factor、Paper replay、Experiment 四条本地
artifact storage 现在共用 `quant_system.storage.artifacts.save_parquet_artifact()`
完成 `reset_index(drop=True)`、Parquet 写入和可选 DuckDB table 写入；业务层仍保留
各自的目录、文件名和 experiment 表名后缀语义，尚未进入完整 ArtifactStore 重构。
`tests/test_storage_artifacts.py` 覆盖公共 helper 的 Parquet 与带引号 DuckDB 表行为。

2026-06-15 状态补充：评估报告中“Futu 期权缓存过期清扫”的快赢项已处理。
`OptionQuotesCache.prune_expired()` 与 `expired_snapshot_ids()` 会按 `expires_at`
删除过期 snapshot 及其 quote rows；`quant-system options prune-cache` 默认
dry-run，只在传 `--apply` 时删除，且支持 `--cache-path` 与 `--as-of` 验证。
`tests/test_options_cache.py` 和 `tests/test_options_cache_cli.py` 覆盖只删过期项、
保留新鲜项和 dry-run 不删除；`docs/futu/futu_options_data_provider.md` 已记录用法。

2026-06-16 状态补充：评估报告中“期权定价 / 希腊字母正确性未审计”的一处
输入边界已加固。`implied_volatility()` 现在会先按无股息 European option
上下界校验市场价，低于折现内在价值或高于理论上界时显式抛错，避免把不可能价格
解成 0.0001 / 5.0 这类看似有效的 IV。`tests/test_options_local_tools.py` 已覆盖
Black-Scholes 参考值、Greeks 参考值、IV solver 正常恢复和 no-arbitrage violation。

2026-06-15 状态补充：评估报告中“持续模拟账户成交定价链路覆盖不足”的
测试缺口已补强。`tests/test_paper_price_source.py` 现在直接覆盖
`PaperPriceSource` 的 Futu snapshot 优先级、本地缓存只接受近期真实 provider
收盘价、sample-only / stale-only 本地缓存拒单、Tiingo 远程 fallback 成功路径，
以及 Tiingo fallback 不得使用 sample provider。实现本身已符合
`docs/guides/paper-trading.md` 和 AGENTS.md 中的“持续账户绝不使用 sample 价格成交”
边界，本次变更主要是防回归测试。

2026-06-15 状态补充：评估报告中“`data/api_runs` 缺少可交付备份路径”的小项
已处理。`scripts/backup_api_runs.py` 会把 `data/api_runs/` 打成 zip 并写入
`manifest.json`，默认排除 `.env`、DuckDB 文件、lock 文件等不应进入备份包的
本地状态；README 的 “Local Run Artifacts and Backups” 已给出命令，
`tests/test_backup_api_runs_script.py` 会锁定归档内容与排除规则。

2026-06-15 状态补充：评估报告中“`attach_safety_footer` 可被同名字段遮蔽”的
小项已加固。JSON 响应中间件现在会强制覆盖 `payload["safety"]` 为当前
`SafetySettings` 与绑定地址生成的 footer，而不是仅在缺失时 `setdefault`；
`tests/test_api_safety.py` 覆盖了路由伪造 `safety.live_trading_enabled=true` 时
仍会被中间件改回真实安全状态。

2026-06-15 状态补充：评估报告中“CLI 可无条件覆盖 kill-switch，而 API 同操作
返回 409”的小项已处理。`quant-system paper run-sample --no-kill-switch` 现在在
`QS_KILL_SWITCH=true` 时直接退出，不进入历史回放 pipeline、不落盘 paper 产物；
只有先显式设置 `QS_KILL_SWITCH=false` 的本地模拟进程才允许该 replay 覆盖。
`tests/test_paper_trading_pipeline_cli.py` 覆盖默认拒绝和显式关闭后的本地成交演示。

2026-06-15 状态补充：评估报告中“kill-switch 与账户冻结作用域交叉、账户直接
下单路径缺全局闸门”的建议不应按字面执行。当前现行设计已把两者分离：
`QS_KILL_SWITCH` / `SafetySettings.kill_switch` 是历史回放 (`POST /api/paper/run`
和 `quant-system paper run-sample`) 的全局安全锁；持续模拟账户使用
`PaperAccount.kill_switch` / `POST /api/paper/account/kill-switch` 作为账户级冻结，
默认关闭但可由用户冻结。AGENTS.md 与 paper-account 文档已明确二者不同；后续可
考虑改名为 `account_frozen` 做语义澄清，但不应把全局历史回放锁直接强接到
持续账户手动单/再平衡路径，否则会违背已采用的账户级模拟交易设计。

2026-06-15 状态补充：同一条中的 `/settings` 脱敏守护也已补强。
`mask_secret_fields()` 现在除了按字段名遮蔽 `key` / `secret` / `token` /
`password` / `private`，还会直接识别并遮蔽 `pydantic.SecretStr` /
`SecretBytes` 值；测试覆盖字段名本身不含敏感关键词但值类型为 secret 的情况。

2026-06-16 状态补充：`/api/settings` 的响应形状已从裸 settings dump 调整为
`{"settings": <masked settings>, "safety": <footer>}`，避免中间件强制覆盖
顶层 `safety` 时吞掉 `Settings.safety` 的完整配置；`mask_secret_fields()` 在
`api_keys` 这类 secret-like 分组下会保留嵌套结构并遮蔽叶子值。

2026-06-15 状态补充：评估报告中“Tiingo 可能使用未复权价格”的 critical 候选项
在当前代码上已证伪。`TiingoEODProvider` 会优先使用 `adjOpen` / `adjHigh` /
`adjLow` / `adjClose` / `adjVolume`，缺失时才回退 raw 字段，并写入
`price_adjustment=adjusted|raw|mixed`；`tests/test_data_tiingo_provider.py`
已覆盖全复权、全缺失和部分缺失三种情形。

2026-06-16 状态补充：评估报告中“Tiingo 每次回测全量重下载、没有本地缓存接通”
在当前代码上已不准确。`build_ohlcv_provider` 会把 Tiingo 包装为
`CachedOHLCVProvider`，通过 `LocalDataStorage` 做 read-through 缓存：完整本地
窗口直接复用，缺失窗口才回源并写回缓存。本次补强了多标的覆盖判定，缓存命中
必须逐个请求标的都覆盖 `start` / `end`，避免一个标的完整、另一个标的缺边界时
误判为缓存完整；`tests/test_provider_factory.py` 覆盖完整缓存复用和部分标的窗口
缺失时回源。

2026-06-15 状态补充：评估报告里“默认历史回放在安全锁开启时仍会产生
0 成交成功 run”的表述已过时。`POST /api/paper/run` 在回放请求试图开启
kill switch 时会返回 `409 detail.code=replay_kill_switch_enabled`；若请求试图
绕过仍开启的全局 `QS_KILL_SWITCH`，会返回
`409 detail.code=global_kill_switch_enabled`。前端回放表单也会在
`health.safety.kill_switch` 开启时禁用提交，并把结果状态显示为
`execution_status=blocked|filled|no_orders|unfilled`。

2026-06-15 状态补充：评估报告中“期权雷达 CLI/API 阈值双轨，`max_delta`
漂移”的小项已处理到当前防回归状态。CLI 与 API 都通过各自的
`_build_radar_screen_config()` 从同一个 `OptionsRadarSettings.max_delta_for_radar`
读取阈值，环境变量别名为 `QS_OPTIONS_RADAR_MAX_DELTA_FOR_RADAR`；
`tests/test_settings_options_radar.py` 覆盖默认值、环境变量覆盖，以及 CLI/API
构建出的 `OptionsScreenerConfig.max_delta` 一致性。

2026-06-16 状态补充：评估报告中“期权雷达完整交易所节假日判断”的剩余项已
处理到常规美股整天休市日级别。`QS_OPTIONS_RADAR_STARTUP_CATCHUP_ENABLED=true`
时，API 启动补跑会按最近一个常规美股交易日找缺失快照，先刷新本地标的池、
财报日历和 VIX 输入，再运行只读扫描；周末、Good Friday、Juneteenth、
独立日补休、感恩节等会回退到上一个交易日。临时闭市和半日交易仍由 Windows
计划任务或人工流程处理；`tests/test_api_options_radar.py` 覆盖这些启动补跑
目标日期和刷新步骤。

2026-06-15 状态补充：评估报告中“回测 Sharpe / 年化指标缺少数值锚点”的
测试缺口已补上。`tests/test_backtest_engine_metrics.py` 中的
`test_performance_metrics_match_hand_calculated_return_and_sharpe` 使用手算样例锁定
`total_return`、`annualized_return`、`volatility` 和 `sharpe`，避免后续在
`calculate_performance_metrics()` 中重排收益率、年化因子或标准差逻辑时无声漂移。

2026-06-15 状态补充：评估报告中“缺少真实默认 env 形态下的 paper replay
守护测试”已覆盖。`tests/test_paper_trading_pipeline_cli.py` 已覆盖
`QS_KILL_SWITCH=true` 默认环境下 `run-sample` 不得成交、显式 `--kill-switch`
必须 blocked、试图 `--no-kill-switch` 但未先关闭全局环境变量时必须失败，
以及只有 `QS_KILL_SWITCH=false` 的本地模拟进程才允许生成演示成交。

2026-06-16 状态补充：评估报告中“回测与模拟执行订单生成行为漂移”的一处
小切片已收紧。历史 paper replay 的 `_generate_rebalance_requests()` 现在会把
目标或持仓标的的缺价、0 价、NaN/inf 价统一视为
`missing order generation price` 并显式中止，不再静默跳过缺价目标或把无效价
泄漏到除零 / Pydantic 校验错误。`tests/test_signal_paper_trading_integration.py`
覆盖该边界。

2026-06-15 状态补充：快赢 #9“回测详情页读取 `benchmark.source` 并挂
`DataSourceBadge`”已处理。`/backtest` 列表页和 `/backtest/[runId]` 详情页
都从详情响应里的 `benchmark` 对象读取持久化曲线与 `source`，不再现场调用
`getBenchmark()`；`tests/test_frontend_backtest_benchmark_source.py` 覆盖徽章渲染
和“只使用 detail response 中的 persisted benchmark”这两条前端契约。

2026-06-15 状态补充：快赢 #10“`scripts/verify.sh` 一键验证 + conftest Python
版本断言”已处理。仓库现在同时保留 PowerShell 与 POSIX shell 验证入口，默认跑
pytest、ruff、frontend lint、frontend type-check、frontend unit tests，build 需显式开启；
`tests/conftest.py` 会给出 Python 3.11+ / `conda activate ai-quant` 的清晰提示，
`tests/test_verify_scripts.py` 锁定这些入口。

2026-06-15 状态补充：评估报告中“断网渲染假 `$1M` 账户”的残余问题
“HoldingsPanel/LedgerPanel 无法区分后端离线与真为空”已处理。`/paper-trading`
会把 `account.apiError` / `ledger.apiError` 分别映射为 `accountDown` /
`ledgerDown`，离线时展示不可达文案而不是空持仓/空流水；
`tests/test_frontend_paper_trading_offline_state.py` 覆盖该展示契约。

2026-06-15 状态补充：快赢 #14“TopBar 去导航化”已处理。桌面导航权威已收敛到
`Sidebar`，`TopBar` 不再维护 `topNavItems` 或重复的 backtest/options radar
导航入口；`tests/test_frontend_topbar_navigation_contract.py` 会防止顶部栏重新变成
第二套桌面导航。

2026-06-15 状态补充：快赢 #15“paper 账户 `.bak` 副本 + 损坏改名保留”已处理。
`PaperAccountStorage.save()` 在覆盖 `account.json` 前写 `account.json.bak`，
`load()` 读到损坏 JSON 时会把原文件移动成 `account.corrupt-<timestamp>.json`
后再重新开户；`tests/test_paper_account.py` 覆盖前一版账户备份和损坏文件保留。
2026-06-16 进一步补上恢复路径：如果 `account.json.bak` 是有效账户快照，
`load()` 会先恢复备份到 `account.json` 并返回该账户；只有无有效备份时才重新开户。
新增测试覆盖主文件损坏、备份有效时不会丢失原账户现金和账本。
2026-06-16 继续处理 `_atomic_replace` 的非原子 fallback：10 次 `os.replace` 重试耗尽后
现在会清理临时文件并重新抛出 `PermissionError`，旧 `account.json` 保持不变；
测试覆盖持续替换失败时不会静默普通写覆盖。

2026-06-16 状态补充：评估报告和前端审查中“限价单缺购买力/可卖数量预留”的
剩余项已处理。`PendingAccountOrder` 持久化 `reserved_cash` / `reserved_quantity`；
买入挂单按 `quantity * limit_price` 预留现金，卖出挂单预留对应持仓数量。
后续手动单和策略再平衡的撮合视图只使用 `available_cash` 与未预留持仓，处理某个
挂单时会释放该挂单自己的预留。`GET /api/paper/account` 暴露 `cash`、
`reserved_cash`、`available_cash`，前端账户摘要和持仓地图显示可用现金。
2026-06-16 进一步补上 API 后台自动检查：默认每 30 秒处理已存在账户的
`pending_orders`，复用与手动 `POST /api/paper/account/orders/process` 相同的账户锁、
文件锁和真实纸面价格路径；测试环境强制关闭该 worker。随后又补上完整自然日
真实 daily OHLCV 高低价区间回看：当前纸面价格仍未触价时，处理流程会检查
上次检查/创建之后、当前检查日之前的完整自然日区间，命中则按原限价成交；
该路径不使用 sample 数据，也不推断下单当天的日内先后顺序。

2026-06-15 状态补充：评估报告中“API 路由缺少 `response_model`、前后端契约
漂移”的高风险项已按低风险切片治理到当前全量防回归状态。已治理接口
已挂上 FastAPI `response_model`：`GET /api/health`、`GET /api/symbols`、
`GET /api/ohlcv`、`GET /api/benchmark`、`GET /api/strategies`、
`GET /api/backtests`、`GET /api/backtests/{run_id}`、`GET /api/experiments`、`GET /api/experiments/{experiment_id}`、`GET /api/universes`、`GET /api/factors`、`GET /api/factors/lab`、`GET /api/factors/runs`、`GET /api/factors/{run_id}`、
`GET /api/paper`、`GET /api/paper/{run_id}`、`GET /api/paper/account`、`GET /api/paper/account/ledger`、`GET /api/replications/reversal-momentum/{run_id}`、`GET /api/settings`、`GET /api/runs/recent`、`GET /api/market-data/history`、
`POST /api/paper/run`、`POST /api/paper/account/reset`、`POST /api/paper/account/kill-switch`、
`POST /api/paper/account/orders`、`POST /api/paper/account/orders/process`、
`POST /api/paper/account/orders/{order_id}/cancel`、`POST /api/paper/account/rebalance`、
`GET /api/options/daily-scan/dates`、`GET /api/options/daily-scan/status`、
`GET /api/options/daily-scan`、`GET /api/options/daily-scan/symbol/{ticker}`、
`GET /api/options/expirations`、`GET /api/options/chain`、`GET /api/options/snapshot/{ticker}`、
`GET /api/options/tools/vol-surface/{ticker}`、`GET /api/options/tools/vol-smile/{ticker}`、
`GET /api/agent/candidates`、`GET /api/agent/candidates/{candidate_id}`、`GET /api/agent/llm-config`、`GET /api/options/tools/strategy/templates`、
`GET /api/options/tools/watchlist`、`GET /api/prediction-market/markets`、
`GET /api/prediction-market/results/{run_id}`、`GET /api/prediction-market/timeseries-backtest/{run_id}`、
`POST /api/agent/tasks`、`POST /api/agent/candidates/{candidate_id}/review`、
`POST /api/prediction-market/scan`、`POST /api/prediction-market/collect`、
`POST /api/prediction-market/dry-arbitrage`、`POST /api/prediction-market/backtest`、
`POST /api/prediction-market/timeseries-backtest`、`POST /api/options/refresh/universe`、
`POST /api/options/refresh/earnings`、`POST /api/options/refresh/vix`、
`POST /api/options/daily-scan/run`、`POST /api/options/screener`、
`POST /api/options/tools/greeks`、`POST /api/options/tools/implied-volatility`、
`POST /api/options/tools/simulate`、`POST /api/options/tools/strategy/build`、
`POST /api/options/tools/score-contracts`、`POST /api/options/tools/strategy/rank`、
`POST /api/options/tools/bull-put-signal`、`POST /api/options/tools/fear-score`、
`POST /api/options/tools/iv-rank`、`POST /api/options/tools/market-sentiment`、
`POST /api/options/tools/earnings-crush`、`POST /api/options/tools/hedge-advisor`、
`POST /api/options/tools/unusual-activity`、`POST /api/options/tools/watchlist`、
`POST /api/options/tools/alerts/evaluate`、`POST /api/options/tools/health-check`、
`POST /api/factors/run`、`POST /api/backtests/run`、`POST /api/experiments/run`、
`POST /api/replications/reversal-momentum/run`；同时补齐
`HealthResponse`、`OHLCVResponse`、`BenchmarkResponse`、`MarketDataHistoryResponse`
与 `AgentLLMConfigResponse` 中已由真实响应返回但 schema 缺失的字段，并为策略/股票池/因子 catalog、因子 run
lab 看板、列表/详情、回测列表/详情、实验列表/详情、replay paper-run 列表/详情/提交响应、persistent paper account/ledger/mutation 响应、研报复现详情、脱敏 settings、最近运行活动流、期权雷达日常扫描状态/快照/单标的快照/刷新/手动扫描、期权筛选器、Futu options 到期日/链/快照/波动率曲面/微笑响应、options local tools 基础计算/模拟/模板构建/本地研究评分/监控响应、research run 提交响应、Agent task/review 响应、Agent candidate 列表/详情、Agent LLM 配置探针、prediction-market markets/backtest/timeseries/collector POST 结果增加薄 wrapper response schema；`GET /api/prediction-market/timeseries-backtest/{run_id}/artifacts/{artifact_name}` 显式声明为 `FileResponse`，不再暴露匿名 JSON schema。
本轮 OpenAPI 统计为 40 个 POST `$ref` 响应、0 个裸 POST JSON 响应。
`tests/test_api_response_models.py` 现在还会全局检查所有 `200 application/json`
响应都必须引用 `components/schemas/*`，并继续检查 OpenAPI schema 引用和
关键字段，现有 `tests/test_api_health.py`、`tests/test_api_data.py`、
`tests/test_api_backtest.py`、`tests/test_api_strategy_universe_catalog.py` 与
`tests/test_api_factors.py`、`tests/test_api_runs_recent.py`、
`tests/test_api_market_data_futu.py`、`tests/test_api_options_radar.py`、
`tests/test_api_agent_llm_config.py`、`tests/test_api_options_local_tools.py`、
`tests/test_api_prediction_market.py` 继续覆盖 runtime 响应与 safety footer。下一步若要
生成/替换前端类型，仍应按路由域逐批推进，而不是一次性替换全部前端类型。

2026-06-16 状态补充：上述前端类型收敛已开始按路由域推进。Backtest、Factor、
Experiment、Paper 四个核心 run-submit 表单以及 Agent task/review 表单不再在组件内
局部手写窄响应类型；`src/frontend/lib/api.ts` 统一导出 `BacktestRunResponse`、
`FactorRunResponse`、`ExperimentRunResponse`、`PaperRunResponse`、
`AgentTaskResponse`、`AgentReviewResponse`，字段覆盖对应后端 `response_model`
中的 source、warnings、paths、timings、execution status、candidate metadata、
manual registration status 等运行元数据。`tests/test_frontend_run_response_type_contract.py`
锁定这些表单必须使用共享 API 类型，防止局部 response type 回潮。其余路由域仍可
后续逐批收敛。
Factor Lab dashboard 的 `guardrails` / `cache` 也从匿名对象收敛为
`FactorLabGuardrailsResponse` / `FactorLabCacheResponse`，OpenAPI 现在暴露
walk-forward、leakage audit 和 cache key 的结构化 schema；前端 `FactorLabDashboard`
可直接读取 `walk_forward.fold_count` 与 `leakage_audit.status`，不再对这些字段做
`Record<string, unknown>` 强转。
同日 Backtest run-submit 响应里的 `timings_ms` 也改用
`BacktestRunTimingsResponse`，`tests/test_frontend_run_response_type_contract.py`
会防止它回退成 `Record<string, unknown>`。随后同一响应中的 request echo、
summary metrics、benchmark snapshot 和 artifact paths 也改用结构化共享类型。
同日补齐 `AgentLLMConfigResponse` 前端类型命名，与后端 OpenAPI schema 名称保持一致；
旧的 `AgentLlmConfigResponse` 仅保留为兼容 alias。
同日补齐 prediction-market run response 前端类型命名：`PredictionMarketBacktestRunResponse`
与 `PredictionMarketTimeseriesBacktestRunResponse` 现在与后端 schema 名称一致，旧简名仅保留
为兼容 alias。

2026-06-16 进一步推进 options live 域类型收敛：`OptionsRadarSymbolLive` 与
`OptionsToolsWorkbench` 不再分别手写 snapshot / expirations / chain 响应类型；
`src/frontend/lib/api.ts` 统一导出 `OptionContract`、`OptionsSnapshotResponse`、
`OptionsExpirationsResponse`、`OptionsChainResponse`，覆盖后端 schema 中的
`success`、`source`、`iv_rank_source`、`assumptions`、`option_type` 等字段。
`tests/test_frontend_options_response_type_contract.py` 锁定这两个组件必须复用共享
options API 类型。

2026-06-16 继续推进 buy-side options assistant 类型收敛：
`BuySideOptionsAssistant` 不再在组件内手写 `AssistantResponse` / `Recommendation` /
`StrategyLeg` 等响应类型；`src/frontend/lib/api.ts` 统一导出
`BuySideAssistantResponse`、`BuySideDecisionThesis`、`BuySideRecommendation`、
`BuySideStrategyLeg`、`BuySideScenarioSummary`、`BuySideScenarioEv`，覆盖后端
`BuySideAssistantResponse` response model 中的 thesis、recommendations、assumptions、
risk attribution、scenario summary / subjective EV、leg quote/greeks/computed 字段。
`tests/test_frontend_buy_side_response_type_contract.py` 锁定该组件必须复用共享类型，
防止本地窄响应类型回潮。

同日继续收敛 persistent paper account mutation 响应：`AccountTradePanel` 与
`PendingOrderCancelButton` 不再局部手写 order/process/rebalance/cancel 结果类型；
`src/frontend/lib/api.ts` 统一导出 `PaperAccountOrderOutcome`、
`PaperAccountOrderResponse`、`PaperAccountOrdersProcessResponse`、
`PaperAccountRebalanceResponse`，复用已有 `PaperAccountResponse` 并覆盖后端
`PaperAccountOrderOutcomeResponse` 中的 `requested_quantity`、`filled_quantity`、
nullable `price` / `price_kind`、`rejected_reason` 以及再平衡 target weights。
前端 receipt 渲染同步处理 nullable price，避免类型收敛后仍隐含成交价必定存在的假设。

同日继续收敛 options screener 响应：`OptionsScreenerForm` 不再局部手写
`ScreenerResult` / `ScreenerCandidate`；`src/frontend/lib/api.ts` 统一导出
`OptionsScreenerResult` 与 `OptionsScreenerCandidate`，覆盖后端
`OptionsScreenerResult` / `OptionsScreenerCandidate` response model 中的
underlying、bid/ask/mid、HV/IV、trend、market regime、rating、rejection summary、
assumptions 等字段。`tests/test_frontend_options_screener_response_type_contract.py`
锁定该表单必须复用共享类型。

同日拆分推进 options tools live GET 响应：`OptionsToolsWorkbench` 的 vol surface /
vol smile 面板不再局部手写 `SurfaceResult` / `SmileResult`；`src/frontend/lib/api.ts`
统一导出 `OptionsVolSurfaceResponse`、`OptionsVolSmileResponse` 及其嵌套 surface /
smile 类型，覆盖后端 response model 中的 source、atm term structure、surface points、
dte、smile deltas / moneyness、skew metrics、assumptions 等字段。POST 工具结果类型
仍留待后续分批收敛。

同日继续推进 options tools POST 结果类型收敛：`OptionsToolsWorkbench` 的 Greeks 与
Simulator 面板不再局部手写 `GreeksResult` / `SimulationResult`；`src/frontend/lib/api.ts`
统一导出 `OptionsGreeksResponse`、`OptionsSimulationResponse` 与
`OptionsSimulationPnlAtExpiry`，覆盖后端 response model 中的二阶 Greeks、position、
P&L 曲线、breakevens、risk/reward、scenarios、assumptions 等字段。
2026-06-16 又收敛了 Signals 面板响应：implied volatility、bull-put signal、
fear score、IV rank/snapshot、earnings crush、unusual activity 均使用
`src/frontend/lib/api.ts` 的共享 `OptionsSignalsResponse` union 与具体响应类型，
不再通过 `unknown` 或局部 `{ fear_score: number }` 接收。
同日继续收敛 Research Ops 面板响应：strategy templates、strategy build、
watchlist add/load、alerts evaluation 均使用共享 `OptionsResearchOpsResponse`
union 与具体响应类型，`OptionsToolsWorkbench` 不再用 `payload: unknown` /
`Promise<unknown>` 管理工具结果。

同日继续收敛 Strategy Catalog 动态运行响应：`src/frontend/lib/api.ts` 新增
`ReversalMomentumReplicationRunResponse` 与 `StrategyRunResponse` union，覆盖
catalog-dispatched backtest run 与 reversal-momentum replication run；
`StrategyCatalogWorkbench` 和复现详情页不再用裸 `Record<string, unknown>` 管理
运行结果。

同日补齐 Options Tools 剩余本地研究响应合同：market sentiment、hedge advisor、
research health check 现在都有共享 frontend response type，并纳入
`OptionsSignalsResponse` / `OptionsResearchOpsResponse` union；页面接通了已有文案中的
Market Sentiment 与 Health Check 按钮。随后 Research Ops 补上 Hedge Advisor
持仓输入区（shares / cost_basis / purpose）和按钮，先读取当前标的只读 Futu
快照与期权链，再把用户提供的持仓上下文发送到本地 hedge-advisor 端点；该入口只生成
Long Put / Collar 研究候选，不创建订单。
随后开始收敛 `OptionsToolsWorkbench` 巨型组件的职责边界：live option-chain
上下文加载、ATM/strike 选择、工具 payload 组装、signals/research ops 请求已抽到
`src/frontend/lib/optionsToolsLive.ts`；组件侧只保留 tab、状态和渲染逻辑。该批次不做
视觉改版，`tests/test_frontend_options_tools_response_type_contract.py` 会锁定组件不得
重新直接调用 `apiPost` / `apiRequest`，共享 response type 仍由 helper 使用。备用端口
下 `options-tools-and-charts.spec.ts` 4/4 通过。随后补上
`src/frontend/lib/optionsToolsLive.test.ts`，直接覆盖 ticker 规范化、ATM call 选择、
IV 百分比归一、价差腿构造、strategy rank strikes 和空 ticker 拒绝；前端 Vitest
当前为 10 个文件 / 22 个用例通过。

同日补齐 Options Radar daily-scan 前端响应类型命名：`OptionsDailyScanDatesResponse`、
`OptionsDailyScanStatusResponse`、`OptionsDailyScanResponse` 与
`OptionsDailyScanRunResponse` 现在与后端 OpenAPI schema 名称一致；旧的
`OptionsRadar*` 与 `OptionsDailyTaskStatusResponse` 仅保留为兼容 alias。
`OptionsRadarView` 的 status、snapshot 与 manual scan 调用已改用后端一致命名，
并由 `tests/test_frontend_options_radar_response_type_contract.py` 防回归。
2026-06-16 后续补强：同一测试现在会用后端 `options_radar` response model
字段集合校验前端同名 type 至少覆盖所有后端字段；本轮补齐了
`OptionsRefreshResponse.warning`，避免刷新 universe / earnings / VIX 时后端 warning
字段被前端类型遗漏。
随后同域补齐单标的详情与候选行命名：`OptionsDailyScanSymbolResponse` 与
`OptionsRadarCandidateResponse` 现在在前端共享类型中显式导出，`/options-radar/[symbol]`
页面改用 `getOptionsDailyScanSymbol()`，旧 `getOptionsRadarSymbol()` 与
`OptionsRadarSymbolResponse` 仅保留为兼容入口。

同日补齐 catalog wrapper 前端类型命名：`StrategyCatalogResponse`、
`UniverseCatalogResponse` 与 `FactorCatalogResponse` 现在与后端 schema 名称一致；
旧 `StrategiesResponse`、`UniversesResponse`、`FactorsResponse` 保留为兼容 alias。
`getStrategies()`、`getUniverses()`、`getFactors()` 已改用后端一致响应类型，并由
`tests/test_frontend_catalog_response_type_contract.py` 防回归。

同日继续补齐 Prediction Market GET/detail 响应命名：`PredictionMarketMarketsResponse`、
`PredictionMarketCandidateResponse`、`PredictionMarketBacktestResultResponse` 与
`PredictionMarketTimeseriesBacktestResultResponse` 现在在前端共享类型中显式导出；
旧 `PredictionMarketResponse`、`PredictionMarketCandidate` 与 detail 简名保留为
兼容 alias。`getPredictionMarkets()` 已改用后端一致响应类型。

同日补齐基础行情响应命名：`src/frontend/lib/api.ts` 现在导出后端一致的
`OHLCVResponse`，`getOhlcv()` 已改用该类型；旧 `OhlcvResponse` 仅保留为
兼容 alias，并由 `tests/test_frontend_data_response_type_contract.py` 防回归。
2026-06-16 后续补强：同一测试现在会校验 `HealthResponse` 前端 type 覆盖
后端字段集合；本轮补齐 `data_provider.configured_default` 与
`data_provider.tiingo_token_present`，并同步离线 fallback。

同日补齐 persistent paper account 嵌套响应命名：`AccountPositionResponse`、
`PendingAccountOrderResponse`、`PaperAccountPriceSourceResponse`、
`PaperAccountOrderOutcomeResponse`、`PaperAccountRebalanceSummaryResponse` 与
`LedgerEntryResponse` 现在在前端共享类型中显式导出；旧 View/短名类型继续作为
兼容 alias，`tests/test_frontend_paper_account_response_type_contract.py` 覆盖这些
mutation、ledger 与 account snapshot 类型关系。

同日补齐通用错误响应命名：前端共享类型现在导出 `ErrorResponse`，与后端
`detail` + 可选 `safety` envelope 一致。至此 `src/quant_system/api/schemas/`
中的 80 个 `*Response` Pydantic schema 均已有 `src/frontend/lib/api.ts` 同名导出；
`tests/test_frontend_backend_response_type_exports.py` 会全局扫描后端 schema 并锁定该
前端导出覆盖率。剩余工作不再是“是否有同名类型”，而是后续是否用 OpenAPI 生成
替代手写定义。
