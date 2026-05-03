# Fix Plan — Phase 9 联调修复路线（待确认）

> 本文是 [FRONTEND_BACKEND_AUDIT.md](FRONTEND_BACKEND_AUDIT.md) / [UI_FUNCTION_MATRIX.md](UI_FUNCTION_MATRIX.md) / [API_AUDIT.md](API_AUDIT.md) / [MARKET_DATA_SOURCE_AUDIT.md](MARKET_DATA_SOURCE_AUDIT.md) 的修复方案合集。**本文未动任何代码，仅请求授权。**

## 总体策略

把修复分为 **3 个 priority + 6 个 step**。每个 step 都给出：问题、影响、文件、修复方式、验收方式、估计工作量（S=小、M=中、L=大）。

执行顺序原则：

1. 先修"诚实性"问题（mock/fake 直接误导用户）→ P0
2. 再修"可用性"问题（按钮不能点）→ P0
3. 最后修"打磨"问题（loading/error/tooltip 等）→ P1/P2

不调整既有 invariant：

- 仍是 dry-run / paper-only / kill-switch on
- agent approve 仍只写 lock，不动 FactorRegistry
- 不引入 broker / WebSocket / 后台 worker
- 真实 API key 永不出现在前端 / 文档 / 日志

---

## P0 — 必须先修

### P0-1 路由与导航不一致（dead links）

**问题**：[Sidebar.tsx](../src/frontend/components/Sidebar.tsx) 列了 `/settings`（不存在）；缺 `/data-explorer` `/order-book` `/position-map` 链接；`paper-trading` 在导航里曾使用旧命名。

**影响**：用户点 Settings 直接 404；用户根本进不去 data-explorer。

**涉及文件**：[Sidebar.tsx](../src/frontend/components/Sidebar.tsx) + 新建 [app/settings/page.tsx](../src/frontend/app/settings/page.tsx)。

**修复**：

- 创建 [app/settings/page.tsx](../src/frontend/app/settings/page.tsx)：server component，调 `getSettings()`（**新加** [lib/api.ts](../src/frontend/lib/api.ts) 函数），渲染 masked settings + theme/lang switcher（client component 子组件）。
- Sidebar 加上 Data Explorer / Order Book / Position Map 三个条目。
- 把旧命名改回 "Paper Trading"（按 design_brief）。

**验收**：手测 9 个路由全部 200，sidebar 高亮当前路径。

**估计**：S。

---

### P0-2 SafetyStrip / 假 System Log / 假 CPU·RAM·Coverage·Y 轴

**问题**：见 [FRONTEND_BACKEND_AUDIT §6](FRONTEND_BACKEND_AUDIT.md#6-mock--fake--placeholder-风险点按文件汇总)。

**影响**：让用户误判系统状态。

**涉及文件**：

- [components/SafetyStrip.tsx](../src/frontend/components/SafetyStrip.tsx) — 改成 server component 调 `getHealth()` 显示真值
- [app/page.tsx](../src/frontend/app/page.tsx) — 删除 System Log 假行 / Experiment progress / CPU·RAM 假占用条
- [app/data-explorer/page.tsx](../src/frontend/app/data-explorer/page.tsx) — 删除 5 个硬编码 bar、删除 Y 轴硬编码刻度、删除 Coverage / Missing Days / Spike 三块假卡（先删再后续接真）

**修复**：删除装饰节，留 `<EmptyState>` 占位 + "TODO: connect to /api/data/quality" 注释。

**验收**：grep 这些文件不再出现硬编码数字 / 文案。

**估计**：M。

---

### P0-3 真实 SPY market data（接 Tiingo provider）

**问题**：见 [MARKET_DATA_SOURCE_AUDIT.md](MARKET_DATA_SOURCE_AUDIT.md)。

**影响**：用户做研究时拿到合成数据，得出错误结论；专业 token 形同虚设。

**涉及文件**：

- 新建 [src/quant_system/data/provider_factory.py](../src/quant_system/data/provider_factory.py)
- 修改 [api/routes/data.py](../src/quant_system/api/routes/data.py) / [api/routes/benchmark.py](../src/quant_system/api/routes/benchmark.py)
- 修改 [src/quant_system/api/dependencies.py](../src/quant_system/api/dependencies.py) 暴露一个 `OhlcvProviderDep`
- [.env.example](../.env.example) 注释 `QS_DEFAULT_DATA_PROVIDER` 推荐改 `"tiingo"`
- [lib/api.ts](../src/frontend/lib/api.ts) `getOhlcv` / `getBenchmark` 增加 `provider?` 可选参数
- 前端任何展示数据的页面顶部加 `<DataSourceBadge source={ohlcv.source}/>`

**修复**：见 [MARKET_DATA_SOURCE_AUDIT §5](MARKET_DATA_SOURCE_AUDIT.md#5-修复方案推荐-p0-实施)。

**验收**：

```powershell
curl "http://127.0.0.1:8765/api/ohlcv?symbol=SPY&start=2024-01-02&end=2024-01-12&provider=tiingo"
# 期望 source=tiingo, close ~ 472
```

测试：新增 [tests/test_provider_factory.py](../tests/test_provider_factory.py)（覆盖：有 token 走 tiingo / 缺 token 显式 fallback / 显式指定 sample 仍走 sample）。**不要在 CI 里真的打 Tiingo**，用 `get_json` mock。

**估计**：M。

---

### P0-4 前端 7 个页面改成可交互（这是最大的一笔）

**问题**：所有 button / select / input 都是装饰，零 onClick / onChange。

**影响**：所有"运行"功能不可用。

**修复策略**（不一刀切全改 client）：

- 保留每个页面的 server component 顶层（用于初始 SSR + 安全态读取）
- 把"配置面板 + 主交互区"抽成 client component（`use client` + react-hook-form）
- 客户端用 `fetch(...)` 调 backend POST，复用 [lib/api.ts](../src/frontend/lib/api.ts) 同样的 BASE_URL + envelope 处理
- 引入 [@tanstack/react-query](https://tanstack.com/query/latest) 处理 mutation / loading / error / 重试

**最小可用集（按页）**：

| 页面 | 必接 POST | 必加交互组件 |
| --- | --- | --- |
| Backtest | `POST /api/backtests/run` | `<BacktestForm>` (client) + 跑完后 `router.refresh()` |
| Paper Trading | `POST /api/paper/run` | `<PaperRunForm>` + KillSwitch confirm dialog（必须两步确认）|
| Factor Lab | `POST /api/factors/run` | `<FactorRunForm>` |
| Agent Studio | `POST /api/agent/tasks` + `POST /api/agent/candidates/{id}/review` | `<AgentTaskForm>` + `<ApproveDialog>`（按 design_brief §7：approve 二次确认 + 警示文案）|
| Prediction Market | `POST /api/prediction-market/scan` + `dry-arbitrage` | `<PMRunForm>` |
| Data Explorer | （只 GET）需要 form 触发刷新，用 URL search params + Server Action 或 client component | `<DataExplorerControls>` |
| Experiments | （目前只 GET）暂不接 POST | 加 detail tab 切换 |
| Dashboard | Quick Actions 改成 Link 跳到 Backtest / Factor Lab / Agent Studio | 不必接 POST |

**新增前端依赖**：`@tanstack/react-query`、`react-hook-form`、`zod`（与 design_brief §9 一致）。

**安全约束（写进每个 form）**：

- Paper Trading form：`enable_kill_switch` toggle 默认 true 且**禁止取消**（点击触发 `<AlertDialog>` 显示 `kill_switch=true on the backend; you cannot disable it from the API.`）。
- Agent Approve：必须二步确认 + 警示文案 "Approving creates an `approved.lock` file only. It does NOT register the factor automatically."
- Prediction Market：UI 永远不出现"polymarket_api_key"输入框；form 提交时永远传 `null`。

**验收**：每个页面手动跑一次端到端：填表 → 提交 → 看到 loading → 看到 success → 再次 GET 列表能看到新 run。

**估计**：L（这部分占整轮工作量 50%+）。

---

### P0-5 LLM 配置进 Settings + 安全暴露

**问题**：[.env](../.env) 里 `LLM_*` 全部被 `extra="ignore"` 丢弃。

**影响**：用户以为 Agent 会用 xai 路由，实际仍是 stub。是诚实性问题。

**涉及文件**：

- [src/quant_system/config/settings.py](../src/quant_system/config/settings.py) 新增 `LLMSettings` 子模型（fields: `api_key: SecretStr | None`、`base_url: str | None`、`model: str | None`、`timeout: int = 60`、`provider: str = "stub"`）。注意 env 前缀仍是 `QS_`，所以用户需在 `.env` 里改：

  ```
  QS_LLM_API_KEY=<redacted>
  QS_LLM_BASE_URL=https://api.xairouter.com/v1
  QS_LLM_MODEL=gpt-5.4
  QS_LLM_PROVIDER=xai
  ```

  **建议加 alias 兼容当前的 `LLM_*` 写法**（pydantic `Field(alias="LLM_API_KEY", validation_alias=AliasChoices(...))`)。

- [api/routes/agent.py](../src/quant_system/api/routes/agent.py) 新增 `GET /api/agent/llm-config`，返回 `{provider, model, base_url, has_api_key: bool}`（**永不返回明文 key**）。
- [api/safety/masking.py](../src/quant_system/api/safety/masking.py) 把 `llm_*` / `api_key` 字段也加入掩码白名单。
- [agent/llm.py](../src/quant_system/agent/llm.py) 根据 `settings.llm.provider` 选择 stub vs OpenAI-compatible（xai router 用 OpenAI client + base_url override）。
- [agent/runner.py](../src/quant_system/agent/runner.py) 接受 settings 注入。

**验收**：

```powershell
curl http://127.0.0.1:8765/api/agent/llm-config
# {"provider":"xai","model":"gpt-5.4","base_url":"https://api.xairouter.com/v1","has_api_key":true}
curl http://127.0.0.1:8765/api/settings | grep -i api_key
# 全部 **********
```

**新增测试**：`tests/test_api_agent_llm_config.py` 验证 key 不外泄；`tests/test_settings_llm_alias.py` 验证 alias 能读到 `LLM_*` 形式。

**估计**：M。

---

### P0-6 CORS 默认含 3001

**问题**：默认 CORS allow list 不含 `3001`，client component 一接通就撞墙。

**修复**：[settings.py](../src/quant_system/config/settings.py) 默认追加 `127.0.0.1:3001` / `localhost:3001`，文档注明可用 `QS_API_CORS_ORIGINS='[...]'` 覆盖。

**验收**：`curl -H "Origin: http://127.0.0.1:3001" -X OPTIONS http://127.0.0.1:8765/api/health -i` 返回 `Access-Control-Allow-Origin: http://127.0.0.1:3001`。

**估计**：S。

---

## P1 — 重要修复

### P1-1 Select / Dropdown 样式

**问题**：用户截图显示 universe `<select>` 选项几乎不可见。

**修复**：

- 临时方案：所有 `<option>` 加 `style={{background:'#0E1511',color:'#F1F5F9'}}`（兼容 Windows 浏览器原生 dropdown）。
- 长期方案：引入 [shadcn/ui](https://ui.shadcn.com/) Select（可由 Radix Select 渲染，完全可主题化）。

**估计**：S（临时） / M（长期）。

### P1-2 Loading / Error / Empty 状态

**问题**：前端没有 loading skeleton、没有 error banner、没有 empty CTA。

**修复**：实现 `<LoadingSkeleton>` / `<ErrorBanner>` / `<EmptyState>`，所有页面统一使用。`<ErrorBanner>` 检测 `apiError` 字段并显示。

**估计**：M。

### P1-3 文档与代码一致性

**问题**：[design_brief.md](frontend/design_brief.md) 列了 9 页，实际代码曾有 `/settings` 缺失和 paper trading 命名漂移。

**修复**：随 P0-1 一起修；修完后旧命名应为 0 命中。

### P1-4 测试

**新增**：

- `src/frontend/tests/` 用 Vitest（unit 工具函数）+ Playwright（smoke：每个路由能加载 + 至少一个按钮可点）。
- `tests/test_provider_factory.py`、`tests/test_api_agent_llm_config.py`、`tests/test_api_cors.py`。
- 维持 backend `pytest -q` 绿（当前 118 → 期望 130+）。

**估计**：M。

---

## P2 — 体验优化

### P2-1 数据源徽章 / 水印

每个图表角标"sample / live / local"。

### P2-2 Tooltip 与 helper text

Kill Switch toggle、agent approve 按钮、prediction-market 红 banner 都加 tooltip。

### P2-3 Theme switcher

`<html className="dark">` 当前写死，改成可切换（在 settings 页）。

### P2-4 真实 data quality

新增 `/api/data/quality?symbol=&start=&end=`（pandas 计算 coverage / missing days），前端替换假卡。

### P2-5 真实 audit log

`/api/agent/audit/{task_id}` 把 jsonl 解析成结构化 timeline 给前端。

### P2-6 Prediction Market 完整 UI

按 [design_brief §4.8](frontend/design_brief.md) 实现完整页（当前未做的）。

---

## 工作量估算

| 阶段 | 估计 |
| --- | --- |
| P0 全部 | 中等 |
| P1 全部 | 中等 |
| P2 全部 | 较大（建议分批）|

总体 P0+P1 一次集中冲刺可完成；P2 拆为后续多轮。

---

## 验证清单（修复后用）

### 后端

```powershell
conda activate ai-quant
python -m pytest -q                      # 期望 130+ passed
ruff check .                              # 期望 All checks passed!
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765

# 数据真实性
curl "http://127.0.0.1:8765/api/ohlcv?symbol=SPY&start=2024-01-02&end=2024-01-12&provider=tiingo"
# → source=tiingo, close ~ 472

# LLM 配置
curl http://127.0.0.1:8765/api/agent/llm-config
# → has_api_key=true, provider=xai

# 安全 invariant 仍守住
curl http://127.0.0.1:8765/api/orders/submit
# → 404
curl http://127.0.0.1:8765/api/settings | findstr "**********"
# → 多行
```

### 前端

```powershell
cd src/frontend
npm run lint
npm run build
npx playwright test       # 9 个路由 200 + 关键按钮可点
npm run dev -- --port 3001
```

浏览器手测：

1. `/data-explorer` → 选 SPY → 看到 K 线图（不是装饰 bar），数据源标签 = tiingo
2. `/backtest` → 填 form → 提交 → 看 progress → 看 result
3. `/paper-trading` → 同上 + 强制 kill_switch=on confirm
4. `/agent-studio` → 提交 task → 拿 candidate → approve 二次确认弹窗 → 文档 audit jsonl 出现一条
5. `/settings` → 看到 masked secrets，看不到任何明文 key

---

## 等待确认

请回复以下任一：

- **「按 P0 全部开干」** — 我将顺序实施 P0-1 到 P0-6（多次 commit，每个 step 一次绿色测试 + push）。
- **「先做 P0-3 + P0-5 这两条最伤诚实性」** — 我只修真数据源 + LLM 配置。
- **「调整优先级：…」** — 自定义。
- **「再补充 X 页 / X 组件的细化矩阵」** — 我先把矩阵铺满（[UI_FUNCTION_MATRIX.md](UI_FUNCTION_MATRIX.md) §2.5 列出的 backtest/factor/experiments/order-book/position-map 的逐控件清单）再实施。

在收到确认前，本仓库**不会再发生任何代码改动**。
