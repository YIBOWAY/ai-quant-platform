# Frontend / Backend Audit — Phase 9 联调

> 本文是 [UI_FUNCTION_MATRIX.md](UI_FUNCTION_MATRIX.md) / [API_AUDIT.md](API_AUDIT.md) / [MARKET_DATA_SOURCE_AUDIT.md](MARKET_DATA_SOURCE_AUDIT.md) 的合并性结论，提供给非工程读者也能理解。详细矩阵见各分文档。

## 1. 既有文档总结

[docs/](../docs/) 已存在的相关文档：

- [docs/architecture/phase_9_api_architecture.md](architecture/phase_9_api_architecture.md) — API 层设计
- [docs/delivery/phase_9_api_delivery.md](delivery/phase_9_api_delivery.md) — API 交付清单
- [docs/delivery/phase_9_frontend_api_integration.md](delivery/phase_9_frontend_api_integration.md) — 联调启动指南
- [docs/frontend/design_brief.md](frontend/design_brief.md) — 给设计 agent 的视觉/交互合同

## 2. 文档与代码不一致点

| 文档断言 | 代码实情 | 处置 |
| --- | --- | --- |
| design_brief §4.4 写明 backtest 页有 "Run / Save snapshot" 等可交互按钮 | 整个前端没有任何 onClick handler | 文档先行，代码未追上 → 标记 P0 |
| design_brief §6 列了 11 个 API 路由 | 后端确实存在这 11 个；但前端 [api.ts](../src/frontend/lib/api.ts) 只用了其中的 GET 子集 | 缺 POST 调用 → 标记 P0 |
| design_brief §7 "Approve 按钮必须二次确认 + 不会注册因子" | 前端 Agent Studio 页没有 review 按钮，更没有二次确认 | 完全未实现 → P0 |
| Phase 9 delivery 写明 `/api/symbols` "本地优先 + sample fallback" | 实情确是这样，但**没有第三档 Tiingo** | 文档没说应该有，但用户期望有 → 见 [MARKET_DATA_SOURCE_AUDIT](MARKET_DATA_SOURCE_AUDIT.md) |
| `phase_9_frontend_api_integration.md` 强调 "real responses from Phase 9 backend" | 真：但 backend 自己用的是 sample provider，所以 "real response from a fake source" | 措辞需更精确 |
| settings 在 sidebar 出现，但 `/settings` 路由不存在 | UI ↔ 代码不一致 | P0 |

## 3. 缺失接口（前端将需要而后端没有）

参见 [API_AUDIT §3](API_AUDIT.md#3-缺失的-endpoint前端将来需要目前-backend-没有)。

简表：

- **必加**：让 `/api/ohlcv` / `/api/benchmark` 接 Tiingo（不是新路由，是扩展逻辑）
- 建议加：`/api/data/quality`、`/api/agent/llm-config`（masked）、`/api/agent/audit/{task_id}`
- **不要加**：CPU/RAM 这种系统遥测，前端假数据应直接删掉

## 4. 前端未接的功能

完整清单见 [UI_FUNCTION_MATRIX.md](UI_FUNCTION_MATRIX.md)。一句话：**前端只调用了所有 GET，零 POST**。意味着：

- 无法启动 backtest / paper / factor / agent task
- 无法 review agent candidate
- 无法跑 prediction-market scan / dry arbitrage

## 5. 后端未实现的功能

按 Phase 9 计划，后端核心 endpoint **基本到位**。真正没实现的是：

- 真实 market data provider 选择逻辑
- LLM 配置在 Settings 里的字段定义（导致 .env 中 `LLM_*` 完全无效）
- 数据质量计算
- 实验运行触发（`/api/experiments/run` 不存在；当前只能列出 / 看详情）

## 6. Mock / Fake / Placeholder 风险点（按文件汇总）

### 6.1 后端

| 文件 | 行号 | 问题 |
| --- | --- | --- |
| [api/routes/data.py](../src/quant_system/api/routes/data.py) | L13 | `_DEFAULT_SAMPLE_SYMBOLS` 硬编码 5 个 ETF |
| [api/routes/data.py](../src/quant_system/api/routes/data.py) | L46 | fallback 只到 sample，缺 Tiingo |
| [api/routes/benchmark.py](../src/quant_system/api/routes/benchmark.py) | L15 | benchmark 直连 sample |
| [data/providers/sample.py](../src/quant_system/data/providers/sample.py) | L23-33 | 合成 OHLCV 序列（设计如此，但应在 source 标注） |
| [agent/llm.py](../src/quant_system/agent/llm.py) | StubLLMClient 默认 | 用户 .env 中 `LLM_*` 全部丢失 |

### 6.2 前端

| 文件 | 问题 |
| --- | --- |
| [app/page.tsx](../src/frontend/app/page.tsx) | System Log 三条时间戳硬编码、Experiment 卡 progress 45% 硬编码、CPU 42% / RAM 65% 硬编码 |
| [app/data-explorer/page.tsx](../src/frontend/app/data-explorer/page.tsx) | 主 chart 5 根硬编码 `<div>` bar、Y 轴刻度硬编码、Data Quality 三卡硬编码、"Live Sync" 假动画 |
| [app/agent-studio/page.tsx](../src/frontend/app/agent-studio/page.tsx) | 代码 preview 是固定 momentum 模板（不是 candidate 真实源码）、"PASS" 标签恒亮、左侧 RL_Agent_v1 / Sentiment_LLM 是假文件 |
| [app/paper-trading/page.tsx](../src/frontend/app/paper-trading/page.tsx) | 多处比例条硬编码 |
| [app/backtest/page.tsx](../src/frontend/app/backtest/page.tsx) / [factor-lab](../src/frontend/app/factor-lab/page.tsx) / [experiments](../src/frontend/app/experiments/page.tsx) / [order-book](../src/frontend/app/order-book/page.tsx) / [position-map](../src/frontend/app/position-map/page.tsx) | 待逐文件清查（结构同上：server component + 装饰元素混杂真实 API 字段）|

## 7. 重启项目（验证修复时用）

```powershell
# 后端
conda activate ai-quant
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765

# 前端（另一个窗口）
cd src/frontend
npm install   # 若 node_modules 已存在可跳过
npm run dev -- --port 3001
```

打开浏览器：

- 后端探活：<http://127.0.0.1:8765/api/health>
- 前端：<http://127.0.0.1:3001>

## 8. 下一步

继续阅读 [FIX_PLAN.md](FIX_PLAN.md) 获取分阶段修复方案，然后**等用户确认**再动代码。
