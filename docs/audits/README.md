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
继续返回 200。未传 provider 的只读行情默认路径仍可使用带标注的 sample fallback。

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

2026-06-15 状态补充：评估报告中“缺少后端落盘日志”的小项已处理。后端
CLI 启动和 app-factory 路径都会把结构化 JSONL 运行日志写入
`data/_runtime/logs/backend.jsonl`，并由 `RotatingFileHandler` 控制文件大小；
`tests/test_logging_setup.py` 覆盖了 stdout JSON 与文件 JSONL 两条路径。

2026-06-15 状态补充：评估报告中“回测缺少下载 / 引擎 / 落盘分段耗时”的
可观测性小项已处理。`run_backtest` 现在会生成 `timings_ms`，包含
`data_fetch`、`engine`、`persist`、`total` 四段毫秒耗时；`POST /api/backtests/run`
会把该字段写入 run 的 `metadata.json`，`GET /api/backtests/{run_id}` 详情也会
随 `metadata` 返回。该字段只用于诊断慢点，不参与回测指标计算。

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
其他历史回放和跨模块 404 仍未做全局统一。

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
在本地 `quantplatform-db` 容器运行时，`QS_TEST_DATABASE_URL=postgresql://quant:quantpass@127.0.0.1:5432/quantplatform`
下的 `tests/test_runs_repository_postgres.py` 通过，说明可选 run index 仍可用。

2026-06-15 状态补充：评估报告中“`environment.yml` 缺 `[api]` extra”的小项
已处理。`environment.yml` 当前通过 pip 安装 `-e .[api,dev]`，与 README 的
本地安装口径一致；`tests/test_environment_file.py` 会锁定该依赖声明，避免
恢复环境后缺 FastAPI / uvicorn / psycopg 等 API 运行依赖。

2026-06-15 状态补充：评估报告中“AI Studio 模板残留”的小项已继续收敛。
`src/frontend/package.json` 已使用项目包名且不包含 `@google/genai` /
`firebase-tools`，`next.config.ts` 不再跳过 lint/build 错误；本次进一步清理了
`src/frontend/.env.example` 中的 Gemini / AI Studio / Cloud Run / `APP_URL`
模板变量，只保留本地前端需要的 `NEXT_PUBLIC_QUANT_API_BASE_URL`。相关守护断言在
`tests/test_frontend_e2e_config.py`。

2026-06-15 状态补充：评估报告中“逐 run DuckDB 副本是纯死重”的高风险项
已处理到当前防回归状态。API 路径的 backtest / factor / paper / experiment run
已有测试断言不会在 `api_runs` 下生成 `.duckdb` 文件；历史遗留副本可用
`scripts/cleanup_api_run_duckdb.py` 先 dry-run 再 `--apply` 清理，且测试会确保
该脚本只处理 `api_runs` 下的 run 副本，不触碰 ingest DuckDB 或 Futu 期权缓存。

2026-06-15 状态补充：评估报告中“Futu 期权缓存过期清扫”的快赢项已处理。
`OptionQuotesCache.prune_expired()` 与 `expired_snapshot_ids()` 会按 `expires_at`
删除过期 snapshot 及其 quote rows；`quant-system options prune-cache` 默认
dry-run，只在传 `--apply` 时删除，且支持 `--cache-path` 与 `--as-of` 验证。
`tests/test_options_cache.py` 和 `tests/test_options_cache_cli.py` 覆盖只删过期项、
保留新鲜项和 dry-run 不删除；`docs/futu/futu_options_data_provider.md` 已记录用法。

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

2026-06-15 状态补充：评估报告中“Tiingo 可能使用未复权价格”的 critical 候选项
在当前代码上已证伪。`TiingoEODProvider` 会优先使用 `adjOpen` / `adjHigh` /
`adjLow` / `adjClose` / `adjVolume`，缺失时才回退 raw 字段，并写入
`price_adjustment=adjusted|raw|mixed`；`tests/test_data_tiingo_provider.py`
已覆盖全复权、全缺失和部分缺失三种情形。

2026-06-15 状态补充：评估报告里“默认历史回放在安全锁开启时仍会产生
0 成交成功 run”的表述已过时。`POST /api/paper/run` 在回放请求试图开启
kill switch 时会返回 409；前端回放表单也会在 `health.safety.kill_switch`
开启时禁用提交，并把结果状态显示为 `execution_status=blocked|filled|no_orders|unfilled`。

2026-06-15 状态补充：评估报告中“期权雷达 CLI/API 阈值双轨，`max_delta`
漂移”的小项已处理到当前防回归状态。CLI 与 API 都通过各自的
`_build_radar_screen_config()` 从同一个 `OptionsRadarSettings.max_delta_for_radar`
读取阈值，环境变量别名为 `QS_OPTIONS_RADAR_MAX_DELTA_FOR_RADAR`；
`tests/test_settings_options_radar.py` 覆盖默认值、环境变量覆盖，以及 CLI/API
构建出的 `OptionsScreenerConfig.max_delta` 一致性。

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

2026-06-15 状态补充：快赢 #9“回测详情页读取 `benchmark.source` 并挂
`DataSourceBadge`”已处理。`/backtest` 列表页和 `/backtest/[runId]` 详情页
都从详情响应里的 `benchmark` 对象读取持久化曲线与 `source`，不再现场调用
`getBenchmark()`；`tests/test_frontend_backtest_benchmark_source.py` 覆盖徽章渲染
和“只使用 detail response 中的 persisted benchmark”这两条前端契约。

2026-06-15 状态补充：快赢 #10“`scripts/verify.sh` 一键验证 + conftest Python
版本断言”已处理。仓库现在同时保留 PowerShell 与 POSIX shell 验证入口，默认跑
pytest、ruff、frontend lint、frontend unit tests，build 需显式开启；
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

2026-06-15 状态补充：评估报告中“API 路由缺少 `response_model`、前后端契约
漂移”的高风险项已开始按低风险切片治理，但尚未全量完成。第一批只读市场/健康
接口已挂上 FastAPI `response_model`：`GET /api/health`、`GET /api/symbols`、
`GET /api/ohlcv`、`GET /api/benchmark`、`GET /api/strategies`、
`GET /api/universes`、`GET /api/factors`、`GET /api/factors/runs`、
`GET /api/runs/recent`、`GET /api/market-data/history`；同时补齐 `HealthResponse`、
`OHLCVResponse`、`BenchmarkResponse`、`MarketDataHistoryResponse` 中已由真实响应
返回但 schema 缺失的字段，并为策略/股票池/因子 catalog、因子 run 列表与最近运行活动流增加薄 wrapper response schema。
`tests/test_api_response_models.py` 会检查 OpenAPI schema 引用和
关键字段，现有 `tests/test_api_health.py`、`tests/test_api_data.py`、
`tests/test_api_backtest.py`、`tests/test_api_strategy_universe_catalog.py` 与
`tests/test_api_factors.py`、`tests/test_api_runs_recent.py`、
`tests/test_api_market_data_futu.py` 继续覆盖 runtime 响应与 safety footer。下一步仍应
按路由域逐批补齐，而不是一次性生成/替换全部前端类型。
