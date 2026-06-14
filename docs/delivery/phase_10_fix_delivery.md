# Phase 10 修复交付

## 范围

Phase 10 修复了 Phase 9 前后端集成审计中发现的问题，同时保持平台
仍为纯本地、纯模拟（paper-only），并默认安全。

## 修复计划清单

- [x] P0-1 侧边栏路由与 `/settings` 页面与既有前端路由对齐。
- [x] P0-2 移除虚假遥测、装饰性指标、虚假日志以及具有误导性的小部件。
- [x] P0-3 OHLCV provider 工厂与数据源标签。
- [x] P0-4 用于 POST 工作流的交互式客户端表单。
- [x] P0-5 LLM 设置与脱敏后的 LLM 配置端点。
- [x] P0-6 CORS 默认包含前端端口 3001。
- [x] P1-1 深色可读的原生 `<option>` 样式。
- [x] P1-2 各页面的加载、错误与空状态组件。
- [x] P1-3 文档/代码漂移清理。
- [x] P1-4 Playwright 冒烟测试。
- [x] P1-5 运行按钮在水合（hydration）完成前不会回退到原生页面提交。

## 验证日志

### P0-1

```text
python -m pytest -q                      PASS
ruff check .                              PASS
cd src/frontend && npm run lint           PASS
cd src/frontend && npm run build          PASS
Route smoke on 127.0.0.1:3001             /, /data-explorer, /factor-lab,
                                          /backtest, /experiments, /paper-trading,
                                          /agent-studio, /order-book, /position-map,
                                          /settings all returned 200
```

### P0-2

```text
python -m pytest -q                      PASS
ruff check .                              PASS
cd src/frontend && npm run lint           PASS
cd src/frontend && npm run build          PASS
rg "45%|65%|99\.98%|MLK Day|Live Sync"   no matches
Route smoke on 127.0.0.1:3001             /, /data-explorer, /factor-lab,
                                          /backtest, /experiments, /paper-trading,
                                          /agent-studio, /order-book, /position-map,
                                          /settings all returned 200
```

### P0-3

```text
python -m pytest tests/test_provider_factory.py tests/test_api_data_provider_param.py -q
6 passed
python -m pytest -q                      PASS
ruff check .                              PASS
cd src/frontend && npm run lint           PASS
cd src/frontend && npm run build          PASS
```

### P0-4

新增的仅前端依赖：

- `@tanstack/react-query`：用于同步本地 API 调用的 mutation 状态管理。
- `react-hook-form` + `zod`：具备本地校验的无障碍表单。
- `sonner`：本地运行请求后的成功/错误 toast 提示。

```text
python -m pytest -q                      PASS
ruff check .                              PASS
cd src/frontend && npm run lint           PASS
cd src/frontend && npm run build          PASS
manual API smoke                          backtest, factor, paper, agent task,
                                          agent review, prediction-market scan,
                                          dry-arbitrage all returned success
manual frontend smoke                     /backtest, /factor-lab, /paper-trading,
                                          /agent-studio, /data-explorer,
                                          /order-book all returned 200
```

### P0-5

```text
python -m pytest tests/test_settings_llm_alias.py tests/test_api_agent_llm_config.py tests/test_llm_factory.py -q
5 passed
python -m pytest -q                      PASS
ruff check .                              PASS
cd src/frontend && npm run lint           PASS
cd src/frontend && npm run build          PASS
```

### P0-6

```text
python -m pytest tests/test_api_cors.py -q
1 passed
python -m pytest -q                      PASS
ruff check .                              PASS
cd src/frontend && npm run lint           PASS
cd src/frontend && npm run build          PASS
```

### P1

新增的前端开发依赖：

- `@playwright/test`：受限的本地冒烟测试。除非设置 `PW_E2E=1`，否则不会运行。

backtest、factor、paper、agent 以及 prediction-market 表单中的运行按钮
在客户端页面就绪前保持禁用，随后使用显式的客户端点击处理器，
而非原生表单提交。这样可避免在客户端 bundle 尚未完全
水合（hydration）时，用户点击触发浏览器级别的页面跳转或无效点击。

```text
rg "<option(?![^>]*style)" -P src/frontend   no matches
rg legacy-paper-label .                     no matches
cd src/frontend && npx playwright test       all tests skipped unless PW_E2E=1
PW_E2E=1 npx playwright test                 11 passed
```

## 手动冒烟测试输出

后端在 `127.0.0.1:8765` 启动，使用临时数据目录，并为 agent 工作流冒烟测试
设置 `QS_LLM_PROVIDER=stub`。前端在
`127.0.0.1:3001` 启动。

```text
health status=ok dry_run=True paper=True live=False kill_switch=True bind=127.0.0.1
ohlcv symbol=SPY source=tiingo rows=9
llm provider=stub model= has_api_key=False key_value_returned=False
settings masked_contains_star=True contains_api_key_field=True
backtest run_id=backtest-20260429T181631Z-b0ae0dcf total_return=0.281682946899275
factor run_id=factor-20260429T181632Z-48a6a121 rows=284
paper run_id=paper-20260429T181634Z-429ec952 orders= breaches=
agent candidate_id=factor-low_vol_momentum-9de4cebf99 auto_promotion=False
agent review decision=approve registration=manual_required
pm scan candidates=3
pm dry proposed_trades=3
orders route status=404
pm live-key status=400
page / status=200
page /data-explorer status=200
page /factor-lab status=200
page /backtest status=200
page /experiments status=200
page /paper-trading status=200
page /agent-studio status=200
page /order-book status=200
page /position-map status=200
page /settings status=200
```

浏览器冒烟测试：

```text
Running 11 tests using 1 worker

  ✓ route / loads
  ✓ route /data-explorer loads
  ✓ route /factor-lab loads
  ✓ route /backtest loads
  ✓ route /experiments loads
  ✓ route /paper-trading loads
  ✓ route /agent-studio loads
  ✓ route /order-book loads
  ✓ route /position-map loads
  ✓ route /settings loads
  ✓ primary local workflow buttons are clickable

  11 passed
```

## 复审更新 - 2026-05-01

在一次全新的前后端复审中，浏览器冒烟测试发现部分运行按钮
可能在客户端页面就绪前就已可见。受影响的按钮
现在会保持禁用，直到水合（hydration）完成，然后通过
客户端 mutation 路径调用 API。这样可在快速的自动化测试或缺乏耐心的
手动操作下，同时避免原生表单跳转和无效点击。

```text
python -m pytest -q                         PASS, 156 collected
ruff check .                                 PASS
cd src/frontend && npm run lint              PASS
cd src/frontend && npm run build             PASS
PW_E2E=1 npx playwright test                 11 passed
API smoke                                    health/settings/llm/ohlcv/backtest/
                                             factor/paper/prediction-market OK
Safety smoke                                 /api/orders/submit -> 404,
                                             Polymarket API key request -> 400
```
