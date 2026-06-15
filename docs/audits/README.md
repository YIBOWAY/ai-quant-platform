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

2026-06-15 状态补充：评估报告中“缺少后端落盘日志”的小项已处理。后端
CLI 启动和 app-factory 路径都会把结构化 JSONL 运行日志写入
`data/_runtime/logs/backend.jsonl`，并由 `RotatingFileHandler` 控制文件大小；
`tests/test_logging_setup.py` 覆盖了 stdout JSON 与文件 JSONL 两条路径。

2026-06-15 状态补充：评估报告中“.env.example 声称默认 sample 而代码默认
futu”的小项已对齐。`.env.example` 现在使用
`QS_DEFAULT_DATA_PROVIDER="futu"`，并说明 `sample` 只用于显式离线流程测试；
`tests/test_environment_file.py` 会锁定示例文件与 `DataSettings` 默认值一致。

2026-06-15 状态补充：评估报告中“错误响应格式不一致”的一部分已收敛。
持续模拟账户 API 的领域错误现在返回结构化 `detail.code` / `detail.message`，
覆盖账户冻结、缺价、策略数据不可用、未知或不支持的账户再平衡策略等常见失败态。
其他历史回放和跨模块 404 仍未做全局统一。

2026-06-15 状态补充：同一条中的 provider 错误也已收敛为共享 helper。
`quant_system.api.errors.provider_unavailable_400()` 统一生成
`detail.code=provider_unavailable`、`detail.provider` 与 `detail.message`；
backtest、factor、experiment、paper、ohlcv、benchmark、market-data 等路由不再
各自复制该响应结构。

2026-06-15 状态补充：评估报告中“前端纯函数缺测试”的一部分已补强。
Strategy Catalog 的 schema-driven payload 构建逻辑已抽到
`src/frontend/lib/strategyPayload.ts`，并由 `strategyPayload.test.ts` 覆盖
symbol list、number、integer_or_null 和 factor weight map 转换。

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
