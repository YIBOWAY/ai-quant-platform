# Phase 14 执行说明

Phase 14 涵盖买方美股期权策略助手。它已接入后端 API、CLI 与前端页面，
仍然是只读的研究功能。

## 环境

```powershell
conda activate ai-quant
```

## 启动后端

```powershell
quant-system serve --host 127.0.0.1 --port 8765
```

等效的直接启动方式：

```powershell
python -m uvicorn quant_system.api.server:create_app --factory --host 127.0.0.1 --port 8765
```

## 启动前端

```powershell
cd src/frontend
npm run dev -- --hostname 127.0.0.1 --port 3001
```

打开：

```text
http://127.0.0.1:3001/options-buyside
```

## API

```powershell
curl -X POST http://127.0.0.1:8765/api/options/buy-side/assistant ^
  -H "Content-Type: application/json" ^
  -d "{\"ticker\":\"AAPL\",\"view_type\":\"long_term_aggressive_bullish\",\"target_price\":220,\"target_date\":\"2026-12-31\",\"provider\":\"futu\"}"
```

接口契约摘要：

- 请求 schema：`BuySideAssistantRequest`
- 响应 schema：`BuySideAssistantResponse`
- 预期的 API 错误：
  - `422`：无效的论点输入
  - `404`：未找到标的或期权链
  - `503`：Futu OpenD/数据提供方不可用
  - `403`：Futu 权限问题
  - `400`：不支持的数据提供方或无效的参数组合

## CLI

```powershell
quant-system options buyside-screen --ticker AAPL --view long_term_aggressive_bullish --target-price 220 --target-date 2026-12-31
```

该 CLI 仅打印研究输出，无法下单交易。

## 验证

后端：

```powershell
python -m pytest -q
ruff check src/quant_system tests
```

前端：

```powershell
npm --prefix src/frontend run lint
npm --prefix src/frontend run build
```

浏览器冒烟测试：

```powershell
cd src/frontend
$env:PW_E2E="1"
npx playwright test --config playwright.config.ts --workers=1 tests/e2e/phase14-buyside-smoke.spec.ts
```

## 安全检查

Phase 14 的各模块必须保持只读：

```powershell
git grep -nE "OpenSecTradeContext|unlock_trade|place_order|modify_order|cancel_order|web3|eth_account|wallet|private_key" -- src/quant_system/options tests src/frontend
```

预期结果：不存在可执行的交易代码。文档中可能提及这些术语，但仅作为
被禁止的能力来说明。

## 风险披露

`/options-buyside` 页面必须展示所要求的期权风险披露，并应引导用户查阅
OCC 的 `Characteristics and Risks of Standardized Options`。这段文字是
必需的风险提示，而非装饰性文案。
