# AI-Assisted Quant Research Platform

## Phase 14 note: Buy-Side Options Assistant

Phase 14 adds a read-only Buy-Side US Options Strategy Assistant for bullish
option structures: Long Call, Bull Call Spread, LEAPS Call, and LEAPS Call
Spread.

It provides research output for option diagnostics, candidate ranking, scenario
analysis, and a frontend page at `/options-buyside`. It does not add live
trading, Futu account unlock, order placement, wallet signing, or broker
execution.

Read:

- [docs/options/buyside_strategy_learning.md](docs/options/buyside_strategy_learning.md)
- [docs/execution/phase_14_execution.md](docs/execution/phase_14_execution.md)
- [docs/delivery/phase_14_delivery.md](docs/delivery/phase_14_delivery.md)

Focused validation:

```powershell
conda activate ai-quant
python -m pytest -q
ruff check src/quant_system tests
npm --prefix src/frontend run lint
npm --prefix src/frontend run build
```

Debug CLI:

```powershell
quant-system options buyside-screen --ticker AAPL --view long_term_aggressive_bullish --target-price 220 --target-date 2026-12-31
```

Frontend:

```text
http://127.0.0.1:3001/options-buyside
```

The page displays an options risk disclosure and reminds users to review OCC's
`Characteristics and Risks of Standardized Options`.

本项目是一套本地运行的量化研究、回测、模拟交易与只读市场研究平台。

当前进度：**Phase 14 已完成**。

平台可以做：

- 美股 / ETF 历史行情研究，主数据源支持 Futu OpenD，也保留 sample / Tiingo 回退。
- 因子计算、因子评估、策略回测、实验记录、paper trading。
- 本地 FastAPI 后端与 Next.js 前端联动。
- AI 研究助手：只生成候选研究产物，不会自动上线。
- Polymarket / prediction market 只读数据、历史快照、时间序列回放。
- Futu 只读期权数据、单标的卖方期权筛选器、每日全市场 Options Radar。

平台不会做：

- 不实盘交易。
- 不连接钱包。
- 不签名。
- 不下真实订单。
- 不解锁 Futu 交易账户。
- 不提供任何 live trading 能力。

## 快速开始

推荐使用已经创建好的 conda 环境：

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[api,dev]"
```

前端依赖：

```powershell
cd src/frontend
npm install
```

## 启动后端

```powershell
conda activate ai-quant
quant-system serve --host 127.0.0.1 --port 8765
```

等价的直接启动方式：

```powershell
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

健康检查：

```powershell
curl http://127.0.0.1:8765/api/health
```

默认只绑定本机 `127.0.0.1`。

## 启动前端

另开一个 PowerShell：

```powershell
cd src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

打开：

```text
http://127.0.0.1:3001
```

常用页面：

- `/data-explorer`：股票历史行情。
- `/factor-lab`：因子运行。
- `/backtest`：回测。
- `/paper-trading`：模拟交易。
- `/options-screener`：单标的卖方期权筛选。
- `/options-radar`：每日全市场卖方期权扫描结果。
- `/options-buyside`：买方期权策略助手。
- `/order-book`：Polymarket / prediction market 只读研究页面。

## Futu 只读数据

Futu 用于读取美股和美股期权行情。使用前需要：

1. 本机 OpenD 已运行并登录。
2. conda 环境 `ai-quant` 已安装 `futu-api`。
3. `.env` 中 Futu 设置保持只读用途。

验证：

```powershell
conda activate ai-quant
python scripts/verify_futu_connection.py
```

注意：本项目只使用 Futu quote context，不使用交易 context。

## Options Radar

离线样例扫描：

```powershell
conda activate ai-quant
quant-system options daily-scan --provider sample --top 5 --date 2026-05-03 --output-dir data\_phase13_sample_scan
```

真实 Futu dry run：

```powershell
quant-system options daily-scan --top 5 --dry-run
```

刷新 VIX 历史（Yahoo Chart REST，只读，无 API key）：

```powershell
python scripts/refresh_vix_history.py --output data/options_universe/vix_history.csv --lookback-days 400
```

刷新后 daily-scan 会输出 `market_regime=Normal/Elevated/Panic` 一行，前端
`/options-radar` 顶部会显示对应的状态横幅。

查看前端：

```text
http://127.0.0.1:3001/options-radar
```

## 测试

后端：

```powershell
conda activate ai-quant
python -m pytest -q
ruff check src/quant_system tests
```

前端：

```powershell
npm --prefix src/frontend run lint
npm --prefix src/frontend run build
```

浏览器联调：

```powershell
cd src/frontend
$env:PW_E2E="1"
npx playwright test --config playwright.config.ts --workers=1
```

当前已验证结果：

- `pytest`：320 个测试通过（含买方期权 API 与前端冒烟覆盖）。
- `ruff`：通过。
- 前端 lint / build：通过。
- Playwright：14 个浏览器测试通过。

## 重要文档

从这里开始读：

- [docs/OVERVIEW.md](docs/OVERVIEW.md)
- [docs/INDEX.md](docs/INDEX.md)
- [docs/SYSTEM_DESIGN_RESEARCH.md](docs/SYSTEM_DESIGN_RESEARCH.md)

当前阶段：

- [docs/architecture/phase_13_architecture.md](docs/architecture/phase_13_architecture.md)
- [docs/execution/phase_13_execution.md](docs/execution/phase_13_execution.md)
- [docs/learning/phase_13_learning.md](docs/learning/phase_13_learning.md)
- [docs/delivery/phase_13_delivery.md](docs/delivery/phase_13_delivery.md)

Futu / 期权：

- [docs/futu/futu_environment_setup.md](docs/futu/futu_environment_setup.md)
- [docs/futu/futu_market_data_provider.md](docs/futu/futu_market_data_provider.md)
- [docs/futu/futu_options_data_provider.md](docs/futu/futu_options_data_provider.md)
- [docs/options/options_screener_learning.md](docs/options/options_screener_learning.md)

Polymarket：

- [docs/polymarket/polymarket_read_only_integration.md](docs/polymarket/polymarket_read_only_integration.md)
- [docs/polymarket/polymarket_history_collection.md](docs/polymarket/polymarket_history_collection.md)
- [docs/polymarket/polymarket_timeseries_backtest_learning.md](docs/polymarket/polymarket_timeseries_backtest_learning.md)

## 安全边界

默认安全配置：

- `QS_DRY_RUN=true`
- `QS_PAPER_TRADING=true`
- `QS_LIVE_TRADING_ENABLED=false`
- `QS_NO_LIVE_TRADE_WITHOUT_MANUAL_APPROVAL=true`
- `QS_KILL_SWITCH=true`

这些边界不能被前端、Agent、策略、回测或 API 绕过。
