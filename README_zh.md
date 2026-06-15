# AI 辅助量化研究平台

本地优先的量化研究、回测、模拟交易、只读行情与期权研究平台。

当前项目交付至 Phase 14，主要功能包括：

- 美股及 ETF 历史数据流水线。
- 因子研究、因子实验室诊断（2026-06-11 起真实数据优先：默认 `futu`，数据源/股票池/择时标的/基准可在界面调整，并可保存因子研究运行）、策略/股票池注册、回测、实验和模拟交易。
- 本地 FastAPI 后端 + Next.js 前端。
- AI 研究助手，带候选池和人工审核门禁。
- 只读 Polymarket 预测市场研究、快照、回放和报告。
- 富途 OpenD 只读美股及期权数据。
- 期权收入筛选器（Options Income Screener）、期权雷达（Options Radar）、买方期权助手（Buy-Side Options Assistant）。
- 本地 AlphaGBM 风格期权工具箱及本地富途期权报价缓存。
- 策略目录：包含 reversal/momentum 论文复现、已注册的横截面 Top-N 回测策略、均值回归 Top-N 策略。
- reversal/momentum 复现运行会以 `replication-*` 形式本地持久化，并提供专门详情页。
- 回测引擎控制项：再平衡频率（每根 K 线 / 每周 / 每月）、单标的权重上限、提供行业映射时的 API 层面行业上限、以及按标的的收益归因。
- 可选 PostgreSQL 运行索引（覆盖本地回测/因子/模拟交易运行记录）。

本项目**不包含**实盘交易、券商下单、钱包连接、签名、富途账户解锁或真实订单提交。

## 快速开始

在已有的 conda 环境中安装 Python 依赖：

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[api,dev]"
```

安装前端依赖：

```powershell
cd src/frontend
npm install
```

启动后端：

```powershell
conda activate ai-quant
quant-system serve --host 127.0.0.1 --port 8765
```

CLI 后端入口会把结构化 JSONL 运行日志写入
`data/_runtime/logs/backend.jsonl`，同时保留控制台输出。

等效的直接 FastAPI 命令：

```powershell
conda activate ai-quant
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

## 主要页面

| 页面 | 用途 |
|---|---|
| `/data-explorer` | 美股历史数据查看器。 |
| `/factor-lab` | 因子健康与择时诊断（横截面 / 择时两个标签页）；数据源/股票池/择时标的/基准可在侧栏调整（默认 `futu`），并可保存因子研究运行。 |
| `/backtest` | 运行策略、股票池、因子加权及基准回测。 |
| `/replications` | 已注册研究策略的策略目录。 |
| `/replications/[runId]` | 已落盘的 reversal/momentum 复现运行详情。 |
| `/docs/reversal-momentum` | 论文复现的前端可读笔记。 |
| `/experiments` | 查看实验扫描、分折、对比，并将最佳参数发送至回测。 |
| `/paper-trading` | 持久模拟账户（手动下单 + 策略一键再平衡）＋历史回放（研究）。 |
| `/position-map` | 模拟账户实时持仓地图（净值/现金/暴露/来源归因），另含回测暴露对比块。 |
| `/options-screener` | 单标的卖方期权筛选器。 |
| `/options-radar` | 每日卖方期权雷达快照。 |
| `/options-radar/[symbol]` | 单标的雷达下钻与实时期权链加载。 |
| `/options-tools` | 本地 AlphaGBM 风格期权工具箱。 |
| `/options-buyside` | 买方期权策略助手。 |
| `/order-book` | 只读预测市场研究页面。 |
| `/agent-studio` | AI 研究助手候选流程。 |
| `/settings` | 脱敏后的本地设置。 |

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
conda activate ai-quant
python scripts/verify_futu_connection.py
```

**重要约束**：

- 不使用富途交易上下文（TradeContext）。
- 不进行账户解锁。
- 不进行下单。
- 不进行券商执行。

交互式期权页面包含短期进程内缓存、本地 DuckDB 支持的富途期权报价缓存，以及针对富途限频响应的单次重试。宽泛的每日扫描仍应计划执行，并在富途限速下预计运行较慢。

## 可选 PostgreSQL 运行索引

回测、因子和模拟交易运行记录始终写入本地文件
`data/api_runs/<kind>/<run_id>/`。你可以选择将这三类运行索引到 PostgreSQL 中以加速历史列表查询。
reversal/momentum 复现运行也会写入 `data/api_runs/replications/<run_id>/`，但暂不进入可选 PostgreSQL run index。
该功能**默认关闭**；当数据库关闭或无法访问时，所有已索引端点自动回退到文件系统读取。

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
QS_DATABASE_AUTO_MIGRATE=true
```

后端启动时会在后台线程中运行索引迁移/回填：创建 `quant_system.runs` 表，回填已有的文件运行记录，
并清理文件已被删除的索引行。如果 PostgreSQL 不可用，首次探测很短，后续请求在短暂的冷却窗口内
跳过重复连接尝试，同时继续从本地文件读取。可通过以下命令检查：

```powershell
curl http://127.0.0.1:8765/api/health   # database.reachable 应为 true
```

`psycopg` 驱动随 `api` extra 一起安装。数据库仅存储研究运行元数据；连接 URL 在 `/api/settings`
中已脱敏。详见 [docs/architecture/database_cache_plan.md](docs/architecture/database_cache_plan.md)。

## 模拟账户

一个持续存在、初始 100 万美元的模拟账户：你可以手动买卖，也可以让策略一键再平衡，
两者都汇入同一账户并实时反映到持仓地图。它**仅为模拟**——绝不触及真实下单、券商、钱包或账户解锁。

- 手动下单：`POST /api/paper/account/orders`（买/卖、按数量或金额、可选限价）。
  成交价优先使用 Futu 实时快照，OpenD 离线时只回退到本地缓存或 Tiingo
  的真实最近收盘价；未触及价格的限价单会保存在账户 `pending_orders`
  队列中，并可通过 `POST /api/paper/account/orders/process` 重新检查；
  也可通过 `POST /api/paper/account/orders/{order_id}/cancel` 取消；
  `/paper-trading` 页面会显示挂单列表、检查按钮和逐单取消按钮。持续账户
  绝不会使用 sample / 演示价格成交。
- 策略再平衡：`POST /api/paper/account/rebalance`（一键；任一腿无法成交则整体原子中止）。
  它只接受真实市场历史；sample 演示历史不会改变持续账户。
- 查看 / 冻结 / 重置 / 账本：`GET /api/paper/account`、
  `POST /api/paper/account/kill-switch`、`POST /api/paper/account/reset`、
  `GET /api/paper/account/ledger`。

定时自动再平衡（例如通过 Windows 任务计划程序）：

```powershell
conda activate ai-quant
quant-system paper rebalance --account default --strategy cross_sectional_top_n
```

旧的 `POST /api/paper/run` 历史回放保持不变，自 2026-06-11 起位于同一页面的「历史回放（研究）」标签页。详见
[docs/guides/paper-trading.md](docs/guides/paper-trading.md) 与
[docs/design/paper_trading_position_map_redesign.md](docs/design/paper_trading_position_map_redesign.md)。

## 因子实验室刷新

自 2026-06-11 起，因子实验室界面默认使用真实数据（`provider=futu`），数据源/股票池/择时标的/基准可在侧栏调整，并支持可保存的因子研究运行。下面的 CLI 用于从后端或计划任务刷新其本地诊断缓存：

```powershell
conda activate ai-quant
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

每日卖方期权雷达：

```powershell
conda activate ai-quant
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
`QS_OPTIONS_RADAR_STARTUP_CATCHUP_ENABLED=true` 后，API 启动才会在当天雷达快照缺失时后台运行一次 `daily-scan` 补跑。

本地期权工具箱：

```text
http://127.0.0.1:3001/options-tools
```

买方助手调试 CLI：

```powershell
conda activate ai-quant
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
conda activate ai-quant
quant-system prediction-market collect --provider sample --duration 0 --limit 10
quant-system prediction-market timeseries-backtest --provider sample
```

该模块不进行签名、赎回、转账或提交真实市场订单。

## 验证

本地一键检查：

```powershell
conda activate ai-quant
.\scripts\verify.ps1
```

该脚本会检查 Python 版本、后端 lint / 测试、前端 lint 和前端单元测试。默认不运行
`npm run build`，因为它会重写 `src/frontend/.next`；只有在前端 dev server 停止时才运行
`.\scripts\verify.ps1 -Build`。

仅后端：

```powershell
conda activate ai-quant
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

- [docs/OVERVIEW.md](docs/OVERVIEW.md)
- [docs/INDEX.md](docs/INDEX.md)
- [docs/SYSTEM_DESIGN_RESEARCH.md](docs/SYSTEM_DESIGN_RESEARCH.md)

当前期权相关文档：

- [docs/futu/futu_environment_setup.md](docs/futu/futu_environment_setup.md)
- [docs/futu/futu_options_data_provider.md](docs/futu/futu_options_data_provider.md)
- [docs/options/options_screener_learning.md](docs/options/options_screener_learning.md)
- [docs/options/buyside_strategy_learning.md](docs/options/buyside_strategy_learning.md)
- [docs/options/local_alphagbm_tools.md](docs/options/local_alphagbm_tools.md)
- [docs/delivery/phase_14_delivery.md](docs/delivery/phase_14_delivery.md)

论文复现：

- [docs/replications/reversal_momentum_replication.md](docs/replications/reversal_momentum_replication.md)

本地缓存方案及当前状态：

- [docs/architecture/database_cache_plan.md](docs/architecture/database_cache_plan.md)

## 安全边界

平台默认安全姿态：

- `QS_DRY_RUN=true`
- `QS_PAPER_TRADING=true`
- `QS_LIVE_TRADING_ENABLED=false`
- `QS_NO_LIVE_TRADE_WITHOUT_MANUAL_APPROVAL=true`
- `QS_KILL_SWITCH=true`

前端页面、API 路由、AI Agent、策略、回测以及模拟交易流程均**不得**绕过以上边界。
