# Phase 10 Fix Learning

## 核心概念

Phase 10 不增加业务，只解决"看起来能用但其实在骗人"的部分：UI placeholder、未联调表单、不可读错误、缺少 E2E、CORS 过宽、LLM key 暴露风险。它把"前端展示"与"后端真实状态"对齐，让后续阶段可以在一个**可信的基线**上继续叠加。

## 为什么先做诚实化再做新功能

如果 UI 上写着 "Live Sync 99.98%" 而后端根本没这个指标，任何看到页面的人都会被误导，进一步开发也会被错误的成功感掩盖问题。审计 → 修复 → 文档 这三步必须先于 Phase 11 的 Polymarket 真实数据接入。

## 为什么 P0 / P1 分批

- **P0**：不修就影响功能正确性（路由错位、tiingo provider 没接通、placeholder 让人误判系统状态、CORS `*`、LLM key 可能回显）。这一批以独立小 commit 落地，可单独 revert。
- **P1**：质量与可验收性（错误 UX、骨架屏、E2E、审计文档）。这一批可以聚合提交，不影响功能。

## 关键技术点

### 1. 表单 hydration-safe pattern

问题：Next.js SSR 渲染后客户端 React 还没接管时，用户已经能看到按钮。如果按钮是 `<button type="submit">` 且外层 `<form>` 没有阻止默认行为，点击会触发**浏览器原生表单提交**，导致整页跳转 / 闪烁 / 状态丢失。

修复模式：

```tsx
<form onSubmit={(e) => e.preventDefault()}>
  <button type="button" onClick={() => void runMutation()}>
    Run
  </button>
</form>
```

代价：在 input 里按 Enter 不会自动提交。如果需要 Enter 提交，给 input 加 `onKeyDown={e => { if (e.key === 'Enter') runMutation(); }}` 即可。

### 2. 可读错误：`ApiClientError`

后端通过 FastAPI 默认返回的 `{ "detail": "..." }`，如果直接 `JSON.stringify` 渲染会出现 `[object Object]`。统一用：

```ts
class ApiClientError extends Error {
  constructor(public status: number, public detail: string) { super(detail); }
}
```

`apiPost` / `apiGet` 抛出该错误，表单组件用 `mutation.error instanceof ApiClientError ? mutation.error.message : undefined` 渲染。

### 3. Provider factory 避免硬编码

`/api/ohlcv` 旧实现里 `provider=tiingo` 被忽略，永远跑 sample。修复后通过 `build_ohlcv_provider(name)` 工厂分发，并补 `tests/test_api_data_provider_param.py` 覆盖。这一模式同样被 Phase 11 的 `build_prediction_market_provider` 复用。

### 4. CORS 不能写 `*`

放开 `*` 看似省事，实际上让任何站点都能在用户浏览器里调用本机 API。Phase 10 改成显式 allowlist：`http://127.0.0.1:3000` 与 `http://127.0.0.1:3001`，并在测试里断言 ACAO 头。

### 5. LLM 配置端点的"masked"约束

`/api/agent/llm-config` 必须只暴露：

- `provider`（如 `stub` / `xai` / `openai`）
- `model`、`base_url`、`timeout`
- **`has_api_key: bool`**（是否配置，**不是 key 本身**）
- `safety` 状态

任何序列化路径都不允许把 `api_key` 字段渗出到响应体。`tests/test_api_safety.py` 增加针对该端点的明文扫描断言。

### 6. Playwright 走 build 而不是 dev

dev 模式的 HMR 会让页面在测试断言时被悄悄重渲染、按钮短暂消失，导致间歇性失败。Playwright 配置里改成 `npm run build && npm run start`，配合 `webServer.reuseExistingServer: !process.env.CI`。

## 常见错误

- **以为 "tiingo rows=9" 是 sample 假装**：实际是真实 Tiingo 返回，2024-01-02..01-12 含 9 个交易日，first_close=472.65 与历史一致。
- **以为修了 placeholder 就够了**：还要补 `grep '45%|99.98%|MLK Day|Live Sync' src/frontend/app` 的零匹配断言（写进审计文档），防止下次回退。
- **以为 type=button 是黑魔法**：它只是让按钮不再是默认的 `submit`；真正的关键是阻止 form 在 hydration 之前被原生触发。
- **以为 E2E 通过 = 真用户流程没问题**：当前 11 个用例只覆盖路由可加载和表单按钮可点击，不覆盖端到端业务流。Phase 11 会在此基础上扩展。

## 自检清单

- 所有页面 grep 不到假数据字面量
- 所有表单都通过 react-hook-form + zodResolver
- 所有按钮都是 `type="button"` 或外层 form 显式 `preventDefault`
- 后端 `/api/health.safety` 四项位都正确
- `/api/orders/submit` 仍返回 404
- `/api/agent/llm-config` 永远不回显明文 key
- CORS allowlist 不含 `*`
- Playwright 在 build 模式下 11/11 通过

## 与下一阶段的衔接

Phase 11 在 Phase 10 的诚实化基线之上，引入 Polymarket 只读真实数据 + provider factory + 准回测 + 图表 + 前端 provider 切换。所有新页面与新组件都沿用本阶段确立的 `react-hook-form + zod + react-query + ApiClientError + type=button` 模式。
