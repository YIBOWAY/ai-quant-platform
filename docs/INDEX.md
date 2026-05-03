# 项目文档索引

这份文档是整个仓库的总入口。你可以把它当成：

- 项目地图
- 阶段进度表
- 常用命令速查表
- 安全边界清单

当前状态已经推进到 **Phase 12**。平台现在包含：

- 股票真实历史数据驱动的因子研究、回测、模拟交易
- 只读的 Polymarket 公开数据接入
- 预测市场历史快照采集
- 预测市场按时间推进的历史回放
- 前后端联动页面

红线不变：

- 不实盘
- 不签名
- 不连钱包
- 不下真实订单
- `live_trading_enabled = false`

---

## 0. 30 秒介绍

这是一个本地运行的量化研究和模拟交易平台。

它现在能做两类事：

1. 股票方向  
   用真实历史行情做因子研究、回测、实验对比和 paper trading。

2. 预测市场方向  
   只读获取 Polymarket 公开数据，做历史快照采集、扫描、时间序列回放和图表报告。

它不是实盘交易系统，也不是自动下单机器人。

---

## 1. 推荐阅读顺序

如果你第一次看这个仓库，按这个顺序读最省时间：

1. [SYSTEM_DESIGN_RESEARCH.md](SYSTEM_DESIGN_RESEARCH.md)
2. [OVERVIEW.md](OVERVIEW.md)
3. [learning/phase_0_learning.md](learning/phase_0_learning.md)
4. [execution/phase_0_execution.md](execution/phase_0_execution.md)
5. [delivery/phase_5_delivery.md](delivery/phase_5_delivery.md)
6. [delivery/phase_11_delivery.md](delivery/phase_11_delivery.md)
7. [delivery/phase_12_delivery.md](delivery/phase_12_delivery.md)

---

## 2. 目录结构

```text
docs/
  INDEX.md
  OVERVIEW.md
  SYSTEM_DESIGN_RESEARCH.md
  architecture/
  delivery/
  execution/
  learning/
  polymarket_*.md

src/quant_system/
  api/                    本地 HTTP API
  backtest/               股票回测主链
  config/                 安全配置与环境变量
  data/                   股票行情 provider 与存储
  execution/              paper trading 与执行模拟
  experiments/            实验记录
  factors/                因子研究
  prediction_market/      只读预测市场研究模块
    collector.py          历史快照采集器
    storage.py            历史快照落盘与读取
    timeseries_backtest.py 时间序列回放
    charts.py             图表输出
    reporting.py          报告输出

src/frontend/
  app/                    页面
  components/             表单与展示组件
  lib/                    API 客户端
  tests/e2e/              浏览器联调

tests/                    pytest
data/                     本地缓存、实验、报告、历史快照
```

---

## 3. 阶段地图

| Phase | 内容 | 架构 | 执行 | 学习 | 交付 |
|---|---|---|---|---|---|
| 0 | 项目骨架与基础工程 | [phase_0_architecture.md](architecture/phase_0_architecture.md) | [phase_0_execution.md](execution/phase_0_execution.md) | [phase_0_learning.md](learning/phase_0_learning.md) | [phase_0_delivery.md](delivery/phase_0_delivery.md) |
| 1 | 数据层 MVP | [phase_1_architecture.md](architecture/phase_1_architecture.md) | [phase_1_execution.md](execution/phase_1_execution.md) | [phase_1_learning.md](learning/phase_1_learning.md) | [phase_1_delivery.md](delivery/phase_1_delivery.md) |
| 2 | 因子研究层 MVP | [phase_2_architecture.md](architecture/phase_2_architecture.md) | [phase_2_execution.md](execution/phase_2_execution.md) | [phase_2_learning.md](learning/phase_2_learning.md) | [phase_2_delivery.md](delivery/phase_2_delivery.md) |
| 3 | 回测引擎 MVP | [phase_3_architecture.md](architecture/phase_3_architecture.md) | [phase_3_execution.md](execution/phase_3_execution.md) | [phase_3_learning.md](learning/phase_3_learning.md) | [phase_3_delivery.md](delivery/phase_3_delivery.md) |
| 4 | 多因子与实验管理 | [phase_4_architecture.md](architecture/phase_4_architecture.md) | [phase_4_execution.md](execution/phase_4_execution.md) | [phase_4_learning.md](learning/phase_4_learning.md) | [phase_4_delivery.md](delivery/phase_4_delivery.md) |
| 5 | 风控与 paper trading | [phase_5_architecture.md](architecture/phase_5_architecture.md) | [phase_5_execution.md](execution/phase_5_execution.md) | [phase_5_learning.md](learning/phase_5_learning.md) | [phase_5_delivery.md](delivery/phase_5_delivery.md) |
| 7 | AI 研究助手 | [phase_7_architecture.md](architecture/phase_7_architecture.md) | [phase_7_execution.md](execution/phase_7_execution.md) | [phase_7_learning.md](learning/phase_7_learning.md) | [phase_7_delivery.md](delivery/phase_7_delivery.md) |
| 8 | Prediction market 接口骨架 | [phase_8_architecture.md](architecture/phase_8_architecture.md) | [phase_8_execution.md](execution/phase_8_execution.md) | [phase_8_learning.md](learning/phase_8_learning.md) | [phase_8_delivery.md](delivery/phase_8_delivery.md) |
| 9 | 本地 HTTP API | [phase_9_api_architecture.md](architecture/phase_9_api_architecture.md) | [phase_9_api_execution.md](execution/phase_9_api_execution.md) | [phase_9_api_learning.md](learning/phase_9_api_learning.md) | [phase_9_api_delivery.md](delivery/phase_9_api_delivery.md) |
| 10 | 前后端修正与联调 | - | [phase_10_execution.md](execution/phase_10_execution.md) | [phase_10_learning.md](learning/phase_10_learning.md) | [phase_10_fix_delivery.md](delivery/phase_10_fix_delivery.md) |
| 11 | Polymarket 真实只读 + 准回测 | [phase_11_architecture.md](architecture/phase_11_architecture.md) | [phase_11_execution.md](execution/phase_11_execution.md) | [phase_11_learning.md](learning/phase_11_learning.md) | [phase_11_delivery.md](delivery/phase_11_delivery.md) |
| 12 | Polymarket 历史采集 + 时间序列回放 + Futu 行情 / 期权卖方筛选器 | [phase_12_architecture.md](architecture/phase_12_architecture.md) | [phase_12_execution.md](execution/phase_12_execution.md) | [phase_12_learning.md](learning/phase_12_learning.md) | [phase_12_delivery.md](delivery/phase_12_delivery.md) |
| 13 | 每日全市场期权卖方扫描器 (Options Radar) — 设计中 | [options/phase_13_options_radar_codex_prompt.md](options/phase_13_options_radar_codex_prompt.md) | - | - | - |

---

## 4. 预测市场专题文档

| 文件 | 作用 |
|---|---|
| [polymarket/polymarket_read_only_integration.md](polymarket/polymarket_read_only_integration.md) | 只读接入说明 |
| [polymarket/polymarket_history_collection.md](polymarket/polymarket_history_collection.md) | 历史快照采集器说明 |
| [polymarket/polymarket_timeseries_backtest_learning.md](polymarket/polymarket_timeseries_backtest_learning.md) | 时间序列回放入门 |
| [polymarket/polymarket_charts_and_metrics.md](polymarket/polymarket_charts_and_metrics.md) | 图表与指标解释 |
| [polymarket/polymarket_troubleshooting.md](polymarket/polymarket_troubleshooting.md) | 常见错误排查 |
| [polymarket/polymarket_safety_boundaries.md](polymarket/polymarket_safety_boundaries.md) | 安全边界 |
| [polymarket/polymarket_strategy_backtest_learning.md](polymarket/polymarket_strategy_backtest_learning.md) | 策略回测入门 |

---

## 4-bis. 期权 / Futu 专题文档

| 文件 | 作用 |
|---|---|
| [futu/futu_integration_design.md](futu/futu_integration_design.md) | Futu 整体集成设计（只读 + OpenD） |
| [futu/futu_options_data_provider.md](futu/futu_options_data_provider.md) | Futu 期权数据 provider（LV1 已含全部期权行情权限） |
| [futu/futu_market_data_provider.md](futu/futu_market_data_provider.md) | Futu 行情 provider |
| [futu/futu_environment_setup.md](futu/futu_environment_setup.md) | OpenD 本地部署 |
| [futu/futu_troubleshooting.md](futu/futu_troubleshooting.md) | Futu 接入常见问题 |
| [futu/futu_frontend_backend_integration_report.md](futu/futu_frontend_backend_integration_report.md) | Futu 前后端联调报告 |
| [options/options_screener_api.md](options/options_screener_api.md) | 期权筛选器 API 端点参考 |
| [options/options_screener_learning.md](options/options_screener_learning.md) | 卖方期权筛选器入门 |
| [options/options_screener_review_2026_05_03.md](options/options_screener_review_2026_05_03.md) | 2026-05-03 卖方策略 review + 预设重定标 |
| [options/phase_13_options_radar_codex_prompt.md](options/phase_13_options_radar_codex_prompt.md) | Phase 13 全市场扫描器 Codex prompt |

---

## 4-ter. 阶段设计冻结 / 路线图

| 文件 | 作用 |
|---|---|
| [phases/phase_11_design_spec.md](phases/phase_11_design_spec.md) | Phase 11 设计冻结 |
| [phases/phase_11_next_roadmap.md](phases/phase_11_next_roadmap.md) | Phase 11 后续路线 |
| [phases/phase_12_design_spec.md](phases/phase_12_design_spec.md) | Phase 12 设计冻结 |

---

## 4-quater. 历史审计文档（只供追溯）

| 文件 | 作用 |
|---|---|
| [audits/API_AUDIT.md](audits/API_AUDIT.md) | Phase 9 后 API 审计 |
| [audits/FRONTEND_BACKEND_AUDIT.md](audits/FRONTEND_BACKEND_AUDIT.md) | 前后端审计总结 |
| [audits/MARKET_DATA_SOURCE_AUDIT.md](audits/MARKET_DATA_SOURCE_AUDIT.md) | 股票数据源审计 |
| [audits/UI_FUNCTION_MATRIX.md](audits/UI_FUNCTION_MATRIX.md) | 前端功能矩阵 |
| [audits/FIX_PLAN.md](audits/FIX_PLAN.md) | 审计后修复计划 |

---

## 5. 关键代码入口

| 想改什么 | 从哪里开始看 |
|---|---|
| 股票数据源 | `src/quant_system/data/provider_factory.py` |
| 股票因子研究 | `src/quant_system/factors/pipeline.py` |
| 股票回测 | `src/quant_system/backtest/pipeline.py` |
| 股票 paper trading | `src/quant_system/execution/pipeline.py` |
| 预测市场 provider | `src/quant_system/prediction_market/provider_factory.py` |
| 预测市场历史采集 | `src/quant_system/prediction_market/collector.py` |
| 预测市场历史存储 | `src/quant_system/prediction_market/storage.py` |
| 预测市场时间序列回放 | `src/quant_system/prediction_market/timeseries_backtest.py` |
| 预测市场图表 | `src/quant_system/prediction_market/charts.py` |
| 预测市场 API | `src/quant_system/api/routes/prediction_market.py` |
| 前端预测市场页面 | `src/frontend/app/order-book/page.tsx` |

---

## 6. 常用命令

### 6.1 基础

```powershell
conda activate ai-quant
python -m pip install -i https://pypi.tuna.tsinghua.edu.cn/simple -e ".[api,dev]"
```

### 6.2 启动后端

```powershell
conda activate ai-quant
quant-system serve --host 127.0.0.1 --port 8765
```

### 6.3 启动前端

```powershell
cd src/frontend
npm install
npm run dev -- --hostname 127.0.0.1 --port 3001
```

### 6.4 股票真实数据链

```powershell
curl -X POST http://127.0.0.1:8765/api/factors/run ^
  -H "Content-Type: application/json" ^
  -d "{\"symbols\":[\"SPY\",\"QQQ\"],\"start\":\"2024-01-02\",\"end\":\"2024-02-15\",\"provider\":\"tiingo\"}"

curl -X POST http://127.0.0.1:8765/api/backtests/run ^
  -H "Content-Type: application/json" ^
  -d "{\"symbols\":[\"SPY\",\"QQQ\"],\"start\":\"2024-01-02\",\"end\":\"2024-02-15\",\"provider\":\"tiingo\"}"

curl -X POST http://127.0.0.1:8765/api/paper/run ^
  -H "Content-Type: application/json" ^
  -d "{\"symbols\":[\"SPY\",\"QQQ\"],\"start\":\"2024-01-02\",\"end\":\"2024-02-15\",\"provider\":\"tiingo\",\"lookback\":20,\"top_n\":2}"
```

### 6.5 预测市场历史采集与回放

```powershell
conda activate ai-quant
quant-system prediction-market collect --provider sample --duration 0 --limit 10
quant-system prediction-market timeseries-backtest --provider sample
```

---

## 7. 八项安全自检

1. `/api/health` 显示 `live_trading_enabled=false`
2. `/api/orders/submit` 返回 404
3. `/api/settings` 不暴露明文密钥
4. `/api/agent/llm-config` 不返回明文 key
5. 任意带 `polymarket_api_key` 的预测市场请求返回 400
6. 默认 provider 仍是 `sample`
7. 没有钱包、签名、真实下单路由
8. 前端页面始终标明 read-only / simulated / no real fills

---

## 8. 常见任务速查

| 任务 | 入口 |
|---|---|
| 看股票真实数据是否生效 | `/data-explorer`，检查 source 标签 |
| 跑一次因子研究 | `/factor-lab` 或 `POST /api/factors/run` |
| 跑一次股票回测 | `/backtest` 或 `POST /api/backtests/run` |
| 跑一次 paper trading | `/paper-trading` 或 `POST /api/paper/run` |
| 拉一批预测市场历史快照 | `quant-system prediction-market collect` |
| 跑一次预测市场历史回放 | `quant-system prediction-market timeseries-backtest` |
| 看预测市场页面 | `/order-book` |

---

## 9. 当前状态

- 后端测试、代码检查、前端 lint/build、浏览器联调都已覆盖到 Phase 12
- 股票三条主链已经能走真实历史数据
- Polymarket 已支持只读历史采集与时间序列回放
- 预测市场仍然是研究用途，不具备真实交易能力

---

## 10. 下一步建议

如果你要继续往前做，最自然的方向有三个：

1. 扩大真实预测市场历史样本积累窗口
2. 增加更多 scanner 和参数对比
3. 把预测市场回放结果纳入更系统的实验管理
