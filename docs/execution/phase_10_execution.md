# Phase 10 Fix Execution

## 阶段定位

Phase 10 是一次"诚实化与稳态化"修复，不引入新业务能力。它针对 Phase 9 验收时发现的前后端不一致、UI 假数据、表单未联调、错误信息不可读、E2E 缺失等问题做集中收口。

修复分两批：

- P0：影响功能正确性的硬伤（路由对齐、provider 工厂分发、placeholder 清理、表单接通后端、masked LLM 配置端点、CORS 收紧）。
- P1：质量与可验收性（react-hook-form + zod 表单重构、可读错误展示、加载骨架、Playwright E2E、审计文档落档）。

## 环境要求

- Windows + conda env `ai-quant`
- Python 3.11+
- Node.js 20+，npm 10+
- 后端 API extra 已安装：`pip install -e ".[api,dev]"`

## 后端验证

```powershell
conda activate ai-quant
$env:PYTHONPATH = "."
pytest -q
ruff check .
```

预期：所有用例通过；ruff 无告警。

启动后端：

```powershell
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

冒烟（关键端点都应返回 200，且响应体包含 `safety` 字段）：

```powershell
curl http://127.0.0.1:8765/api/health
curl "http://127.0.0.1:8765/api/ohlcv?symbol=SPY&start=2024-01-02&end=2024-01-12&provider=tiingo"
curl http://127.0.0.1:8765/api/agent/llm-config
curl http://127.0.0.1:8765/api/prediction-market/markets
```

`/api/orders/submit` 必须返回 404（无下单路由）。
带 `polymarket_api_key` 的请求必须返回 400。

## 前端验证

```powershell
cd src/frontend
npm install
npm run lint
npm run build
```

启动开发服务器（仅本地）：

```powershell
$env:NEXT_PUBLIC_API_BASE_URL = "http://127.0.0.1:8765"
npm run dev -- --port 3001
```

打开 [http://127.0.0.1:3001](http://127.0.0.1:3001) 后逐页检查：

- 侧边栏所有路由可点开，无 404
- 各页面不再出现假百分比、假节假日、假 "Live Sync" 等 placeholder
- 提交表单（Backtest/Factor/Paper/Agent/PM）能调通后端，错误信息可读
- Paper trading 页 kill_switch 是只读 toggle，点击弹窗解释，不能关闭

## E2E（Playwright）

为避免开发热更新干扰，Playwright 默认走生产构建：

```powershell
cd src/frontend
$env:PW_E2E = "1"
npx playwright install --with-deps chromium  # 首次
npx playwright test
```

预期：11/11 通过。

如需在 dev 模式调试，可手动 `npm run dev` 后另起 `npx playwright test --ui`。

## 一键 / 分步前后端联调

按 [phase_9_api_execution.md](phase_9_api_execution.md) 中的脚本路径启动；本阶段不修改启动脚本，沿用即可。

## 安全边界（不应被破坏）

- `/api/health.safety.live_trading_enabled = false`
- `/api/health.safety.kill_switch = true`
- `/api/health.safety.bind_address = 127.0.0.1`
- 默认 CORS 只放行 `http://127.0.0.1:3000` 与 `http://127.0.0.1:3001`
- LLM 配置端点不返回明文 API key，仅返回是否配置（`has_api_key`）

## 成功标志

- 后端 pytest + ruff 全通过
- 前端 lint + build 通过
- Playwright 11/11 通过
- 4 类表单都能在浏览器中真实触发后端请求并展示结果
- 5 份审计文档与本阶段 delivery 文档落档
